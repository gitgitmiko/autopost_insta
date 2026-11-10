"""Pertukaran token Meta Graph API (posting sendiri dilakukan oleh workflow n8n)."""
import requests

from . import settings


class MetaError(Exception):
    pass


def _get(base, path, token, **params):
    r = requests.get(f"{base}/{path}", params={"access_token": token, **params}, timeout=30).json()
    if "error" in r:
        raise MetaError(r["error"].get("message"))
    return r


PAGE_FIELDS = "id,name,access_token,instagram_business_account{id,username}"


def exchange_tokens(app_id, app_secret, short_user_token, version=None, page_ids=()):
    """User token pendek -> user token jangka panjang -> daftar Page beserta token Page-nya
    (token Page dari user token jangka panjang tidak kedaluwarsa).

    Page yang dikelola lewat Business Portfolio (tidak muncul di /me/accounts) dicari lewat
    /me/businesses -> owned_pages/client_pages lalu token Page diminta langsung.
    Return list dict {id, name, access_token, instagram_business_account}."""
    base = f"https://graph.facebook.com/{version or settings.GRAPH_VERSION}"
    r = requests.get(f"{base}/oauth/access_token", params={
        "grant_type": "fb_exchange_token", "client_id": app_id, "client_secret": app_secret,
        "fb_exchange_token": short_user_token}, timeout=30).json()
    if "error" in r:
        raise MetaError(r["error"].get("message"))
    token = r["access_token"]

    pages = {p["id"]: p for p in _get(base, "me/accounts", token, fields=PAGE_FIELDS, limit=100).get("data", [])}
    if not pages:
        businesses = _get(base, "me/businesses", token, fields="id,name", limit=100).get("data", [])
        for b in businesses:
            for edge in ("owned_pages", "client_pages"):
                try:
                    for p in _get(base, f"{b['id']}/{edge}", token, fields="id,name", limit=100).get("data", []):
                        if p["id"] in pages:
                            continue
                        try:
                            pages[p["id"]] = _get(base, p["id"], token, fields=PAGE_FIELDS)
                        except MetaError as e:
                            pages[p["id"]] = {**p, "error": str(e)}
                except MetaError:
                    continue
    # Page yang diizinkan per-Page saat login (granular_scopes) atau diminta eksplisit (--page-id)
    candidates = set(page_ids)
    try:
        dbg = _get(base, "debug_token", f"{app_id}|{app_secret}", input_token=token).get("data", {})
        for g in dbg.get("granular_scopes", []):
            if g.get("scope") in ("pages_show_list", "pages_read_engagement"):
                candidates.update(g.get("target_ids", []))
    except MetaError:
        pass
    for pid in candidates - set(pages):
        try:
            pages[pid] = _get(base, pid, token, fields=PAGE_FIELDS)
        except MetaError as e:
            pages[pid] = {"id": pid, "error": str(e)}
    return list(pages.values())
