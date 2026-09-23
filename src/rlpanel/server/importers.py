"""Log dosyalarını ortak ara biçime (ImportedRun) çevirir.

Veritabanı bilmez; yazma işi yalnız `ingest` içinde yapılır.
"""
from __future__ import annotations

import csv
import io
import json
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

STEP_COLUMNS = ("time/total_timesteps", "total_timesteps", "timesteps", "step")
TIME_COLUMN = "time/time_elapsed"
LONG_HEADER = ["key", "step", "value", "wall_time"]
LOG_TIME_FORMAT = "%Y-%m-%d %H:%M:%S.%f"
ZIP_CSV_NAMES = {"progress.csv", "metrics.csv"}
ZIP_SKIP_NAMES = {"run.json"}


class UnsupportedFile(ValueError):
    pass


@dataclass
class ImportedRun:
    metrics: list = field(default_factory=list)
    logs: list = field(default_factory=list)
    config: dict | None = None
    results: dict | None = None
    total_steps: int | None = None
    status: str = "finished"
    errors: list[str] = field(default_factory=list)

    def merge(self, other: "ImportedRun") -> "ImportedRun":
        self.metrics += other.metrics
        self.logs += other.logs
        self.errors += other.errors
        if other.config is not None:
            self.config = {**(self.config or {}), **other.config}
        if other.results is not None:
            self.results = {**(self.results or {}), **other.results}
        if other.total_steps is not None:
            self.total_steps = max(self.total_steps or 0, other.total_steps)
        if other.status != "finished":
            self.status = other.status
        return self

    @property
    def empty(self) -> bool:
        return not (self.metrics or self.logs or self.config or self.results)


def _num(text) -> float | None:
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def parse_progress_csv(text: str) -> ImportedRun:
    out = ImportedRun()
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if not header:
        out.errors.append("CSV boş")
        return out
    header = [h.strip() for h in header]
    if header == LONG_HEADER:
        return _parse_long_csv(reader, out)
    step_col = next((c for c in STEP_COLUMNS if c in header), None)
    step_idx = header.index(step_col) if step_col else None
    time_idx = header.index(TIME_COLUMN) if TIME_COLUMN in header else None
    bad: dict[str, int] = {}
    for line_no, row in enumerate(reader, start=2):
        if not row:
            continue
        if len(row) != len(header):
            out.errors.append(f"satır {line_no}: {len(row)} sütun var, başlıkta {len(header)}")
            continue
        if step_idx is None:
            step = line_no - 2
        else:
            parsed = _num(row[step_idx])
            if parsed is None:
                out.errors.append(f"satır {line_no}: adım değeri okunamadı")
                continue
            step = int(parsed)
        wall = _num(row[time_idx]) if time_idx is not None else None
        for index, (key, cell) in enumerate(zip(header, row)):
            if index == step_idx or cell == "":
                continue
            value = _num(cell)
            if value is None:
                bad[key] = bad.get(key, 0) + 1
                continue
            out.metrics.append([key, step, value, wall])
    for key, count in bad.items():
        out.errors.append(f"'{key}' sütununda {count} sayısal olmayan değer atlandı")
    if out.metrics:
        out.total_steps = max(m[1] for m in out.metrics)
    return out


def _parse_long_csv(reader, out: ImportedRun) -> ImportedRun:
    for line_no, row in enumerate(reader, start=2):
        if not row:
            continue
        if len(row) != 4:
            out.errors.append(f"satır {line_no}: 4 sütun bekleniyordu")
            continue
        key, step, value, wall = row
        step_num, value_num = _num(step), _num(value)
        if step_num is None or value_num is None:
            out.errors.append(f"satır {line_no}: sayı okunamadı")
            continue
        out.metrics.append([key, int(step_num), value_num, _num(wall) if wall else None])
    if out.metrics:
        out.total_steps = max(m[1] for m in out.metrics)
    return out


def parse_json(text: str, name: str = "results.json") -> ImportedRun:
    out = ImportedRun()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        out.errors.append(f"{Path(name).name}: bozuk JSON ({exc.msg}, satır {exc.lineno})")
        return out
    if not isinstance(data, dict):
        data = {"value": data}
    if Path(name.replace("\\", "/")).name.lower() == "config.json":
        out.config = data
    else:
        out.results = data
    return out


def parse_buffer_jsonl(text: str) -> ImportedRun:
    out = ImportedRun(status="stopped")  # son kayıtta durum yoksa eğitim bitmeden kesilmiştir
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            op = json.loads(line)
        except json.JSONDecodeError:
            out.errors.append(f"satır {line_no}: bozuk JSON")
            continue
        kind = op.get("op") if isinstance(op, dict) else None
        if kind == "create":
            if op.get("config") is not None:
                out.config = op["config"]
            if op.get("total_steps") is not None:
                out.total_steps = int(op["total_steps"])
        elif kind == "batch":
            batch = op.get("batch") or {}
            out.metrics += [list(m) for m in batch.get("metrics", []) if len(m) == 4]
            out.logs += [list(entry) for entry in batch.get("logs", []) if len(entry) == 3]
            if batch.get("config") is not None:
                out.config = batch["config"]
            if batch.get("results") is not None:
                out.results = {**(out.results or {}), **batch["results"]}
            if batch.get("total_steps") is not None:
                out.total_steps = int(batch["total_steps"])
            if batch.get("status"):
                out.status = batch["status"]
        else:
            out.errors.append(f"satır {line_no}: bilinmeyen kayıt")
    if out.total_steps is None and out.metrics:
        out.total_steps = max(int(m[1]) for m in out.metrics)
    return out


