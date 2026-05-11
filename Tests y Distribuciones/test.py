import pandas as pd
import numpy as np
from fitter import Fitter
import matplotlib.pyplot as plt
import os

# ==========================================
# 1. CARGA Y PREPARACIÓN DE DATOS
# ==========================================
directorio_script = os.path.dirname(os.path.abspath(__file__))
ruta_archivo = os.path.join(directorio_script, "Base_Consolidada_Completa.xlsx")

print("Cargando la base de datos...")
df = pd.read_excel(ruta_archivo)

# Asegurarse de que Hora_Ingreso es datetime
df['Hora_Ingreso'] = pd.to_datetime(df['Hora_Ingreso'])
df = df.sort_values('Hora_Ingreso')

# Extraer el día de la semana (0=Lunes, 6=Domingo), la fecha exacta y la hora
df['Dia_Semana'] = df['Hora_Ingreso'].dt.dayofweek
df['Fecha_Exacta'] = df['Hora_Ingreso'].dt.date
df['Hora_Dia'] = df['Hora_Ingreso'].dt.hour

nombres_dias = {0: 'Lunes', 1: 'Martes', 2: 'Miércoles', 3: 'Jueves', 4: 'Viernes', 5: 'Sábado', 6: 'Domingo'}
df['Nombre_Dia'] = df['Dia_Semana'].map(nombres_dias)

# a) Datos de Volumen
datos_volumen = df[(df['M3SSC'] > 5) & (df['M3SSC'] <= 100)]['M3SSC'].dropna().values

# b) Datos de Edad
datos_edad = df[(df['Age(M)'] <= 25)]['Age(M)'].dropna().values

# c) Calcular Tiempo entre Llegadas (en minutos) CORRECTAMENTE por día
# Agrupamos por fecha exacta para no restar el último camión del lunes con el primero del martes
df['Tiempo_Entre_Llegadas'] = df.groupby('Fecha_Exacta')['Hora_Ingreso'].diff().dt.total_seconds() / 60

# ==========================================
# 2. FUNCIONES DE ANÁLISIS
# ==========================================

def probar_distribuciones(datos, nombre_variable):
    """Prueba distribuciones para un conjunto de datos y guarda el gráfico."""
    print(f"\n{'-'*50}")
    print(f"Iniciando Test de Ajuste para: {nombre_variable}")
    print(f"Cantidad de datos a analizar: {len(datos)}")
    print(f"{'-'*50}")
    
    if len(datos) < 10:
        print("⚠️ No hay suficientes datos para ajustar una distribución.")
        return

    distribuciones_industriales = ['norm', 'expon', 'lognorm', 'uniform', 'triang']
    
    f = Fitter(datos, distributions=distribuciones_industriales, timeout=60)
    f.fit()
    
    mejor = f.get_best(method='sumsquare_error')
    nombre_mejor = list(mejor.keys())[0]
    parametros = mejor[nombre_mejor]
    
    print(f"\n🌟 LA MEJOR DISTRIBUCIÓN ES: {nombre_mejor.upper()} 🌟")
    print(f"Parámetros a usar en tu simulador: {parametros}")
    
    plt.figure(figsize=(10, 6))
    f.summary()
    plt.title(f"Ajuste de Distribución: {nombre_variable}")
    plt.xlabel("Valor")
    plt.ylabel("Frecuencia")
    
    nombre_seguro = nombre_variable.replace(" ", "_").replace("(", "").replace(")", "").replace("Ó", "O")
    ruta_imagen = os.path.join(directorio_script, f"Dist_{nombre_seguro}.png")
    
    plt.savefig(ruta_imagen, dpi=300, bbox_inches='tight')
    print(f"📸 Gráfico guardado exitosamente como: Dist_{nombre_seguro}.png")
    plt.close()

def analizar_llegadas_por_hora(df_datos):
    """Genera histogramas de llegadas por hora para cada día de la semana con el mismo eje Y."""
    print(f"\n{'-'*50}")
    print("Generando Histogramas Horarios (24 Bins) por Día de la Semana...")
    print(f"{'-'*50}")
    
    # 1. Encontrar el límite máximo para el eje Y (para que todos los gráficos sean comparables)
    # Contamos camiones agrupados por Día exacto, Día de semana y Hora
    conteos_por_hora = df_datos.groupby(['Fecha_Exacta', 'Dia_Semana', 'Hora_Dia']).size().reset_index(name='Camiones')
    # Sacamos el promedio de camiones que llegan en una hora específica para cada día de la semana
    promedio_llegadas_hora = conteos_por_hora.groupby(['Dia_Semana', 'Hora_Dia'])['Camiones'].mean().reset_index()
    
    # Calculamos el Y máximo de todos los días y le sumamos un 10% de margen
    if not promedio_llegadas_hora.empty:
        max_y = promedio_llegadas_hora['Camiones'].max() * 1.1 
    else:
        max_y = 10
        
    # 2. Generar un gráfico por cada día de la semana
    for dia_idx in range(7):
        nombre_dia = nombres_dias[dia_idx]
        datos_dia = promedio_llegadas_hora[promedio_llegadas_hora['Dia_Semana'] == dia_idx]
        
        plt.figure(figsize=(12, 6))
        
        # Si hay datos, graficamos las 24 horas (bins)
        if not datos_dia.empty:
            plt.bar(datos_dia['Hora_Dia'], datos_dia['Camiones'], color='#2ca02c', width=0.8, edgecolor='black')
        
        plt.title(f"Promedio de Camiones por Hora - {nombre_dia}", fontsize=14)
        plt.xlabel("Hora del Día (0 - 23)", fontsize=12)
        plt.ylabel("Cantidad de Camiones", fontsize=12)
        
        # Forzar el eje X para que muestre de 0 a 23 horas
        plt.xticks(range(0, 24))
        
        # Forzar el eje Y para que sea igual en todos los días
        plt.ylim(0, max_y)
        
        plt.grid(axis='y', linestyle='--', alpha=0.7)
        
        ruta_imagen = os.path.join(directorio_script, f"Llegadas_Hora_{nombre_dia}.png")
        plt.savefig(ruta_imagen, dpi=300, bbox_inches='tight')
        plt.close()
        print(f"📸 Histograma horario guardado: Llegadas_Hora_{nombre_dia}.png")

# ==========================================
# 3. EJECUCIÓN DE LAS PRUEBAS
# ==========================================
if __name__ == "__main__":
    
    # 1. Variables Globales
    if len(datos_volumen) > 0:
        probar_distribuciones(datos_volumen, "Volumen del Camion M3SSC")
        
    if len(datos_edad) > 0:
        probar_distribuciones(datos_edad, "Edad de la Madera Meses")
        
    # 2. Tiempos entre llegadas POR DÍA DE LA SEMANA
    for dia_idx in range(7):
        nombre_dia = nombres_dias[dia_idx]
        df_dia = df[df['Dia_Semana'] == dia_idx]
        
        datos_llegadas_dia = df_dia[(df_dia['Tiempo_Entre_Llegadas'] > 0) & 
                                    (df_dia['Tiempo_Entre_Llegadas'] <= 120)]['Tiempo_Entre_Llegadas'].dropna().values
                                    
        if len(datos_llegadas_dia) > 0:
            probar_distribuciones(datos_llegadas_dia, f"Tiempo Entre Llegadas - {nombre_dia}")

    # 3. Gráficos de cantidad de camiones por hora para cada día
    analizar_llegadas_por_hora(df)
    
    print("\n✅ ¡Todos los análisis han finalizado y las imágenes han sido guardadas!")