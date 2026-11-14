"""HTTP API untuk workflow n8n (stdlib, tanpa dependensi tambahan).

POST /prepare  {"account": "game", "hour": 8, "minute": 0}   → konten siap posting / skip / duplicate
POST /report   {"post_id": 1, "status": "posted", "platform_post_id": "...", "permalink": "...", "error": "..."}
GET  /overview?platform=             → ringkasan & jadwal hari ini semua akun (untuk dashboard)
GET  /posts?account=&platform=&status=&date=&page=&pageSize=  → riwayat posting
GET  /health
Semua request wajib header X-API-Key = SOCIAL_API_KEY.
"""
import hmac
import json
import logging
import threading
from datetime import date
from urllib.parse import parse_qs, urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ..db import Session, init_db
from . import service, settings

log = logging.getLogger(__name__)
_prepare_lock = threading.Lock()  # satu prepare dalam satu waktu: hindari dua slot memilih berita yang sama


class Handler(BaseHTTPRequestHandler):
    server_version = "scraper-social/1.0"

    def log_message(self, fmt, *args):
        log.debug("%s %s", self.address_string(), fmt % args)

    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self):
        key = self.headers.get("X-API-Key", "")
        return bool(settings.API_KEY) and hmac.compare_digest(key, settings.API_KEY)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/health":
            return self._send(200, {"ok": True})
        if not self._authorized():
            return self._send(401, {"error": "X-API-Key salah"})
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            with Session() as db:
                if url.path == "/overview":
                    return self._send(200, service.overview(db, platform=q.get("platform") or None))
                if url.path == "/posts":
                    day = date.fromisoformat(q["date"]) if q.get("date") else None
                    return self._send(200, service.list_posts(
                        db, q.get("account") or None, q.get("status") or None, day,
                        int(q.get("page") or 1), int(q.get("pageSize") or 10), q.get("platform") or None))
            self._send(404, {"error": "not found"})
        except ValueError as e:
            self._send(400, {"error": f"parameter tidak valid: {e}"})
        except Exception as e:
            log.exception("API error %s", self.path)
            self._send(500, {"error": str(e)[:500]})

    def do_POST(self):
        if not self._authorized():
            return self._send(401, {"error": "X-API-Key salah"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._send(400, {"error": "body harus JSON"})
        try:
            with Session() as db:
                if self.path == "/prepare":
                    with _prepare_lock:
                        out = service.prepare(db, data["account"], data.get("hour"), data.get("minute"),
                                              data.get("kind"), topic=data.get("topic"),
                                              article_id=data.get("article_id"))
                elif self.path == "/report":
                    out = service.report(db, data["post_id"], data.get("status"), data.get("platform_post_id"),
                                         data.get("permalink"), data.get("error"), data.get("note"))
                else:
                    return self._send(404, {"error": "not found"})
            self._send(200, out)
        except KeyError as e:
            self._send(400, {"error": f"field/akun tidak valid: {e}"})
        except Exception as e:
            log.exception("API error %s", self.path)
            self._send(500, {"status": "error", "error": str(e)[:500]})


def serve():
    if not settings.API_KEY:
        raise SystemExit("SOCIAL_API_KEY belum diisi di .env (jalankan: python -m scraper.social n8n-sync)")
    init_db()
    httpd = ThreadingHTTPServer((settings.API_HOST, settings.API_PORT), Handler)
    log.info("API sosial mendengarkan di http://%s:%d", settings.API_HOST, settings.API_PORT)
    httpd.serve_forever()
