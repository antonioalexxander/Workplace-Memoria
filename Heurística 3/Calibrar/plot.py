import optuna
import pandas as pd

# 1. CARGAR DATOS
study = optuna.load_study(study_name="calibracion_final", storage="sqlite:///calibracion_romana.db")
df = study.trials_dataframe()
df = df[df['state'] == 'COMPLETE'].rename(columns={
    'values_0': 'Err_Linea', 'values_1': 'Edad_Cancha', 'values_2': 'Err_Ratio',
    'params_w1': 'W1', 'params_w2': 'W2', 'params_w3': 'W3'
})

# ==========================================
# FILTRADO DE SUPERVIVENCIA (La "Criba" Industrial)
# ==========================================
# Definimos límites tolerables para la operación
max_error_ratio = 0.04  # No aceptamos más de 4% de error en el flujo (60% +/- 4)
max_error_linea = 0.30  # No aceptamos más de 0.3 meses de error en la línea

# Aplicamos el filtro
df_validas = df[(df['Err_Ratio'] <= max_error_ratio) & (df['Err_Linea'] <= max_error_linea)]

if not df_validas.empty:
    # De las que sobreviven, buscamos la que tenga la MEJOR (mínima) edad a cancha
    idx_mejor_cancha = df_validas['Edad_Cancha'].idxmin()
    
    # También buscamos el equilibrio por rangos dentro de las soluciones válidas
    df_validas['Rank_L'] = df_validas['Err_Linea'].rank()
    df_validas['Rank_C'] = df_validas['Edad_Cancha'].rank()
    idx_equilibrio_real = (df_validas['Rank_L'] + df_validas['Rank_C']).idxmin()
else:
    idx_mejor_cancha = None
    idx_equilibrio_real = None
    print("⚠️ No se encontraron soluciones que cumplan con los límites de la criba.")

# ==========================================
# EXTREMOS GLOBALES (Enfoque en un solo KPI)
# ==========================================
# Buscamos el mínimo absoluto en toda la base de datos (ignorando restricciones)
idx_extremo_linea = df['Err_Linea'].idxmin()
idx_extremo_cancha = df['Edad_Cancha'].idxmin()
idx_extremo_ratio = df['Err_Ratio'].idxmin()

# ==========================================
# REPORTE DE RESULTADOS
# ==========================================
def imprimir_resultado(nombre, idx):
    if idx is None: return
    fila = df.loc[idx]
    print(f"\n--- {nombre} ---")
    print(f"Pesos -> W1: {fila['W1']:.0f} | W2: {fila['W2']:.0f} | W3: {fila['W3']:.0f}")
    print(f"🌲 Error Edad Línea : {fila['Err_Linea']:.3f} meses")
    print(f"🪵 Edad a Cancha    : {fila['Edad_Cancha']:.2f} meses")
    print(f"⚖️ Error Ratio       : {(fila['Err_Ratio']*100):.1f}%")

print("==================================================")
print("🔍 REPORTE DE EQUILIBRIO Y POLÍTICAS EXTREMAS")
print("==================================================")

print("\n>>> ESCENARIOS FACTIBLES (Pasan el Filtro Industrial) <<<")
imprimir_resultado("EL EQUILIBRIO REAL (Prioriza Cancha dentro de los límites)", idx_mejor_cancha)
imprimir_resultado("EQUILIBRIO POR RANGOS (Balance estable general)", idx_equilibrio_real)

print("\n--------------------------------------------------")
print(">>> POLÍTICAS EXTREMAS (Ignorando restricciones operativas) <<<")
print("--------------------------------------------------")
imprimir_resultado("ENFOQUE ABSOLUTO EN LÍNEA (Calidad de Celulosa Pura)", idx_extremo_linea)
imprimir_resultado("ENFOQUE ABSOLUTO EN CANCHA (Renovación Extrema de Acopio)", idx_extremo_cancha)
imprimir_resultado("ENFOQUE ABSOLUTO EN FLUJO (Logística de Grúas Pura)", idx_extremo_ratio)