class Romana:
    def __init__(self, w1, w2, w3, stateSy=None):
        self.W1 = w1 # Peso Edad Objetivo
        self.W2 = w2 # Peso Antiguedad de la Cancha
        self.W3 = w3 # Peso Porcentaje

        self.objectiveAge = 3.5  #Meses
        self.densityWood = 0.39
        self.capacityLine = 150 / self.densityWood  #Toneladas/h
        self.objectiveLinePercent = 0.6  #(%)

        self.storageYard = {
            'Descarga' : {'vol': 0.0, 'age': 0.0}
        }

        # ESTADO DE LAS LÍNEAS POR HORA
        self.volLineHour = 0.0
        self.ageLineHour = 0.0

        # MEMORIA DEL TURNO
        self.volLineDay = 0.0
        self.volStorageYardDay = 0.0 
        self.ageLineDay = 0.0 
        self.ageStorageYardDay = 0.0

        # MEMORIA DEL TURNO EN LINEA COMPLETA
        self.totalCraneDay = 0.0
        self.totalMachineDay = 0.0
        self.sumVolAgeMachineDay = 0.0

    def _EvaluateTruck(self, id, volTruck, ageTruck, activeLines, unloadingSy, remainingCraneVol, maxCranePerHour, ageStorageYard):
        # ------------------------------------------------
        # BYPASS FERROCARRIL
        # ------------------------------------------------
        if id == 'FFCC':
            volLineSimA = self.volLineHour + volTruck
            ageLineSimA = (self.volLineHour * self.ageLineHour + volTruck * ageTruck) / volLineSimA if volLineSimA > 0 else ageTruck
            volShiftSimA = self.volLineDay + volTruck
            ageShiftSimA = (self.volLineDay * self.ageLineDay + volTruck * ageTruck) / volShiftSimA if volShiftSimA > 0 else ageTruck
            
            self.volLineHour = volLineSimA
            self.ageLineHour = ageLineSimA
            self.volLineDay = volShiftSimA
            self.ageLineDay = ageShiftSimA
            # Devolvemos 0.0 en las penalizaciones porque el FFCC no toma decisión heurística
            return 'Picado Directo', 0.0, 0.0, 0.0

        # ------------------------------------------------
        # LÓGICA NORMAL
        # ------------------------------------------------
        volActualUnloadSy = self.storageYard[unloadingSy]['vol']
        ageActualUnloadSy = self.storageYard[unloadingSy]['age']

        demandActual = activeLines * self.capacityLine
        volTotalDay = self.volLineDay + self.volStorageYardDay + volTruck

        # RESTRICCIÓN 1: FÍSICA
        if demandActual == 0 or (self.volLineHour + volTruck) * self.densityWood > demandActual:
            self._StoreSy('Descarga', volTruck, ageTruck)
            return f'{unloadingSy} (Restricción Física)', 0.0, 0.0, 0.0
        
        # ESCENARIO A: LÍNEA DIRECTA
        volLineSimA = self.volLineHour + volTruck
        ageLineSimA = (self.volLineHour * self.ageLineHour + volTruck * ageTruck) / volLineSimA

        # Brecha para cumplir la demanda de la línea
        gapA = max(0.0, demandActual - volLineSimA)

        # Definir si se puede suplir la demanda con lo que existe en cancha
        craneVolA = min(gapA, remainingCraneVol, maxCranePerHour)

        # Estados de Línea Completa (Picado Directo + Cancha)
        machineVolA = volLineSimA + craneVolA
        machineAgeA = ((volLineSimA * ageLineSimA) + (craneVolA * ageStorageYard)) / machineVolA if machineVolA > 0 else 0

        # Memoria del turno completo para escenario A
        projTotalMachineVolA = self.totalMachineDay + machineVolA
        projTotalMachineAgeA = (self.sumVolAgeMachineDay + (machineVolA * machineAgeA)) / projTotalMachineVolA if projTotalMachineVolA > 0 else self.objectiveAge

        ageShiftSimA = (self.volLineDay * self.ageLineDay + volTruck * ageTruck) / (self.volLineDay + volTruck)
        ratioA = (self.volLineDay + volTruck) / volTotalDay

        # ESCENARIO B: CANCHA
        volLineSimB = self.volLineHour 
        ageLineSimB = self.ageLineHour

        # Brecha para cumplir la demanda de la línea
        gapB = max(0.0, demandActual - volLineSimB)

        # Definir si se puede suplir la demanda con lo que existe en cancha
        craneVolB = min(gapB, remainingCraneVol, maxCranePerHour)

        # Estados de Línea Completa (Picado Directo + Cancha)
        machineVolB = volLineSimB + craneVolB
        machineAgeB = ((volLineSimB * ageLineSimB) + (craneVolB * ageStorageYard)) / machineVolB if machineVolB > 0 else 0

        # Memoria del turno completo para escenario B
        projTotalMachineVolB = self.totalMachineDay + machineVolB
        projTotalMachineAgeB = (self.sumVolAgeMachineDay + (machineVolB * machineAgeB)) / projTotalMachineVolB if projTotalMachineVolB > 0 else self.objectiveAge

        volUnloadSySimB = volActualUnloadSy + volTruck
        if volUnloadSySimB > 0:
            ageUnloadSySimB = (self.storageYard['Descarga']['vol'] * self.storageYard['Descarga']['age'] + volTruck * ageTruck) / volUnloadSySimB
        else:
            ageUnloadSySimB = ageTruck

        ratioB = self.volLineDay / volTotalDay

        # ==========================================
        # PENALIZACIONES BASE (COMPRIMIDAS A ESCALA ~ 0 a 3)
        # ==========================================
        # P1 Lineal: Reacciona de inmediato a cualquier cambio
        pen1A = abs(machineAgeA - self.objectiveAge) / self.objectiveAge
        pen1B = abs(machineAgeB - self.objectiveAge) / self.objectiveAge
        
        # P2 Cuadrático: Tolerante con madera fresca, brutal con madera vieja
        pen2B = (ageTruck / self.objectiveAge) ** 2
        
        # P3 Lineal: Para que el W3 no necesite ser 5000 para funcionar
        maxRatio = max(self.objectiveLinePercent, 1.0 - self.objectiveLinePercent)
        pen3A = abs(ratioA - self.objectiveLinePercent) / maxRatio
        pen3B = abs(ratioB - self.objectiveLinePercent) / maxRatio

        # Costos Finales Multiplicados por tus W
        costA = (self.W1 * pen1A) + (self.W3 * pen3A)
        costB = (self.W1 * pen1B) + (self.W2 * pen2B) + (self.W3 * pen3B)

        # DECISIÓN
        if costA <= costB:
            self.volLineHour = volLineSimA
            self.ageLineHour = ageLineSimA
            self.volLineDay += volTruck
            self.ageLineDay = ageShiftSimA 
            # Devolvemos las penalizaciones que generó el escenario ganador
            return 'Enviado a Picado Directo', pen1A, 0.0, pen3A
        else:
            self.storageYard[unloadingSy]['vol'] = volUnloadSySimB
            self.storageYard[unloadingSy]['age'] = ageUnloadSySimB
            self.volStorageYardDay += volTruck
            self.ageStorageYardDay = ageUnloadSySimB 
            # Devolvemos las penalizaciones que generó el escenario ganador
            return f'Enviado a {unloadingSy}', pen1B, pen2B, pen3B

    def _StoreSy(self, nameSy, volTruck, ageTruck):
        volActualUnload = self.storageYard[nameSy]['vol']
        ageActualUnload = self.storageYard[nameSy]['age']
        newAge = (volActualUnload * ageActualUnload + volTruck * ageTruck) / (volActualUnload + volTruck)
        self.storageYard[nameSy]['vol'] += volTruck
        self.storageYard[nameSy]['age'] = newAge
        self.volStorageYardDay += volTruck
        self.ageStorageYardDay = newAge
        return f'Se sumó {volTruck} a Descarga'

    def _CloseHour(self, activeLines, remainingCraneVol, maxCranePerHour, ageStorageYard):
        targetHour = activeLines * self.capacityLine
        
        # ★ NUEVA LÓGICA: Si no hay líneas activas, la grúa NO puede aportar nada
        if activeLines <= 0.0:
            craneVolHour = 0.0
        else:
            # Si hay líneas activas, la grúa rellena el gap normalmente
            gap = max(0.0, targetHour - self.volLineHour)
            craneVolHour = min(gap, remainingCraneVol, maxCranePerHour)
        
        totalMachineHour = self.volLineHour + craneVolHour
        if totalMachineHour > 0:
            ageMachineHour = ((self.volLineHour * self.ageLineHour) + (craneVolHour * ageStorageYard)) / totalMachineHour
        else:
            ageMachineHour = 0.0
            
        self.totalCraneDay += craneVolHour
        self.totalMachineDay += totalMachineHour
        self.sumVolAgeMachineDay += (totalMachineHour * ageMachineHour)
        
        remainingCraneVol -= craneVolHour
        
        volLineHourOut = self.volLineHour
        ageLineHourOut = self.ageLineHour
        self.volLineHour = 0.0
        self.ageLineHour = 0.0
        
        return volLineHourOut, ageLineHourOut, craneVolHour, totalMachineHour, ageMachineHour, remainingCraneVol