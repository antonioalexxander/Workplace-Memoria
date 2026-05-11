import pandas as pd
import numpy as np
from fitter import Fitter
import matplotlib.pyplot as plt
import streamlit as st
import os

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
    # Organización en Pestañas (Tabs)
    tab_dist, tab_trafico = st.tabs(["🎯 Ajuste de Distribuciones", "🚛 Tráfico de Camiones (Totales)"])

    # ==========================================
    # PESTAÑA 1: AJUSTE DE DISTRIBUCIONES
    # ==========================================
    with tab_dist:
        st.sidebar.header("⚙️ Configuración")
        variable = st.sidebar.selectbox(
            "Selecciona Variable:",
            ["Tiempo Entre Llegadas (Minutos)", "Volumen del Camión (M3SSC)", "Edad de la Madera (Meses)"]
        )
        
        dias_opciones = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo', 'Comparativa de todos los días']
        dia_seleccionado = st.sidebar.selectbox("Selecciona el Día:", dias_opciones)
        
        # Lista extendida de distribuciones para ingeniería
        distribuciones_industriales = [
            'norm',         # Normal (Campana de Gauss)
            'expon',        # Exponencial (Clásica para tiempos entre llegadas)
            'lognorm',      # Lognormal (Variables sesgadas a la derecha, sin negativos)
            'uniform',      # Uniforme (Cualquier valor entre A y B es igual de probable)
            'triang',       # Triangular (Basada en un Mínimo, Moda y Máximo)
            'weibull_min',  # Weibull (Excelente para tasas variables industriales)
            'gamma',        # Gamma (Similar a Weibull, para tiempos de espera)
            'beta'          # Beta (Muy flexible, acotada entre dos valores)
        ]
        
        dists_seleccionadas = st.sidebar.multiselect(
            "Distribuciones a evaluar:",
            distribuciones_industriales,
            # Dejamos seleccionadas por defecto las más comunes + Weibull y Uniforme
            default=['norm', 'expon', 'lognorm', 'uniform', 'weibull_min'] 
        )

        if st.sidebar.button("🚀 Ejecutar Ajuste"):
            nombres_dias = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
            
            if dia_seleccionado == 'Comparativa de todos los días':
                # Grid de 4x2 para ver todos los días uno al lado del otro
                fig, axes = plt.subplots(4, 2, figsize=(15, 20))
                axes = axes.flatten()
                
                for i, dia in enumerate(nombres_dias):
                    df_dia = df[df['Nombre_Dia'] == dia]
                    
                    # Selección de datos y limpieza (Outliers)
                    if variable == "Tiempo Entre Llegadas (Minutos)":
                        data = df_dia['Tiempo_Entre_Llegadas'].dropna()
                    elif variable == "Volumen del Camión (M3SSC)":
                        data = df_dia['M3SSC'].dropna()
                    else:
                        data = df_dia['Age(M)'].dropna()
                    
                    if len(data) > 10:
                        l_inf, l_sup = data.quantile(0.025), data.quantile(0.975)
                        data_clean = data[(data >= l_inf) & (data <= l_sup)].values
                        
                        f = Fitter(data_clean, distributions=dists_seleccionadas, timeout=30)
                        f.fit()
                        
                        plt.sca(axes[i])
                        
                        # Agregar el histograma real de fondo
                        axes[i].hist(data_clean, bins='auto', density=True, alpha=0.4, color='gray', edgecolor='black')
                        
                        # Trazar las curvas matemáticas encima
                        f.plot_pdf()
                        
                        axes[i].set_title(f"{dia} (n={len(data_clean)})")
                    else:
                        axes[i].text(0.5, 0.5, f"Sin datos suf. para {dia}", ha='center')
                
                # --- Estas líneas están fuera del 'for' ---
                plt.tight_layout()
                st.pyplot(fig)
            
            else:
                # Análisis de un solo día (el código que ya teníamos)
                df_dia = df[df['Nombre_Dia'] == dia_seleccionado]
                if variable == "Tiempo Entre Llegadas (Minutos)":
                    data = df_dia['Tiempo_Entre_Llegadas'].dropna()
                elif variable == "Volumen del Camión (M3SSC)":
                    data = df_dia['M3SSC'].dropna()
                else:
                    data = df_dia['Age(M)'].dropna()
                
                l_inf, l_sup = data.quantile(0.025), data.quantile(0.975)
                data_clean = data[(data >= l_inf) & (data <= l_sup)].values
                
                f = Fitter(data_clean, distributions=dists_seleccionadas)
                f.fit()
                
                col1, col2 = st.columns([2, 1])
                with col1:
                    fig, ax = plt.subplots()
                    f.summary()
                    st.pyplot(fig)
                with col2:
                    st.json(f.get_best())

    # ==========================================
    # PESTAÑA 2: TRÁFICO TOTAL (Suma de Camiones)
    # ==========================================
    # ==========================================
    # PESTAÑA 2: TRÁFICO TOTAL (Suma de Camiones)
    # ==========================================
    with tab_trafico:
        st.subheader("📊 Frecuencia Acumulada de Llegadas por Hora")
        st.markdown("Este histograma suma la cantidad total de camiones histórica para identificar los picos de demanda en la romana.")
        
        # Agrupamos por día de la semana y hora para contar camiones totales
        df_counts = df.groupby(['Dia_Semana', 'Nombre_Dia', 'Hora_Dia']).size().reset_index(name='Total_Camiones')
        
        # Grid para mostrar los 7 días. IMPORTANTE: Sin sharex=True para que todos tengan etiquetas
        fig_trafico, axes_t = plt.subplots(7, 1, figsize=(12, 28))
        
        nombres_dias = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
        max_y = df_counts['Total_Camiones'].max() * 1.1 # Escala igual para todos
        
        for i, dia in enumerate(nombres_dias):
            data_dia = df_counts[df_counts['Nombre_Dia'] == dia]
            
            # Asegurar que existan las 24 horas aunque tengan 0 camiones
            full_hours = pd.DataFrame({'Hora_Dia': range(24)})
            data_dia = full_hours.merge(data_dia, on='Hora_Dia', how='left').fillna(0)
            
            axes_t[i].bar(data_dia['Hora_Dia'], data_dia['Total_Camiones'], color='steelblue', edgecolor='black')
            axes_t[i].set_title(f"Total Camiones: {dia}", fontweight='bold')
            axes_t[i].set_ylabel("Cant. Camiones")
            axes_t[i].set_ylim(0, max_y)
            
            # Formatear el eje X con formato de RANGO de hora (ej: 00:00 - 01:00) en TODOS los gráficos
            etiquetas_rango = [f"{h:02d}:00 - {h+1:02d}:00" for h in range(24)]
            
            axes_t[i].set_xticks(range(24))
            axes_t[i].set_xticklabels(etiquetas_rango, rotation=45, ha='right')
            
        plt.tight_layout()
        st.pyplot(fig_trafico)