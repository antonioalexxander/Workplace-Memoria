import simpy
import pandas as pd
import numpy as np
import random
from scipy import stats 
import concurrent.futures
from pulpsim import PulpFacilitySimulation, algorithm_strategy
from heuristica import Romana
from operador import OperadorHumano


# ==========================================
# 1. DEFINICIÓN DE ESCENARIOS
# ==========================================
escenarios = [
    {
        "nombre": "CASO BASE (Operación Normal)",
        "params": {} 
    },
    {
        "nombre": "ESCENARIO 1: Flujo Extremo (+40% llegadas de camiones)",
        "params": {"arrival_multiplier": 0.6} 
    },
    {
        "nombre": "ESCENARIO 2: Crisis de Edades Bosque (Polarizada 1 y 8 meses)",
        "params": {"age_crisis": True} 
    },
    {
        "nombre": "ESCENARIO 3: Caída de Demanda en Planta (-20% consumo)",
        "params": {"line_demand_tons_min": 2.0} 
    },
    {
        "nombre": "ESCENARIO 4: Herencia Crítica (Patio iniciado con 8 meses de vejez)",
        "params": {"override_init_age_days": 360.0} 
    },
    {
        "nombre": "ESCENARIO 5: Colapso Logístico (Descargas lentas x3)",
        "params": {"unload_delay_multiplier": 3.0} 
    }
]

def ejecutar_simulacion(nombre_escenario, algoritmo, dias=30, **kwargs):
    env = simpy.Environment()
    facility = PulpFacilitySimulation(env, strategy_func=algorithm_strategy, **kwargs)
    facility.algorithm = algoritmo 
    facility.run()
    env.run(until=dias * 24 * 60)
    
    if len(facility.daily_stats) < dias:
        facility._record_daily_snapshot(len(facility.daily_stats) + 1)
        
    return facility

# ==========================================
# 2. FUNCIÓN DE PROCESAMIENTO PARALELO
# ==========================================
def procesar_escenario(esc):
    nombre_esc = esc["nombre"]
    params_esc = esc["params"]
    
    # --- CONFIGURACIÓN ---
    N_ITERACIONES = 100
    DIAS_SIMULACION = 180
    W1_opt, W2_opt, W3_opt, W4_opt = 4098, 8, 16, 172 

    metricas_globales_humano = []
    metricas_globales_ia = []
    dfs_diarios_humano = []
    dfs_diarios_ia = []
    cancha_final_humano = []
    cancha_final_ia = []

    for i in range(N_ITERACIONES):
        # --- ESCENARIO HUMANO ---
        random.seed(i)  
        np.random.seed(i)
        operador = OperadorHumano()
        sim_humano = ejecutar_simulacion("Operador", operador, DIAS_SIMULACION, **params_esc)
        
        metricas_globales_humano.append(sim_humano.get_metrics())
        df_h = pd.DataFrame(sim_humano.daily_stats)
        df_h['iteracion'] = i + 1
        dfs_diarios_humano.append(df_h)
        
        for area_id, columnas in sim_humano.stock_areas.items():
            for col in columnas:
                cancha_final_humano.append({
                    'iteracion': i, 'Area': area_id, 'Columna': col.name,
                    'Vol_Humano': col.container.level,
                    'Edad_Humano': col.current_age / 30.4167 if col.container.level > 0 else 0.0
                })
        
        # --- ESCENARIO ALGORITMO ---
        random.seed(i)  
        np.random.seed(i)
        romana_ai = Romana(w1=W1_opt, w2=W2_opt, w3=W3_opt, w4=W4_opt)
        sim_ia = ejecutar_simulacion("Algoritmo", romana_ai, DIAS_SIMULACION, **params_esc)
        
        metricas_globales_ia.append(sim_ia.get_metrics())
        df_ia = pd.DataFrame(sim_ia.daily_stats)
        df_ia['iteracion'] = i + 1
        dfs_diarios_ia.append(df_ia)

        for area_id, columnas in sim_ia.stock_areas.items():
            for col in columnas:
                cancha_final_ia.append({
                    'iteracion': i, 'Area': area_id, 'Columna': col.name,
                    'Vol_IA': col.container.level,
                    'Edad_IA': col.current_age / 30.4167 if col.container.level > 0 else 0.0
                })
        # AGREGA ESTAS DOS LÍNEAS AQUÍ:
        if (i+1) % 5 == 0 or i == 0:
            print(f"      -> Procesando iteración {i+1} de {N_ITERACIONES}...")

    # --- AGREGACIÓN DE RESULTADOS ---
    avg_humano = np.mean(metricas_globales_humano, axis=0)
    avg_ia = np.mean(metricas_globales_ia, axis=0)
    df_diario_humano_total = pd.concat(dfs_diarios_humano, ignore_index=True)
    df_diario_ia_total = pd.concat(dfs_diarios_ia, ignore_index=True)

    # --- CONSTRUCCIÓN DEL TEXTO DE REPORTE ---
    out = []
    out.append("\n" + "#"*100)
    out.append(f" RESULTADOS: {nombre_esc.upper()}")
    out.append("#"*100)

    tabla_comparativa = pd.DataFrame({
        f"Métrica Promedio ({N_ITERACIONES} sim)": [
            "Ratio Picado Directo (%)", "Edad Promedio Mezcla (Meses)", 
            "Edad Final Patio (Meses)", "Inanición Total (Min)", "Espera Camiones (Min)"
        ],
        "Operador": [f"{avg_humano[0]*100:.1f}%", f"{avg_humano[1]/30.4167:.2f}", f"{avg_humano[5]/30.4167:.2f}", f"{avg_humano[3]:.0f}", f"{avg_humano[2]:.1f}"],
        "Algoritmo": [f"{avg_ia[0]*100:.1f}%", f"{avg_ia[1]/30.4167:.2f}", f"{avg_ia[5]/30.4167:.2f}", f"{avg_ia[3]:.0f}", f"{avg_ia[2]:.1f}"]
    })
    
    def calcular_estadisticas(df, columna, factor=1.0):
        serie = df[columna].dropna() / factor
        return [f"{serie.mean():.2f}", f"{serie.std():.2f}", f"{serie.min():.2f}", f"{serie.max():.2f}", f"{serie.quantile(0.90):.2f}", f"{serie.quantile(0.99):.2f}"]

    etiquetas_stats = ["Media", "Desv. Est", "Mínimo", "Máximo", "P90", "P99"]
    df_stats_espera = pd.DataFrame({"Estadística": etiquetas_stats, "Operador (Min)": calcular_estadisticas(df_diario_humano_total, 'mean_truck_wait_min', 1.0), "Algoritmo (Min)": calcular_estadisticas(df_diario_ia_total, 'mean_truck_wait_min', 1.0)})

    resultados_test = []
    for nombre, idx, factor in [("Ratio (%)", 0, 100), ("Edad Mezcla", 1, 1/30.4167), ("Varianza", 6, 1.0), ("Edad Patio", 5, 1/30.4167), ("Espera Camiones", 2, 1.0)]:
        vals_h = [m[idx] * factor for m in metricas_globales_humano]
        vals_ia = [m[idx] * factor for m in metricas_globales_ia]
        t_stat, p_val = stats.ttest_rel(vals_h, vals_ia)
        mean_h, mean_i = np.mean(vals_h), np.mean(vals_ia)
        
        if np.isnan(p_val): conclusion = "Empate"
        elif p_val < 0.05:
            if "Ratio" in nombre: conclusion = "Algoritmo mejor" if abs(mean_i - 60) < abs(mean_h - 60) else "Operador mejor"
            elif "Edad Mezcla" in nombre: conclusion = "Algoritmo mejor" if abs(mean_i - 3.5) < abs(mean_h - 3.5) else "Operador mejor"
            else: conclusion = "Algoritmo mejor" if mean_i < mean_h else "Operador mejor"
        else: conclusion = "Empate Estadístico"
        
        resultados_test.append({"KPI": nombre, "p-value": "N/A" if np.isnan(p_val) else f"{p_val:.4f}", "Mejor": conclusion})

    out.append("\nRESUMEN GLOBAL PROMEDIO:")
    out.append(tabla_comparativa.to_string(index=False))
    out.append("\nANÁLISIS DE ESPERA DE CAMIONES EN PORTERÍA:")
    out.append(df_stats_espera.to_string(index=False))
    out.append("\nPRUEBA DE HIPÓTESIS (TEST T-PAREADO):")
    out.append(pd.DataFrame(resultados_test).to_string(index=False))

    resumen_dict = {
        'Calidad Operador': avg_humano[1]/30.4167, 'Calidad Algoritmo': avg_ia[1]/30.4167,
        'Patio Operador': avg_humano[5]/30.4167, 'Patio Algoritmo': avg_ia[5]/30.4167,
        'Espera Operador': avg_humano[2], 'Espera Algoritmo': avg_ia[2],
        'Starvation Operador': avg_humano[3], 'Starvation Algoritmo': avg_ia[3]
    }

    return nombre_esc, "\n".join(out), resumen_dict

