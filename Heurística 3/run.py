import pandas as pd
import time 
from heuristica import Romana
import math
import os
import statistics
from datetime import datetime

W1 = 4098
W2 = 8
W3 = 16
W4 = 172
# ==============================================================
# FUNCIÓN: Formato LaTeX
# ==============================================================
def formato_es(numero, decimales=2):
    return f"{numero:.{decimales}f}".replace('.', ',')

# ==============================================================
# FUNCIÓN: Calculador Dinámico de Disponibilidad
# ==============================================================
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

def _simulatorHour(file, fileDowntime, fileCancha):
    print('Cargando datos de simulación y tiempos perdidos...')

    try:
        df = pd.read_excel(file, decimal=',')
    except Exception as e:
        print(f'Error al leer el archivo principal:\n{e}')
        return

    # --- Carga de Tiempos Perdidos ---
    try:
        dfDowntime = pd.read_excel(fileDowntime)
        dfDowntime['Parada de Equipo'] = pd.to_datetime(dfDowntime['Parada de Equipo'])
        dfDowntime['Entrega de Equipo'] = pd.to_datetime(dfDowntime['Entrega de Equipo'])
        print('✅ Archivo de Tiempos Perdidos cargado correctamente.')
    except Exception as e:
        print(f'⚠️ No se encontró archivo de fallas, asumiendo 100% operativo:\n{e}')
        dfDowntime = None

    # --- Carga de Consumo Diario de Cancha ---
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
    
    outputExcelFile = 'Reporte_Heuristica_Romana.xlsx'
    all_export_data = {}
    resumen_global = []
    resumen_mensual_puro = []
    latex_table_rows = []
    globalP1, globalP2, globalP3 = [], [], []

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
        
    min_date, max_date = min(all_dates), max(all_dates)
    date_range = pd.date_range(start=min_date, end=max_date)

    if not os.path.exists('Resultados Simulador'):
        os.makedirs('Resultados Simulador')

    # ==============================================================
    # AGRUPACIÓN POR MES
    # ==============================================================
    dates_by_month = {}
    for d in date_range:
        m_key = d.strftime('%Y-%m') 
        if m_key not in dates_by_month:
            dates_by_month[m_key] = []
        dates_by_month[m_key].append(d)

    meses_es = {"01":"Enero", "02":"Febrero", "03":"Marzo", "04":"Abril", "05":"Mayo", "06":"Junio", 
                "07":"Julio", "08":"Agosto", "09":"Septiembre", "10":"Octubre", "11":"Noviembre", "12":"Diciembre"}

    for month_key, month_dates in dates_by_month.items():
        nombre_mes = meses_es[month_key.split('-')[1]]
        print(f'\n==================================================')
        print(f'📅 INICIANDO PROCESAMIENTO DEL MES: {nombre_mes}')
        print(f'==================================================')
        
        # --- REINICIAR ACUMULADORES ---
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
        maxAgeCanchaMonth = 0.0  

        # --- LISTAS PARA ESTADÍSTICOS DEL MES ---
        list_pctPicadoDay_for_month = []
        list_pctCanchaDay_for_month = []
        list_ageMachineDay_for_month = []
        list_ageCanchaDay_for_month = []

        for single_date in month_dates:
            dateObj = single_date.date()
            dateStr = single_date.strftime('%d-%m-%Y')
            dia_mes = single_date.strftime('%d-%m')
            dfDay = df[df['Fecha_Ingreso_Date'] == dateObj]
            fileSave = f'Resultados Simulador/Reporte_Romana_{dateStr}.txt'

            print(f'\n--- Operación Día {dateStr} ---')

            # PESOS
            system = Romana(w1=W1, w2=W2, w3=W3, w4=W4)
            
            if dateStr in canchaDict:
                volCraneRealDay, ageStorageYard = canchaDict[dateStr]
            else:
                volCraneRealDay = 1000.0
                ageStorageYard = 4.0

            chunkVol = volCraneRealDay / 4.0
            remainingCraneVol = 0.0
            
            auxP1, auxP2, auxP3 = [], [], []
            sumVolAge2MachineDay = 0.0
            sumVolAgeSyDay = 0.0
            sumVolAge2SyDay = 0.0
            volSyDay = 0.0
            maxAgeMachineHour = -1.0
            maxAgeCanchaDay = 0.0 
            volAtMaxAge = 0.0
            excelDataDay = []

            list_pctPicadoHour_for_day = []
            list_pctCanchaHour_for_day = []

            with open(fileSave, 'w', encoding='utf-8') as fTxt:
                fTxt.write('------ Reporte Detallado por Hora ------\n')

                for h in range(24):
                    if h == 0 or h == 6 or h == 12 or h == 18:
                        remainingCraneVol += chunkVol

                    targetHour, andesUptime, pacificoUptime = _getDynamicTargetHour(single_date, h, dfDowntime, densityWood)
                    
                    if single_date.weekday() == 6:
                        limite_grua = 200.0
                    else:
                        limite_grua = 125.0
                        
                    dynamicMaxCrane = min(limite_grua, targetHour)
                    
                    lineActives = 0
                    if andesUptime > 1.0: lineActives += 1
                    if pacificoUptime > 1.0: lineActives += 1

                    volStorageYardHour = 0
                    sumVolAgeStorageYardHour = 0
                    sumVolAge2StorageYardHour = 0
                    sumVolAge2LineHour = 0
                    truckHour = 0

                    trucks_in_hour = dfDay[dfDay['Hora_Ingreso'].dt.hour == h]
                    
                    for index, row in trucks_in_hour.iterrows():
                        idTruck = row['Camion']
                        vol = row['M3SSC']
                        age = row['Edad']
                        hourTxt = row['Hora_Ingreso'].strftime('%H:%M:%S')

                        decision, p1, p2, p3, p4 = system._EvaluateTruck(
                            id=idTruck, volTruck=vol, ageTruck=age, activeLines=lineActives, unloadingSy='Descarga',
                            remainingCraneVol=remainingCraneVol, maxCranePerHour=dynamicMaxCrane, ageStorageYard=ageStorageYard
                        )

                        if idTruck != 'FFCC' and 'Restricción' not in decision:
                            globalP1.append(p1); auxP1.append(p1)
                            globalP3.append(p3); auxP3.append(p3)
                            if 'Descarga' in decision:
                                globalP2.append(p2); auxP2.append(p2)
                        
                        if 'Descarga' in decision:
                            volStorageYardHour += vol
                            sumVolAgeStorageYardHour += (vol * age)
                            sumVolAge2StorageYardHour += (vol * (age**2))
                            if age > maxAgeCanchaDay:
                                maxAgeCanchaDay = age
                        else:
                            sumVolAge2LineHour += (vol * (age**2))

                        truckHour += 1
                        time.sleep(pause)

                    volLineHour, ageLineHour, craneVolHour, totalMachineHour, ageMachineHour, remainingCraneVol = system._CloseHour(
                        lineActives, remainingCraneVol, dynamicMaxCrane, ageStorageYard
                    )

                    volTotalHour = volLineHour + volStorageYardHour
                    if volTotalHour > 0:
                        pctPicadoHour = (volLineHour / volTotalHour) * 100
                        pctCanchaHour = (volStorageYardHour / volTotalHour) * 100
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

                    sumVolAge2MachineHour = sumVolAge2LineHour + (craneVolHour * (ageStorageYard**2))
                    sumVolAge2MachineDay += sumVolAge2MachineHour
                    volSyDay += volStorageYardHour
                    sumVolAgeSyDay += sumVolAgeStorageYardHour
                    sumVolAge2SyDay += sumVolAge2StorageYardHour
                    sumVolAgeCanchaApMonth += (craneVolHour * ageStorageYard)

                ageTotalMachine = system.sumVolAgeMachineDay / system.totalMachineDay if system.totalMachineDay > 0 else 0
                stdTotalMachine = math.sqrt(max(0.0, (sumVolAge2MachineDay / system.totalMachineDay) - (ageTotalMachine**2))) if system.totalMachineDay > 0 else 0

                ageStorageYardDayOut = (sumVolAgeSyDay / volSyDay) if volSyDay > 0 else 0.0
                stdStorageYardDayOut = math.sqrt(max(0.0, (sumVolAge2SyDay / volSyDay) - (ageStorageYardDayOut**2))) if volSyDay > 0 else 0.0

                pctVolAtMaxAge = (volAtMaxAge / system.totalMachineDay) * 100 if system.totalMachineDay > 0 else 0.0

                volTotalReceived = system.volLineDay + system.volStorageYardDay
                
                if len(list_pctPicadoHour_for_day) > 1:
                    stdPctPicadoDay = statistics.stdev(list_pctPicadoHour_for_day)
                    stdPctCanchaDay = statistics.stdev(list_pctCanchaHour_for_day)
                else:
                    stdPctPicadoDay = 0.0
                    stdPctCanchaDay = 0.0

                if volTotalReceived > 0:
                    pctPicadoDay = (system.volLineDay / volTotalReceived) * 100
                    pctCanchaDay = (volSyDay / volTotalReceived) * 100
                    
                    list_pctPicadoDay_for_month.append(pctPicadoDay)
                    list_pctCanchaDay_for_month.append(pctCanchaDay)
                    list_ageMachineDay_for_month.append(ageTotalMachine)
                    list_ageCanchaDay_for_month.append(ageStorageYardDayOut)
                else:
                    pctPicadoDay = 0.0
                    pctCanchaDay = 0.0

                volMachineMonth += system.totalMachineDay
                sumVolAgeMachineMonth += system.sumVolAgeMachineDay
                sumVolAge2MachineMonth += sumVolAge2MachineDay
                
                volSyMonth += volSyDay
                sumVolAgeSyMonth += sumVolAgeSyDay
                sumVolAge2SyMonth += sumVolAge2SyDay
                
                volPicadoMonth += system.volLineDay
                volCanchaApMonth += system.totalCraneDay
                
                if maxAgeMachineHour > maxAgeMonth:
                    maxAgeMonth = maxAgeMachineHour
                    volAtMaxAgeMonth = volAtMaxAge
                elif maxAgeMachineHour == maxAgeMonth:
                    volAtMaxAgeMonth += volAtMaxAge

                if maxAgeCanchaDay > maxAgeCanchaMonth:
                    maxAgeCanchaMonth = maxAgeCanchaDay

                excelDataDay.append({
                    'Hora': 'TOTAL / PROM',
                    'Edad Operación / Mezcla en Línea': round(ageTotalMachine, 2),
                    'Aporte de Cancha Real': round(system.totalCraneDay, 2),
                    'Enviado a Picado Directo (M3SSC)': round(system.volLineDay, 2),
                    'Enviado a Cancha (M3SSC)': round(volSyDay, 2),
                    '% Picado Directo': round(pctPicadoDay, 2),
                    '% Enviado a Cancha': round(pctCanchaDay, 2)
                })

                all_export_data[dateStr] = excelDataDay
                
                fila_latex = f"        {dia_mes} & {formato_es(ageTotalMachine)} $\\pm$ {formato_es(stdTotalMachine)} & {formato_es(ageStorageYard)} $\\pm$ 0,00 & {formato_es(ageStorageYardDayOut)} $\\pm$ {formato_es(stdStorageYardDayOut)} & {formato_es(maxAgeMachineHour)} ({formato_es(pctVolAtMaxAge)}\\%) & {formato_es(pctPicadoDay)}\\% & {formato_es(pctCanchaDay)}\\% \\\\"
                latex_table_rows.append(fila_latex)

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
                    'Enviado a Picado Directo (M3SSC)': round(system.volLineDay, 2),
                    'Enviado a Cancha (M3SSC)': round(volSyDay, 2)
                })

        # ==============================================================
        # CIERRE DEL MES ACTUAL
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

        resumen_mensual_puro.append({
            'Mes': nombre_mes,
            'Edad Prom. Mezcla (Meses)': round(ageMonthMachine, 2),
            'RMSE Línea (Castigo)': round(rmse_linea_mes, 4), 
            'Desv. Est. Mezcla': round(stdMonthMachine, 2),
            'Edad Máxima en Línea (Meses)': round(maxAgeMonth, 2),
            'Edad Prom. a Cancha (Meses)': round(ageMonthSyOut, 2),
            'Edad Máx. a Cancha (Meses)': round(maxAgeCanchaMonth, 2),
            'Desv. Est. Envío a Cancha': round(stdMonthSyOut, 2),
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

    # ==============================================================
    # EXPORTACIÓN FINAL A EXCEL Y LATEX
    # ==============================================================
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

    # print("==========================================================")
    # print("📋 CÓDIGO LATEX GENERADO PARA TU DOCUMENTO:")
    # print("==========================================================")
    # print("\\begin{table}[H]")
    # print("    \\centering")
    # print("    \\caption{Resumen de Edad de Madera y Distribución de Recepción (Heurística)}")
    # print("    \\label{tab:resumen_mensual_heuristica}")
    # print("    \\fontsize{10pt}{11pt}\\selectfont")
    # print("    \\begin{tabular}{lccccccc}")
    # print("        \\toprule")
    # print("        \\textbf{Día} & \\textbf{Edad Mezcla} & \\textbf{Edad Ap. Cancha} & \\textbf{Edad Env. Cancha} & \\textbf{Edad Máx. (\\%)} & \\textbf{Picado (\\%)} & \\textbf{Cancha (\\%)} \\\\")
    # print("        \\midrule")
    # for fila in latex_table_rows:
    #     print(fila)
    # print("        \\bottomrule")
    # print("    \\end{tabular}")
    # print("\\end{table}")
    # print("==========================================================\n")

    # ==============================================================
    # ★ NUEVO: CÁLCULO DE CONTRIBUCIÓN DE PESOS EFECTIVOS
    # ==============================================================
    if len(globalP1) > 0 and len(globalP2) > 0 and len(globalP3) > 0:
        promP1 = sum(globalP1) / len(globalP1)
        promP2 = sum(globalP2) / len(globalP2)
        promP3 = sum(globalP3) / len(globalP3)
        
        c1 = W1 * promP1
        c2 = W2 * promP2
        c3 = W3 * promP3
        
        total_C = c1 + c2 + c3
        
        pct_C1 = (c1 / total_C) * 100 if total_C > 0 else 0
        pct_C2 = (c2 / total_C) * 100 if total_C > 0 else 0
        pct_C3 = (c3 / total_C) * 100 if total_C > 0 else 0
        
        print("==========================================================")
        print("ANÁLISIS DE PESOS EFECTIVOS (IMPACTO REAL DE LOS W)")
        print("==========================================================")
        print(f"   - Penalización Promedio Línea  (P1) : {promP1:.6f}  |  (C1 = W1 * P1 = {c1:.4f})")
        print(f"   - Penalización Promedio Cancha (P2) : {promP2:.6f}  |  (C2 = W2 * P2 = {c2:.4f})")
        print(f"   - Penalización Promedio Ratio  (P3) : {promP3:.6f}  |  (C3 = W3 * P3 = {c3:.4f})")
        print("----------------------------------------------------------")
        print("CONTRIBUCIÓN PORCENTUAL AL COSTO TOTAL:")
        print(f"   - Peso Efectivo Línea  (W1) : {pct_C1:.2f} %")
        print(f"   - Peso Efectivo Cancha (W2) : {pct_C2:.2f} %")
        print(f"   - Peso Efectivo Ratio  (W3) : {pct_C3:.2f} %")
        print("==========================================================\n")

    # ==============================================================
    # REPORTE DE SCORE EN TERMINAL
    # ==============================================================
    if len(global_age_machine) > 0:
        print("==========================================================")
        print("ESTADÍSTICOS DE DESEMPEÑO")
        print("==========================================================")
        print(f"   - RMSE Línea (Castigo por desviarse de 3.5m) : {global_rmse_linea:.4f} meses")
        print(f"   - RMSE Ratio (Castigo por desviarse de 60%)  : {global_rmse_ratio:.4f}%")
        print(f"   - Promedio Edad Enviada a Cancha             : {global_prom_cancha:.4f} meses")
        print("==========================================================\n")

if __name__ == '__main__':
    file = 'Datos_Simulación.xlsx'
    fileDowntime = 'Tiempos_Perdidos.xlsx'
    fileCancha = 'ConsumoCanchaNov2025.txt'
    _simulatorHour(file, fileDowntime, fileCancha)