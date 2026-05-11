import pandas as pd
import numpy as np
from fitter import Fitter
import matplotlib.pyplot as plt
import os

# ==========================================
# 1. CARGA Y CÁLCULO DE VARIABLES
# ==========================================
print("Procesando histórico de fallas...")

# Obtener el directorio actual para guardar las imágenes ahí mismo
directorio_script = os.path.dirname(os.path.abspath(__file__))
ruta_datos = os.path.join(directorio_script, "Tiempos_Perdidos.xlsx")

# Lee el archivo
df = pd.read_excel(ruta_datos)

df['Parada de Equipo'] = pd.to_datetime(df['Parada de Equipo'], format='%d-%m-%y %H:%M')
df['Entrega de Equipo'] = pd.to_datetime(df['Entrega de Equipo'], format='%d-%m-%y %H:%M')

# --- CÁLCULO 1: Tiempo de Reparación (TTR) en Minutos ---
df['TTR_Minutos'] = (df['Entrega de Equipo'] - df['Parada de Equipo']).dt.total_seconds() / 60

# --- CÁLCULO 2: Tiempo Entre Fallas (TBF) en Minutos ---
df = df.sort_values(by=['Línea', 'Parada de Equipo'])
df['TBF_Minutos'] = df.groupby('Línea').apply(
    lambda x: (x['Parada de Equipo'] - x['Entrega de Equipo'].shift(1)).dt.total_seconds() / 60
).reset_index(level=0, drop=True)

# ==========================================
# 2. SEPARACIÓN Y TESTS DE BONDAD DE AJUSTE
# ==========================================
distribuciones = ['norm', 'expon', 'lognorm', 'gamma']

def evaluar_falla(datos, titulo):
    datos_limpios = datos.dropna().values
    if len(datos_limpios) < 5:
        print(f"\n⚠️ Muy pocos datos para analizar {titulo}")
        return
        
    print(f"\n--- Evaluando: {titulo} ---")
    f = Fitter(datos_limpios, distributions=distribuciones, timeout=30)
    f.fit()
    
    # Imprimir parámetros para el simulador
    mejor_dict = f.get_best(method='sumsquare_error')
    mejor_nombre = list(mejor_dict.keys())[0]
    parametros = mejor_dict[mejor_nombre]
    
    print(f"👉 Mejor distribución: {mejor_nombre.upper()}")
    print(f"⚙️ PARÁMETROS PARA TU SIMULADOR: {parametros}")
    
    # Crear y configurar el gráfico
    plt.title(f"Ajuste: {titulo}")
    plt.xlabel("Minutos")
    plt.ylabel("Densidad")
    
    # Generar un nombre de archivo seguro (sin espacios ni caracteres raros)
    nombre_seguro = titulo.replace(" ", "_").replace("(", "").replace(")", "").replace("-", "").replace("Á", "A")
    ruta_imagen = os.path.join(directorio_script, f"{nombre_seguro}.png")
    
    # 📸 GUARDAR LA IMAGEN (Alta resolución: dpi=300, bbox_inches ajusta los márgenes)
    plt.savefig(ruta_imagen, dpi=300, bbox_inches='tight')
    print(f"📸 Histograma guardado exitosamente como: {nombre_seguro}.png")
    
    # Mostrar la imagen en pantalla y luego limpiar la memoria
    plt.show() 
    plt.clf() # Limpia el gráfico "invisible" que queda en memoria para que no se mezcle con el siguiente

# Ejecutamos las pruebas
if __name__ == "__main__":
    evaluar_falla(df['TBF_Minutos'], "Tiempo Entre Fallas TBF")
    
    datos_operativos = df[df['Area Responsable'] == 'Operativos']['TTR_Minutos']
    evaluar_falla(datos_operativos, "Tiempo Reparacion TTR OPERATIVOS")
    
    datos_mecanicos = df[df['Area Responsable'] == 'Mecánicos']['TTR_Minutos']
    evaluar_falla(datos_mecanicos, "Tiempo Reparacion TTR MECANICOS")