"""Küçük stdlib HTTP yardımcıları (istemci tarafında `requests` bağımlılığı olmasın).

Sistem proxy'leri kullanılmaz: kurumsal proxy ayarı localhost isteklerini yutmasın.
"""
from __future__ import annotations

import json
import urllib.request
import uuid
from pathlib import Path
from typing import Any

TIMEOUT = 5.0
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _send(request: urllib.request.Request, timeout: float) -> Any:
    with _OPENER.open(request, timeout=timeout) as response:
        body = response.read()
    return json.loads(body) if body else None


def get_json(url: str, timeout: float = TIMEOUT) -> Any:
    return _send(urllib.request.Request(url, headers={"Accept": "application/json"}), timeout)


def post_json(url: str, payload: Any, timeout: float = TIMEOUT) -> Any:
    data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})
    return _send(request, timeout)


def delete_json(url: str, timeout: float = TIMEOUT) -> Any:
    return _send(urllib.request.Request(url, method="DELETE"), timeout)


def post_file(url: str, path: str | Path, fields: dict[str, str], timeout: float = 120.0) -> Any:
    path = Path(path)
    boundary = uuid.uuid4().hex
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n".encode() + path.read_bytes() + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    request = urllib.request.Request(url, data=b"".join(parts), method="POST",
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    return _send(request, timeout)
