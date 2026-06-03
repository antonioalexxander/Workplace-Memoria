import json
import simpy
import random
import pandas as pd
from dataclasses import dataclass
from typing import Callable, Optional
from scipy.stats import norm, expon, lognorm, weibull_min, gamma
import statistics
import math
from heuristica import Romana
from operador import OperadorHumano

# Map 
DIST_MAP = {
    'norm': norm,
    'expon': expon,
    'lognorm': lognorm,
    'weibull_min': weibull_min,
    'gamma': gamma
}

days = [
    'Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo'
    ]

density = 0.384 

# ==========================================
# 1. ENTITIES & DATA STRUCTURES
# ==========================================

@dataclass
class Truck:
    truck_id: int
    arrival_time: float
    volume: float
    mean_age: float # In days
    route_taken: Optional[str] = None
    target_obj: Optional[object] = None
    departure_time: Optional[float] = None

class StockColumn:
    def __init__(self, env: simpy.Environment, name: str, capacity: float, init_vol: float = 0, init_age: float = 0):
        self.name = name
        self.container = simpy.Container(env, capacity=capacity, init=init_vol)
        self.current_age = init_age # Mean age in days

    def put(self, volume: float, age: float):
        if volume > 0:
            current_vol = self.container.level
            self.current_age = ((current_vol * self.current_age) + (volume * age)) / (current_vol + volume)
        return self.container.put(volume)

    def get(self, volume: float):
        return self.container.get(volume)

class ProductionLine:
    def __init__(self, env: simpy.Environment, line_id: int, hopper_capacity: float):
        self.id = line_id
        self.resource = simpy.Resource(env, capacity=1)
        self.hopper = StockColumn(env, f"Line_{line_id}_Hopper", capacity=hopper_capacity)

# ==========================================
# 2. SIMULATION ENVIRONMENT
# ==========================================

