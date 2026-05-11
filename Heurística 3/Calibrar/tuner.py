import optuna
import pandas as pd
import warnings
from heuristica import Romana

# Ignorar warnings de pandas para que la consola se mantenga limpia
warnings.filterwarnings('ignore')


# 2. FUNCIONES
def _getDynamicTargetHour(dateObj, actualHour, dfDowntime, densityWood):
    hourStart = pd.Timestamp(dateObj.year, dateObj.month, dateObj.day, actualHour, 0, 0)
    hourEnd = hourStart + pd.Timedelta(hours=1)

    andesUptime = 60.0
    pacificoUptime = 60.0

    if dfDowntime is not None and not dfDowntime.empty:
        for index, row in dfDowntime.iterrows():
            downStart = row['Parada de Equipo']
            downEnd = row['Entrega de Equipo']
            lineName = str(row['Línea']).strip().lower()

            overlapStart = max(hourStart, downStart)
            overlapEnd = min(hourEnd, downEnd)

            if overlapEnd > overlapStart:
                downMinutes = (overlapEnd - overlapStart).total_seconds() / 60.0
                
                if 'andes' in lineName:
                    andesUptime = max(0.0, andesUptime - downMinutes)
                elif 'pacifico' in lineName or 'pacífico' in lineName:
                    pacificoUptime = max(0.0, pacificoUptime - downMinutes)

    capacityAndes = (andesUptime / 60.0) * 150.0
    capacityPacifico = (pacificoUptime / 60.0) * 150.0
    
    targetHour = (capacityAndes + capacityPacifico) / densityWood
    
    return targetHour, andesUptime, pacificoUptime

def run_simulation_headless(w1, w2, w3, df, dfDowntime, canchaDict, date_range):
    total_vol_machine_global = 0.0
    total_sum_vol_age_machine_global = 0.0
    
    total_vol_sy_global = 0.0
    total_sum_vol_age_sy_global = 0.0
    
    total_vol_picado_global = 0.0

    for single_date in date_range:
        dateObj = single_date.date()
        dateStr = single_date.strftime('%d-%m-%Y')
        dfDay = df[df['Fecha_Ingreso_Date'] == dateObj]
        
        if dfDay.empty:
            continue

        # Inicializamos la heurística CADA DÍA, tal como en tu código original
        system = Romana(w1=w1, w2=w2, w3=w3)
        
        if dateStr in canchaDict:
            volCraneRealDay, ageStorageYard = canchaDict[dateStr]
        else:
            volCraneRealDay = 1000.0
            ageStorageYard = 4.0

        chunkVol = volCraneRealDay / 4.0
        remainingCraneVol = 0.0
        
        volSyDay = 0.0
        sumVolAgeSyDay = 0.0

        for h in range(24):
            if h == 0 or h == 6 or h == 12 or h == 18:
                remainingCraneVol += chunkVol

                targetHour, andesUptime, pacificoUptime = _getDynamicTargetHour(single_date, h, dfDowntime, 0.39)
                    
                # CAPACIDAD DINÁMICA DE GRÚA (DOMINGOS VS SEMANA)
                # single_date.weekday() devuelve 6 cuando es Domingo
                if single_date.weekday() == 6:
                    # 200 M3SSC
                    limite_grua = 200.0
                else:
                    # 125 M3SSC
                    limite_grua = 125.0
                    
                dynamicMaxCrane = min(limite_grua, targetHour)
            
            lineActives = 0
            if andesUptime > 1.0: lineActives += 1
            if pacificoUptime > 1.0: lineActives += 1

            trucks_in_hour = dfDay[dfDay['Hora_Ingreso'].dt.hour == h]
            
            for index, row in trucks_in_hour.iterrows():
                idTruck = row['Camion']
                vol = row['M3SSC']
                age = row['Edad']

                decision, p1, p2, p3 = system._EvaluateTruck(
                    id=idTruck, volTruck=vol, ageTruck=age, activeLines=lineActives, unloadingSy='Descarga',
                    remainingCraneVol=remainingCraneVol, maxCranePerHour=dynamicMaxCrane, ageStorageYard=ageStorageYard
                )

                if 'Descarga' in decision:
                    volSyDay += vol
                    sumVolAgeSyDay += (vol * age)

            system._CloseHour(lineActives, remainingCraneVol, dynamicMaxCrane, ageStorageYard)

        # Acumular resultados del día a las variables globales
        total_vol_machine_global += system.totalMachineDay
        total_sum_vol_age_machine_global += system.sumVolAgeMachineDay
        
        total_vol_sy_global += volSyDay
        total_sum_vol_age_sy_global += sumVolAgeSyDay
        
        total_vol_picado_global += system.volLineDay

    # Cálculos Finales
    edad_promedio_mezcla = total_sum_vol_age_machine_global / total_vol_machine_global if total_vol_machine_global > 0 else 0
    edad_promedio_descarga = total_sum_vol_age_sy_global / total_vol_sy_global if total_vol_sy_global > 0 else 0
    
    vol_recibido_total = total_vol_picado_global + total_vol_sy_global
    ratio_picado = total_vol_picado_global / vol_recibido_total if vol_recibido_total > 0 else 0

    return edad_promedio_mezcla, edad_promedio_descarga, ratio_picado

