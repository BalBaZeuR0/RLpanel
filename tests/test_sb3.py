import pytest

pytest.importorskip("stable_baselines3")

from stable_baselines3 import PPO  # noqa: E402

from rlpanel import Panel, PanelCallback  # noqa: E402

pytestmark = pytest.mark.slow


def _model():
    return PPO("MlpPolicy", "CartPole-v1", n_steps=64, batch_size=32, n_epochs=1, seed=0, verbose=0, device="cpu")


def test_callback_streams_metrics_and_progress(live_server, tmp_path):
    panel = Panel("Test", "cartpole", server=live_server.url, run_dir=tmp_path, open_browser=False,
                  capture_logs=False, flush_interval=0.1)
    _model().learn(total_timesteps=256, callback=PanelCallback(panel, progress_every=16))
    panel.finish()
    store = live_server.store
    run = store.get_run(panel.run_id)
    assert (run["total_steps"], run["current_step"], run["status"]) == (256, 256, "finished")
    keys = set(store.metric_keys(panel.run_id))
    assert {"rollout/ep_rew_mean", "rollout/ep_len_mean", "train/learning_rate", "time/fps"} <= keys


def test_callback_can_own_its_panel(live_server, tmp_path):
    callback = PanelCallback(project="Test", run="owned", server=live_server.url, run_dir=tmp_path,
                             open_browser=False, capture_logs=False)
    _model().learn(total_timesteps=128, callback=callback)
    run = live_server.store.get_run(callback.panel.run_id)
    assert run["status"] == "finished"
    assert run["config"]["algo"] == "PPO" and run["config"]["n_steps"] == 64


def test_callback_requires_panel_or_names():
    with pytest.raises(ValueError):
        PanelCallback()
