import json
import simpy
import random
import pandas as pd
from dataclasses import dataclass
from typing import Callable, Optional
from scipy.stats import norm, expon, lognorm, weibull_min, gamma

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
    def __init__(self, env: simpy.Environment, strategy_func: Callable):
        self.env = env
        self.strategy_func = strategy_func

        # --- NEW: Upload the inter-arrival time file ---
        with open("arrivalTime.json", "r", encoding="utf-8") as f:
            self.masterArrivalTime = json.load(f)
        
        self.lines = [ProductionLine(env, i, hopper_capacity=500) for i in range(2)]
        
        self.stock_areas = {}
        for area_id in range(1, 12):
            self.stock_areas[area_id] = []
            for col_idx in range(5):
                # Pre-fill area 1 heavily so we survive multi-week simulation starts
                init_v = 150 if area_id == 1 else 0
                init_a = random.uniform(5, 10) if area_id == 1 else 0
                col = StockColumn(env, f"Area_{area_id}_Col_{col_idx}", capacity=500, init_vol=init_v, init_age=init_a)
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
                    # A random value is generated
                    randomValue = DIST_MAP[nameDist].rvs(**params)
                    # Avoid negative or extremely small numbers
                    # It was taking me way too long, and I wasn't getting anything done. Set a time limit of 240 minutes.
                    arrivalInterTime = max(0.5, min(randomValue, 240.0)) 

            # simulator queue
            yield self.env.timeout(arrivalInterTime)

            # The truck is created
            truck_id += 1


            paramsVol = {
                "s" : 0.11044,
                "loc" : -4.97973,
                "scale" : 34.28130
            }
            vol = lognorm.rvs(**paramsVol)

            paramsAge = {
                "s" : 1.40205,
                "loc" : -0.03016,
                "scale" : 0.88713
            }
            age = lognorm.rvs(**paramsAge)

            truck = Truck(truck_id=truck_id, arrival_time=self.env.now, volume=vol, mean_age=age)
            
            self.strategy_func(truck, self)
            self.env.process(self.truck_lifecycle(truck))

    def truck_lifecycle(self, truck: Truck):
        unload_time = 10.0 
        
        if truck.route_taken == 'Direct':
            line: ProductionLine = truck.target_obj
            with line.resource.request() as req:
                yield req 
                yield self.env.timeout(unload_time)
                yield line.hopper.put(truck.volume, truck.mean_age)
                
        elif truck.route_taken == 'Stock':
            col: StockColumn = truck.target_obj
            yield self.env.timeout(unload_time + 5.0) 
            yield col.put(truck.volume, truck.mean_age)

        truck.departure_time = self.env.now
        self._record_truck(truck)

    def line_feeding_process(self, line: ProductionLine, batch_size_tons: float = 75.0):
        """
        Discretized continuous flow: Pulls 2.5 tons/minute.
        If hopper is empty, requests a large `batch_size_tons` from stock to last several minutes.
        """
        tons_per_min = 2.5 
        predefined_reclaim_area = 1
        
        while True:
            # 1. Batch Pull Logic: If hopper can't sustain the next minute, fetch a batch
            if line.hopper.container.level < tons_per_min:
                fetch_amount = min(batch_size_tons, line.hopper.container.capacity - line.hopper.container.level)
                
                # Find a column in the active area with enough volume
                for col in self.stock_areas[predefined_reclaim_area]:
                    if col.container.level >= fetch_amount:
                        pulled_age = col.current_age
                        yield col.container.get(fetch_amount)
                        # Add batch to the hopper
                        yield line.hopper.put(fetch_amount, pulled_age)
                        break 
            
            # 2. Consumption Logic: Consume 1 minute worth of logs
            if line.hopper.container.level >= tons_per_min:
                age = line.hopper.current_age
                yield line.hopper.container.get(tons_per_min)
                self._record_feed(self.env.now, tons_per_min, age)
            else:
                self.starvation_minutes += 1
                self._day_starvation += 1
                
            yield self.env.timeout(1) 

    def stock_monitoring_process(self):
        """Takes a snapshot every 60 minutes and increments log age."""
        while True:
            for area_id, cols in self.stock_areas.items():
                for col in cols:
                    # AGING LOGIC: Increment age by 1 hour (1/24th of a day) if logs exist
                    if col.container.level > 0:
                        col.current_age += (1.0 / 24.0)

                    # Snapshot
                    self.stock_stats.append({
                        'time': self.env.now,
                        'area': area_id,
                        'column': col.name,
                        'level': col.container.level,
                        'mean_age': col.current_age
                    })
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
        day_trucks = [t for t in self.truck_stats if day_start_min <= t['arrival_time'] < day_end_min]
        n_total = len(day_trucks)
        n_direct = sum(1 for t in day_trucks if t['route_taken'] == 'Direct')
        n_stock = n_total - n_direct
        mean_wait = (sum(t['time_in_system'] for t in day_trucks) / n_total) if n_total > 0 else None

        self.daily_stats.append({
            'day': day,
            'mean_feed_age_days': round(mean_feed_age, 2) if mean_feed_age is not None else None,
            'mean_stock_age_days': round(mean_stock_age, 2) if mean_stock_age is not None else None,
            'total_stock_vol': round(total_vol, 1),
            'starvation_min': self._day_starvation,
            'trucks_total': n_total,
            'trucks_direct': n_direct,
            'trucks_stock': n_stock,
            'stock_pct': round(n_stock / n_total, 3) if n_total > 0 else None,
            'mean_truck_wait_min': round(mean_wait, 1) if mean_wait is not None else None,
        })

    # --- METRIC RECORDERS ---

    def _record_truck(self, truck: Truck):
        self.truck_stats.append({
            'truck_id': truck.truck_id,
            'arrival_time': truck.arrival_time,
            'time_in_system': truck.departure_time - truck.arrival_time,
            'volume': truck.volume,
            'route_taken': truck.route_taken
        })

    def _record_feed(self, current_time: float, volume: float, age: float):
        hour = int(current_time // 60)
        if hour not in self.hourly_feed:
            self.hourly_feed[hour] = {'total_vol': 0.0, 'vol_x_age': 0.0}
        self.hourly_feed[hour]['total_vol'] += volume
        self.hourly_feed[hour]['vol_x_age'] += (volume * age)


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

# ==========================================
# 4. EXECUTION BLOCK
# ==========================================

if __name__ == "__main__":
    SIM_DAYS = 14
    SIMULATION_TIME = SIM_DAYS * 24 * 60

    print(f"Initializing {SIM_DAYS}-Day Simulation...")
    env = simpy.Environment()
    facility = PulpFacilitySimulation(env, strategy_func=priority_direct_strategy)
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
    df_trucks = pd.DataFrame(facility.truck_stats)
    df_trucks['day'] = (df_trucks['arrival_time'] // 1440).astype(int) + 1

    feed_rows = [
        {'hour': h, 'day': h // 24 + 1, 'total_vol': d['total_vol'],
         'mean_feed_age': d['vol_x_age'] / d['total_vol']}
        for h, d in facility.hourly_feed.items() if d['total_vol'] > 0
    ]
    df_feed = pd.DataFrame(feed_rows).sort_values('hour')

    pd.set_option('display.float_format', '{:.2f}'.format)
    pd.set_option('display.max_rows', 60)

    # ── [1] Daily summary ──────────────────────────────────────────────────────
    print("\n[1] DAILY SUMMARY")
    print(df_daily.to_string(index=False))

    # ── [2] Routing split ─────────────────────────────────────────────────────
    print("\n[2] TRUCK ROUTING (overall)")
    rc = df_trucks['route_taken'].value_counts()
    n = len(df_trucks)
    print(f"  Total trucks  : {n}")
    print(f"  Direct        : {rc.get('Direct', 0)}  ({rc.get('Direct', 0)/n*100:.1f}%)")
    print(f"  Stock         : {rc.get('Stock',  0)}  ({rc.get('Stock',  0)/n*100:.1f}%)")

    # ── [3] Starvation ────────────────────────────────────────────────────────
    print("\n[3] STARVATION (per production line, combined)")
    print(f"  Total         : {facility.starvation_minutes} min  "
          f"({facility.starvation_minutes/60:.1f} h)")
    if not df_daily.empty:
        print(f"  Daily min/max : {int(df_daily['starvation_min'].min())} / "
              f"{int(df_daily['starvation_min'].max())} min")

    # ── [4] Feed age by day ───────────────────────────────────────────────────
    print("\n[4] WEIGHTED MEAN AGE OF LOGS FED TO LINE (daily)")
    print(df_daily[['day', 'mean_feed_age_days']].to_string(index=False))

    # ── [5] Stock health by day ───────────────────────────────────────────────
    print("\n[5] STOCK HEALTH (end-of-day snapshot)")
    print(df_daily[['day', 'total_stock_vol', 'mean_stock_age_days']].to_string(index=False))

    # ── [6] Truck wait times ──────────────────────────────────────────────────
    print("\n[6] TRUCK WAIT TIMES (daily mean, minutes)")
    print(df_daily[['day', 'trucks_total', 'trucks_direct', 'trucks_stock',
                    'stock_pct', 'mean_truck_wait_min']].to_string(index=False))