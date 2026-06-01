import optuna
import warnings
import random
import simpy
from pulpsim_tuner import PulpFacilitySimulation, algorithm_strategy

warnings.filterwarnings('ignore')

# ==============================================================
# CONFIGURACIÓN DE OPTUNA Y EJECUCIÓN DINÁMICA
# ==============================================================
def objective(trial):
    random.seed(42) 
    
    w1 = trial.suggest_int('w1', 1.0, 10000.0, log=True)
    w2 = trial.suggest_int('w2', 1.0, 10000.0, log=True)
    w3 = trial.suggest_int('w3', 1.0, 10000.0, log=True)
    w4 = trial.suggest_int('w4', 1.0, 10000.0, log=True)
    
    env = simpy.Environment()
    facility = PulpFacilitySimulation(env, w1=w1, w2=w2, w3=w3, w4=w4, strategy_func=algorithm_strategy) 
    facility.run()
    env.run(until=30*24*60) 
    
    # --- RECIBIMOS LAS 7 VARIABLES ---
    ratio_picado, mean_feed_age_days, mean_truck_wait_min, starvation_min, mean_stock_routing_age_days, final_yard_age_days, std_feed_age_months = facility.get_metrics()
    
    # --- CONVERSIONES A MESES ---
    mean_feed_age_months = mean_feed_age_days / 30.4167
    mean_stock_routing_age_months = mean_stock_routing_age_days / 30.4167
    final_yard_age_months = final_yard_age_days / 30.4167
    
    # --- METAS ESTRATÉGICAS ---
    target_age_months = 3.5 
    target_ratio = 0.60
    
    brecha_edad = abs(mean_feed_age_months - target_age_months)
    brecha_ratio = abs(ratio_picado - target_ratio)
    
    # --- CASTIGO NUCLEAR AL RATIO ---
    score_edad = brecha_edad * 1000000
    # Subimos a 10,000,000. Cualquier desvío destruirá el fitness de Optuna.
    score_ratio = brecha_ratio * 1000000
    
    # --- MULTA 1: NO ENVIAR MADERA VIEJA A CANCHA ---
    limite_edad_enviada = 2.75  
    multa_envio_cancha = 0.0
    if mean_stock_routing_age_months > limite_edad_enviada:
        multa_envio_cancha = (mean_stock_routing_age_months - limite_edad_enviada) * 10000
        
    # --- MULTA 2: COSTO DE OBSOLESCENCIA DEL PATIO ---
    limite_edad_patio = 6.0 
    multa_patio_estancado = 0.0
    if final_yard_age_months > limite_edad_patio:
        multa_patio_estancado = (final_yard_age_months - limite_edad_patio) * 50000

    # --- NUEVA MULTA: INESTABILIDAD DIARIA ---
    # Toleramos un desvío estándar de 0.3 meses (~9 días)
    limite_desviacion = 0.30 
    multa_inestabilidad = 0.0
    if std_feed_age_months > limite_desviacion:
        # Castigo gigante para obligar a estabilizar el consumo diario
        multa_inestabilidad = (std_feed_age_months - limite_desviacion) * 500000

    # --- LÍMITES FÍSICOS (Damos un poco más de aire) ---
    limite_espera_camion = 90.0  # Subimos la tolerancia a 1.5 horas
    limite_starvation = 360.0    # Subimos a 6 horas para permitir el uso intensivo de grúas
    
    multa_espera = 0.0
    if mean_truck_wait_min > limite_espera_camion:
        multa_espera = (mean_truck_wait_min - limite_espera_camion) * 50
        
    multa_starvation = 0.0
    if starvation_min > limite_starvation:
        multa_starvation = (starvation_min - limite_starvation) * 100
        
    # --- FITNESS A MINIMIZAR ---
    fitness_total = score_edad + score_ratio + multa_envio_cancha + multa_patio_estancado + multa_espera + multa_starvation + multa_inestabilidad

    # Guardar métricas
    trial.set_user_attr("Edad_Linea_Meses", mean_feed_age_months)
    trial.set_user_attr("Varianza_Diaria", std_feed_age_months) # <-- Guardamos la varianza
    trial.set_user_attr("Ratio_Picado", ratio_picado)
    trial.set_user_attr("Edad_Final_Patio_Meses", final_yard_age_months) 
    trial.set_user_attr("Espera_Promedio_Min", mean_truck_wait_min)
    trial.set_user_attr("Starvation_Min", starvation_min)
    
    return fitness_total

if __name__ == '__main__':
    study = optuna.create_study(
        study_name="calibracion_dinamica_simpy_v8", # <-- v6 para probar esta nueva política
        storage="sqlite:///calibracion_romana_dinamica.db", 
        load_if_exists=True, 
        direction="minimize" 
    )
    
    print("🚀 INICIANDO BÚSQUEDA DINÁMICA CON COSTO DE OBSOLESCENCIA (>6 MESES)...")
    study.optimize(objective, n_trials=1000) 
    
    mejor_prueba = study.best_trial
    
    print(f"\n--- MEJOR SOLUCIÓN ENCONTRADA ---")
    print(f"Pesos  -> W1: {mejor_prueba.params['w1']:.2f} | W2: {mejor_prueba.params['w2']:.2f} | W3: {mejor_prueba.params['w3']:.2f} | W4: {mejor_prueba.params['w4']:.2f}")
    print(f"🌲 Edad Mezcla Línea       : {mejor_prueba.user_attrs['Edad_Linea_Meses']:.2f} meses")
    print(f"🏭 Edad Final del Patio    : {mejor_prueba.user_attrs['Edad_Final_Patio_Meses']:.2f} meses")
    print(f"⚖️ Ratio Picado Directo    : {(mejor_prueba.user_attrs['Ratio_Picado']*100):.1f}%")
    print(f"🚛 Espera Promedio Portería: {mejor_prueba.user_attrs['Espera_Promedio_Min']:.1f} minutos")
    print(f"⏳ Inanición (Starvation)  : {mejor_prueba.user_attrs['Starvation_Min']} minutos")