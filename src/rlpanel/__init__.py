"""rlpanel: RL eğitimlerini canlı izlemek için yerel web paneli."""

__version__ = "0.1.0"

from rlpanel.client import Panel  # noqa: E402

__all__ = ["Panel", "PanelCallback", "__version__"]


def __getattr__(name: str):
    if name == "PanelCallback":  # SB3 yalnız gerekince içe aktarılsın
        from rlpanel.sb3 import PanelCallback

        return PanelCallback
    raise AttributeError(f"module 'rlpanel' has no attribute {name!r}")
