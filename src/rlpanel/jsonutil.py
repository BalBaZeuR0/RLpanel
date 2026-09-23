"""JSON temizliği: NaN/inf JSON standardında yok; Starlette yanıtları ve tarayıcı JSON.parse bunlarda patlar."""
from __future__ import annotations

import math
from typing import Any


def clean_json(value: Any) -> Any:
    """NaN/inf → "nan"/"inf" metni, sözlük anahtarları → str, tuple → list (özyinelemeli)."""
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, dict):
        return {str(k): clean_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(v) for v in value]
    return value
