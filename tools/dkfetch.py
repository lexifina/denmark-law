"""Cached, polite fetching from Retsinformation (Civilstyrelsen open data; terms: https://www.retsinformation.dk/static/api.html)."""
from __future__ import annotations
import gzip
import hashlib
import json
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE / '.cache'
BASE = 'https://www.retsinformation.dk'
UA = 'lexifina-watch/1.0 (+https://lexifina.com/watch; corpus@lexifina.com)'
PAUSE = 0.5          # seconds between the starts of two requests (at most 2 a second; the terms forbid disproportionate load)


class Missing(Exception):
    """Retsinformation answered 404 for this request, or HTTP 500 on every one of four tries (some old documents' XML is
    broken on the site); cached as <key>.404 / <key>.500, so it is not asked again. Delete those files to ask again."""
REQUESTS: list[dict] = []
_lock = threading.Lock()
_last = [0.0]


def _http(url: str, post: bytes | None) -> bytes:
    with _lock:
        wait = _last[0] + PAUSE - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.monotonic()
    headers = {'User-Agent': UA, 'Accept': 'application/json, application/xml, */*', 'Accept-Encoding': 'gzip'}
    if post is not None:
        headers['Content-Type'] = 'application/json'
    try:
        req = urllib.request.Request(url, data=post, headers=headers)
        with urllib.request.urlopen(req, timeout=120) as r:
            body = r.read()
            if r.headers.get('Content-Encoding', '').lower() == 'gzip':
                body = gzip.decompress(body)
            return body
    except Exception as exc:
        if 'CERTIFICATE' not in str(exc).upper():
            raise
        cmd = ['curl', '-sS', '-f', '-L', '--compressed', '--max-redirs', '4', '-A', UA]
        if post is not None:
            cmd += ['-X', 'POST', '-H', 'Content-Type: application/json', '-d', post.decode()]
        out = subprocess.run(cmd + [url], capture_output=True)
        if out.returncode:
            raise RuntimeError(f'curl {url}: {out.stderr.decode(errors="replace")}')
        return out.stdout


def fetch(path: str, post: dict | None = None, offline: bool = False, kind: str = 'xml') -> bytes:
    """GET (or POST a JSON body) BASE+path with a file cache keyed by the request, negative answers included."""
    url = BASE + path
    body = json.dumps(post).encode() if post is not None else None
    key = hashlib.sha256((url + (body or b'').decode()).encode()).hexdigest()[:32]
    p = CACHE / key
    with _lock:
        REQUESTS.append({'url': url, 'post': post, 'file': p})
    if p.exists():
        return p.read_bytes()
    neg = CACHE / (key + '.404')
    broken = CACHE / (key + '.500')
    if neg.exists() or broken.exists():
        raise Missing(url)
    if offline:
        raise SystemExit(f'not cached: {url}')
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / '.gitignore').write_text('*\n')
    for attempt in range(4):
        try:
            data = _http(url, body)
            if kind == 'xml' and b'<Dokument' not in data[:2000]:
                raise RuntimeError(f'no document at {url}')
            if kind == 'json':
                json.loads(data.decode('utf-8'))
            p.write_bytes(data)
            return data
        except Exception as exc:
            if getattr(exc, 'code', None) == 404 or 'error: 404' in str(exc) or '(22) The requested URL returned error: 404' in str(exc):
                neg.write_bytes(b'')
                raise Missing(url) from None
            if attempt == 3:
                if getattr(exc, 'code', None) == 500:
                    broken.write_bytes(b'')
                    raise Missing(url) from None
                raise
            time.sleep(10 * (attempt + 1))
    raise AssertionError
