"""Membuat & memasang workflow n8n (satu workflow per akun) dan credential-nya lewat CLI n8n di container."""
import json
import logging
import os
import subprocess
import uuid

from . import settings

log = logging.getLogger(__name__)
IMPORT_DIR_HOST = os.path.join(settings.N8N_DIR, "content", ".import")
IMPORT_DIR_CONTAINER = "/files/content/.import"
API_CRED = {"id": "sdg-api", "name": "Scraper API (X-API-Key)"}
TOKEN_PLACEHOLDER = "BELUM_DIISI"


def meta_cred(key):
    return {"id": f"sdg-meta-{key}", "name": f"Meta Page Token - {key}"}


def workflow_id(key):
    return f"sdg-social-{key}"


# ---------------------------------------------------------------- workflow builder
def _node(name, type_, version, pos, params, **extra):
    return {"id": str(uuid.uuid5(uuid.NAMESPACE_DNS, name + type_)), "name": name, "type": f"n8n-nodes-base.{type_}",
            "typeVersion": version, "position": pos, "parameters": params, **extra}


def _if(name, pos, left, op_type, operation, right=None):
    cond = {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, name)), "leftValue": left,
            "operator": {"type": op_type, "operation": operation}}
    if right is not None:
        cond["rightValue"] = right
    if operation in ("true", "false"):
        cond["operator"]["singleValue"] = True
    return _node(name, "if", 2.2, pos, {
        "conditions": {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
                       "conditions": [cond], "combinator": "and"},
        "options": {}})


def _http(name, pos, method, url, cred_type, cred, body=None, form=None, query=None, one_by_one=0, **extra):
    p = {"method": method, "url": url, "authentication": "genericCredentialType", "genericAuthType": cred_type,
         "options": {"timeout": 120000}}
    if one_by_one:  # satu item per request dengan jeda (ms) — urutan komentar/slide dikirim berurutan
        p["options"]["batching"] = {"batch": {"batchSize": 1, "batchInterval": int(one_by_one)}}
    if body is not None:
        p.update(sendBody=True, specifyBody="json", jsonBody=body)
    if form is not None:
        p.update(sendBody=True, contentType="form-urlencoded",
                 bodyParameters={"parameters": [{"name": k, "value": v} for k, v in form.items()]})
    if query is not None:
        p.update(sendQuery=True, queryParameters={"parameters": [{"name": k, "value": v} for k, v in query.items()]})
    return _node(name, "httpRequest", 4.2, pos, p, credentials={cred_type: cred}, **extra)


def _split(name, pos, field):
    return _node(name, "splitOut", 1, pos, {"fieldToSplitOut": field, "include": "noOtherFields", "options": {}})


def _aggregate(name, pos, field, out):
    return _node(name, "aggregate", 1, pos, {
        "aggregate": "aggregateIndividualFields",
        "fieldsToAggregate": {"fieldToAggregate": [{"fieldToAggregate": field, "renameField": True,
                                                    "outputFieldName": out}]},
        "options": {}})


def _set(name, pos, values):
    """values: {nama: (tipe, ekspresi)}"""
    return _node(name, "set", 3.4, pos, {
        "mode": "manual", "includeOtherFields": False, "options": {},
        "assignments": {"assignments": [
            {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, name + k)), "name": k, "type": t, "value": v}
            for k, (t, v) in values.items()]}})


def _report_body(post_expr, status, pid_expr="null", link_expr="null", err_expr="null"):
    return ("={{ JSON.stringify({ post_id: " + post_expr + ", status: '" + status + "', platform_post_id: "
            + pid_expr + ", permalink: " + link_expr + ", error: " + err_expr + " }) }}")


