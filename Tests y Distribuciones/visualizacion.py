import pandas as pd
import numpy as np
from fitter import Fitter
import matplotlib.pyplot as plt
import streamlit as st
import os
from scipy.stats import poisson, nbinom
import json

# ==========================================
# CONFIGURACIÓN DE LA INTERFAZ
# ==========================================
st.set_page_config(page_title="Dashboard Logística - Recepción Maderas", layout="wide")

st.title("📊 Análisis de Distribución y Tráfico de Camiones")
st.markdown("Herramienta de soporte para la configuración del simulador SimPy y análisis de variabilidad operativa.")

# ==========================================
# CARGA Y PROCESAMIENTO
# ==========================================
@st.cache_data
def cargar_datos():
    directorio_script = os.path.dirname(os.path.abspath(__file__))
    ruta_archivo = os.path.join(directorio_script, "Base_Consolidada_Completa.xlsx")
    
    try:
        df = pd.read_excel(ruta_archivo)
    except Exception:
        st.error("Error al cargar la base. Verifica el archivo Excel.")
        return pd.DataFrame()

    df['Hora_Ingreso'] = pd.to_datetime(df['Hora_Ingreso'])
    df = df.sort_values('Hora_Ingreso')

    df['Dia_Semana'] = df['Hora_Ingreso'].dt.dayofweek
    df['Fecha_Exacta'] = df['Hora_Ingreso'].dt.date
    df['Hora_Dia'] = df['Hora_Ingreso'].dt.hour
    
    nombres_dias = {0: 'Lunes', 1: 'Martes', 2: 'Miércoles', 3: 'Jueves', 4: 'Viernes', 5: 'Sábado', 6: 'Domingo'}
    df['Nombre_Dia'] = df['Dia_Semana'].map(nombres_dias)

    # Tiempos entre llegadas agrupados por día exacto
    df['Tiempo_Entre_Llegadas'] = df.groupby('Fecha_Exacta')['Hora_Ingreso'].diff().dt.total_seconds() / 60
    
    return df

df = cargar_datos()

