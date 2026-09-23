"""Log yükleme ve run dışa aktarma uçları."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile

from rlpanel.server.export import build_export_zip
from rlpanel.server.hub import Hub
from rlpanel.server.importers import UnsupportedFile, ingest, parse_file
from rlpanel.server.store import Store


def safe_filename(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_") or "run"


def files_router(store: Store, hub: Hub) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.post("/upload", status_code=201)
    def upload(file: UploadFile = File(...), project: str = Form(""), run: str = Form("")) -> dict:
        data = file.file.read()
        filename = file.filename or "yukleme"
        if not data:
            raise HTTPException(400, detail={"message": "dosya boş"})
        digest = hashlib.sha256(data).hexdigest()
        existing = store.find_run_by_hash(digest)
        if existing is not None:
            raise HTTPException(409, detail={"message": "bu dosya zaten yüklenmiş", "run_id": existing})
        try:
            imported = parse_file(filename, data)
        except UnsupportedFile as exc:
            raise HTTPException(400, detail={"message": str(exc)}) from exc
        if imported.empty:
            raise HTTPException(422, detail={"message": "dosyada okunabilir veri bulunamadı",
                                             "errors": imported.errors[:50]})
        run_id = ingest(store, project.strip() or "Yüklenenler", run.strip() or Path(filename).stem,
                        imported, source="upload", content_hash=digest)
        created = store.get_run(run_id)
        created.update(store.reward_summary(run_id))
        hub.publish({"type": "run", "run": created})
        return {"id": run_id, "metrics": len(imported.metrics), "errors": imported.errors[:50]}

    @router.get("/runs/{run_id}/export.zip")
    def export(run_id: int) -> Response:
        data = build_export_zip(store, run_id)
        if data is None:
            raise HTTPException(404, detail="run bulunamadı")
        run = store.get_run(run_id)
        filename = safe_filename(f"{run['project']}_{run['name']}") + ".zip"
        return Response(data, media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    return router
