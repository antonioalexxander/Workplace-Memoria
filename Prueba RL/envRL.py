import gymnasium as gym
from gymnasium import spaces
import numpy as np
import simpy
import json
from RLsim import PulpFacilitySimulation, Truck

class PulpYardEnv(gym.Env):
    """
    Entorno personalizado de Gymnasium para el Patio de Maderas.
    Conecta la física asíncrona de SimPy con el aprendizaje síncrono de RL.
    """
    def __init__(self, dias_simulacion=180):
        super(PulpYardEnv, self).__init__()
        self.dias_simulacion = dias_simulacion
        self.max_tiempo = dias_simulacion * 24 * 60
        
        # Cargar configuración para saber cuántas columnas hay físicamente
        with open("yardConfig.json", "r", encoding="utf-8") as f:
            yard_config = json.load(f)
            
        self.num_lineas = 2
        self.num_columnas = sum(area["columns"] for area in yard_config["areas"])
        
        # ==========================================
        # 1. ESPACIO DE ACCIÓN (Action Space)
        # ==========================================
        # 0 y 1 -> Mandar directo a Línea 0 o Línea 1
        # 2 a N -> Mandar al patio (Columna X)
        self.total_acciones = self.num_lineas + self.num_columnas
        self.action_space = spaces.Discrete(self.total_acciones)
        
        # ==========================================
        # 2. ESPACIO DE OBSERVACIÓN (Observation Space)
        # ==========================================
        # Qué "ve" el agente: [Vol_Camion, Edad_Camion, Nivel_L1, Nivel_L2, Vol_C1, Edad_C1, Vol_C2, Edad_C2...]
        num_observaciones = 2 + self.num_lineas + (self.num_columnas * 2)
        self.observation_space = spaces.Box(low=0, high=np.inf, shape=(num_observaciones,), dtype=np.float32)
        
        # Variables de control SimPy-RL
        self.env = None
        self.facility = None
        self.current_truck = None
        self.decision_event = None
        self.action_event = None
        self.chosen_action = None
        self.flat_columns = []
        
        # Variables para calcular recompensas (deltas)
        self.last_starvation = 0
        self.last_wait_time_total = 0

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        if seed is not None:
            np.random.seed(seed)
            
        self.env = simpy.Environment()
        
        # Instanciamos tu simulador, inyectando nuestra estrategia RL
        self.facility = PulpFacilitySimulation(self.env, strategy_func=self._rl_strategy)
        
        # Aplanar la lista de columnas para que el Agente las pueda elegir por índice (0, 1, 2...)
        self.flat_columns = []
        for area_id in sorted(self.facility.stock_areas.keys()):
            for col in self.facility.stock_areas[area_id]:
                self.flat_columns.append(col)
                
        # Iniciar procesos físicos
        self.env.process(self.facility.truck_arrival_process())
        self.env.process(self.facility.stock_monitoring_process())
        for line in self.facility.lines:
            self.env.process(self.facility.line_feeding_process(line))
            
        # Reseteo de métricas
        self.last_starvation = 0
        self.last_wait_time_total = 0
            
        # Crear el primer evento de decisión y correr SimPy hasta que llegue el primer camión
        self.decision_event = self.env.event()
        self._avanzar_simulacion()
        
        return self._get_obs(), {}

    def step(self, action):
        # 1. Guardar la acción elegida por la red neuronal
        self.chosen_action = action
        
        # 2. Desbloquear el camión en SimPy para que se mueva físicamente
        if self.action_event is not None and not self.action_event.triggered:
            self.action_event.succeed()
            
        # 3. Crear un nuevo evento de decisión y avanzar el tiempo hasta el próximo camión
        self.decision_event = self.env.event()
        terminated = self._avanzar_simulacion()
        
        # 4. Obtener la nueva foto de la planta y calcular el puntaje
        obs = self._get_obs()
        reward = self._calcular_recompensa()
        
        return obs, reward, terminated, False, {}

    # --- FUNCIONES DE SINCRONIZACIÓN ---

    def _rl_strategy(self, truck, sim):
        self.current_truck = truck
        
        if not self.decision_event.triggered:
            self.decision_event.succeed()
            
        self.action_event = self.env.event()
        yield self.action_event 
        
        # ==========================================================
        # EL GUARDIA DE SEGURIDAD SUAVE (ANTI-DEADLOCK)
        # ==========================================================
        accion = self.chosen_action
        es_invalida = False

        if accion < self.num_lineas:
            destino = sim.lines[accion]
            if destino.hopper.container.level + truck.volume > destino.hopper.container.capacity:
                es_invalida = True
        else:
            idx_col = accion - self.num_lineas
            destino = self.flat_columns[idx_col]
            if destino.container.level + truck.volume > destino.container.capacity:
                es_invalida = True

        if es_invalida:
            # 1. Multa leve para que aprenda sin asustarse
            self.multa_guardia = 10.0
            
            # 2. Salvar el camión en un lugar válido para que SimPy no se detenga
            lineas_disponibles = [l for l in sim.lines if l.hopper.container.level + truck.volume <= l.hopper.container.capacity]
            if lineas_disponibles:
                truck.route_taken = 'Direct'
                truck.target_obj = min(lineas_disponibles, key=lambda l: l.hopper.container.level)
            else:
                cols_disponibles = [c for c in self.flat_columns if c.container.level + truck.volume <= c.container.capacity]
                if cols_disponibles:
                    import random
                    truck.route_taken = 'Stock'
                    truck.target_obj = random.choice(cols_disponibles)
                else:
                    # Si todo falla, forzar a la línea más vacía
                    truck.route_taken = 'Direct'
                    truck.target_obj = min(sim.lines, key=lambda l: l.hopper.container.level)
        else:
            self.multa_guardia = 0.0
            if accion < self.num_lineas:
                truck.route_taken = 'Direct'
                truck.target_obj = sim.lines[accion]
            else:
                idx_col = accion - self.num_lineas
                truck.route_taken = 'Stock'
                truck.target_obj = self.flat_columns[idx_col]

    def _avanzar_simulacion(self):
        """Corre SimPy hasta el próximo camión o hasta el fin del mes"""
        timeout_event = self.env.timeout(self.max_tiempo - self.env.now)
        resultado = self.env.run(until=simpy.AnyOf(self.env, [self.decision_event, timeout_event]))
        
        # Si se activó el timeout, significa que se acabaron los 30 días
        if timeout_event in resultado.events:
            return True 
        return False

    def _get_obs(self):
        """LOS NUEVOS OJOS (Datos Normalizados entre 0 y 1)"""
        obs = []
        
        # 1. Camión (Volumen normalizado a 100m3 y Edad a 12 meses)
        if self.current_truck:
            obs.append(self.current_truck.volume / 100.0)
            obs.append((self.current_truck.mean_age / 30.4167) / 12.0)
        else:
            obs.extend([0.0, 0.0])
            
        # 2. Líneas (Nivel normalizado a su capacidad máxima)
        for line in self.facility.lines:
            capacidad = max(line.hopper.container.capacity, 1.0)
            obs.append(line.hopper.container.level / capacidad)
            
        # 3. Patio (Nivel normalizado a capacidad y Edad a 12 meses)
        for col in self.flat_columns:
            capacidad_col = max(col.container.capacity, 1.0)
            obs.append(col.container.level / capacidad_col)
            obs.append((col.current_age / 30.4167) / 12.0)
            
        return np.array(obs, dtype=np.float32)

    def _calcular_recompensa(self):
        # 0. COBRAR MULTA SI EL GUARDIA INTERVINO
        if hasattr(self, 'multa_guardia') and self.multa_guardia > 0:
            return -self.multa_guardia

        # ¡Premio base por mantener la planta funcionando un paso más!
        reward = 1.0 

        # 1. DOLOR BÁSICO: Starvation
        delta_starvation = self.facility.starvation_minutes - self.last_starvation
        if delta_starvation > 0:
            reward -= (delta_starvation * 2.0)
        self.last_starvation = self.facility.starvation_minutes

        # 2. EL PREMIO DEL RATIO 60/40 (El "Caramelo")
        vol_total_hist = sum(t['volume'] for t in self.facility.truck_stats)
        vol_direct_hist = sum(t['volume'] for t in self.facility.truck_stats if t['route_taken'] == 'Direct')
        ratio_vivo = (vol_direct_hist / vol_total_hist) if vol_total_hist > 0 else 0.5

        if self.chosen_action < self.num_lineas:
            # Acción Directo
            if ratio_vivo < 0.60: reward += 15.0 # ¡Bien hecho!
            else: reward -= 2.0 # Ligero castigo, ya te pasaste
        else:
            # Acción Patio
            if ratio_vivo >= 0.60: reward += 15.0 # ¡Bien hecho, estás bajando el ratio!
            else: reward -= 2.0 # Ligero castigo, falta madera directa

        # 3. QUÍMICA: Tirón elástico suave para la edad (Meta 3.5)
        vol_total_tolvas = sum(l.hopper.container.level for l in self.facility.lines)
        if vol_total_tolvas > 0:
            edad_ponderada = sum((l.hopper.container.level * l.hopper.current_age) for l in self.facility.lines)
            edad_actual_meses = (edad_ponderada / vol_total_tolvas) / 30.4167
            error_edad = abs(edad_actual_meses - 3.5)
            reward -= error_edad * 2.0 

        return reward