def build_workflow(acct):
    api, mc = settings.API_URL, meta_cred(acct.key)
    prep = "$('Siapkan konten').first().json"
    graph = "={{ " + prep + ".graph_base }}"
    cid = "$('IG: simpan container').first().json.container_id"
    # hanya pesan error (objek error n8n juga memuat isi request & stack trace)
    err = "String($json.error?.message ?? $json.error?.description ?? JSON.stringify($json).slice(0, 500)).slice(0, 2000)"
    retry = {"retryOnFail": True, "maxTries": 3, "waitBetweenTries": 5000}
    crons = [{"field": "cronExpression", "expression": f"{int(s['time'][3:5])} {int(s['time'][:2])} * * *"}
             for s in acct.schedule]
    nodes = [
        _node("Jadwal", "scheduleTrigger", 1.2, [0, 0], {"rule": {"interval": crons}}),
        _node("Tes manual", "manualTrigger", 1, [0, 200], {}),
        _http("Siapkan konten", [240, 100], "POST", f"{api}/prepare", "httpHeaderAuth", API_CRED,
              body="={{ JSON.stringify({ account: '" + acct.key + "', hour: $json.Hour ?? null, "
                   "minute: $json.Minute ?? null }) }}", **retry),
        _if("Konten siap?", [480, 100], "={{ $json.status }}", "string", "equals", "ready"),

        # ---------------- Instagram: satu gambar, Reel berlagu, atau carousel
        _if("Posting IG?", [720, -100], "={{ $json.instagram }}", "boolean", "true"),
        _if("IG: carousel?", [960, -100], "={{ $json.carousel }}", "boolean", "true"),
        _http("IG: buat container", [1200, 0], "POST", graph + "/{{ " + prep + ".ig_user_id }}/media",
              "httpQueryAuth", mc,
              # Reel: video berlagu (cover = kartu pertama) dan tetap tampil di grid feed.
              # Data dari "Siapkan konten" (bukan $json): node ini juga dipanggil ulang dari "Ulang Reel?"
              body="={{ (p => JSON.stringify(p.reel ? { media_type: 'REELS', video_url: p.reel_url, "
                   "cover_url: p.reel_cover_url ?? p.image_url, share_to_feed: true, caption: p.caption_instagram } "
                   ": { image_url: p.image_url, caption: p.caption_instagram }))(" + prep + ") }}",
              retryOnFail=True, maxTries=3, waitBetweenTries=20000, onError="continueErrorOutput"),
        _split("IG: pecah slide", [1200, -260], "slides"),
        _http("IG: buat item carousel", [1440, -260], "POST", graph + "/{{ " + prep + ".ig_user_id }}/media",
              "httpQueryAuth", mc,
              # Split Out atas array objek menghasilkan item {url, type}
              body="={{ JSON.stringify($json.type === 'video' ? { media_type: 'VIDEO', video_url: $json.url, "
                   "is_carousel_item: true } : { image_url: $json.url, is_carousel_item: true }) }}",
              one_by_one=1500, retryOnFail=True, maxTries=3, waitBetweenTries=20000, onError="continueErrorOutput"),
        _aggregate("IG: kumpulkan item", [1680, -260], "id", "ids"),
        # video perlu diproses Instagram dulu sebelum bisa dimasukkan ke carousel
        _if("Ada video?", [1920, -260], "={{ " + prep + ".has_video }}", "boolean", "true"),
        _node("Tunggu item IG", "wait", 1.1, [2160, -420], {"amount": 10, "unit": "seconds"}),
        # cek status tiap item satu per satu (parameter ?ids= sudah tidak didukung sejak Graph API v26.0)
        _set("IG: daftar item", [2400, -420],
             {"ids": ("array", "={{ $('IG: kumpulkan item').first().json.ids }}")}),
        _split("IG: pecah item", [2640, -420], "ids"),
        _http("IG: cek item", [2880, -420], "GET", graph + "/{{ $json.ids }}", "httpQueryAuth", mc,
              query={"fields": "status_code"}, **retry, onError="continueErrorOutput"),
        _aggregate("IG: kumpulkan status", [3120, -420], "status_code", "statuses"),
        _if("Semua item siap?", [3360, -420],
            "={{ $json.statuses.every(s => s === 'FINISHED') }}", "boolean", "true"),
        _if("Item masih diproses?", [3600, -340],
            "={{ !$json.statuses.some(s => ['ERROR', 'EXPIRED'].includes(s)) && $runIndex < 60 }}",
            "boolean", "true"),
        _http("IG: buat carousel", [3600, -560], "POST", graph + "/{{ " + prep + ".ig_user_id }}/media",
              "httpQueryAuth", mc,
              form={"media_type": "CAROUSEL",
                    "children": "={{ $('IG: kumpulkan item').first().json.ids.join(',') }}",
                    "caption": "={{ " + prep + ".caption_instagram }}"},
              retryOnFail=True, maxTries=3, waitBetweenTries=20000, onError="continueErrorOutput"),
        _set("IG: simpan container", [2160, -100], {"container_id": ("string", "={{ $json.id }}")}),
        _node("Tunggu proses IG", "wait", 1.1, [2400, -100], {"amount": 5, "unit": "seconds"}),
        _http("IG: cek status", [2640, -100], "GET", graph + "/{{ " + cid + " }}", "httpQueryAuth", mc,
              query={"fields": "status_code,status"}, **retry, onError="continueErrorOutput"),
        _if("Selesai diproses?", [2880, -100], "={{ $json.status_code }}", "string", "equals", "FINISHED"),
        # Reel bisa beberapa menit diproses Instagram: maks. 72 × 5 detik
        _if("Masih diproses?", [3120, 40], "={{ $json.status_code === 'IN_PROGRESS' && $runIndex < 72 }}",
            "boolean", "true"),
        _http("IG: publish", [3120, -220], "POST", graph + "/{{ " + prep + ".ig_user_id }}/media_publish",
              "httpQueryAuth", mc, form={"creation_id": "={{ " + cid + " }}"}, onError="continueErrorOutput"),
        _http("IG: ambil permalink", [3360, -300], "GET", graph + "/{{ $json.id }}", "httpQueryAuth", mc,
              query={"fields": "permalink"}, **retry, onError="continueRegularOutput"),
        _http("Lapor IG berhasil", [3600, -380], "POST", f"{api}/report", "httpHeaderAuth", API_CRED,
              body=_report_body(prep + ".post_id_instagram", "posted", "$('IG: publish').first().json.id",
                                "$json.permalink ?? null"), **retry),
        # Instagram kadang gagal memproses Reel yang sah (mis. kode 2207077): buat container baru sekali lagi
        _if("Ulang Reel?", [3360, 160],
            "={{ $json.status_code === 'ERROR' && " + prep + ".reel && $runIndex < 1 }}", "boolean", "true"),
        _node("Jeda sebelum ulang", "wait", 1.1, [3600, 260], {"amount": 30, "unit": "seconds"}),
        _http("Lapor IG gagal", [3600, 120], "POST", f"{api}/report", "httpHeaderAuth", API_CRED,
              body=_report_body(prep + ".post_id_instagram", "failed", err_expr=err), **retry),

        # ---------------- Instagram: lanjutan caption sebagai komentar
        _if("Ada komentar?", [3600, -220], "={{ (" + prep + ".comments_instagram || []).length > 0 }}",
            "boolean", "true"),
        _set("IG: siapkan komentar", [3840, -220],
             {"comments": ("array", "={{ " + prep + ".comments_instagram }}")}),
        _split("IG: pecah komentar", [4080, -220], "comments"),
        _http("IG: kirim komentar", [4320, -220], "POST",
              graph + "/{{ $('IG: publish').first().json.id }}/comments", "httpQueryAuth", mc,
              form={"message": "={{ $json.comments }}"}, one_by_one=5000, retryOnFail=True, maxTries=2,
              waitBetweenTries=5000, onError="continueErrorOutput"),
        _http("Catat komentar gagal", [4560, -120], "POST", f"{api}/report", "httpHeaderAuth", API_CRED,
              body="={{ JSON.stringify({ post_id: " + prep + ".post_id_instagram, note: 'Komentar lanjutan "
                   "gagal: ' + " + err + " }) }}", **retry),

        # ---------------- Facebook Page: satu foto atau album multi-foto
        _if("Posting FB?", [720, 400], "={{ $json.facebook }}", "boolean", "true"),
        _if("FB: carousel?", [960, 400], "={{ $json.fb_carousel }}", "boolean", "true"),
        _http("FB: posting foto", [1200, 500], "POST", graph + "/{{ " + prep + ".page_id }}/photos",
              "httpQueryAuth", mc, form={"url": "={{ $json.image_url }}", "message": "={{ $json.caption_facebook }}",
                                         "published": "true"}, onError="continueErrorOutput"),
        _split("FB: pecah slide", [1200, 320], "fb_slides"),
        _http("FB: unggah foto", [1440, 320], "POST", graph + "/{{ " + prep + ".page_id }}/photos",
              "httpQueryAuth", mc, form={"url": "={{ $json.fb_slides }}", "published": "false"},
              one_by_one=1500, retryOnFail=True, maxTries=3, waitBetweenTries=20000, onError="continueErrorOutput"),
        _aggregate("FB: kumpulkan foto", [1680, 320], "id", "ids"),
        _http("FB: posting album", [1920, 320], "POST", graph + "/{{ " + prep + ".page_id }}/feed",
              "httpQueryAuth", mc,
              form={"message": "={{ " + prep + ".caption_facebook }}",
                    "attached_media": "={{ JSON.stringify($json.ids.map(id => ({ media_fbid: id }))) }}"},
              onError="continueErrorOutput"),
        _http("Lapor FB berhasil", [2160, 420], "POST", f"{api}/report", "httpHeaderAuth", API_CRED,
              body=_report_body(prep + ".post_id_facebook", "posted", "$json.post_id ?? $json.id",
                                "'https://www.facebook.com/' + ($json.post_id ?? $json.id)"), **retry),
        _http("Lapor FB gagal", [2160, 600], "POST", f"{api}/report", "httpHeaderAuth", API_CRED,
              body=_report_body(prep + ".post_id_facebook", "failed", err_expr=err), **retry),
    ]

    def to(*names, out=0):
        return {"out": out, "to": names}

    edges = {
        "Jadwal": [to("Siapkan konten")],
        "Tes manual": [to("Siapkan konten")],
        "Siapkan konten": [to("Konten siap?")],
        "Konten siap?": [to("Posting IG?", "Posting FB?")],
        "Posting IG?": [to("IG: carousel?")],
        "IG: carousel?": [to("IG: pecah slide"), to("IG: buat container", out=1)],
        "IG: buat container": [to("IG: simpan container"), to("Lapor IG gagal", out=1)],
        "IG: pecah slide": [to("IG: buat item carousel")],
        "IG: buat item carousel": [to("IG: kumpulkan item"), to("Lapor IG gagal", out=1)],
        "IG: kumpulkan item": [to("Ada video?")],
        "Ada video?": [to("Tunggu item IG"), to("IG: buat carousel", out=1)],
        "Tunggu item IG": [to("IG: daftar item")],
        "IG: daftar item": [to("IG: pecah item")],
        "IG: pecah item": [to("IG: cek item")],
        "IG: cek item": [to("IG: kumpulkan status"), to("Lapor IG gagal", out=1)],
        "IG: kumpulkan status": [to("Semua item siap?")],
        "Semua item siap?": [to("IG: buat carousel"), to("Item masih diproses?", out=1)],
        "Item masih diproses?": [to("Tunggu item IG"), to("Lapor IG gagal", out=1)],
        "IG: buat carousel": [to("IG: simpan container"), to("Lapor IG gagal", out=1)],
        "IG: simpan container": [to("Tunggu proses IG")],
        "Tunggu proses IG": [to("IG: cek status")],
        "IG: cek status": [to("Selesai diproses?"), to("Lapor IG gagal", out=1)],
        "Selesai diproses?": [to("IG: publish"), to("Masih diproses?", out=1)],
        "Masih diproses?": [to("Tunggu proses IG"), to("Ulang Reel?", out=1)],
        "Ulang Reel?": [to("Jeda sebelum ulang"), to("Lapor IG gagal", out=1)],
        "Jeda sebelum ulang": [to("IG: buat container")],
        "IG: publish": [to("IG: ambil permalink"), to("Lapor IG gagal", out=1)],
        "IG: ambil permalink": [to("Lapor IG berhasil", "Ada komentar?")],
        "Ada komentar?": [to("IG: siapkan komentar")],
        "IG: siapkan komentar": [to("IG: pecah komentar")],
        "IG: pecah komentar": [to("IG: kirim komentar")],
        "IG: kirim komentar": [to(), to("Catat komentar gagal", out=1)],
        "Posting FB?": [to("FB: carousel?")],
        "FB: carousel?": [to("FB: pecah slide"), to("FB: posting foto", out=1)],
        "FB: posting foto": [to("Lapor FB berhasil"), to("Lapor FB gagal", out=1)],
        "FB: pecah slide": [to("FB: unggah foto")],
        "FB: unggah foto": [to("FB: kumpulkan foto"), to("Lapor FB gagal", out=1)],
        "FB: kumpulkan foto": [to("FB: posting album")],
        "FB: posting album": [to("Lapor FB berhasil"), to("Lapor FB gagal", out=1)],
    }
    connections = {}
    for src, outs in edges.items():
        n_out = max(o["out"] for o in outs) + 1
        main = [[] for _ in range(n_out)]
        for o in outs:
            main[o["out"]] += [{"node": t, "type": "main", "index": 0} for t in o["to"]]
        connections[src] = {"main": main}

    return {
        "id": workflow_id(acct.key),
        "name": f"Sosmed {acct.key} — {acct.brand_name} (otomatis dari scraper)",
        "nodes": nodes,
        "connections": connections,
        "settings": {"executionOrder": "v1", "timezone": "Asia/Jakarta", "saveManualExecutions": True,
                     "callerPolicy": "workflowsFromSameOwner"},
        "pinData": {},
        "active": False,
    }


