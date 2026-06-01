class OperadorHumano:
    def __init__(self):
        self.objectiveAge = 3.5  
        self.densityWood = 0.384 
        self.capacityLine = 150 / self.densityWood  
        self.objectiveLinePercent = 0.6  

        self.storageYard = {
            'Descarga' : {'vol': 0.0, 'age': 0.0}
        }

        # ESTADO FÍSICO A CORTO PLAZO (Control de la Hora)
        self.volLineHour = 0.0
        
        # BITÁCORA DEL OPERADOR A LARGO PLAZO (El mes completo)
        self.volLineTotal = 0.0
        self.volStorageYardTotal = 0.0

    def _EvaluateTruck(self, id, volTruck, ageTruck, activeLines, unloadingSy, remainingCraneVol, maxCranePerHour, ageStorageYard):
        # ------------------------------------------------
        # BYPASS FERROCARRIL
        # ------------------------------------------------
        if id == 'FFCC':
            self.volLineHour += volTruck
            self.volLineTotal += volTruck
            # Retorna la decisión + 3 ceros para mantener las 4 variables de salida
            return 'Picado Directo', 0.0, 0.0, 0.0

        # ------------------------------------------------
        # LÓGICA DEL OPERADOR HUMANO
        # ------------------------------------------------
        demandActual = activeLines * self.capacityLine
        
        # RESTRICCIÓN FÍSICA INMEDIATA: Si la máquina ya tiene demasiada madera 
        # para esta hora, el operador manda el camión a cancha obligatoriamente.
        if demandActual == 0 or (self.volLineHour + volTruck) * self.densityWood > demandActual:
            self.volStorageYardTotal += volTruck
            self._ActualizarCanchaFisica(unloadingSy, volTruck, ageTruck)
            return f'Enviado a {unloadingSy}', 0.0, 0.0, 0.0

        # CÁLCULO DEL RATIO MENSUAL (La única métrica que mira el operador)
        volTotalMensual = self.volLineTotal + self.volStorageYardTotal + volTruck
        ratio_actual = (self.volLineTotal + volTruck) / volTotalMensual if volTotalMensual > 0 else 0.0

        # DECISIÓN BASADA SOLO EN EL PORCENTAJE MENSUAL
        if ratio_actual <= self.objectiveLinePercent:
            # Aún le falta para cumplir su meta del 60%, lo manda directo
            self.volLineHour += volTruck
            self.volLineTotal += volTruck
            return 'Enviado a Picado Directo', 0.0, 0.0, 0.0
        else:
            # Ya cumplió o se pasó del 60%, lo manda a la pila
            self.volStorageYardTotal += volTruck
            self._ActualizarCanchaFisica(unloadingSy, volTruck, ageTruck)
            return f'Enviado a {unloadingSy}', 0.0, 0.0, 0.0

    def _ActualizarCanchaFisica(self, unloadingSy, volTruck, ageTruck):
        # Método interno mínimo para que el simulador mantenga el volumen de la cancha actualizado
        volActual = self.storageYard[unloadingSy]['vol']
        ageActual = self.storageYard[unloadingSy]['age']
        
        if (volActual + volTruck) > 0:
            newAge = (volActual * ageActual + volTruck * ageTruck) / (volActual + volTruck)
        else:
            newAge = ageTruck
            
        self.storageYard[unloadingSy]['vol'] += volTruck
        self.storageYard[unloadingSy]['age'] = newAge

    def _CloseHour(self, activeLines, remainingCraneVol, maxCranePerHour, ageStorageYard):
        # Cálculo de la grúa para que el simulador cierre la hora sin fallar
        targetHour = activeLines * self.capacityLine
        
        if activeLines <= 0.0:
            craneVolHour = 0.0
        else:
            gap = max(0.0, targetHour - self.volLineHour)
            craneVolHour = min(gap, remainingCraneVol, maxCranePerHour)
        
        totalMachineHour = self.volLineHour + craneVolHour
        remainingCraneVol -= craneVolHour
        
        volLineHourOut = self.volLineHour
        self.volLineHour = 0.0
        
        # Retorna exactamente las 6 variables esperadas (reemplazando las edades que el operador no calcula por 0.0)
        return volLineHourOut, 0.0, craneVolHour, totalMachineHour, 0.0, remainingCraneVol