# ==============================================================
# 3. CARGA GLOBAL DE DATOS
# ==============================================================
print("Cargando datos en memoria (Esto tomará unos segundos)...")

file = 'Datos_Simulación.xlsx'
fileDowntime = 'Tiempos_Perdidos.xlsx'
fileCancha = 'ConsumoCanchaNov2025.txt'

df = pd.read_excel(file, decimal=',')
try:
    dfDowntime = pd.read_excel(fileDowntime)
    dfDowntime['Parada de Equipo'] = pd.to_datetime(dfDowntime['Parada de Equipo'])
    dfDowntime['Entrega de Equipo'] = pd.to_datetime(dfDowntime['Entrega de Equipo'])
except:
    dfDowntime = None

canchaDict = {}
try:
    with open(fileCancha, 'r', encoding='utf-8') as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 3:
                dateStrRaw = pd.to_datetime(parts[0], format='%d-%m-%y').strftime('%d-%m-%Y')
                canchaDict[dateStrRaw] = (float(parts[1]), float(parts[2]))
except:
    pass

df['Hora_Ingreso'] = pd.to_datetime(df['Hora_Ingreso'], format='%d-%m-%Y %H:%M:%S')
df['Fecha_Corta'] = pd.to_datetime(df['Fecha_Corta'], format='%d-%m-%Y')
df['Edad'] = ((df['Hora_Ingreso'] - df['Fecha_Corta']).dt.days) / 30.4167
df = df.sort_values('Hora_Ingreso')
df['Fecha_Ingreso_Date'] = df['Hora_Ingreso'].dt.date

dates_from_cancha = [pd.to_datetime(d, format='%d-%m-%Y').date() for d in canchaDict.keys()]
dates_from_df = list(df['Fecha_Ingreso_Date'].dropna().unique())
all_dates = list(set(dates_from_cancha + dates_from_df))
min_date, max_date = min(all_dates), max(all_dates)
date_range = pd.date_range(start=min_date, end=max_date)

print("Datos cargados correctamente. Iniciando calibración con Optuna...")