def format_console_line(wall_time: float | None, level: str, line: str) -> str:
    stamp = datetime.fromtimestamp(wall_time).strftime(LOG_TIME_FORMAT) if wall_time is not None else "-"
    return f"{stamp}\t{level}\t" + str(line).replace("\n", "\n\t\t")


def _timestamp(stamp: datetime) -> float | None:
    try:
        return stamp.timestamp()
    except (OSError, OverflowError, ValueError):  # Windows 1970 civarı yerel saatleri çeviremiyor
        return None


def parse_console_log(text: str) -> ImportedRun:
    out = ImportedRun()
    for raw in text.splitlines():
        if raw.startswith("\t\t") and out.logs:
            out.logs[-1][2] += "\n" + raw[2:]
            continue
        parts = raw.split("\t", 2)
        if len(parts) == 3:
            if parts[0] == "-":
                out.logs.append([None, parts[1], parts[2]])
                continue
            try:
                stamp = datetime.strptime(parts[0], LOG_TIME_FORMAT)
            except ValueError:
                stamp = None
            if stamp is not None:
                out.logs.append([_timestamp(stamp), parts[1], parts[2]])
                continue
        if raw.strip():
            out.logs.append([None, "INFO", raw])
    return out


def parse_tfevents(path: str | Path) -> ImportedRun:
    out = ImportedRun()
    try:
        from tensorboard.backend.event_processing.event_accumulator import EventAccumulator
    except ImportError:
        out.errors.append('TensorBoard dosyası için: pip install "rlpanel[tb]"')
        return out
    accumulator = EventAccumulator(str(path), size_guidance={"scalars": 0})
    accumulator.Reload()
    for tag in accumulator.Tags().get("scalars", []):
        for event in accumulator.Scalars(tag):
            out.metrics.append([tag, int(event.step), float(event.value), float(event.wall_time)])
    if out.metrics:
        out.total_steps = max(m[1] for m in out.metrics)
    return out


def parse_zip(data: bytes) -> ImportedRun:
    out = ImportedRun()
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        out.errors.append("zip dosyası bozuk")
        return out
    with archive:
        members = [info for info in archive.infolist() if not info.is_dir()]
        names = [Path(info.filename).name.lower() for info in members]
        csv_members = [m for m, n in zip(members, names) if n in ZIP_CSV_NAMES]
        if len(csv_members) > 1:
            out.errors.append(f"zip'te birden çok run var ({len(csv_members)} metrik dosyası); yalnız ilki alındı: "
                              f"{csv_members[0].filename}")
        has_csv = bool(csv_members)
        for info, name in zip(members, names):
            if name in ZIP_SKIP_NAMES or name.endswith(".png"):
                continue
            if name.endswith(".csv") and (name not in ZIP_CSV_NAMES or info is not csv_members[0]):
                continue
            if "tfevents" in name and has_csv:
                continue  # aynı metrikler iki kez gelmesin
            try:
                out.merge(parse_file(info.filename, archive.read(info)))
            except UnsupportedFile:
                continue
    return out


def parse_file(filename: str, data: bytes) -> ImportedRun:
    name = Path(filename.replace("\\", "/")).name.lower()
    if name.endswith(".zip"):
        return parse_zip(data)
    if "tfevents" in name:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "events.out.tfevents.upload"
            path.write_bytes(data)
            return parse_tfevents(path)
    text = data.decode("utf-8-sig", errors="replace")
    if name.endswith(".csv"):
        return parse_progress_csv(text)
    if name.endswith(".jsonl"):
        return parse_buffer_jsonl(text)
    if name.endswith(".json"):
        return parse_json(text, name)
    if name.endswith((".log", ".txt")):
        return parse_console_log(text)
    raise UnsupportedFile(f"desteklenmeyen dosya türü: {Path(filename).name}")


def ingest(store, project: str, run_name: str, imported: ImportedRun, *, source: str,
           content_hash: str | None = None) -> int:
    run_id = store.create_run(project, run_name, source=source, config=imported.config,
                              total_steps=imported.total_steps, content_hash=content_hash, status=imported.status)
    store.add_metrics(run_id, imported.metrics)
    store.add_logs(run_id, imported.logs)
    store.update_run(run_id, results=imported.results, current_step=imported.total_steps or 0, ended_at=time.time())
    return run_id
