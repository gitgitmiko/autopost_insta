import socket

import requests
import urllib3.util.connection
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0 Safari/537.36"
)
TIMEOUT = 20

# IPv6 di server ini tidak tersambung ke internet: tanpa ini setiap host ber-IPv6 menggantung sampai
# timeout sebelum mencoba IPv4.
urllib3.util.connection.allowed_gai_family = lambda: socket.AF_INET


def make_session():
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "id-ID,id;q=0.9,en;q=0.8"})
    retry = Retry(total=3, backoff_factor=1.5, status_forcelist=(429, 500, 502, 503, 504))
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))
    return s


session = make_session()


def get(url, **kw):
    kw.setdefault("timeout", TIMEOUT)
    r = session.get(url, **kw)
    r.raise_for_status()
    return r