# ---------------------------------------------------------------- docker / CLI
def docker(*args, input_text=None):
    cmd = settings.DOCKER_CMD + list(args)
    r = subprocess.run(cmd, capture_output=True, text=True, input=input_text)
    out = (r.stdout + r.stderr).strip()
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:4])}… gagal: {out[-500:]}")
    return out


def n8n_cli(*args):
    return docker("exec", settings.N8N_CONTAINER, "n8n", *args)


def _import(kind, obj, name):
    """Tulis JSON ke folder yang di-mount container, import, lalu hapus (bisa berisi rahasia)."""
    os.makedirs(IMPORT_DIR_HOST, exist_ok=True)
    path = os.path.join(IMPORT_DIR_HOST, f"{name}.json")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(obj, f, ensure_ascii=False)
    try:
        return n8n_cli(f"import:{kind}", f"--input={IMPORT_DIR_CONTAINER}/{name}.json")
    finally:
        os.remove(path)


def _sql(query):
    return docker("exec", settings.N8N_DB_CONTAINER, "psql", "-U", "n8n", "-d", "n8n", "-tAc", query)


def credential_value(cred_id):
    """Nilai credential saat ini (untuk cek apakah token sudah diisi). None bila belum ada."""
    if not _sql(f"select id from credentials_entity where id = '{cred_id}'"):
        return None
    out = n8n_cli("export:credentials", f"--id={cred_id}", "--decrypted",
                  f"--output={IMPORT_DIR_CONTAINER}/export-{cred_id}.json")
    path = os.path.join(IMPORT_DIR_HOST, f"export-{cred_id}.json")
    try:
        with open(path) as f:
            return json.load(f)[0]["data"].get("value")
    except (OSError, ValueError, IndexError, KeyError):
        log.debug("export credential gagal: %s", out)
        return None
    finally:
        if os.path.exists(path):
            os.remove(path)