if not df.empty:
    # ==========================================
    # BARRA LATERAL DE CONTROL GLOBAL
    # ==========================================
    st.sidebar.header("⚙️ Configuración Global")
    
    variable = st.sidebar.selectbox(
        "1. Variable a analizar:",
        [
            "Tasa de Llegadas (Camiones por Hora)", 
            "Tiempo Entre Llegadas (Minutos)", 
            "Volumen del Camión (M3SSC)", 
            "Edad de la Madera (Meses)"
        ]
    )
    
    dias_ordenados = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
    dias_seleccionados = st.sidebar.multiselect(
        "2. Selecciona los Días a Agrupar:", 
        options=dias_ordenados,
        default=['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes']
    )
    
    rango_horas = st.sidebar.selectbox(
        "3. Tamaño del Bloque Horario:", 
        options=[1, 2, 3, 4, 6, 8, 12], 
        index=3, 
        format_func=lambda x: f"Bloques de {x} hora(s)"
    )
    
    distribuciones_industriales = ['norm', 'expon', 'lognorm', 'uniform', 'triang', 'weibull_min', 'gamma']
    
    if variable == "Tasa de Llegadas (Camiones por Hora)":
        st.sidebar.info("📌 Para esta variable discreta, se ajustará automáticamente una Distribución de Poisson.")
        dists_seleccionadas = []
    else:
        dists_seleccionadas = st.sidebar.multiselect(
            "4. Distribuciones a evaluar:", 
            distribuciones_industriales, 
            default=['norm', 'expon', 'lognorm', 'uniform', 'weibull_min']
        )

    tab_dist, tab_trafico = st.tabs(["🎯 Ajuste de Distribuciones", "🚛 Tráfico de Camiones (Totales)"])

    # ==========================================
    # PESTAÑA 1: AJUSTE DE DISTRIBUCIONES
    # ==========================================
    with tab_dist:
        if not dias_seleccionados:
            st.warning("⚠️ Por favor, selecciona al menos un día en la barra lateral para iniciar el análisis.")
        else:
            modo_vista = st.radio(
                "Modo de Visualización:", 
                ["Un solo gráfico consolidado", "Comparativa: Por Bloques Horarios"], 
                horizontal=True
            )

            if st.button("🚀 Ejecutar Ajuste Matemático"):
                
                df_filtro = df[df['Nombre_Dia'].isin(dias_seleccionados)]
                texto_dias_comb = ", ".join(dias_seleccionados)
                
                def obtener_datos(df_subset):
                    if variable == "Tasa de Llegadas (Camiones por Hora)":
                        conteo = df_subset.groupby(['Fecha_Exacta', 'Hora_Dia']).size()
                        return conteo.values
                    elif variable == "Tiempo Entre Llegadas (Minutos)":
                        return df_subset['Tiempo_Entre_Llegadas'].dropna().values
                    elif variable == "Volumen del Camión (M3SSC)":
                        return df_subset['M3SSC'].dropna().values
                    else:
                        return df_subset['Age(M)'].dropna().values

                # ----------------------------------------------------
                # MODO 1: COMPARATIVA POR BLOQUES HORARIOS
                # ----------------------------------------------------
                if modo_vista == "Comparativa: Por Bloques Horarios":
                    bloques_posibles = list(range(0, 24, rango_horas))
                    cols = 2
                    rows = int(np.ceil(len(bloques_posibles) / cols))
                    
                    fig, axes = plt.subplots(rows, cols, figsize=(15, rows * 5))
                    axes = axes.flatten() if len(bloques_posibles) > 1 else [axes]
                    
                    resultados_bloques = {}
                    
                    for i, b in enumerate(bloques_posibles):
                        df_bloque = df_filtro[(df_filtro['Hora_Dia'] >= b) & (df_filtro['Hora_Dia'] < b + rango_horas)]
                        data_cruda = obtener_datos(df_bloque)
                        etiqueta_rango = f"{b:02d}:00 - {b+rango_horas:02d}:00"
                        
                        if len(data_cruda) > 10:
                            l_inf, l_sup = np.quantile(data_cruda, 0.0), np.quantile(data_cruda, 0.975)
                            data_clean = data_cruda[(data_cruda >= l_inf) & (data_cruda <= l_sup)]
                            
                            plt.sca(axes[i])
                            
                            # --- LÓGICA DISCRETA ---
                            if variable == "Tasa de Llegadas (Camiones por Hora)":
                                lambda_val = np.mean(data_clean)
                                max_val = int(np.max(data_clean))
                                
                                bins_discretos = np.arange(0, max_val + 2) - 0.5
                                axes[i].hist(data_clean, bins=bins_discretos, density=True, alpha=0.5, color='#1f77b4', edgecolor='black')
                                
                                x_poisson = np.arange(0, max_val + 1)
                                y_poisson = poisson.pmf(x_poisson, lambda_val)
                                axes[i].plot(x_poisson, y_poisson, 'ro-', lw=2, label=f'Poisson (λ={lambda_val:.2f})')
                                
                                varianza = np.var(data_clean)
                                if varianza > lambda_val: 
                                    p = lambda_val / varianza
                                    n = (lambda_val**2) / (varianza - lambda_val)
                                    y_nbinom = nbinom.pmf(x_poisson, n, p)
                                    axes[i].plot(x_poisson, y_nbinom, 'go-', lw=2, label=f'Binomial Neg. (n={n:.1f}, p={p:.2f})')
                                
                                axes[i].legend()
                                axes[i].set_title(f"Bloque {etiqueta_rango} | Discretas", fontweight='bold')
                                
                                resultados_bloques[etiqueta_rango] = {
                                    "Poisson_lambda": lambda_val, 
                                    "Varianza": varianza,
                                    "Sobredispersión": bool(varianza > lambda_val)
                                }
                                
                            # --- LÓGICA CONTINUA (USANDO KS) ---
                            else:
                                f = Fitter(data_clean, distributions=dists_seleccionadas, timeout=30)
                                f.fit()
                                
                                # Extraer el ganador basado en el estadístico KS (el más cercano a 0)
                                resumen_estadistico = f.summary(Nbest=len(dists_seleccionadas), plot=False)
                                resumen_ordenado = resumen_estadistico.sort_values(by='ks_statistic', ascending=True)
                                nombre_ganador = resumen_ordenado.index[0]
                                mejor_dist = {nombre_ganador: f.fitted_param[nombre_ganador]}
                                
                                resultados_bloques[etiqueta_rango] = mejor_dist
                                
                                if variable == "Tiempo Entre Llegadas (Minutos)":
                                    max_val = int(np.ceil(np.max(data_clean)))
                                    bins_grafico = np.arange(0, max_val + 2)
                                else:
                                    bins_grafico = 'auto'
                                    
                                # 1. Dibujar el histograma explícitamente en 'ax'
                                ax.hist(data_clean, bins=bins_grafico, density=True, alpha=0.4, color='gray', edgecolor='black', label='Datos Históricos')
                                
                                # 2. Dibujar las distribuciones de Fitter
                                f.plot_pdf() 
                                
                                # 3. Forzar el título y las etiquetas explícitamente en el objeto 'ax'
                                ax.set_title(f"{variable}\n[Días: {texto_dias_comb}]", fontweight='bold', fontsize=14)
                                ax.set_xlabel("Valor", fontweight='bold')
                                ax.set_ylabel("Densidad", fontweight='bold')
                                
                                # 4. Forzar la leyenda para mostrar tanto el histograma como las curvas
                                ax.legend()
                                
                                # 5. Ajustar el layout antes de enviar a Streamlit
                                fig.tight_layout()
                                
                                # 6. Renderizar
                                st.pyplot(fig)
                        else:
                            axes[i].text(0.5, 0.5, f"Sin datos suficientes\n(n={len(data_cruda)})", ha='center', va='center')
                            axes[i].set_title(f"Bloque {etiqueta_rango}", fontweight='bold')
                            resultados_bloques[etiqueta_rango] = "Datos insuficientes"
                    
                    for j in range(i + 1, len(axes)):
                        fig.delaxes(axes[j])
                        
                    plt.tight_layout()
                    st.pyplot(fig)
                    st.markdown(f"### 📋 Parámetros por Bloque Horario (Datos combinados de: {texto_dias_comb})")
                    st.json(resultados_bloques)
                    
                    json_data = json.dumps(resultados_bloques, indent=4, ensure_ascii=False)
                    st.download_button(
                        label="📥 Descargar Configuración (.json)",
                        data=json_data,
                        file_name="config_llegadas.json",
                        mime="application/json"
                    )

                # ----------------------------------------------------
                # MODO 2: UN SOLO GRÁFICO CONSOLIDADO
                # ----------------------------------------------------
                else:
                    data_cruda = obtener_datos(df_filtro)
                    
                    if len(data_cruda) > 10:
                        l_inf, l_sup = np.quantile(data_cruda, 0.0), np.quantile(data_cruda, 0.975)
                        data_clean = data_cruda[(data_cruda >= l_inf) & (data_cruda <= l_sup)]
                        
                        col1, col2 = st.columns([2, 1])
                        with col1:
                            fig, ax = plt.subplots(figsize=(10, 6))
                            
                            # --- LÓGICA DISCRETA ---
                            if variable == "Tasa de Llegadas (Camiones por Hora)":
                                lambda_val = np.mean(data_clean)
                                max_val = int(np.max(data_clean))
                                bins_discretos = np.arange(0, max_val + 2) - 0.5
                                ax.hist(data_clean, bins=bins_discretos, density=True, alpha=0.5, color='#1f77b4', edgecolor='black')
                                
                                x_poisson = np.arange(0, max_val + 1)
                                y_poisson = poisson.pmf(x_poisson, lambda_val)
                                ax.plot(x_poisson, y_poisson, 'ro-', lw=2, label=f'Poisson (λ={lambda_val:.2f})')
                                
                                varianza = np.var(data_clean)
                                hay_sobredispersion = varianza > lambda_val
                                if hay_sobredispersion:
                                    p = lambda_val / varianza
                                    n = (lambda_val**2) / (varianza - lambda_val)
                                    y_nbinom = nbinom.pmf(x_poisson, n, p)
                                    ax.plot(x_poisson, y_nbinom, 'go-', lw=2, label=f'Binomial Neg. (n={n:.1f}, p={p:.2f})')
                                
                                ax.legend()
                                plt.title(f"Tasa de Llegadas - Ajuste Discreto\n[Días: {texto_dias_comb}]", fontweight='bold')
                                st.pyplot(fig)
                                
                                with col2:
                                    st.markdown("### 🏆 Análisis Discreto")
                                    st.info(f"Promedio (λ): **{lambda_val:.2f} camiones/hora**\nVarianza: **{varianza:.2f}**")
                                    
                                    if hay_sobredispersion:
                                        st.success("⚠️ **Hay sobredispersión.**\nLa Binomial Negativa modela mejor los grupos de camiones.")
                                        st.json({"n": n, "p": p})
                                    else:
                                        st.info("✅ **La varianza es baja.**\nLa distribución de Poisson es el mejor modelo para este caso.")
                            
                            # --- LÓGICA CONTINUA (USANDO KS) ---
                            else:
                                f = Fitter(data_clean, distributions=dists_seleccionadas)
                                f.fit()
                                
                                resumen_estadistico = f.summary(Nbest=len(dists_seleccionadas), plot=False)
                                resumen_ordenado = resumen_estadistico.sort_values(by='ks_statistic', ascending=True)
                                nombre_ganador = resumen_ordenado.index[0]
                                mejor_dist = {nombre_ganador: f.fitted_param[nombre_ganador]}
                                
                                if variable == "Tiempo Entre Llegadas (Minutos)":
                                    max_val = int(np.ceil(np.max(data_clean)))
                                    bins_grafico = np.arange(0, max_val + 2)
                                else:
                                    bins_grafico = 'auto'
                                    
                                ax.hist(data_clean, bins=bins_grafico, density=True, alpha=0.4, color='gray', edgecolor='black')
                                f.plot_pdf()
                                plt.title(f"{variable}\n[Días: {texto_dias_comb}]", fontweight='bold')
                                st.pyplot(fig)
                                
                                with col2:
                                    st.markdown(f"### 🏆 Distribución Ganadora (KS: {nombre_ganador})")
                                    st.json(mejor_dist)
                                    st.markdown("**Ranking Completo (Ordenado por KS):**")
                                    st.dataframe(resumen_ordenado[['sumsquare_error', 'ks_statistic', 'ks_pvalue']])
                    else:
                        st.warning("No hay suficientes datos.")

    # ==========================================
    # PESTAÑA 2: TRÁFICO TOTAL (Suma de Camiones por Bloques)
    # ==========================================
    with tab_trafico:
        st.subheader("📊 Frecuencia Acumulada de Llegadas por Bloques Horarios")
        st.markdown("Este histograma suma la cantidad total histórica de camiones en los bloques horarios definidos.")
        
        df_trafico = df.copy()
        df_trafico['Bloque_Inicio'] = (df_trafico['Hora_Dia'] // rango_horas) * rango_horas
        
        df_counts = df_trafico.groupby(['Dia_Semana', 'Nombre_Dia', 'Bloque_Inicio']).size().reset_index(name='Total_Camiones')
        
        bloques_posibles = list(range(0, 24, rango_horas))
        full_blocks = pd.DataFrame({'Bloque_Inicio': bloques_posibles})
        
        fig_trafico, axes_t = plt.subplots(7, 1, figsize=(12, 28))
        max_y = df_counts['Total_Camiones'].max() * 1.1 if not df_counts.empty else 10
            
        for i, dia in enumerate(dias_ordenados):
            data_dia = df_counts[df_counts['Nombre_Dia'] == dia]
            data_dia = full_blocks.merge(data_dia, on='Bloque_Inicio', how='left').fillna(0)
            
            x_pos = np.arange(len(bloques_posibles))
            
            axes_t[i].bar(x_pos, data_dia['Total_Camiones'], color='steelblue', edgecolor='black', width=0.8)
            axes_t[i].set_title(f"Total Camiones: {dia}", fontweight='bold')
            axes_t[i].set_ylabel("Cant. Camiones")
            axes_t[i].set_ylim(0, max_y)
            
            etiquetas_rango = [f"{b:02d}:00 - {b + rango_horas:02d}:00" for b in bloques_posibles]
            axes_t[i].set_xticks(x_pos)
            axes_t[i].set_xticklabels(etiquetas_rango, rotation=45, ha='right')
            
        plt.tight_layout()
        st.pyplot(fig_trafico)