# ==========================================
# 3. EJECUCIÓN PARALELA ULTRA-RÁPIDA (CON JOBLIB)
# ==========================================
if __name__ == "__main__":
    from joblib import Parallel, delayed
    import multiprocessing

    num_nucleos = multiprocessing.cpu_count()
    print(f"\n🚀 INICIANDO EJECUCIÓN EN PARALELO ACELERADA...")
    print(f"   Utilizando {num_nucleos} núcleos de tu procesador. Esto será mucho más rápido.\n")

    # joblib se encarga de repartir los escenarios en tus núcleos sin colapsar macOS
    resultados = Parallel(n_jobs=-1)(delayed(procesar_escenario)(esc) for esc in escenarios)

    reportes_texto = []
    resumen_ejecutivo = {}

    # Recopilamos y mostramos lo que joblib procesó en paralelo
    for nombre_esc, texto_reporte, dict_resumen in resultados:
        reportes_texto.append(texto_reporte)
        resumen_ejecutivo[nombre_esc] = dict_resumen
        print(texto_reporte)

    # Construir tabla final resumen
    texto_final = []
    texto_final.append("\n" + "="*100)
    texto_final.append(" 🏆 REPORTE FINAL: ANÁLISIS DE SENSIBILIDAD MULTI-ESCENARIO")
    texto_final.append("="*100)
    df_resumen = pd.DataFrame.from_dict(resumen_ejecutivo, orient='index')
    texto_final.append(df_resumen.round(2).to_string())
    texto_final.append("="*100 + "\n")

    print("\n".join(texto_final))

    # ==========================================
    # 4. EXPORTAR TODO A ARCHIVO .TXT
    # ==========================================
    nombre_archivo = "reporte_escenarios.txt"
    with open(nombre_archivo, "w", encoding="utf-8") as f:
        f.write("REPORTE DE SIMULACIÓN Y ANÁLISIS DE SENSIBILIDAD\n")
        f.write("="*100 + "\n")
        for reporte in reportes_texto:
            f.write(reporte)
            f.write("\n")
        f.write("\n".join(texto_final))
    
    print(f"✅ ¡Todo finalizado a máxima velocidad! Resultados guardados en: {nombre_archivo}")