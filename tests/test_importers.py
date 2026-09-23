import io
import json
import zipfile

import pytest

from rlpanel.server.importers import (
    ImportedRun, UnsupportedFile, format_console_line, ingest, parse_buffer_jsonl,
    parse_console_log, parse_file, parse_json, parse_progress_csv, parse_tfevents, parse_zip,
)
from rlpanel.server.store import Store

SB3_CSV = (
    "rollout/ep_len_mean,rollout/ep_rew_mean,time/fps,time/iterations,time/time_elapsed,"
    "time/total_timesteps,train/learning_rate\n"
    "20.5,20.5,900,1,0,64,\n"
    "25.0,25.0,950,2,1,128,0.0003\n"
)


def test_sb3_progress_csv_uses_total_timesteps_as_step_and_elapsed_as_time():
    run = parse_progress_csv(SB3_CSV)
    rewards = [m for m in run.metrics if m[0] == "rollout/ep_rew_mean"]
    assert rewards == [["rollout/ep_rew_mean", 64, 20.5, 0.0], ["rollout/ep_rew_mean", 128, 25.0, 1.0]]
    assert not any(m[0] == "time/total_timesteps" for m in run.metrics)
    assert [m for m in run.metrics if m[0] == "train/learning_rate"] == [["train/learning_rate", 128, 0.0003, 1.0]]
    assert run.total_steps == 128
    assert run.errors == []


def test_csv_without_step_column_uses_row_index():
    run = parse_progress_csv("loss\n0.5\n0.4\n")
    assert run.metrics == [["loss", 0, 0.5, None], ["loss", 1, 0.4, None]]


def test_csv_non_numeric_column_reported_once_other_values_kept():
    run = parse_progress_csv("step,loss,note\n1,0.5,hello\n2,0.4,world\n")
    assert [m[:3] for m in run.metrics] == [["loss", 1, 0.5], ["loss", 2, 0.4]]
    assert run.errors == ["'note' sütununda 2 sayısal olmayan değer atlandı"]


def test_csv_bad_row_reported_with_line_number():
    run = parse_progress_csv("step,loss\n1,0.5\n2,0.4,extra\nx,0.3\n4,0.2\n")
    assert [m[1] for m in run.metrics] == [1, 4]
    assert run.errors == ["satır 3: 3 sütun var, başlıkta 2", "satır 4: adım değeri okunamadı"]


def test_empty_csv():
    assert parse_progress_csv("").errors == ["CSV boş"]


def test_long_format_csv_roundtrip():
    run = parse_progress_csv("key,step,value,wall_time\nloss,1,0.5,10.0\nacc,2,0.9,\n")
    assert run.metrics == [["loss", 1, 0.5, 10.0], ["acc", 2, 0.9, None]]
    assert run.total_steps == 2


def test_json_results_and_config():
    assert parse_json('{"score": 1}').results == {"score": 1}
    assert parse_json('{"lr": 0.1}', "sub/config.json").config == {"lr": 0.1}
    assert parse_json("[1, 2]").results == {"value": [1, 2]}
    bad = parse_json("{oops", "results.json")
    assert bad.results is None and bad.errors[0].startswith("results.json: bozuk JSON")


def test_buffer_jsonl():
    lines = [
        json.dumps({"op": "create", "project": "P", "name": "r", "config": {"lr": 1}, "total_steps": 100}),
        json.dumps({"op": "batch", "batch": {"metrics": [["loss", 1, 0.5, 10.0]], "logs": [[10.0, "INFO", "hi"]],
                                              "current_step": 1}}),
        "{broken",
        json.dumps({"op": "batch", "batch": {"metrics": [], "logs": [], "results": {"a": 1}, "status": "crashed"}}),
    ]
    run = parse_buffer_jsonl("\n".join(lines))
    assert run.config == {"lr": 1}
    assert run.total_steps == 100
    assert run.metrics == [["loss", 1, 0.5, 10.0]]
    assert run.logs == [[10.0, "INFO", "hi"]]
    assert run.results == {"a": 1}
    assert run.status == "crashed"
    assert run.errors == ["satır 3: bozuk JSON"]


def test_buffer_without_status_is_stopped():
    line = json.dumps({"op": "batch", "batch": {"metrics": [["x", 5, 1.0, None]], "logs": []}})
    run = parse_buffer_jsonl(line)
    assert run.status == "stopped" and run.total_steps == 5


