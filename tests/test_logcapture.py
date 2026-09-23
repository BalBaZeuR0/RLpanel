import logging
import sys

from rlpanel import logcapture


def test_print_and_logging_are_captured_once_with_levels():
    lines = []
    sink = lambda line, level: lines.append((line, level))
    original = sys.stdout
    logcapture.set_sink(sink)
    logger = logging.getLogger("deneme.capture")
    handler = logging.StreamHandler(sys.stdout)  # tee'ye yazan bir handler: satır iki kez gelmemeli
    logger.addHandler(handler)
    try:
        print("merhaba")
        logger.warning("dikkat")
        print("a\rb")
        print("")
    finally:
        logger.removeHandler(handler)
        logcapture.clear_sink(sink)
    assert lines == [("merhaba", "INFO"), ("dikkat", "WARNING"), ("b", "INFO")]
    assert sys.stdout is original


def test_rlpanel_own_logs_are_ignored():
    lines = []
    sink = lambda line, level: lines.append(line)
    logcapture.set_sink(sink)
    try:
        logging.getLogger("rlpanel.watcher").warning("iç log")
    finally:
        logcapture.clear_sink(sink)
    assert lines == []


def test_clear_sink_with_other_sink_keeps_capture():
    first, second = [], []
    a = lambda line, level: first.append(line)
    b = lambda line, level: second.append(line)
    logcapture.set_sink(a)
    logcapture.set_sink(b)
    logcapture.clear_sink(a)  # güncel hedef b; a'yı silmek yakalamayı kapatmamalı
    try:
        print("x")
    finally:
        logcapture.clear_sink(b)
    assert first == [] and second == ["x"]
