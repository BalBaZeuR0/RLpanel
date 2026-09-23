"""Komut satırı: `rlpanel serve | watch | import`."""
from __future__ import annotations

import argparse
import sys
import threading
import urllib.error
from pathlib import Path

from rlpanel import http, launcher


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rlpanel", description="Yerel RL eğitim paneli")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="Paneli başlat")
    serve.add_argument("--port", type=int, default=launcher.DEFAULT_PORT)
    serve.add_argument("--host", default="127.0.0.1", help="Uzak makinelerden erişim için 0.0.0.0")
    serve.add_argument("--db", default=None, help="SQLite dosyası (varsayılan ~/.rlpanel/panel.db)")
    serve.add_argument("--watch", action="append", default=[], help="Açılışta izlenecek klasör (tekrarlanabilir)")
    serve.add_argument("--no-browser", action="store_true")

    watch = sub.add_parser("watch", help="Bir klasörü izlemeye ekle")
    watch.add_argument("path")
    watch.add_argument("--server", default=None)

    imp = sub.add_parser("import", help="Bitmiş bir eğitimin log dosyasını yükle")
    imp.add_argument("file")
    imp.add_argument("--project", default="")
    imp.add_argument("--run", default="")
    imp.add_argument("--server", default=None)

    args = parser.parse_args(argv)
    if args.command == "serve":
        return _serve(args)
    if args.command == "watch":
        return _watch(args)
    return _import(args)


def _serve(args) -> int:
    local_url = f"http://127.0.0.1:{args.port}"
    probe_host = "0.0.0.0" if args.host == "0.0.0.0" else "127.0.0.1"
    if not launcher.port_free(args.port, probe_host):
        if launcher.health(local_url):
            print(f"rlpanel zaten çalışıyor: {local_url}")
            if not args.no_browser:
                launcher.open_browser(local_url)
            return 0
        print(f"port {args.port} başka bir program tarafından kullanılıyor", file=sys.stderr)
        return 1
    import uvicorn

    from rlpanel.server.app import create_app

    app = create_app(args.db, watch_dirs=args.watch)
    print(f"rlpanel: {local_url}")
    if args.host == "0.0.0.0":
        print("Uzak makineler için: RLPANEL_SERVER=http://<bu-bilgisayarın-ip'si>:%d" % args.port)
    if not args.no_browser:
        threading.Timer(1.0, launcher.open_browser, [local_url]).start()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def _server_or_fail(explicit: str | None) -> str | None:
    url, _ = launcher.ensure_server(explicit)
    if url is None:
        print("panel sunucusuna ulaşılamadı", file=sys.stderr)
    return url


def _error_message(exc: urllib.error.HTTPError) -> str:
    try:
        import json

        detail = json.loads(exc.read() or b"{}").get("detail")
    except Exception:
        detail = None
    if isinstance(detail, dict):
        return detail.get("message", str(exc))
    return str(detail or exc)


def _watch(args) -> int:
    url = _server_or_fail(args.server)
    if url is None:
        return 1
    try:
        result = http.post_json(f"{url}/api/watch", {"path": str(Path(args.path).resolve())})
    except urllib.error.HTTPError as exc:
        print(_error_message(exc), file=sys.stderr)
        return 1
    print(f"izleniyor: {result['added']}")
    return 0


def _import(args) -> int:
    path = Path(args.file)
    if not path.is_file():
        print(f"dosya bulunamadı: {path}", file=sys.stderr)
        return 1
    url = _server_or_fail(args.server)
    if url is None:
        return 1
    try:
        result = http.post_file(f"{url}/api/upload", path, {"project": args.project, "run": args.run})
    except urllib.error.HTTPError as exc:
        print(_error_message(exc), file=sys.stderr)
        return 1
    print(f"yüklendi: {url}/#/run/{result['id']} ({result['metrics']} metrik satırı)")
    for warning in result.get("errors", []):
        print(f"  uyarı: {warning}")
    return 0
