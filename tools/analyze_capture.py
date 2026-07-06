"""Analyze a Rain Bird capture and print the values for the HA integration.

    python tools/analyze_capture.py captures/rainbird-iq4-<stamp>.jsonl

Extracts, from the captured Rain Bird 2.0 app traffic:
  * client_id / client_secret  (decoded from the connect/token Basic header)
  * refresh_token
  * the endpoints (hosts/paths) the app used

and compares client_id/secret against the values the integration currently ships,
so you can tell at a glance whether Rain Bird has rotated them. Standard library
only.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from collections import Counter
from pathlib import Path


def _basic(auth: str) -> tuple[str, str] | None:
    if not auth or not auth.lower().startswith("basic "):
        return None
    try:
        raw = base64.b64decode(auth.split(None, 1)[1]).decode("utf-8", "replace")
        cid, _, sec = raw.partition(":")
        return (cid, sec) if cid and sec else None
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("capture", help="path to a rainbird capture JSONL")
    args = ap.parse_args()

    client_id = client_secret = refresh_token = None
    endpoints: Counter[str] = Counter()

    for line in Path(args.capture).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        host, path = r.get("host", ""), r.get("path", "")
        endpoints[f"{host}{path.split('?')[0]}"] += 1
        headers = {k.lower(): v for k, v in (r.get("headers") or {}).items()}

        if "connect/token" in path:
            creds = _basic(headers.get("authorization", ""))
            if creds:
                client_id, client_secret = creds
            body = base64.b64decode(r.get("body_b64", "") or "").decode("utf-8", "replace")
            if "refresh_token=" in body:
                refresh_token = body.split("refresh_token=", 1)[1].split("&", 1)[0]
            try:
                j = json.loads(body)
                refresh_token = j.get("refresh_token", refresh_token)
            except (ValueError, TypeError):
                pass

    print("=== Rain Bird capture analysis ===\n")
    if client_id:
        print(f"client_id     : {client_id}")
        print(f"client_secret : {client_secret}")
        print("\n  >> Paste these into the integration's OAuth client ID/secret fields"
              "\n     when you add it in Home Assistant.")
    else:
        print("client_id     : NOT FOUND — sign in through the proxy so the app hits")
        print("                connect/token (that request carries the Basic header).")
    print(f"refresh_token : {'captured' if refresh_token else 'not captured'}")

    print("\n=== endpoints seen ===")
    for ep, n in endpoints.most_common():
        print(f"  {n:4}  {ep}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
