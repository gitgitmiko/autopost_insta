"""CLI media sosial (posting dijalankan oleh workflow n8n).

  python -m scraper.social api                                # server API untuk n8n (dijalankan systemd)
  python -m scraper.social n8n-sync [--account game]          # pasang/perbarui workflow & credential di n8n
  python -m scraper.social setup-token --account politik crypto saham --app-id ID --app-secret SECRET --user-token TOKEN
  python -m scraper.social preview --account game [--kind news] [--count 3]
  python -m scraper.social status --account game
"""
import argparse
import logging
import os
import secrets
import subprocess
from datetime import datetime

from ..db import Session, init_db
from . import service, settings


def write_env(values):
    path = os.path.join(settings.ROOT, ".env")
    lines = open(path).read().splitlines() if os.path.exists(path) else []
    for key, val in values.items():
        idx = next((i for i, ln in enumerate(lines) if ln.startswith(f"{key}=")), None)
        if idx is None:
            lines.append(f"{key}={val}")
        else:
            lines[idx] = f"{key}={val}"
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(path, 0o600)


def cmd_sync(args):
    from . import n8n
    if not settings.API_KEY:
        settings.API_KEY = secrets.token_urlsafe(32)
        write_env({"SOCIAL_API_KEY": settings.API_KEY})
        print("✓ SOCIAL_API_KEY baru dibuat di .env — restart API: sudo systemctl restart scraper-social-api")
    accounts = settings.load_accounts()
    keys = [args.account] if args.account else list(accounts)
    for key in keys:
        print(f"[{key}]")
        for m in n8n.sync_account(accounts[key]):
            print("  -", m)
    if not args.no_restart:
        n8n.restart_n8n()
        print("✓ n8n di-restart agar jadwal workflow dimuat ulang")
    # API tidak memuat ulang kode sendiri; restart agar perubahan kode/tampilan langsung dipakai
    sudo = [c for c in settings.DOCKER_CMD[:-1]] if settings.DOCKER_CMD[-1] == "docker" else ["sudo"]
    r = subprocess.run(sudo + ["systemctl", "restart", "scraper-social-api"], capture_output=True, text=True)
    print("✓ service scraper-social-api di-restart" if r.returncode == 0 else
          f"! restart scraper-social-api gagal, jalankan manual: sudo systemctl restart scraper-social-api")


def cmd_setup_token(args):
    """Satu token pengguna bisa menghubungkan beberapa akun sekaligus. Page tiap akun dicari otomatis dari
    username Instagram yang terhubung (= brand_handle akun), atau dipaksa dengan --page-id (satu akun)."""
    from . import n8n
    from .meta import exchange_tokens
    accts = [settings.get_account(k) for k in args.account]
    if args.page_id and len(accts) != 1:
        raise SystemExit("--page-id hanya bisa dipakai untuk satu akun")
    pages = exchange_tokens(args.app_id, args.app_secret, args.user_token,
                            page_ids=[args.page_id] if args.page_id else ())
    for p in pages:
        if "error" in p or not p.get("access_token"):
            print(f"✗ Page '{p.get('name')}' ({p['id']}) ditemukan tapi token Page tidak bisa diambil: "
                  f"{p.get('error', 'tanpa access_token')}")
    pages = [p for p in pages if p.get("access_token")]
    by_ig = {(p.get("instagram_business_account") or {}).get("username", "").lower(): p for p in pages}

    done = []
    for acct in accts:
        if args.page_id:
            page = next((p for p in pages if p["id"] == args.page_id), None)
        else:
            page = by_ig.get(acct.brand_handle.lstrip("@").lower())
        ig = (page or {}).get("instagram_business_account") or {}
        if not page or not ig:
            print(f"✗ Akun '{acct.key}' ({acct.brand_handle}): Page yang terhubung ke Instagram ini tidak ada di token.")
            continue
        settings.update_account(acct.key, page_id=page["id"], ig_user_id=ig["id"])
        n8n.put_credential(n8n.meta_cred(acct.key), "httpQueryAuth", "access_token", page["access_token"])
        print(f"✓ Akun '{acct.key}': Page '{page['name']}' ({page['id']}) → Instagram @{ig.get('username')} ({ig['id']})")
        done.append(acct.key)
    if not done:
        print("Page yang bisa dikelola token ini:")
        for p in pages:
            print(f"  - {p['id']}  {p['name']}  IG: @{(p.get('instagram_business_account') or {}).get('username', '-')}")
        raise SystemExit("Tidak ada akun yang terhubung")
    print("✓ Token Page (tidak kedaluwarsa) disimpan sebagai credential n8n")
    accounts = settings.load_accounts()
    for key in done:
        print(f"[{key}]")
        for m in n8n.sync_account(accounts[key]):
            print("  -", m)
    n8n.restart_n8n()
    print("✓ n8n di-restart agar jadwal workflow dimuat ulang")
    _restart_api()


