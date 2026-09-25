"""Polite JSON/text fetching shared by every public-registry source."""
from __future__ import annotations

import json
import sys
import time
import urllib.request

UA = "bconz-DIA/1.0 (research data partnership discovery; contact: hello@bconz.com)"
TIMEOUT = 40


def get(url: str, as_json: bool = True, retries: int = 2, data: dict | None = None):
    """GET (or POST when `data` is given). Returns None after the last failure
    rather than raising: one flaky registry must not sink a whole run."""
    body = json.dumps(data).encode() if data is not None else None
    headers = {"User-Agent": UA}
    if body is not None:
        headers["Content-Type"] = "application/json"
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=body, headers=headers)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                raw = r.read().decode("utf-8", "replace")
                return json.loads(raw) if as_json else raw
        except Exception as exc:
            if attempt == retries:
                print(f"    ! {type(exc).__name__} {url[:70]}", file=sys.stderr)
                return None
            time.sleep(1.2 * (attempt + 1))
    return None
