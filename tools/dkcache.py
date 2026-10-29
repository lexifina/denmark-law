"""The retrieved Retsinformation answers the build reads (Civilstyrelsen open data; terms:
https://www.retsinformation.dk/static/api.html).

Each answer is one file named by the first 32 hex digits of the sha256 of the request (the URL, then the JSON body of a
POST, if any). An answer the site gave as "not found" (404) is an empty `<key>.404`, one it could not serve (HTTP 500 on
every try) an empty `<key>.500`. The folder is `DK_SOURCES` (by default a folder next to this file). How the answers were
retrieved is not part of the published record.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = Path(os.environ.get('DK_SOURCES') or HERE / '.cache')
BASE = 'https://www.retsinformation.dk'


class Missing(Exception):
    """Retsinformation answered 404 for this request, or could not serve it (HTTP 500 on every try)."""


REQUESTS: list[dict] = []
_lock = threading.Lock()


def key_of(url: str, body: bytes | None) -> str:
    return hashlib.sha256((url + (body or b'').decode()).encode()).hexdigest()[:32]


def fetch(path: str, post: dict | None = None, offline: bool = False, kind: str = 'xml') -> bytes:
    """The retrieved answer to GET (or POST a JSON body to) BASE+path. Without --offline, an answer not yet retrieved is
    asked for by the private retrieval module, when it is present."""
    url = BASE + path
    body = json.dumps(post).encode() if post is not None else None
    key = key_of(url, body)
    p = CACHE / key
    with _lock:
        REQUESTS.append({'url': url, 'post': post, 'file': p})
    if p.exists():
        return p.read_bytes()
    if (CACHE / (key + '.404')).exists() or (CACHE / (key + '.500')).exists():
        raise Missing(url)
    if not offline:
        try:
            import dkfetch
        except ImportError:
            dkfetch = None
        if dkfetch is not None:
            return dkfetch.retrieve(url, body, key, kind)
    raise SystemExit(f'not retrieved: {url}')
