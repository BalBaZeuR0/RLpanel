"""FastAPI uygulaması: REST + WebSocket + statik arayüz."""
from __future__ import annotations

import asyncio
import mimetypes
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal, Sequence

from fastapi import APIRouter, FastAPI, HTTPException, Query, WebSocket
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import rlpanel
from rlpanel import paths
from rlpanel.server.files import files_router
from rlpanel.server.hub import Hub
from rlpanel.server.store import Store
from rlpanel.server.watcher import FolderWatcher, watch_router

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

# Windows kayıt defteri .js'i text/plain gösterebiliyor -> tarayıcı ES modüllerini yüklemez.
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")


class RunCreate(BaseModel):
    project: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=300)
    seed: int | None = None
    host: str | None = None
    config: dict | None = None
    total_steps: int | None = None


class Batch(BaseModel):
    metrics: list[tuple[str, int, float, float | None]] = []
    logs: list[tuple[float | None, str, str]] = []
    current_step: int | None = None
    total_steps: int | None = None
    config: dict | None = None
    results: dict | None = None
    status: Literal["running", "finished", "crashed", "stopped"] | None = None


def create_app(db_path: str | Path | None = None, *, heartbeat_timeout: float = 30.0,
               watch_dirs: Sequence[str] = (), watch_interval: float = 2.0) -> FastAPI:
    db_file = Path(db_path or paths.db_path())
    store = Store(db_file)
    hub = Hub()
    watcher = FolderWatcher(store, hub.publish, interval=watch_interval, state_file=db_file.parent / "watch.json")

    async def reaper() -> None:
        while True:
            await asyncio.sleep(max(0.05, min(5.0, heartbeat_timeout / 2)))
            for run_id in store.mark_unresponsive(heartbeat_timeout):
                hub.publish({"type": "run", "run": store.get_run(run_id)})

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        hub.loop = asyncio.get_running_loop()
        task = asyncio.create_task(reaper())
        for directory in watch_dirs:
            try:
                watcher.add(directory)
            except NotADirectoryError as exc:
                print(f"[rlpanel] izlenemedi: {exc}")
        watcher.start()
        try:
            yield
        finally:
            task.cancel()
            watcher.stop()
            store.close()

    app = FastAPI(title="rlpanel", lifespan=lifespan)
    app.state.store, app.state.hub, app.state.watcher = store, hub, watcher
    app.include_router(core_router(store, hub))
    app.include_router(files_router(store, hub))
    app.include_router(watch_router(watcher))

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await hub.serve(websocket)

    # Statik arayüz en sonda: "/" her yolu yakalar, API yönlendiricileri bundan önce eklenmeli.
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app


def core_router(store: Store, hub: Hub) -> APIRouter:
    router = APIRouter(prefix="/api")

    def run_or_404(run_id: int) -> dict:
        run = store.get_run(run_id)
        if run is None:
            raise HTTPException(404, detail="run bulunamadı")
        return run

    def with_summary(run: dict) -> dict:
        run.update(store.reward_summary(run["id"]))
        return run

    @router.get("/health")
    def health() -> dict:
        return {"app": "rlpanel", "version": rlpanel.__version__}

    @router.get("/runs")
    def list_runs(project: str | None = None) -> list[dict]:
        return store.list_runs(project)

    @router.post("/runs", status_code=201)
    def create_run(body: RunCreate) -> dict:
        run_id = store.create_run(body.project, body.name, seed=body.seed, host=body.host,
                                  config=body.config, total_steps=body.total_steps)
        hub.publish({"type": "run", "run": with_summary(store.get_run(run_id))})
        return {"id": run_id}

    @router.get("/runs/{run_id}")
    def get_run(run_id: int) -> dict:
        run = with_summary(run_or_404(run_id))
        run["metric_keys"] = store.metric_keys(run_id)
        return run

    @router.delete("/runs/{run_id}")
    def delete_run(run_id: int) -> dict:
        run_or_404(run_id)
        store.delete_run(run_id)
        hub.publish({"type": "deleted", "run_id": run_id})
        return {"ok": True}

    @router.get("/runs/{run_id}/metrics")
    def get_metrics(run_id: int, keys: str | None = None) -> dict:
        run_or_404(run_id)
        wanted = [k for k in (keys or "").split(",") if k] or None
        return store.get_metrics(run_id, wanted)

    @router.get("/runs/{run_id}/logs")
    def get_logs(run_id: int, after: int = 0, tail: int | None = Query(None, ge=1, le=100_000)) -> list[dict]:
        run_or_404(run_id)
        return store.get_logs(run_id, after_id=after, tail=tail)

    @router.post("/runs/{run_id}/batch")
    def post_batch(run_id: int, body: Batch) -> dict:
        run = run_or_404(run_id)
        kept = store.add_metrics(run_id, body.metrics)
        logs = store.add_logs(run_id, body.logs)
        now = time.time()
        fields: dict = {"last_heartbeat": now}
        for name in ("current_step", "total_steps", "config", "results"):
            value = getattr(body, name)
            if value is not None:
                fields[name] = value
        if body.status:
            fields["status"] = body.status
            if body.status != "running":
                fields["ended_at"] = now
        elif run["status"] == "unresponsive":
            fields["status"] = "running"
        store.update_run(run_id, **fields)
        if kept or logs or len(fields) > 1:
            hub.publish({"type": "batch", "run": store.get_run(run_id), "metrics": kept, "logs": logs, "reset": False})
        return {"ok": True, "metrics": len(kept), "logs": len(logs)}

    return router
