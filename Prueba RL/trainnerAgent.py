import os
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import EvalCallback
from envRL import PulpYardEnv

if __name__ == "__main__":
    print("🚀 INICIANDO ENTRENAMIENTO DE INTELIGENCIA ARTIFICIAL (PPO)")
    print("   El agente comenzará siendo torpe, pero aprenderá de sus errores...\n")

    # 1. Crear directorios para guardar el cerebro de la IA
    os.makedirs("./modelos_ia/", exist_ok=True)
    os.makedirs("./logs_ia/", exist_ok=True)

    # 2. Instanciar tu nuevo entorno de simulación
    env = PulpYardEnv(dias_simulacion=30)
    
    # Entorno de evaluación (para ver si mejora durante el entrenamiento)
    eval_env = PulpYardEnv(dias_simulacion=30)

    # 3. Configurar la Red Neuronal
    # MlpPolicy: Perceptrón Multicapa (Red Neuronal Estándar)
    modelo_ia = PPO("MlpPolicy", env, verbose=1, tensorboard_log="./logs_ia/")

    # 3. Callback Optimizado
    eval_callback = EvalCallback(
        eval_env, 
        best_model_save_path='./modelos_ia/',
        log_path='./logs_ia/', 
        eval_freq=25000,      # <-- Rinde examen cada 50,000 camiones (20 exámenes en total)
        n_eval_episodes=6,    # <-- Evalúa usando 2 meses simulados
        deterministic=True, 
        render=False
    )

    # 4. Entrenar a fondo
    TOTAL_DECISIONES = 1000000 # <-- 1 Millón de decisiones (Nivel Tesis de Ingeniería)
    
    print(f"⏳ Entrenando por {TOTAL_DECISIONES} decisiones logísticas. Esto tomará varios minutos...")
    modelo_ia.learn(total_timesteps=TOTAL_DECISIONES, callback=eval_callback)

    # 6. Guardar el cerebro final
    modelo_ia.save("./modelos_ia/romana_ppo_final")
    print("\n✅ ¡Entrenamiento Completado! El modelo ha sido guardado.")