# ==============================================================
# 4. CONFIGURACIÓN DE OPTUNA Y EJECUCIÓN
# ==============================================================
def objective(trial):
    # Espacio de búsqueda de parámetros
    w1 = trial.suggest_float('w1', 1.0, 50000.0, log=True)
    w2 = trial.suggest_float('w2', 1.0, 5000.0, log=True)
    w3 = trial.suggest_float('w3', 1.0, 10000.0, log=True)
    
    # Correr simulador
    edad_mezcla, edad_descarga, ratio_picado = run_simulation_headless(
        w1, w2, w3, df, dfDowntime, canchaDict, date_range
    )
    
    # --- 1. FUNCIÓN OBJETIVO PRINCIPAL ---
    error_edad_linea = abs(edad_mezcla - 3.5)
    
    # --- 2. LÍMITES TOLERADOS (Ajusta esto según la planta) ---
    limite_error_ratio = 0.1  # Toleras hasta 4% de desvío del 60%
    limite_edad_cancha = 2.75   # Toleras hasta 3 meses de edad en el acopio
    
    error_ratio = abs(ratio_picado - 0.60)
    
    # --- 3. CÁLCULO DE PENALIZACIONES (Big-M) ---
    multa_ratio = 0.0
    if error_ratio > limite_error_ratio:
        # Si se pasa, multiplicamos el exceso por un castigo gigante (ej. 1000)
        multa_ratio = (error_ratio - limite_error_ratio) * 1000
        
    multa_cancha = 0.0
    if edad_descarga > limite_edad_cancha:
        # Castigo fuerte por enviar madera muy vieja
        multa_cancha = (edad_descarga - limite_edad_cancha) * 100
        
    # --- 4. FITNESS TOTAL A MINIMIZAR ---
    fitness_total = error_edad_linea + multa_ratio + multa_cancha


    # #========== ENFOQUE EN EDAD DE ENVIO A CANCHA ============
    # # --- 1. CÁLCULO DE DESVIACIONES ---
    # error_edad_linea = abs(edad_mezcla - 3.5)
    # error_ratio = abs(ratio_picado - 0.60)
    
    # # --- 2. LÍMITES TOLERADOS (Tu muro de contención) ---
    # limite_error_ratio = 0.04  # Toleras hasta 4% de desvío del 60%
    # limite_error_linea = 0.30  # Toleras hasta 0.3 meses de error en la línea (entre 3.2 y 3.8 meses)
    
    # # --- 3. CÁLCULO DE PENALIZACIONES (Big-M) ---
    # multa_ratio = 0.0
    # if error_ratio > limite_error_ratio:
    #     # Castigo gigante si el flujo de las grúas colapsa
    #     multa_ratio = (error_ratio - limite_error_ratio) * 1000
        
    # multa_linea = 0.0
    # if error_edad_linea > limite_error_linea:
    #     # Castigo gigante si la calidad de la mezcla se arruina
    #     multa_linea = (error_edad_linea - limite_error_linea) * 1000
        
    # # --- 4. FITNESS TOTAL A MINIMIZAR ---
    # # Ahora el algoritmo intentará empujar la edad_descarga hacia cero, 
    # # esquivando las multas de la línea y el ratio.
    # fitness_total = edad_descarga + multa_ratio + multa_linea

    # # --- 1. CÁLCULO DE DESVIACIONES ---
    # error_edad_linea = abs(edad_mezcla - 3.5)
    # error_ratio = abs(ratio_picado - 0.60)
    
    # # --- 2. LÍMITES TOLERADOS (Tu muro de contención) ---
    # limite_error_linea = 0.30  # Toleras hasta 0.3 meses de error en la línea
    # limite_edad_cancha = 3.0   # Toleras hasta 3.0 meses de edad en el acopio
    
    # # --- 3. CÁLCULO DE PENALIZACIONES (Big-M) ---
    # multa_linea = 0.0
    # if error_edad_linea > limite_error_linea:
    #     # Castigo gigante si la calidad de la mezcla se arruina
    #     multa_linea = (error_edad_linea - limite_error_linea) * 1000
        
    # multa_cancha = 0.0
    # if edad_descarga > limite_edad_cancha:
    #     # Castigo fuerte si la madera enviada a cancha envejece demasiado
    #     multa_cancha = (edad_descarga - limite_edad_cancha) * 100
        
    # # --- 4. FITNESS TOTAL A MINIMIZAR ---
    # # Multiplicamos el error del ratio por 100 (para pasarlo a %) y que sea 
    # # el motor principal de búsqueda. Si se cruzan los límites, las multas lo arruinan.
    # fitness_total = (error_ratio * 100) + multa_linea + multa_cancha
    
    # Guardamos los valores reales para no perder el registro en la base de datos
    trial.set_user_attr("Err_Linea_Real", error_edad_linea)
    trial.set_user_attr("Edad_Cancha_Real", edad_descarga)
    trial.set_user_attr("Err_Ratio_Real", error_ratio)
    
    return fitness_total # Ahora solo retornamos UN valor

if __name__ == '__main__':
    # 1. Creamos el estudio Mono-Objetivo
    # Cambiamos "directions" por "direction" (singular)
    study = optuna.create_study(
        study_name="calibracion_final_", # Nuevo nombre para no mezclar BD
        storage="sqlite:///calibracion_romana_final.db", 
        load_if_exists=True, 
        direction="minimize" # Solo buscamos un mínimo general
    )
    
    print("\n==================================================")
    print("🚀 INICIANDO BÚSQUEDA MONO-OBJETIVO CON PENALIZACIONES...")
    print("==================================================")
    
    try:
        study.optimize(objective, n_trials=1000)
    except KeyboardInterrupt:
        print("\n[!] Optimización detenida manualmente por el usuario.")
    
    print(f'\n============== RESULTADO FINAL =====================\n')
    
    # En mono-objetivo, hay UN ganador absoluto, no una frontera de Pareto
    mejor_prueba = study.best_trial
    
    print(f"--- MEJOR SOLUCIÓN ENCONTRADA (Prueba #{mejor_prueba.number}) ---")
    print(f"Pesos  -> W1: {mejor_prueba.params['w1']:.2f} | W2: {mejor_prueba.params['w2']:.2f} | W3: {mejor_prueba.params['w3']:.2f}")
    
    # Recuperamos los valores reales que guardamos sin la multa
    print(f"🌲 Error Edad Línea (3.5m) : {mejor_prueba.user_attrs['Err_Linea_Real']:.3f} meses")
    print(f"🪵 Edad Media a Cancha    : {mejor_prueba.user_attrs['Edad_Cancha_Real']:.2f} meses")
    print(f"⚖️ Error Ratio (60%)       : {(mejor_prueba.user_attrs['Err_Ratio_Real']*100):.1f}%")
    print(f"Score Total (Con multas)   : {mejor_prueba.value:.3f}")

    print(f"\n✅ Proceso completado. Total de combinaciones evaluadas: {len(study.trials)}")