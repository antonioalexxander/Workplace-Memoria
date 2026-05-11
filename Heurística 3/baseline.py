import pandas as pd
import time
import math
import os
import statistics  
from datetime import datetime

def formato_es(numero, decimales=2):
    return f"{numero:.{decimales}f}".replace('.', ',')

def _getDynamicTargetHour(dateObj, actualHour, dfDowntime, densityWood):
    hourStart = pd.Timestamp(dateObj.year, dateObj.month, dateObj.day, actualHour, 0, 0)
    hourEnd = hourStart + pd.Timedelta(hours=1)

    andesUptime = 60.0
    pacificoUptime = 60.0   

    if dfDowntime is not None and not dfDowntime.empty:
        for index, row in dfDowntime.iterrows():
            downStart = row['Fecha/Hora Inicio']
            downEnd = row['Fecha/Hora Inicio2']
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

def _generateBaseline(file, fileDowntime, fileCancha):
    print('Cargando y procesando los datos históricos reales...')
    
    try:
        df = pd.read_excel(file, decimal=',')
    except Exception as e:
        print(f'Error al leer el archivo principal:\n{e}')
        return

    try:
        dfDowntime = pd.read_excel(fileDowntime)
        dfDowntime['Fecha/Hora Inicio'] = pd.to_datetime(dfDowntime['Fecha/Hora Inicio'])
        dfDowntime['Fecha/Hora Inicio2'] = pd.to_datetime(dfDowntime['Fecha/Hora Inicio2'])
        print('✅ Archivo de Tiempos Perdidos cargado correctamente.')
    except Exception as e:
        print(f'⚠️ No se encontró archivo de fallas, asumiendo 100% operativo:\n{e}')
        dfDowntime = None

    canchaDict = {}
    try:
        with open(fileCancha, 'r', encoding='utf-8') as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 3:
                    dateObjRaw = pd.to_datetime(parts[0], format='%d-%m-%y')
                    dateStrRaw = dateObjRaw.strftime('%d-%m-%Y')
                    volCancha = float(parts[1])
                    ageCancha = float(parts[2])
                    canchaDict[dateStrRaw] = (volCancha, ageCancha)
        print('✅ Archivo de Consumo de Cancha cargado correctamente.')
    except Exception as e:
        print(f'⚠️ No se encontró archivo de Consumo de Cancha, se usarán valores por defecto:\n{e}')

    df['Hora_Ingreso'] = pd.to_datetime(df['Hora_Ingreso'], format='%d-%m-%Y %H:%M:%S')
    df['Fecha_Corta'] = pd.to_datetime(df['Fecha_Corta'], format='%d-%m-%Y')
    df['Edad'] = ((df['Hora_Ingreso'] - df['Fecha_Corta']).dt.days) / 30.4167
    
    df = df.sort_values('Hora_Ingreso')
    df['Fecha_Ingreso_Date'] = df['Hora_Ingreso'].dt.date

    pause = 0.0
    densityWood = 0.39
    outputExcelFile = 'Reporte_Baseline_Completo.xlsx'

    all_export_data = {}
    resumen_global = []
    resumen_mensual_puro = []
    latex_table_rows = []

    # --- LISTAS GLOBALES PARA EL SCORE FINAL ---
    global_age_machine = []
    global_pct_picado = []
    global_age_cancha = []

    dates_from_cancha = [pd.to_datetime(d, format='%d-%m-%Y').date() for d in canchaDict.keys()]
    dates_from_df = list(df['Fecha_Ingreso_Date'].dropna().unique())
    all_dates = list(set(dates_from_cancha + dates_from_df))
    
    if not all_dates:
        print("No hay fechas para procesar.")
        return
        
    min_date = min(all_dates)
    max_date = max(all_dates)
    date_range = pd.date_range(start=min_date, end=max_date)

    if not os.path.exists('Resultados BaseLine'):
        os.makedirs('Resultados BaseLine')

    dates_by_month = {}
    for d in date_range:
        m_key = d.strftime('%Y-%m') 
        if m_key not in dates_by_month:
            dates_by_month[m_key] = []
        dates_by_month[m_key].append(d)

    meses_es = {"01":"ENE", "02":"FEB", "03":"MAR", "04":"ABR", "05":"MAY", "06":"JUN", 
                "07":"JUL", "08":"AGO", "09":"SEP", "10":"OCT", "11":"NOV", "12":"DIC"}

    for month_key, month_dates in dates_by_month.items():
        nombre_mes = meses_es[month_key.split('-')[1]]
        print(f'\n==================================================')
        print(f'📅 INICIANDO PROCESAMIENTO DEL MES: {nombre_mes} (BASELINE)')
        print(f'==================================================')
        
        # --- ACUMULADORES MENSUALES ---
        volMachineMonth = 0.0
        sumVolAgeMachineMonth = 0.0
        sumVolAge2MachineMonth = 0.0
        
        volSyMonth = 0.0
        sumVolAgeSyMonth = 0.0
        sumVolAge2SyMonth = 0.0
        
        volCanchaApMonth = 0.0
        sumVolAgeCanchaApMonth = 0.0
        
        volPicadoMonth = 0.0
        maxAgeMonth = -1.0
        volAtMaxAgeMonth = 0.0
        maxAgeCanchaMonth = 0.0  # <-- NUEVO: Acumulador de edad máxima a cancha por mes

        # --- LISTAS PARA DESVIACIÓN ESTÁNDAR Y ERRORES MENSUALES ---
        list_pctPicadoDay_for_month = []
        list_pctCanchaDay_for_month = []
        list_ageMachineDay_for_month = []
        list_ageCanchaDay_for_month = []

        for single_date in month_dates:
            dateObj = single_date.date()
            dateStr = single_date.strftime('%d-%m-%Y')
            dia_mes = single_date.strftime('%d-%m') 
            dfDay = df[df['Fecha_Ingreso_Date'] == dateObj]
            fileSave = f'Resultados BaseLine/Baseline_Real_{dateStr}.txt'

            print(f'\n--- GENERANDO REPORTE REAL DEL DÍA {dateStr} ---')

            if dateStr in canchaDict:
                volCraneRealDay, ageStorageYard = canchaDict[dateStr]
            else:
                volCraneRealDay = 1000.0
                ageStorageYard = 4.0

            chunkVol = volCraneRealDay / 4.0
            remainingCraneVol = 0.0

            volLineDay = 0.0
            volStorageYardDay = 0.0
            sumVolAgeLineDay = 0.0
            sumVolAge2LineDay = 0.0
            sumVolAgeStorageYardDay = 0.0
            sumVolAge2StorageYardDay = 0.0
            totalCraneDay = 0.0
            totalVolMachineDay = 0.0
            sumVolAgeMachineDay = 0.0
            sumVolAge2MachineDay = 0.0
            maxAgeMachineHour = -1.0
            maxAgeCanchaDay = 0.0 # <-- NUEVO: Acumulador de edad máxima a cancha por día
            volAtMaxAge = 0.0
            
            excelDataDay = []
            
            # --- LISTAS PARA DESVIACIÓN ESTÁNDAR DIARIA (Por Hora) ---
            list_pctPicadoHour_for_day = []
            list_pctCanchaHour_for_day = []

            with open(fileSave, 'w', encoding='utf-8') as fTxt:
                fTxt.write('------ Reporte Detallado por Hora ------\n')

                for h in range(24):
                    if h == 0 or h == 6 or h == 12 or h == 18:
                        remainingCraneVol += chunkVol

                    targetHour, andesUptime, pacificoUptime = _getDynamicTargetHour(single_date, h, dfDowntime, densityWood)

                    volLineHour = 0.0
                    sumVolAgeLineHour = 0.0
                    sumVolAge2LineHour = 0.0
                    volStorageYardHour = 0.0
                    sumVolAgeStorageYardHour = 0.0
                    sumVolAge2StorageYardHour = 0.0

                    trucks_in_hour = dfDay[dfDay['Hora_Ingreso'].dt.hour == h]
                    
                    for index, row in trucks_in_hour.iterrows():
                        vol = row['M3SSC']
                        age = row['Edad']
                        destinoReal = str(row['Destino']).strip()

                        if row['Camion'] == 'FFCC' or "Picado Directo" in destinoReal:
                            volLineHour += vol
                            sumVolAgeLineHour += (vol * age)
                            sumVolAge2LineHour += (vol * (age**2))
                        else:
                            volStorageYardHour += vol
                            sumVolAgeStorageYardHour += (vol * age)
                            sumVolAge2StorageYardHour += (vol * (age**2))
                            # NUEVO: Guardamos el registro si este camión a cancha es el más viejo del día
                            if age > maxAgeCanchaDay:
                                maxAgeCanchaDay = age

                    gap = max(0.0, targetHour - volLineHour)
                    craneVolHour = min(gap, remainingCraneVol)
                    remainingCraneVol -= craneVolHour          

                    totalMachineHour = volLineHour + craneVolHour
                    ageMachineHour = (sumVolAgeLineHour + (craneVolHour * ageStorageYard)) / totalMachineHour if totalMachineHour > 0 else 0.0
                    sumVolAge2MachineHour = sumVolAge2LineHour + (craneVolHour * (ageStorageYard**2))
                    
                    volTotalReceivedHour = volLineHour + volStorageYardHour
                    
                    if volTotalReceivedHour > 0:
                        pctPicadoHour = (volLineHour / volTotalReceivedHour) * 100
                        pctCanchaHour = (volStorageYardHour / volTotalReceivedHour) * 100
                        list_pctPicadoHour_for_day.append(pctPicadoHour)
                        list_pctCanchaHour_for_day.append(pctCanchaHour)
                    else:
                        pctPicadoHour = 0.0
                        pctCanchaHour = 0.0

                    if ageMachineHour > maxAgeMachineHour:
                        maxAgeMachineHour = ageMachineHour
                        volAtMaxAge = totalMachineHour

                    excelDataDay.append({
                        'Hora': f'{h:02d}:00 - {h:02d}:59',
                        'Edad Operación / Mezcla en Línea': round(ageMachineHour, 2),
                        'Aporte de Cancha Real': round(craneVolHour, 2),
                        'Enviado a Picado Directo (M3SSC)': round(volLineHour, 2),
                        'Enviado a Cancha (M3SSC)': round(volStorageYardHour, 2),
                        '% Picado Directo': round(pctPicadoHour, 2),
                        '% Enviado a Cancha': round(pctCanchaHour, 2)
                    })

                    volLineDay += volLineHour
                    volStorageYardDay += volStorageYardHour
                    sumVolAgeLineDay += sumVolAgeLineHour
                    sumVolAge2LineDay += sumVolAge2LineHour
                    sumVolAgeStorageYardDay += sumVolAgeStorageYardHour
                    sumVolAge2StorageYardDay += sumVolAge2StorageYardDay
                    totalCraneDay += craneVolHour
                    totalVolMachineDay += totalMachineHour
                    sumVolAgeMachineDay += (sumVolAgeLineHour + (craneVolHour * ageStorageYard))
                    sumVolAge2MachineDay += sumVolAge2MachineHour

                    blockHour = f'''
[ HORA {h:02d}:00  - {h:02d}:59 ]
  Líneas Operativas (Minutos) -> Andes: {andesUptime:.0f}m | Pacífico: {pacificoUptime:.0f}m
  Volumen total camiones: {volTotalReceivedHour:.1f} M3SSC
    ➜ Picado Directo: {volLineHour:.1f} M3SSC ({pctPicadoHour:.1f}%) 
    ➜ Descarga:       {volStorageYardHour:.1f} M3SSC ({pctCanchaHour:.1f}%) 
---------------------------------------------------------------------------------
    ➜ Aporte Directo a Líneas:      {volLineHour:.1f} M3SSC
    ➜ Aporte desde Cancha a Líneas: {craneVolHour:.1f} M3SSC
    ★ Edad Mezcla en Línea:         {ageMachineHour:.2f}m
---------------------------------------------------------------------------------\n'''
                    fTxt.write(blockHour)

                if dateObj.weekday() == 6:
                    unused_cancha = max(0.0, volCraneRealDay - totalCraneDay)
                    if unused_cancha > 0.01:
                        totalCraneDay += unused_cancha
                        totalVolMachineDay += unused_cancha
                        sumVolAgeMachineDay += (unused_cancha * ageStorageYard)
                        sumVolAge2MachineDay += (unused_cancha * (ageStorageYard**2))
                        
                        if ageStorageYard > maxAgeMachineHour:
                            maxAgeMachineHour = ageStorageYard
                            volAtMaxAge = unused_cancha
                            
                        excelDataDay.append({
                            'Hora': 'Ajuste Sin Camiones (Dom)',
                            'Edad Operación / Mezcla en Línea': round(ageStorageYard, 2),
                            'Aporte de Cancha Real': round(unused_cancha, 2),
                            'Enviado a Picado Directo (M3SSC)': 0.00,
                            'Enviado a Cancha (M3SSC)': 0.00,
                            '% Picado Directo': 0.00,
                            '% Enviado a Cancha': 0.00
                        })

                ageTotalMachine = (sumVolAgeMachineDay / totalVolMachineDay) if totalVolMachineDay > 0 else 0.0
                stdTotalMachine = math.sqrt(max(0.0, (sumVolAge2MachineDay / totalVolMachineDay) - (ageTotalMachine**2))) if totalVolMachineDay > 0 else 0.0
                pctVolAtMaxAge = (volAtMaxAge / totalVolMachineDay) * 100 if totalVolMachineDay > 0 else 0.0
                
                ageStorageYardDayOut = (sumVolAgeStorageYardDay / volStorageYardDay) if volStorageYardDay > 0 else 0.0
                stdStorageYardDayOut = math.sqrt(max(0.0, (sumVolAge2StorageYardDay / volStorageYardDay) - (ageStorageYardDayOut**2))) if volStorageYardDay > 0 else 0.0
                
                volTotalReceivedDay = volLineDay + volStorageYardDay
                
                if len(list_pctPicadoHour_for_day) > 1:
                    stdPctPicadoDay = statistics.stdev(list_pctPicadoHour_for_day)
                    stdPctCanchaDay = statistics.stdev(list_pctCanchaHour_for_day)
                else:
                    stdPctPicadoDay = 0.0
                    stdPctCanchaDay = 0.0

                if volTotalReceivedDay > 0:
                    pctPicadoDay = (volLineDay / volTotalReceivedDay) * 100
                    pctCanchaDay = (volStorageYardDay / volTotalReceivedDay) * 100
                    
                    list_pctPicadoDay_for_month.append(pctPicadoDay)
                    list_pctCanchaDay_for_month.append(pctCanchaDay)
                    list_ageMachineDay_for_month.append(ageTotalMachine)
                    list_ageCanchaDay_for_month.append(ageStorageYardDayOut)
                else:
                    pctPicadoDay = 0.0
                    pctCanchaDay = 0.0

                volMachineMonth += totalVolMachineDay
                sumVolAgeMachineMonth += sumVolAgeMachineDay
                sumVolAge2MachineMonth += sumVolAge2MachineDay
                
                volSyMonth += volStorageYardDay
                sumVolAgeSyMonth += sumVolAgeStorageYardDay
                sumVolAge2SyMonth += sumVolAge2StorageYardDay
                
                volPicadoMonth += volLineDay
                volCanchaApMonth += totalCraneDay
                sumVolAgeCanchaApMonth += (totalCraneDay * ageStorageYard)
                
                if maxAgeMachineHour > maxAgeMonth:
                    maxAgeMonth = maxAgeMachineHour
                    volAtMaxAgeMonth = volAtMaxAge
                elif maxAgeMachineHour == maxAgeMonth:
                    volAtMaxAgeMonth += volAtMaxAge

                # NUEVO: Evaluamos si el pico máximo a la cancha superó al del mes
                if maxAgeCanchaDay > maxAgeCanchaMonth:
                    maxAgeCanchaMonth = maxAgeCanchaDay

                excelDataDay.append({
                    'Hora': 'TOTAL / PROM',
                    'Edad Operación / Mezcla en Línea': round(ageTotalMachine, 2),
                    'Aporte de Cancha Real': round(totalCraneDay, 2),
                    'Enviado a Picado Directo (M3SSC)': round(volLineDay, 2),
                    'Enviado a Cancha (M3SSC)': round(volStorageYardDay, 2),
                    '% Picado Directo': round(pctPicadoDay, 2),
                    '% Enviado a Cancha': round(pctCanchaDay, 2)
                })

                all_export_data[dateStr] = excelDataDay
                
                fila_latex = f"        {dia_mes} & {formato_es(ageTotalMachine)} $\\pm$ {formato_es(stdTotalMachine)} & {formato_es(ageStorageYard)} $\\pm$ 0,00 & {formato_es(ageStorageYardDayOut)} $\\pm$ {formato_es(stdStorageYardDayOut)} & {formato_es(maxAgeMachineHour)} ({formato_es(pctVolAtMaxAge)}\\%) & {formato_es(pctPicadoDay)}\\% & {formato_es(pctCanchaDay)}\\% \\\\"
                latex_table_rows.append(fila_latex)
                
                # ACTUALIZADO: Exactamente igual que la Heurística
                resumen_global.append({
                    'Fecha (Día-Mes)': dia_mes,
                    'Edad Prom. Mezcla (Meses)': round(ageTotalMachine, 2),
                    'Error Abs. Línea (vs 3.5)': round(abs(ageTotalMachine - 3.5), 2),
                    'Desv. Est. Mezcla': round(stdTotalMachine, 2),
                    'Edad Máxima en Línea (Meses)': round(maxAgeMachineHour, 2),
                    'Edad Prom. a Cancha (Meses)': round(ageStorageYardDayOut, 2),
                    'Edad Máx. a Cancha (Meses)': round(maxAgeCanchaDay, 2),
                    '% Picado Directo': round(pctPicadoDay, 2),
                    'Error Abs. Ratio (vs 60%)': round(abs(pctPicadoDay - 60.0), 2),
                    'Desv. Est. % Picado': round(stdPctPicadoDay, 2),
                    '% Enviado a Cancha': round(pctCanchaDay, 2),
                    'Enviado a Picado Directo (M3SSC)': round(volLineDay, 2),
                    'Enviado a Cancha (M3SSC)': round(volStorageYardDay, 2)
                })

        # ==============================================================
        # CIERRE DEL MES ACTUAL (BASELINE)
        # ==============================================================
        print(f'\n--- CÁLCULO FINAL DE {nombre_mes} ---')
        
        # --- CÁLCULOS RMSE DEL MES ---
        if len(list_ageMachineDay_for_month) > 0:
            rmse_linea_mes = math.sqrt(sum((x - 3.5)**2 for x in list_ageMachineDay_for_month) / len(list_ageMachineDay_for_month))
            rmse_ratio_mes = math.sqrt(sum((x - 60.0)**2 for x in list_pctPicadoDay_for_month) / len(list_pctPicadoDay_for_month))
        else:
            rmse_linea_mes, rmse_ratio_mes = 0.0, 0.0

        # Guardar para el consolidado global
        global_age_machine.extend(list_ageMachineDay_for_month)
        global_pct_picado.extend(list_pctPicadoDay_for_month)
        global_age_cancha.extend(list_ageCanchaDay_for_month)

        if volMachineMonth > 0:
            ageMonthMachine = sumVolAgeMachineMonth / volMachineMonth
            stdMonthMachine = math.sqrt(max(0.0, (sumVolAge2MachineMonth / volMachineMonth) - (ageMonthMachine**2)))
            pctVolAtMaxAgeMonth = (volAtMaxAgeMonth / volMachineMonth) * 100
        else:
            ageMonthMachine, stdMonthMachine, pctVolAtMaxAgeMonth = 0.0, 0.0, 0.0

        if volSyMonth > 0:
            ageMonthSyOut = sumVolAgeSyMonth / volSyMonth
            stdMonthSyOut = math.sqrt(max(0.0, (sumVolAge2SyMonth / volSyMonth) - (ageMonthSyOut**2)))
        else:
            ageMonthSyOut, stdMonthSyOut = 0.0, 0.0

        volTotalRecMonth = volPicadoMonth + volSyMonth
        if volTotalRecMonth > 0:
            pctPicadoMonth = (volPicadoMonth / volTotalRecMonth) * 100
            pctCanchaMonth = (volSyMonth / volTotalRecMonth) * 100
        else:
            pctPicadoMonth, pctCanchaMonth = 0.0, 0.0

        if len(list_pctPicadoDay_for_month) > 1:
            stdPctPicadoMonth = statistics.stdev(list_pctPicadoDay_for_month)
        else:
            stdPctPicadoMonth = 0.0

        # ACTUALIZADO: Exactamente igual que la Heurística
        resumen_mensual_puro.append({
            'Mes': nombre_mes,
            'Edad Prom. Mezcla (Meses)': round(ageMonthMachine, 2),
            'RMSE Línea (Castigo)': round(rmse_linea_mes, 4), 
            'Desv. Est. Mezcla': round(stdMonthMachine, 2),
            'Edad Máxima en Línea (Meses)': round(maxAgeMonth, 2),
            'Edad Prom. a Cancha (Meses)': round(ageMonthSyOut, 2),
            'Edad Máx. a Cancha (Meses)': round(maxAgeCanchaMonth, 2),
            'Desv. Est. Envío a Cancha': round(stdMonthSyOut, 2), # Mantengo este para cuadrar columnas si la heurística lo tenía
            '% Picado Directo': round(pctPicadoMonth, 2),
            'RMSE Ratio (Castigo)': round(rmse_ratio_mes, 4), 
            'Desv. Est. % Picado': round(stdPctPicadoMonth, 2),
            '% Enviado a Cancha': round(pctCanchaMonth, 2),
            'Enviado a Picado Directo (M3SSC)': round(volPicadoMonth, 2),
            'Enviado a Cancha (M3SSC)': round(volSyMonth, 2)
        })

        resumen_global.append({'Fecha (Día-Mes)': ''})
        resumen_global.append({
            'Fecha (Día-Mes)': f'TOTAL {nombre_mes}',
            'Edad Prom. Mezcla (Meses)': round(ageMonthMachine, 2),
            'Error Abs. Línea (vs 3.5)': f'RMSE: {round(rmse_linea_mes, 2)}', 
            'Desv. Est. Mezcla': round(stdMonthMachine, 2),
            'Edad Máxima en Línea (Meses)': round(maxAgeMonth, 2),
            'Edad Prom. a Cancha (Meses)': round(ageMonthSyOut, 2),
            'Edad Máx. a Cancha (Meses)': round(maxAgeCanchaMonth, 2),
            '% Picado Directo': round(pctPicadoMonth, 2),
            'Error Abs. Ratio (vs 60%)': f'RMSE: {round(rmse_ratio_mes, 2)}', 
            'Desv. Est. % Picado': round(stdPctPicadoMonth, 2),
            '% Enviado a Cancha': round(pctCanchaMonth, 2),
            'Enviado a Picado Directo (M3SSC)': round(volPicadoMonth, 2),
            'Enviado a Cancha (M3SSC)': round(volSyMonth, 2)
        })

        latex_table_rows.append("        \\midrule")
        latex_table_rows.append(f"        \\textbf{{TOTAL {nombre_mes}}} & \\textbf{{{formato_es(ageMonthMachine)} $\\pm$ {formato_es(stdMonthMachine)}}} & \\textbf{{-}} & \\textbf{{{formato_es(ageMonthSyOut)} $\\pm$ {formato_es(stdMonthSyOut)}}} & \\textbf{{{formato_es(maxAgeMonth)} ({formato_es(pctVolAtMaxAgeMonth)}\\%)}} & \\textbf{{{formato_es(pctPicadoMonth)}\\%}} & \\textbf{{{formato_es(pctCanchaMonth)}\\%}} \\\\")
        latex_table_rows.append("        \\midrule")

    # --- CÁLCULO GLOBAL FINAL (6 MESES) ---
    if len(global_age_machine) > 0:
        global_rmse_linea = math.sqrt(sum((x - 3.5)**2 for x in global_age_machine) / len(global_age_machine))
        global_rmse_ratio = math.sqrt(sum((x - 60.0)**2 for x in global_pct_picado) / len(global_pct_picado))
        global_prom_cancha = sum(global_age_cancha) / len(global_age_cancha)

        # Fila TOTAL GLOBAL para resumen puro mensual
        resumen_mensual_puro.append({
            'Mes': 'TOTAL GLOBAL (6m)',
            'Edad Prom. Mezcla (Meses)': round(sum(global_age_machine)/len(global_age_machine), 2),
            'RMSE Línea (Castigo)': round(global_rmse_linea, 4),
            'Desv. Est. Mezcla': '---',
            'Edad Máxima en Línea (Meses)': '---',
            'Edad Prom. a Cancha (Meses)': round(global_prom_cancha, 2),
            'Edad Máx. a Cancha (Meses)': '---',
            'Desv. Est. Envío a Cancha': '---',
            '% Picado Directo': round(sum(global_pct_picado)/len(global_pct_picado), 2),
            'RMSE Ratio (Castigo)': round(global_rmse_ratio, 4),
            'Desv. Est. % Picado': '---',
            '% Enviado a Cancha': '---',
            'Enviado a Picado Directo (M3SSC)': '---',
            'Enviado a Cancha (M3SSC)': '---'
        })

        # Fila TOTAL GLOBAL para detalle de días
        resumen_global.append({'Fecha (Día-Mes)': ''})
        resumen_global.append({
            'Fecha (Día-Mes)': 'TOTAL GLOBAL (6m)',
            'Edad Prom. Mezcla (Meses)': '---',
            'Error Abs. Línea (vs 3.5)': f'RMSE: {round(global_rmse_linea, 2)}',
            'Desv. Est. Mezcla': '---',
            'Edad Máxima en Línea (Meses)': '---',
            'Edad Prom. a Cancha (Meses)': f'PROM: {round(global_prom_cancha, 2)}',
            'Edad Máx. a Cancha (Meses)': '---',
            '% Picado Directo': '---',
            'Error Abs. Ratio (vs 60%)': f'RMSE: {round(global_rmse_ratio, 2)}',
            'Desv. Est. % Picado': '---',
            '% Enviado a Cancha': '---',
            'Enviado a Picado Directo (M3SSC)': '---',
            'Enviado a Cancha (M3SSC)': '---'
        })

    print('\n==================================================')
    print('Guardando base de datos completa en Excel...')
    with pd.ExcelWriter(outputExcelFile, engine='openpyxl') as writer:
        if resumen_global:
            pd.DataFrame(resumen_global).to_excel(writer, sheet_name='Detalle_Dias', index=False)
            
        if resumen_mensual_puro:
            pd.DataFrame(resumen_mensual_puro).to_excel(writer, sheet_name='Consolidado_Mensual', index=False)
            
        for dateStr, data in all_export_data.items():
            dfExport = pd.DataFrame(data)
            dfExport.to_excel(writer, sheet_name=dateStr, index=False)
            
    print(f'✅ ¡Proceso Completado! {outputExcelFile} generado exitosamente.\n')

    # ==============================================================
    # TABLA LATEX
    # ==============================================================
    print("==========================================================")
    print("📋 CÓDIGO LATEX GENERADO PARA TU DOCUMENTO:")
    print("==========================================================")
    print("\\begin{table}[H]")
    print("    \\centering")
    print("    \\caption{Resumen de Edad de Madera y Distribución de Recepción (Baseline)}")
    print("    \\label{tab:resumen_mensual_baseline}")
    print("    \\fontsize{10pt}{11pt}\\selectfont")
    print("    \\begin{tabular}{lccccccc}")
    print("        \\toprule")
    print("        \\textbf{Día} & \\textbf{Edad Mezcla} & \\textbf{Edad Ap. Cancha} & \\textbf{Edad Env. Cancha} & \\textbf{Edad Máx. (\\%)} & \\textbf{Picado (\\%)} & \\textbf{Cancha (\\%)} \\\\")
    print("        \\midrule")
    for fila in latex_table_rows:
        print(fila)
    print("        \\bottomrule")
    print("    \\end{tabular}")
    print("\\end{table}")
    print("==========================================================\n")

    # ==============================================================
    # REPORTE DE SCORE EN TERMINAL (BASELINE)
    # ==============================================================
    if len(global_age_machine) > 0:
        print("==========================================================")
        print("🏆 SCORE BASELINE (GLOBAL DE LA OPERACIÓN REAL)")
        print("==========================================================")
        print(f"🌲 RMSE Línea (Castigo por desviarse de 3.5m) : {global_rmse_linea:.4f} meses")
        print(f"⚖️ RMSE Ratio (Castigo por desviarse de 60%)  : {global_rmse_ratio:.4f}%")
        print(f"🪵 Promedio Edad Enviada a Cancha             : {global_prom_cancha:.4f} meses")
        print("----------------------------------------------------------")
        print("💡 Anota estos valores para compararlos con tu heurística en el estandarizador.")
        print("==========================================================\n")

if __name__ == '__main__':
    # 1. VERIFICA ESTOS NOMBRES: Deben coincidir EXACTAMENTE con los de tus archivos reales.
    file = 'Datos_Simulación.xlsx'  
    fileDowntime = 'Tiempos_Perdidos.xlsx'
    fileCancha = 'ConsumoCanchaNov2025.txt'
    
    print("Iniciando simulador Baseline...")
    print(f"Buscando archivo de datos: {file}")
    
    # 2. Comprobar si el archivo principal existe antes de empezar
    if not os.path.exists(file):
        print(f"❌ ERROR CRÍTICO: No se encontró el archivo '{file}' en la carpeta actual.")
        print(f"La carpeta actual es: {os.getcwd()}")
        print("Por favor, revisa el nombre del archivo o muévelo a esta carpeta.")
    else:
        try:
            # 3. Ejecutar la función
            _generateBaseline(file, fileDowntime, fileCancha)
        except Exception as e:
            print(f"\n❌ Ocurrió un error inesperado durante la ejecución: {e}")
            import traceback
            traceback.print_exc()