import pandas as pd
from stable_baselines3 import PPO
from envRL import PulpYardEnv  # Asegúrate de que este nombre sea correcto según tu archivo

print("🧠 Cargando el cerebro de la Inteligencia Artificial...")
try:
    modelo_ia = PPO.load("./modelos_ia/romana_ppo_final")
    print("✅ ¡Cerebro cargado con éxito!")
except FileNotFoundError:
    print("❌ Error: No se encontró el archivo del modelo.")
    exit()

print("\n🏭 Iniciando simulación de evaluación operada EXCLUSIVAMENTE por la IA...\n")

# Usamos EXACTAMENTE el mismo entorno del entrenamiento
env_eval = PulpYardEnv(dias_simulacion=30)
obs, info = env_eval.reset()

terminado = False
while not terminado:
    accion, _ = modelo_ia.predict(obs, deterministic=True)
    obs, recompensa, terminado, truncado, info = env_eval.step(accion)

facility = env_eval.facility

# Forzar el guardado del último día
last_recorded = len(facility.daily_stats)
if last_recorded < 30:
    facility._record_daily_snapshot(last_recorded + 1)

print("🏁 Simulación finalizada.\n")

df_daily = pd.DataFrame(facility.daily_stats)
if not df_daily.empty:
    df_daily['mean_feed_age_months'] = (df_daily['mean_feed_age_days'] / 30.4167).round(2)
    df_daily['mean_stock_age_months'] = (df_daily['mean_stock_age_days'] / 30.4167).round(2)

pd.set_option('display.float_format', '{:.2f}'.format)
pd.set_option('display.max_rows', 60)

print("================================================================")
print(" 🏆 RESULTADOS DEL AGENTE DE REINFORCEMENT LEARNING (PPO) 🏆")
print("================================================================\n")

print("[1] RESUMEN DE LA OPERACIÓN DIARIA (Edades en Meses)")
cols_to_show = ['day', 'mean_feed_age_months', 'mean_stock_age_months', 'total_stock_vol', 
                'starvation_min', 'vol_direct', 'vol_stock', 'mean_truck_wait_min']
print(df_daily[cols_to_show].to_string(index=False))

ratio, edad_lin, espera, inanicion, edad_rut_patio, edad_fin_patio, std_feed = facility.get_metrics()

print("\n[2] INDICADORES CLAVE DE DESEMPEÑO (KPIs FINALES)")
print(f"  • Ratio Picado Directo : {ratio*100:.1f}%")
print(f"  • Edad Promedio Mezcla : {edad_lin / 30.4167:.2f} meses")
print(f"  • Varianza Diaria      : {std_feed:.2f} meses")
print(f"  • Edad Final del Patio : {edad_fin_patio / 30.4167:.2f} meses")
print(f"  • Inanición Total      : {inanicion} minutos")
print(f"  • Espera Promedio Fila : {espera:.2f} minutos por camión")
print("================================================================\n")