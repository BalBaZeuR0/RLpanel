"""Bir run'ı tek zip olarak dışa aktarır (grafik PNG'leri tarayıcı tarafında eklenir)."""
from __future__ import annotations

import csv
import io
import json
import zipfile

from rlpanel.server.importers import LONG_HEADER, format_console_line
from rlpanel.server.store import Store

RUN_INFO_FIELDS = ("project", "name", "seed", "status", "source", "host", "total_steps",
                   "current_step", "started_at", "ended_at")


def build_export_zip(store: Store, run_id: int) -> bytes | None:
    run = store.get_run(run_id)
    if run is None:
        return None
    metrics = io.StringIO()
    writer = csv.writer(metrics, lineterminator="\n")
    writer.writerow(LONG_HEADER)
    for key, rows in store.get_metrics(run_id).items():
        for step, value, wall_time in rows:
            writer.writerow([key, step, repr(value), "" if wall_time is None else repr(wall_time)])
    console = "\n".join(format_console_line(l["wall_time"], l["level"], l["line"]) for l in store.get_logs(run_id))
    info = {key: run[key] for key in RUN_INFO_FIELDS}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("metrics.csv", metrics.getvalue())
        archive.writestr("config.json", json.dumps(run["config"] or {}, indent=2, ensure_ascii=False))
        archive.writestr("results.json", json.dumps(run["results"] or {}, indent=2, ensure_ascii=False))
        archive.writestr("run.json", json.dumps(info, indent=2, ensure_ascii=False))
        archive.writestr("console.log", console)
    return buffer.getvalue()
