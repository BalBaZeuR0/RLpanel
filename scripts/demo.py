"""Demo verisi: 3 seed'li bitmiş deney + canlı akan bir eğitim. Kullanım: python scripts/demo.py"""
import math
import random
import time

from rlpanel import Panel

random.seed(0)
for seed in range(3):
    panel = Panel("Demo-CartPole", f"ppo/seed_{seed}", seed=seed, config={"algo": "PPO", "lr": 3e-4, "n_steps": 2048},
                  total_steps=100_000, capture_logs=False, open_browser=False)
    for step in range(0, 100_001, 2048):
        reward = 500 * (1 - math.exp(-step / (25_000 + 4_000 * seed))) + random.gauss(0, 12)
        panel.log({"rollout/ep_rew_mean": reward, "rollout/ep_len_mean": reward, "train/learning_rate": 3e-4,
                   "train/entropy_loss": -0.69 + step / 400_000, "train/value_loss": 50 * math.exp(-step / 30_000) + 1,
                   "time/fps": 1800 + random.gauss(0, 50)}, step=step)
        panel.progress(step)
    panel.result({"final_reward": round(reward, 1), "seed": seed})
    panel.finish()

live = Panel("Demo-CartPole", "ppo/seed_3", seed=3, config={"algo": "PPO", "lr": 3e-4}, total_steps=100_000, capture_logs=True)
print(f"Canlı demo: {live.url}")
for step in range(0, 100_001, 1024):
    reward = 500 * (1 - math.exp(-step / 20_000)) + random.gauss(0, 10)
    live.log({"rollout/ep_rew_mean": reward, "rollout/ep_len_mean": reward, "train/learning_rate": 3e-4,
              "rollout/success_rate": min(1.0, step / 80_000), "time/fps": 900}, step=step)
    live.progress(step)
    if step % 8192 == 0:
        print(f"adım {step}: reward {reward:.1f}")
    time.sleep(0.5)
live.finish()