def _restart_api():
    sudo = settings.DOCKER_CMD[:-1] if settings.DOCKER_CMD[-1] == "docker" else ["sudo"]
    r = subprocess.run(sudo + ["systemctl", "restart", "scraper-social-api"], capture_output=True, text=True)
    print("✓ service scraper-social-api di-restart" if r.returncode == 0 else
          "! restart scraper-social-api gagal, jalankan manual: sudo systemctl restart scraper-social-api")


def cmd_preview(args):
    acct = settings.get_account(args.account)
    if args.kind or args.topic:
        entries = [{"kind": args.kind or "news", "topic": args.topic}]
    else:  # satu contoh per kombinasi jenis+topik di jadwal
        entries = list({(s["kind"], s.get("topic")): s for s in acct.schedule}.values())
    stamp = datetime.now(settings.TZ).strftime("%Y%m%d-%H%M%S")
    used = []
    with Session() as db:
        for e in entries:
            kind, topic = e["kind"], e.get("topic")
            name = kind + (f"-{topic}" if topic else "")
            for i in range(args.count if kind == "news" else 1):
                path = os.path.join(settings.OUTBOX_DIR, "preview", f"{acct.key}-{stamp}", f"{name}-{i + 1}.jpg")
                built, reason = service.build(db, acct, kind, path, exclude_ids=used, refresh=not args.no_refresh,
                                              topic=topic, max_age_hours=e.get("max_age_hours"))
                if not built:
                    print(f"== {name}: DILEWATI — {reason}")
                    break
                used.append(built["article_id"])
                with open(path[:-4] + ".instagram.txt", "w") as f:
                    f.write(built["captions"]["instagram"])
                print(f"== {name} #{i + 1} → {path}\n{built['captions']['instagram']}\n")


def main():
    p = argparse.ArgumentParser(prog="python -m scraper.social")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("api")
    s = sub.add_parser("n8n-sync")
    s.add_argument("--account")
    s.add_argument("--no-restart", action="store_true")
    s = sub.add_parser("setup-token")
    s.add_argument("--account", required=True, nargs="+", help="satu atau beberapa akun, mis. politik crypto saham")
    s.add_argument("--app-id", required=True)
    s.add_argument("--app-secret", required=True)
    s.add_argument("--user-token", required=True)
    s.add_argument("--page-id")
    s = sub.add_parser("preview")
    s.add_argument("--account", required=True)
    s.add_argument("--kind")
    s.add_argument("--topic", help="topik game khusus, mis. valorant / dota2")
    s.add_argument("--count", type=int, default=3, help="jumlah contoh berita")
    s.add_argument("--no-refresh", action="store_true")
    s = sub.add_parser("status")
    s.add_argument("--account", required=True)
    s = sub.add_parser("bio", help="buat ulang halaman link di bio")
    s.add_argument("--account", required=True)
    args = p.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.cmd == "api":
        from .api import serve
        serve()
    elif args.cmd == "n8n-sync":
        cmd_sync(args)
    elif args.cmd == "setup-token":
        cmd_setup_token(args)
    elif args.cmd == "preview":
        init_db()
        cmd_preview(args)
    elif args.cmd == "bio":
        from . import bio
        with Session() as db:
            print(bio.render(db, settings.get_account(args.account)) or "bio_slug belum diisi untuk akun ini")
    elif args.cmd == "status":
        with Session() as db:
            for slot, platform, st, info in service.status(db, args.account):
                print(f"{slot:28} {platform:10} {st:9} {info[:100]}")


if __name__ == "__main__":
    main()
