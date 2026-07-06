"""mitmproxy addon: capture Rain Bird 2.0 app traffic and extract the OAuth keys.

Point the Rain Bird 2.0 app's device at this proxy, sign in once, and this
addon writes every Rain Bird flow to a JSONL file AND live-extracts the values
you need for the Home Assistant integration:

  * client_id / client_secret  — decoded from the `Authorization: Basic` header
                                  on the `connect/token` request.
  * refresh_token              — from the token request/response.
  * endpoints                  — the hosts/paths the app talks to.

Run it with the launcher (tools/run_proxy.sh) or directly:

    mitmdump -s tools/rainbird_mitm.py --listen-port 8080

Only mitmproxy + the standard library are required (the IQ4 traffic is plain
JSON over TLS; nothing to decrypt). Decode errors never crash the proxy.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from mitmproxy import http

_LOG = logging.getLogger("rainbird-mitm")

CAPTURE_FILE = os.environ.get("RAINBIRD_CAPTURE_FILE", "captures/rainbird-iq4.jsonl")
KEYS_FILE = os.environ.get("RAINBIRD_KEYS_FILE", "captures/rainbird-keys.json")

_RAINBIRD_HOSTS = ("rainbird.com", "appsync-api", "appsync-realtime-api")
_found: dict[str, Any] = {"client_id": None, "client_secret": None,
                          "refresh_token": None, "endpoints": set()}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_rainbird(flow: http.HTTPFlow) -> bool:
    host = (flow.request.pretty_host or "").lower()
    return any(h in host for h in _RAINBIRD_HOSTS)


def _write_jsonl(rec: dict[str, Any]) -> None:
    try:
        with open(CAPTURE_FILE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
    except OSError as err:
        _LOG.error("capture write failed: %s", err)


def _save_keys() -> None:
    try:
        out = {**_found, "endpoints": sorted(_found["endpoints"])}
        with open(KEYS_FILE, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=2)
    except OSError as err:
        _LOG.error("keys write failed: %s", err)


def _extract_basic(auth_header: str) -> tuple[str, str] | None:
    """Decode 'Basic base64(client_id:client_secret)'."""
    if not auth_header or not auth_header.lower().startswith("basic "):
        return None
    try:
        raw = base64.b64decode(auth_header.split(None, 1)[1]).decode("utf-8", "replace")
        cid, _, secret = raw.partition(":")
        return (cid, secret) if cid and secret else None
    except Exception:  # noqa: BLE001
        return None


def _record(flow: http.HTTPFlow, kind: str) -> dict[str, Any]:
    msg = flow.request if kind == "request" else flow.response
    rec: dict[str, Any] = {
        "ts": _now(), "kind": kind, "method": flow.request.method,
        "host": flow.request.pretty_host, "path": flow.request.path,
    }
    if kind == "response" and flow.response is not None:
        rec["status"] = flow.response.status_code
    if msg is not None:
        rec["headers"] = dict(msg.headers)
        body = msg.raw_content or b""
        rec["body_b64"] = base64.b64encode(body).decode("ascii")
        rec["body_len"] = len(body)
    return rec


def request(flow: http.HTTPFlow) -> None:
    if not _is_rainbird(flow):
        return
    _found["endpoints"].add(f"{flow.request.pretty_host}{flow.request.path.split('?')[0]}")
    _write_jsonl(_record(flow, "request"))

    if "connect/token" in flow.request.path:
        creds = _extract_basic(flow.request.headers.get("Authorization", ""))
        if creds and not _found["client_id"]:
            _found["client_id"], _found["client_secret"] = creds
            _LOG.warning("★ EXTRACTED OAuth client — client_id=%s client_secret=%s",
                         creds[0], creds[1])
            _save_keys()
        # Refresh token often rides in the form body.
        text = (flow.request.get_text(strict=False) or "")
        for part in text.split("&"):
            if part.startswith("refresh_token="):
                _found["refresh_token"] = part.split("=", 1)[1]
                _save_keys()


def response(flow: http.HTTPFlow) -> None:
    if not _is_rainbird(flow):
        return
    _write_jsonl(_record(flow, "response"))
    if "connect/token" in flow.request.path and flow.response is not None:
        try:
            tok = json.loads(flow.response.get_text(strict=False) or "{}")
            if tok.get("refresh_token"):
                _found["refresh_token"] = tok["refresh_token"]
                _save_keys()
        except (ValueError, TypeError):
            pass


def done() -> None:
    if _found["client_id"]:
        _LOG.warning("Keys written to %s", KEYS_FILE)
    else:
        _LOG.warning("No client_id captured — did you sign in / did the app hit "
                     "connect/token through the proxy?")