def put_credential(cred, type_, header_or_param, value):
    _import("credentials", [{**cred, "type": type_, "data": {"name": header_or_param, "value": value}}],
            f"cred-{cred['id']}")


def sync_account(acct, publish=True):
    """Pasang credential + workflow untuk satu akun. Return list pesan status."""
    msgs = []
    put_credential(API_CRED, "httpHeaderAuth", "X-API-Key", settings.API_KEY)
    mc = meta_cred(acct.key)
    token = credential_value(mc["id"])
    if token is None:
        put_credential(mc, "httpQueryAuth", "access_token", TOKEN_PLACEHOLDER)
        token = TOKEN_PLACEHOLDER
        msgs.append(f"credential '{mc['name']}' dibuat (token belum diisi)")
    _import("workflow", build_workflow(acct), f"wf-{acct.key}")
    wid = workflow_id(acct.key)
    msgs.append(f"workflow '{wid}' terpasang ({len(acct.schedule)} jadwal)")

    ready = acct.enabled and acct.ig_user_id and token != TOKEN_PLACEHOLDER
    if publish and ready:
        n8n_cli("publish:workflow", f"--id={wid}")
        msgs.append("workflow AKTIF (published)")
    else:
        try:
            n8n_cli("unpublish:workflow", f"--id={wid}")
        except RuntimeError:
            pass
        why = ("akun dinonaktifkan" if not acct.enabled else "ig_user_id kosong" if not acct.ig_user_id
               else "token Meta belum diisi")
        msgs.append(f"workflow TIDAK aktif: {why} — jalankan setup-token --account {acct.key}")
    return msgs


def restart_n8n():
    """Workflow yang dipublish lewat CLI baru dijadwalkan setelah instance n8n dimuat ulang."""
    docker("restart", settings.N8N_CONTAINER)
