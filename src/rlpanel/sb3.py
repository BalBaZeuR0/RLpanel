"""Stable-Baselines3 köprüsü: SB3 logger'ının yazdığı her şey panele akar."""
from __future__ import annotations

from typing import Any

from stable_baselines3.common.callbacks import BaseCallback
from stable_baselines3.common.logger import KVWriter

from rlpanel.client import Panel

_CONFIG_ATTRS = ("learning_rate", "n_steps", "batch_size", "n_epochs", "gamma", "gae_lambda", "clip_range",
                 "ent_coef", "vf_coef", "max_grad_norm", "buffer_size", "tau", "train_freq",
                 "gradient_steps", "learning_starts", "seed")


def model_config(model) -> dict[str, Any]:
    config: dict[str, Any] = {"algo": type(model).__name__, "policy": type(model.policy).__name__}
    env = getattr(model, "env", None)
    if env is not None:
        config["n_envs"] = getattr(env, "num_envs", None)
    for name in _CONFIG_ATTRS:
        value = getattr(model, name, None)
        if value is None:
            continue
        config[name] = "schedule" if callable(value) else value
    return config


class _PanelWriter(KVWriter):
    def __init__(self, panel: Panel) -> None:
        self.panel = panel

    def write(self, key_values: dict[str, Any], key_excluded: dict[str, Any], step: int = 0) -> None:
        self.panel.log(key_values, step=step)

    def close(self) -> None:
        pass


class PanelCallback(BaseCallback):
    def __init__(self, panel: Panel | None = None, *, project: str | None = None, run: str | None = None,
                 config: dict | None = None, progress_every: int = 256, verbose: int = 0, **panel_kwargs: Any) -> None:
        super().__init__(verbose)
        if panel is None and (project is None or run is None):
            raise ValueError("PanelCallback için ya panel ya da project + run verilmeli")
        self._panel = panel
        self._owns_panel = panel is None
        self._panel_args = {"project": project, "run": run, **panel_kwargs}
        self._config = config
        self.progress_every = max(1, int(progress_every))
        self._writer: _PanelWriter | None = None

    @property
    def panel(self) -> Panel | None:
        return self._panel

    def _on_training_start(self) -> None:
        if self._panel is None:
            self._panel = Panel(config=self._config or model_config(self.model), **self._panel_args)
        elif self._panel.config is None:
            self._panel.set_config(model_config(self.model))
        self._panel.progress(self.num_timesteps, getattr(self.model, "_total_timesteps", None))
        self._writer = _PanelWriter(self._panel)
        self.model.logger.output_formats.append(self._writer)

    def _on_step(self) -> bool:
        if self.n_calls % self.progress_every == 0:
            self._panel.progress(self.num_timesteps)
        return True

    def _on_training_end(self) -> None:
        self._panel.progress(self.num_timesteps)
        formats = self.model.logger.output_formats
        if self._writer in formats:
            formats.remove(self._writer)
        if self._owns_panel:
            self._panel.finish()
