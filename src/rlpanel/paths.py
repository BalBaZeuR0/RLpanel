"""Veri klasörü ve veritabanı yolu. Ortam değişkenleri testlerde/izole kurulumda yolu değiştirir."""
from __future__ import annotations

import os
from pathlib import Path


def home_dir() -> Path:
    return Path(os.environ.get("RLPANEL_HOME") or Path.home() / ".rlpanel")


def db_path() -> Path:
    return Path(os.environ.get("RLPANEL_DB") or home_dir() / "panel.db")
