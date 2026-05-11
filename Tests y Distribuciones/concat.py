import pandas as pd
import numpy as np
from fitter import Fitter
import matplotlib.pyplot as plt
import unicodedata
import glob
import os

def normalizar_texto(texto):
    texto = str(texto).lower()
    texto_normalizado = unicodedata.normalize('NFKD', texto)
    return texto_normalizado.encode('ASCII', 'ignore').decode('utf-8')

def clasificar(prefijo):
    if prefijo in ['C00']:
        return 'Picado Directo'
    else:
        return 'Cancha'

def cargar_datos(archivos):
    lista_dfs = []
    
    for file in archivos:
        try:
            xls = pd.ExcelFile(file)
            hoja = next((h for h in xls.sheet_names if 'recepcion' in normalizar_texto(h)), xls.sheet_names[0])
            df_temp = pd.read_excel(xls, sheet_name=hoja)
            
            cols = [
                'Producto', 'Hora_Ingreso', 'Hora_Salida', 'Rec_Origen', 'Origen', 
                'M3SSC', 'Fecha_Corta', 'Peso_Neto', 'UbicacionPatio'
            ]
            cols_presentes = [c for c in cols if c in df_temp.columns]
            df_temp = df_temp[cols_presentes]
            
            lista_dfs.append(df_temp)
        except Exception as e:
            print(f"Error leyendo {file.name}: {e}")
            continue

    if lista_dfs:
        df_concat = pd.concat(lista_dfs, ignore_index=True)
        
        if 'Hora_Ingreso' in df_concat.columns:
            df_concat['Hora_Ingreso'] = pd.to_datetime(df_concat['Hora_Ingreso'].astype(str), dayfirst=True, errors='coerce')
            df_concat.sort_values('Hora_Ingreso', inplace=True)
        
        if 'Fecha_Corta' in df_concat.columns:
            df_concat['Fecha_Corta'] = pd.to_datetime(df_concat['Fecha_Corta'], dayfirst=True, errors='coerce')
            if 'Hora_Ingreso' in df_concat.columns:
                df_concat['Age(M)'] = ((df_concat['Hora_Ingreso'] - df_concat['Fecha_Corta']) / pd.Timedelta(days=30.44)).round(2)

        # 2. Ubicación
        df_concat['Prefijo_Ubic'] = df_concat['UbicacionPatio'].astype(str).str[:3]
        df_concat['Ubicacion'] = np.where(df_concat['Prefijo_Ubic'] == 'C00', 'Picado Directo', 'Cancha')
        df_concat = df_concat[df_concat['Producto'].isin([781790, 1613728, 1704428])]
                
        return df_concat
    return None

MESES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 5: "Mayo", 6: "Junio",
    7: "Julio", 8: "Agosto", 9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"
}

# ==========================================
# BLOQUE DE EJECUCIÓN (ARCHIVOS EN LA MISMA CARPETA)
# ==========================================
if __name__ == "__main__":
    print("Buscando archivos de Autonomía en la misma carpeta del script...")
    
    # 1. Obtiene la ruta exacta donde está guardado ESTE script de Python
    directorio_script = os.path.dirname(os.path.abspath(__file__))
    
    # 2. Arma la ruta buscando directamente junto al script
    ruta_busqueda = os.path.join(directorio_script, "Autonom*.xlsx")
    
    # 3. Normaliza la ruta
    ruta_busqueda = os.path.abspath(ruta_busqueda)
    
    print(f"Ruta de búsqueda: {ruta_busqueda}\n")
    
    archivos_excel = glob.glob(ruta_busqueda)
    
    if not archivos_excel:
        print("⚠️ No se encontraron archivos. Revisa que se llamen exactamente 'Autonomía...' y sean '.xlsx'")
    else:
        print(f"✅ ¡Se encontraron {len(archivos_excel)} archivos! Uniendo base de datos...\n")
        
        df_final = cargar_datos(archivos_excel)
        
        if df_final is not None:
            nombre_salida = "Base_Consolidada_Completa.xlsx"
            
            # Guárdalo también en la misma carpeta del script
            ruta_salida = os.path.join(directorio_script, nombre_salida)
            df_final.to_excel(ruta_salida, index=False)
            
            print(f"\n🎉 ¡Éxito! Se consolidaron {len(df_final)} camiones.")
            print(f"El archivo se guardó aquí:\n{ruta_salida}")
        else:
            print("No se generó ningún dato consolidado. Revisa las columnas de los archivos.")
