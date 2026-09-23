"""stdout/stderr ve logging kayıtlarını panel Konsol'una aktarır.

Tek örnek: hedef ("sink") en son açılan Panel'dir. Hedef kalmayınca her şey geri alınır.
"""
from __future__ import annotations

import logging
import sys
import threading
from typing import Callable

Sink = Callable[[str, str], None]

_lock = threading.Lock()
_sink: Sink | None = None
_factory = None  # logging kayıt fabrikası sarmalayıcısı (kök logger'a handler eklemez)
_previous_factory = None
_streams: tuple | None = None  # (orijinal_stdout, orijinal_stderr, tee_stdout, tee_stderr)
_EMIT_CODE = logging.StreamHandler.emit.__code__


def _inside_stream_handler() -> bool:
    frame = sys._getframe(2)
    for _ in range(8):
        if frame is None:
            return False
        if frame.f_code is _EMIT_CODE:
            return True
        frame = frame.f_back
    return False


def _capture(record: logging.LogRecord) -> None:
    # Kök logger'a handler eklemek basicConfig()'i etkisiz kılar ve lastResort'u kapatır
    # (kullanıcı terminalde warning göremez). Bunun yerine kayıtları oluştukları anda yakalıyoruz.
    name = record.name
    if not name or name == "rlpanel" or name.startswith("rlpanel."):
        return
    sink = _sink
    if sink is None:
        return
    try:
        message = record.getMessage()
        if record.exc_info:
            message += "\n" + logging.Formatter().formatException(record.exc_info)
        sink(message, record.levelname)
    except Exception:
        pass


class _Tee:
    def __init__(self, stream, level: str) -> None:
        self._stream, self._level, self._buffer = stream, level, ""

    def write(self, text):
        written = self._stream.write(text)
        sink = _sink
        if sink is not None and not _inside_stream_handler():
            try:
                self._buffer += text
                while "\n" in self._buffer:
                    line, self._buffer = self._buffer.split("\n", 1)
                    line = line.rsplit("\r", 1)[-1].rstrip()
                    if line.strip():
                        sink(line, self._level)
                if len(self._buffer) > 10_000:
                    self._buffer = self._buffer[-10_000:]
            except Exception:
                pass
        return written

    def flush(self) -> None:
        self._stream.flush()

    def __getattr__(self, name):
        return getattr(self._stream, name)


def set_sink(sink: Sink) -> None:
    global _sink
    with _lock:
        _sink = sink
        _install()


def clear_sink(sink: Sink) -> None:
    global _sink
    with _lock:
        if _sink == sink:
            _sink = None
            _uninstall()


def _install() -> None:
    global _factory, _previous_factory, _streams
    if _factory is None:
        previous = logging.getLogRecordFactory()

        def factory(*args, **kwargs):
            record = previous(*args, **kwargs)
            _capture(record)
            return record

        _previous_factory, _factory = previous, factory
        logging.setLogRecordFactory(factory)
    if _streams is None and sys.stdout is not None and sys.stderr is not None:
        out, err = sys.stdout, sys.stderr
        tee_out, tee_err = _Tee(out, "INFO"), _Tee(err, "STDERR")
        sys.stdout, sys.stderr = tee_out, tee_err
        _streams = (out, err, tee_out, tee_err)


def _uninstall() -> None:
    global _factory, _previous_factory, _streams
    if _factory is not None:
        if logging.getLogRecordFactory() is _factory:
            logging.setLogRecordFactory(_previous_factory)
        _factory = _previous_factory = None
    if _streams is not None:
        out, err, tee_out, tee_err = _streams
        if sys.stdout is tee_out:
            sys.stdout = out
        if sys.stderr is tee_err:
            sys.stderr = err
        _streams = None