def test_console_log_roundtrip_multiline():
    text = "\n".join([
        format_console_line(1700000000.5, "INFO", "başladı"),
        format_console_line(1700000001.0, "ERROR", "Traceback\n  File x\nValueError"),
        format_console_line(None, "STDERR", "uyarı"),
        "düz satır",
    ])
    run = parse_console_log(text)
    assert [(l[1], l[2]) for l in run.logs] == [
        ("INFO", "başladı"), ("ERROR", "Traceback\n  File x\nValueError"), ("STDERR", "uyarı"), ("INFO", "düz satır")]
    assert run.logs[0][0] == pytest.approx(1700000000.5)
    assert run.logs[2][0] is None


def _zip(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


def test_zip_merges_known_files_and_skips_others():
    data = _zip({
        "exp/seed_0/progress.csv": SB3_CSV,
        "exp/results.json": '{"score": 2}',
        "exp/config.json": '{"lr": 0.1}',
        "exp/run.log": format_console_line(1.0, "INFO", "merhaba"),
        "exp/seed_0/trace_eval.csv": "a,b\n1,2\n",
        "exp/run.json": '{"project": "x"}',
        "exp/grafikler/r.png": b"\x89PNG",
    })
    run = parse_zip(data)
    assert {m[0] for m in run.metrics} >= {"rollout/ep_rew_mean"}
    assert not any(m[0] in ("a", "b") for m in run.metrics)
    assert run.results == {"score": 2}
    assert run.config == {"lr": 0.1}
    assert [l[2] for l in run.logs] == ["merhaba"]


def test_zip_with_two_progress_files_imports_first_and_warns():
    data = _zip({"a/progress.csv": "step,x\n1,1\n", "b/progress.csv": "step,x\n1,2\n"})
    run = parse_zip(data)
    assert [m[2] for m in run.metrics] == [1.0]
    assert any("birden çok" in e for e in run.errors)


def test_bad_zip():
    assert parse_zip(b"not a zip").errors == ["zip dosyası bozuk"]


def test_parse_file_dispatch_and_unsupported():
    assert parse_file("progress.csv", SB3_CSV.encode()).total_steps == 128
    assert parse_file("C:\\x\\results.json", b'{"a": 1}').results == {"a": 1}
    assert parse_file(".rlpanel_buffer.jsonl", b"").metrics == []
    assert parse_file("console.log", b"hello").logs[0][2] == "hello"
    with pytest.raises(UnsupportedFile):
        parse_file("model.pt", b"\x00")


def test_merge_and_empty():
    a = ImportedRun(metrics=[["x", 1, 1.0, None]], total_steps=1)
    b = ImportedRun(results={"r": 1}, total_steps=5, status="crashed", errors=["e"])
    merged = a.merge(b)
    assert merged.total_steps == 5 and merged.results == {"r": 1} and merged.status == "crashed"
    assert merged.errors == ["e"]
    assert ImportedRun().empty and not merged.empty


def test_tfevents(tmp_path):
    pytest.importorskip("tensorboard")
    from tensorboard.compat.proto.event_pb2 import Event
    from tensorboard.compat.proto.summary_pb2 import Summary
    from tensorboard.summary.writer.event_file_writer import EventFileWriter

    writer = EventFileWriter(str(tmp_path))
    for step in range(3):
        value = Summary.Value(tag="rollout/ep_rew_mean", simple_value=float(step * 10))
        writer.add_event(Event(wall_time=1000.0 + step, step=step, summary=Summary(value=[value])))
    writer.close()
    path = next(tmp_path.glob("events.out.tfevents*"))
    run = parse_tfevents(path)
    assert [m[:3] for m in run.metrics] == [["rollout/ep_rew_mean", s, s * 10.0] for s in range(3)]
    assert run.total_steps == 2
    assert parse_file(path.name, path.read_bytes()).total_steps == 2


def test_ingest_creates_finished_run(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    imported = parse_progress_csv(SB3_CSV).merge(parse_json('{"score": 3}'))
    imported.logs.append([1.0, "INFO", "x"])
    run_id = ingest(store, "P", "r", imported, source="upload", content_hash="h")
    run = store.get_run(run_id)
    assert (run["status"], run["source"], run["results"], run["current_step"], run["total_steps"]) == (
        "finished", "upload", {"score": 3}, 128, 128)
    assert run["ended_at"] is not None
    assert len(store.get_metrics(run_id)["rollout/ep_rew_mean"]) == 2
    assert store.get_logs(run_id)[0]["line"] == "x"
    store.close()