class PulpFacilitySimulation:
    def __init__(self, env: simpy.Environment, strategy_func: Callable,
                 arrival_multiplier: float = 1.0,         # Escenario 1: Congestión
                 age_crisis: bool = False,                # Escenario 2: Madera polarizada
                 line_demand_tons_min: float = 2.5,       # Escenario 3: Caída de demanda
                 override_init_age_days: float = None,    # Escenario 4: Cancha vieja
                 unload_delay_multiplier: float = 1.0):   # Escenario 5: Demora en descarga
        
        self.env = env
        self.strategy_func = strategy_func

        # --- GUARDAR PARÁMETROS DE ESTRÉS ---
        self.arrival_multiplier = arrival_multiplier
        self.age_crisis = age_crisis
        self.line_demand_tons_min = line_demand_tons_min
        self.override_init_age_days = override_init_age_days
        self.unload_delay_multiplier = unload_delay_multiplier

        # --- ACTIVAR ALGORITMO ---
        self.algorithm = OperadorHumano() # Cambiar según corresponda

        with open("arrivalTime.json", "r", encoding="utf-8") as f:
            self.masterArrivalTime = json.load(f)
        
        with open("yardConfig.json", "r", encoding="utf-8") as f:
            self.yard_config = json.load(f)
        
        self.lines = [ProductionLine(env, i, hopper_capacity=500) for i in range(2)]
        
        self.stock_areas = {}
        self.crane_times = {} 
        
        for area in self.yard_config["areas"]:
            area_id = area["area_id"]
            self.stock_areas[area_id] = []
            self.crane_times[area_id] = area.get("crane_time_min", 5)
            
            for col_idx in range(area["columns"]):
                if area["pre_fill"]:
                    if random.random() < 0.30:
                        init_v = 0.0
                        init_a = 0.0
                    else:
                        init_v = random.uniform(area["init_vol"] * 0.5, min(area["capacity"], area["init_vol"] * 1.2))
                        
                        # APLICACIÓN ESCENARIO 4: Forzar edad inicial si existe el parámetro
                        if self.override_init_age_days is not None:
                            base_age = self.override_init_age_days
                        else:
                            base_age = area.get("init_age_days", 105.0)
                            
                        init_a = random.uniform(base_age * 0.85, base_age * 1.15)
                else:
                    init_v = 0.0
                    init_a = 0.0
                
                col = StockColumn(
                    env, f"Area_{area_id}_Col_{col_idx}", 
                    capacity=area["capacity"], init_vol=init_v, init_age=init_a
                )
                self.stock_areas[area_id].append(col)
                
        self.truck_stats = []
        self.stock_stats = []
        self.hourly_feed = {}
        self.starvation_minutes = 0
        self._day_starvation = 0
        self.daily_stats = []

    def run(self):
        self.env.process(self.truck_arrival_process())
        self.env.process(self.stock_monitoring_process())
        for line in self.lines:
            self.env.process(self.line_feeding_process(line))
        self.env.process(self.daily_snapshot_process())

    # --- GENERATORS ---

    def truck_arrival_process(self):
        truck_id = 0

        while True:
            # Convert the current time from Simpy to the day of the week
            dayiDx = int((self.env.now // 1440) % 7)
            dayName = days[dayiDx]

            # Convert the current time to hour of the day
            hourActual = int((self.env.now // 60) % 24)

            # Reconstruct the time block key
            keyBlock = f"{hourActual:02d}:00 - {hourActual + 1:02d}:00"

            # Find the corresponding setting in the uploaded JSON file
            configBlock = self.masterArrivalTime[dayName][keyBlock]

            # Time Support (En caso de Datos Insuficientes)
            arrivalInterTime = 75.0

            if isinstance(configBlock, dict):
                nameDist = list(configBlock.keys())[0]
                params = configBlock[nameDist]

                if nameDist in DIST_MAP:
                    randomValue = DIST_MAP[nameDist].rvs(**params)
                    arrivalInterTime = max(0.5, min(randomValue, 240.0)) 

            # APLICACIÓN ESCENARIO 1: Modificador de llegadas (ej: 0.5 = llegan el doble de rápido)
            arrivalInterTime = arrivalInterTime * self.arrival_multiplier

            yield self.env.timeout(arrivalInterTime)

            truck_id += 1

            paramsVol = {"s" : 0.11044, "loc" : -4.97973, "scale" : 34.28130}
            vol = lognorm.rvs(**paramsVol)

            # APLICACIÓN ESCENARIO 2: Madera en crisis
            if self.age_crisis:
                # 50% probabilidad de que sea madera muy fresca (1 mes), 50% que sea muy vieja (8 meses)
                age_months = random.choice([random.uniform(0.5, 1.5), random.uniform(7.0, 9.0)])
            else:
                paramsAge = {"s" : 1.40205, "loc" : -0.03016, "scale" : 0.88713}
                age_months = lognorm.rvs(**paramsAge)

            truck = Truck(truck_id=truck_id, arrival_time=self.env.now, volume=vol, mean_age=age_months * 30.4167)
            
            self.strategy_func(truck, self)
            self.env.process(self.truck_lifecycle(truck))

    def truck_lifecycle(self, truck: Truck):
        # APLICACIÓN ESCENARIO 5: Modificador de demora logística
        unload_time = random.uniform(5.0, 6.0) * self.unload_delay_multiplier
        
        if truck.route_taken == 'Direct':
            line: ProductionLine = truck.target_obj
            with line.resource.request() as req:
                yield req 
                yield self.env.timeout(unload_time)
                yield line.hopper.put(truck.volume, truck.mean_age)
                
        elif truck.route_taken == 'Stock':
            col: StockColumn = truck.target_obj
            # Asume que descargar en el patio demora 5 minutos extra por el viaje interno
            yield self.env.timeout(unload_time + 3.0) 
            yield col.put(truck.volume, truck.mean_age)

        truck.departure_time = self.env.now
        self._record_truck(truck)

    def line_feeding_process(self, line: ProductionLine, batch_size_tons: float = 75.0):
        # APLICACIÓN ESCENARIO 3: Demanda dinámica de la línea
        tons_per_min = self.line_demand_tons_min
        m3_per_min = tons_per_min / density
        batch_size_m3 = batch_size_tons / density
        
        while True:
            # 1. Batch Pull Logic: Si la tolva necesita recarga, la grúa va a la cancha
            if line.hopper.container.level < m3_per_min:
                fetch_amount = min(batch_size_m3, line.hopper.container.capacity - line.hopper.container.level)
                
                lote_conseguido = False
                
                for area_id in sorted(self.stock_areas.keys()):
                    for col in self.stock_areas[area_id]:
                        if col.container.level >= fetch_amount:
                            
                            travel_time = self.crane_times[area_id]
                            
                            # --- NUEVO: La máquina sigue operando mientras la grúa viaja ---
                            for _ in range(travel_time):
                                if line.hopper.container.level >= m3_per_min:
                                    age = line.hopper.current_age
                                    yield line.hopper.container.get(m3_per_min)
                                    self._record_feed(self.env.now, m3_per_min, age)
                                else:
                                    # La máquina colapsó esperando que la grúa volviera
                                    self.starvation_minutes += 1
                                    self._day_starvation += 1
                                yield self.env.timeout(1) # Pasa 1 minuto de viaje
                            
                            # --- Llega la grúa de vuelta con la madera ---
                            pulled_age = col.current_age
                            yield col.container.get(fetch_amount)
                            yield line.hopper.put(fetch_amount, pulled_age)
                            lote_conseguido = True
                            break 
                    if lote_conseguido:
                        break
            
            # 2. Consumption Logic: Consumo normal de 1 minuto cuando la grúa está inactiva
            if line.hopper.container.level >= m3_per_min:
                age = line.hopper.current_age
                yield line.hopper.container.get(m3_per_min)
                self._record_feed(self.env.now, m3_per_min, age)
            else:
                self.starvation_minutes += 1
                self._day_starvation += 1
                
            yield self.env.timeout(1)

    def stock_monitoring_process(self):
        """Toma una foto cada 60 minutos, envejece la madera y resetea la Romana."""
        while True:
            # 1. Envejecer la madera física
            total_vol, vol_x_age = 0.0, 0.0
            for area_id, cols in self.stock_areas.items():
                for col in cols:
                    if col.container.level > 0:
                        col.current_age += (1.0 / 24.0)
                        
                    total_vol += col.container.level
                    vol_x_age += col.container.level * col.current_age
                    
                    self.stock_stats.append({
                        'time': self.env.now,
                        'area': area_id,
                        'column': col.name,
                        'level': col.container.level,
                        'mean_age': col.current_age
                    })
                    
            # 2. Sincronizar con el cerebro Romana
            ageStorageYard_days = (vol_x_age / total_vol) if total_vol > 0 else 0.0
            
            # --- CORRECCIÓN: Romana necesita MESES ---
            self.algorithm._CloseHour(
                activeLines=len(self.lines),
                remainingCraneVol=500.0,
                maxCranePerHour=500.0,
                ageStorageYard=ageStorageYard_days / 30.4167 # <--- EN MESES
            )

            yield self.env.timeout(60)

    def daily_snapshot_process(self):
        day = 0
        while True:
            yield self.env.timeout(1440)
            day += 1
            self._record_daily_snapshot(day)
            self._day_starvation = 0

    def _record_daily_snapshot(self, day: int):
        day_start_min = (day - 1) * 1440
        day_end_min = day * 1440
        day_start_hour = (day - 1) * 24
        day_end_hour = day * 24

        # Weighted mean age of logs fed during this day
        day_vol, day_vol_x_age = 0.0, 0.0
        for h in range(day_start_hour, day_end_hour):
            if h in self.hourly_feed:
                day_vol += self.hourly_feed[h]['total_vol']
                day_vol_x_age += self.hourly_feed[h]['vol_x_age']
        mean_feed_age = (day_vol_x_age / day_vol) if day_vol > 0 else None

        # End-of-day stock snapshot: weighted mean age and total volume
        total_vol, vol_x_age = 0.0, 0.0
        for cols in self.stock_areas.values():
            for col in cols:
                v = col.container.level
                total_vol += v
                vol_x_age += v * col.current_age
        mean_stock_age = (vol_x_age / total_vol) if total_vol > 0 else None

        # Truck metrics for trucks that arrived during this day
        # Truck metrics for trucks that arrived during this day
        day_trucks = [t for t in self.truck_stats if day_start_min <= t['arrival_time'] < day_end_min]
        n_total = len(day_trucks)
        
        # --- NUEVA LÓGICA: PROMEDIOS POR VOLUMEN ---
        vol_total = sum(t['volume'] for t in day_trucks)
        vol_direct = sum(t['volume'] for t in day_trucks if t['route_taken'] == 'Direct')
        vol_stock = vol_total - vol_direct
        
        # Porcentaje de volumen enviado a patio
        stock_pct_vol = (vol_stock / vol_total) if vol_total > 0 else None
        
        # Promedio ponderado del tiempo de espera (según el volumen del camión)
        # Un camión más grande impacta más en la métrica que uno pequeño
        wait_x_vol = sum(t['time_in_system'] * t['volume'] for t in day_trucks)
        mean_wait_weighted = (wait_x_vol / vol_total) if vol_total > 0 else None

        self.daily_stats.append({
            'day': day,
            'mean_feed_age_days': round(mean_feed_age, 2) if mean_feed_age is not None else None,
            'mean_stock_age_days': round(mean_stock_age, 2) if mean_stock_age is not None else None,
            'total_stock_vol': round(total_vol, 1),
            'starvation_min': self._day_starvation,
            'trucks_total': n_total,
            'vol_direct': round(vol_direct, 1), # <-- Cambiado para mostrar M3
            'vol_stock': round(vol_stock, 1),   # <-- Cambiado para mostrar M3
            'stock_pct': round(stock_pct_vol, 3) if stock_pct_vol is not None else None, # <-- Usa el % por volumen
            'mean_truck_wait_min': round(mean_wait_weighted, 1) if mean_wait_weighted is not None else None, # <-- Usa el tiempo ponderado
        })

    # --- METRIC RECORDERS ---

    def _record_truck(self, truck: Truck):
        self.truck_stats.append({
            'truck_id': truck.truck_id,
            'arrival_time': truck.arrival_time,
            'time_in_system': truck.departure_time - truck.arrival_time,
            'volume': truck.volume,
            'route_taken': truck.route_taken,
            'mean_age': truck.mean_age
        })

    def _record_feed(self, current_time: float, volume: float, age: float):
        hour = int(current_time // 60)
        if hour not in self.hourly_feed:
            self.hourly_feed[hour] = {'total_vol': 0.0, 'vol_x_age': 0.0}
        self.hourly_feed[hour]['total_vol'] += volume
        self.hourly_feed[hour]['vol_x_age'] += (volume * age)

    def get_metrics(self):
        # 1. Ratio Directo vs Stock (por volumen)
        vol_total = sum(t['volume'] for t in self.truck_stats)
        vol_direct = sum(t['volume'] for t in self.truck_stats if t['route_taken'] == 'Direct')
        ratio_picado = (vol_direct / vol_total) if vol_total > 0 else 0
        
        # 2. Edad promedio en la línea
        total_vol_fed, total_age_fed = 0.0, 0.0
        for h_data in self.hourly_feed.values():
            total_vol_fed += h_data['total_vol']
            total_age_fed += h_data['vol_x_age']
        mean_feed_age_days = (total_age_fed / total_vol_fed) if total_vol_fed > 0 else 0
        
        # 3. Tiempo promedio de espera
        total_wait = sum(t['time_in_system'] for t in self.truck_stats)
        mean_truck_wait_min = (total_wait / len(self.truck_stats)) if self.truck_stats else 0
        
        # 4. Inanición
        starvation_min = self.starvation_minutes
        
        # 5. Edad de la madera enviada a cancha
        vol_stock = 0.0
        age_vol_stock = 0.0
        for t in self.truck_stats:
            if t['route_taken'] == 'Stock':
                vol_stock += t['volume']
                age_vol_stock += (t['volume'] * t['mean_age'])
        mean_stock_routing_age_days = (age_vol_stock / vol_stock) if vol_stock > 0 else 0.0
        
        # 6. Edad promedio del patio al terminar la simulación
        total_vol_yard, age_vol_yard = 0.0, 0.0
        for cols in self.stock_areas.values():
            for col in cols:
                if col.container.level > 0:
                    total_vol_yard += col.container.level
                    age_vol_yard += (col.container.level * col.current_age)
        final_yard_age_days = (age_vol_yard / total_vol_yard) if total_vol_yard > 0 else 0.0
        
        # ==========================================================
        # 7. NUEVO: DESVIACIÓN ESTÁNDAR PONDERADA (Por Volumen Diario)
        # ==========================================================
        edades_y_pesos = []
        for d_info in self.daily_stats:
            day = d_info['day']
            age_days = d_info['mean_feed_age_days']
            
            if age_days is not None:
                # Reconstruimos el volumen exacto que consumió la máquina ese día
                day_start_hour = (day - 1) * 24
                day_end_hour = day * 24
                vol_dia = sum(self.hourly_feed.get(h, {}).get('total_vol', 0.0) for h in range(day_start_hour, day_end_hour))
                
                # Guardamos la dupla (Edad en meses, Volumen en m3)
                if vol_dia > 0:
                    edades_y_pesos.append((age_days / 30.4167, vol_dia))
        
        # Aplicamos la fórmula de varianza/desviación ponderada
        if len(edades_y_pesos) > 1:
            total_vol_evaluado = sum(vol for age, vol in edades_y_pesos)
            
            # Promedio ponderado (coincide con mean_feed_age_months)
            mean_w = sum(age * vol for age, vol in edades_y_pesos) / total_vol_evaluado
            
            # Varianza ponderada
            var_w = sum(vol * ((age - mean_w) ** 2) for age, vol in edades_y_pesos) / total_vol_evaluado
            
            # Desviación estándar ponderada
            std_feed_age_months = math.sqrt(var_w)
        else:
            std_feed_age_months = 0.0
            
        return ratio_picado, mean_feed_age_days, mean_truck_wait_min, starvation_min, mean_stock_routing_age_days, final_yard_age_days, std_feed_age_months


# ==========================================
# 3. ROUTING STRATEGY
# ==========================================

def priority_direct_strategy(truck: Truck, sim: PulpFacilitySimulation):
    for line in sim.lines:
        if line.hopper.container.level < 150 and (line.hopper.container.level + truck.volume <= line.hopper.container.capacity):
            truck.route_taken = 'Direct'
            truck.target_obj = line
            return

    available_cols = []
    for area_id in range(2, 12):
        for col in sim.stock_areas[area_id]:
            if col.container.level + truck.volume <= col.container.capacity:
                available_cols.append(col)
                
    if available_cols:
        truck.route_taken = 'Stock'
        truck.target_obj = random.choice(available_cols)
    else:
        truck.route_taken = 'Direct'
        truck.target_obj = sim.lines[0]

def algorithm_strategy(truck: Truck, sim: PulpFacilitySimulation):
    total_vol = 0.0
    vol_x_age = 0.0
    for cols in sim.stock_areas.values():
        for col in cols:
            total_vol += col.container.level
            vol_x_age += col.container.level * col.current_age
    
    ageStorageYard_days = (vol_x_age / total_vol) if total_vol > 0 else 0.0
    
    # --- CORRECCIÓN: Romana necesita que le hablen en MESES ---
    ageStorageYard_months = ageStorageYard_days / 30.4167
    ageTruck_months = truck.mean_age / 30.4167
    
    active_lines = len(sim.lines)
    maxCranePerHour = 500.0
    remainingCraneVol = 500.0 
    
    # 2. Consultar al "Cerebro" (Romana)
    decision, pen1, pen2, pen3 = sim.algorithm._EvaluateTruck(
        id=truck.truck_id,
        volTruck=truck.volume,
        ageTruck=ageTruck_months,             
        activeLines=active_lines,
        unloadingSy='Descarga',
        remainingCraneVol=remainingCraneVol,
        maxCranePerHour=maxCranePerHour,
        ageStorageYard=ageStorageYard_months  
    )
    
    # 3. Ejecutar la decisión física en el simulador SimPy
    if 'Picado Directo' in decision:
        truck.route_taken = 'Direct'
        # Buscar la línea que tenga más espacio en su tolva
        best_line = min(sim.lines, key=lambda l: l.hopper.container.level)
        truck.target_obj = best_line
    else:
        truck.route_taken = 'Stock'
        # Buscar columnas disponibles en el patio
        available_cols = []

        # --- NUEVO: Leer los IDs de las canchas directamente desde el JSON ---
        for area_id in sim.stock_areas.keys():
            for col in sim.stock_areas[area_id]:
                if col.container.level + truck.volume <= col.container.capacity:
                    available_cols.append(col)
                    
        if available_cols:
            truck.target_obj = random.choice(available_cols)
        else:
            # Emergencia: Mandar a la línea con menos fila/espacio disponible
            truck.route_taken = 'Direct'
            best_line = min(sim.lines, key=lambda l: len(l.resource.queue) + l.hopper.container.level)
            truck.target_obj = best_line     

# ==========================================
# 4. EXECUTION BLOCK
# ==========================================

if __name__ == "__main__":
    SIM_DAYS = 30
    SIMULATION_TIME = SIM_DAYS * 24 * 60

    print(f"Initializing {SIM_DAYS}-Day Simulation...")
    env = simpy.Environment()
    facility = PulpFacilitySimulation(env, strategy_func=algorithm_strategy)
    facility.run()
    env.run(until=SIMULATION_TIME)

    # SimPy does not process events at exactly t=SIMULATION_TIME, so the last
    # daily_snapshot_process tick may be skipped. Capture any remaining day here.
    last_recorded = len(facility.daily_stats)
    if last_recorded < SIM_DAYS:
        facility._record_daily_snapshot(last_recorded + 1)

    print(f"Simulation complete ({SIM_DAYS} days, {SIMULATION_TIME} minutes).")

    # Build DataFrames
    df_daily = pd.DataFrame(facility.daily_stats)
    # ==============================================================
    # --- NUEVO: CONVERSIÓN DE DÍAS A MESES PARA LA VISUALIZACIÓN ---
    # ==============================================================
    if not df_daily.empty:
        df_daily['mean_feed_age_months'] = (df_daily['mean_feed_age_days'] / 30.4167).round(2)
        df_daily['mean_stock_age_months'] = (df_daily['mean_stock_age_days'] / 30.4167).round(2)

    df_trucks = pd.DataFrame(facility.truck_stats)
    if not df_trucks.empty:
        df_trucks['day'] = (df_trucks['arrival_time'] // 1440).astype(int) + 1

    pd.set_option('display.float_format', '{:.2f}'.format)
    pd.set_option('display.max_rows', 60)

    # ── [1] Daily summary ──────────────────────────────────────────────────────
    print("\n[1] DAILY SUMMARY (Edades en Meses)")
    # Seleccionamos las columnas con los nombres nuevos en meses
    cols_to_show = ['day', 'mean_feed_age_months', 'mean_stock_age_months', 'total_stock_vol', 
                    'starvation_min', 'trucks_total', 'vol_direct', 'vol_stock', 'stock_pct', 'mean_truck_wait_min']
    if not df_daily.empty:
        print(df_daily[cols_to_show].to_string(index=False))

    # ── [2] Routing split ─────────────────────────────────────────────────────
    print("\n[2] TRUCK ROUTING (overall by volume)")
    n_trucks = len(df_trucks)
    
    if n_trucks > 0:
        vol_by_route = df_trucks.groupby('route_taken')['volume'].sum()
        total_vol = df_trucks['volume'].sum()
        vol_direct = vol_by_route.get('Direct', 0.0)
        vol_stock = vol_by_route.get('Stock', 0.0)
        
        print(f"  Total trucks      : {n_trucks}")
        print(f"  Total Volume (m3) : {total_vol:.1f}")
        print(f"  Direct            : {vol_direct:.1f} m3  ({(vol_direct/total_vol)*100:.1f}%)")
        print(f"  Stock             : {vol_stock:.1f} m3  ({(vol_stock/total_vol)*100:.1f}%)")
    else:
        print("  No trucks processed.")

    # ── [3] Starvation ────────────────────────────────────────────────────────
    print("\n[3] STARVATION (per production line, combined)")
    print(f"  Total         : {facility.starvation_minutes} min  "
          f"({facility.starvation_minutes/60:.1f} h)")
    if not df_daily.empty:
        print(f"  Daily min/max : {int(df_daily['starvation_min'].min())} / "
              f"{int(df_daily['starvation_min'].max())} min")

    # ── [4] Feed age by day ───────────────────────────────────────────────────
    print("\n[4] WEIGHTED MEAN AGE OF LOGS FED TO LINE (daily, in months)")
    if not df_daily.empty:
        print(df_daily[['day', 'mean_feed_age_months']].to_string(index=False))

    # ── [5] Stock health by day ───────────────────────────────────────────────
    print("\n[5] STOCK HEALTH (end-of-day snapshot, in months)")
    if not df_daily.empty:
        print(df_daily[['day', 'total_stock_vol', 'mean_stock_age_months']].to_string(index=False))

    # ── [6] Truck wait times ──────────────────────────────────────────────────
    print("\n[6] TRUCK WAIT TIMES (daily mean weighted, minutes)")
    if not df_daily.empty:
        print(df_daily[['day', 'trucks_total', 'vol_direct', 'vol_stock',
                        'stock_pct', 'mean_truck_wait_min']].to_string(index=False))