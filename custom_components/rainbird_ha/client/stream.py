"""AWS AppSync realtime stream for IQ4 controller state.

Ported and trimmed from pyrainbird.cloud.stream, adapted to IQ4Auth. Gives
push updates (active station, remaining seconds, rain delay) over a WebSocket
instead of polling -- this is what makes the integration feel instant and is a
big reliability win over the polling-only HACS integration.
"""

from __future__ import annotations

import asyncio
import base64
import datetime
import json
import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass

import aiohttp

from .iq4 import IQ4Auth

_LOGGER = logging.getLogger(__name__)

# AppSync realtime: connect to the *realtime* host with the base64 ?header=
# query param. The Authorization value MUST be "Bearer <token>" (the raw token
# alone yields "The request headers are invalid"), and the header's `host` field
# is the *api* host. Verified against the live service.
API_HOST = "m3iuhu3l3zbjpkctbnh2of4chm.appsync-api.us-west-2.amazonaws.com"
REALTIME_HOST = "m3iuhu3l3zbjpkctbnh2of4chm.appsync-realtime-api.us-west-2.amazonaws.com"
WS_ENDPOINT = f"wss://{REALTIME_HOST}/graphql"

_SUB_QUERY = (
    "subscription onUpdateDeviceStateTable($PK : String!) {\n"
    "  onUpdateDeviceStateTable(PK: $PK) {\n    PK\n    SK\n    Data\n    TimeStamp\n  }\n}"
)

INITIAL_BACKOFF = 2.0
MAX_BACKOFF = 60.0


_STATION_SK_RE = re.compile(r"Station(\d+)")


@dataclass
class StreamEvent:
    """A realtime device-state update.

    The event's SK identifies which station it concerns (``Station<terminal>``);
    ``running`` is True while that station waters, False when it stops. Non-station
    events (e.g. rain delay) have ``terminal`` None.
    """

    device_uuid: str
    sk: str
    terminal: int | None
    running: bool | None
    remain_seconds: int | None
    rain_delay: int | None
    updated_at: datetime.datetime


class IQ4Stream:
    """Manages a resilient AppSync subscription for one controller."""

    def __init__(self, auth: IQ4Auth, device_uuid: str) -> None:
        self._auth = auth
        self._device_uuid = device_uuid
        self._session = auth.session
        self._force_refresh = False

    def _connection_url(self, token: str) -> str:
        header = base64.urlsafe_b64encode(
            json.dumps({"host": API_HOST, "Authorization": f"Bearer {token}"}).encode()
        ).decode().rstrip("=")
        return f"{WS_ENDPOINT}?header={header}&payload=e30="

    def _parse(self, msg: dict) -> StreamEvent | None:
        ds = (msg.get("payload", {}).get("data", {}) or {}).get("onUpdateDeviceStateTable")
        if not ds:
            return None
        sk = ds.get("SK", "")
        ts = ds.get("TimeStamp")
        try:
            updated = (datetime.datetime.fromtimestamp(int(ts), datetime.timezone.utc)
                       if ts else datetime.datetime.now(datetime.timezone.utc))
        except (ValueError, TypeError):
            updated = datetime.datetime.now(datetime.timezone.utc)
        remain = rain = None
        state_val = None
        inner = ds.get("Data")
        if inner:
            try:
                d = json.loads(inner)
                if isinstance(d, dict):
                    state_val = d.get("state")
                    remain = d.get("remainSec")
                    rain = d.get("rainDelay")
            except json.JSONDecodeError:
                pass
        # SK is "Station<terminal>"; Data.state == 1 means running, -1 stopped.
        m = _STATION_SK_RE.fullmatch(sk)
        terminal = int(m.group(1)) if m else None
        running = None if state_val is None else (state_val == 1)
        return StreamEvent(ds.get("PK", ""), sk, terminal, running, remain, rain, updated)

    async def listen(self) -> AsyncIterator[StreamEvent]:
        """Yield events forever, reconnecting with backoff. Cancel to stop."""
        backoff = INITIAL_BACKOFF
        while True:
            try:
                token = await self._auth.async_access_token(force_refresh=self._force_refresh)
                self._force_refresh = False
                async with self._session.ws_connect(
                    self._connection_url(token), protocols=["graphql-ws"],
                ) as ws:
                    backoff = INITIAL_BACKOFF
                    await ws.send_json({"type": "connection_init"})
                    async for msg in ws:
                        if msg.type != aiohttp.WSMsgType.TEXT:
                            if msg.type in (aiohttp.WSMsgType.CLOSE,
                                            aiohttp.WSMsgType.CLOSING,
                                            aiohttp.WSMsgType.CLOSED):
                                break
                            continue
                        data = msg.json()
                        mtype = data.get("type")
                        if mtype == "connection_ack":
                            await ws.send_json({
                                "id": "sub_device_state", "type": "start",
                                "payload": {
                                    "data": json.dumps({
                                        "query": _SUB_QUERY,
                                        "variables": {"PK": self._device_uuid},
                                    }),
                                    "extensions": {"authorization": {
                                        "host": API_HOST,
                                        "Authorization": f"Bearer {token}"}},
                                },
                            })
                            _LOGGER.debug("AppSync subscription registered")
                        elif mtype == "data":
                            ev = self._parse(data)
                            if ev:
                                yield ev
                        elif mtype in ("connection_error", "error"):
                            errs = data.get("payload", {}).get("errors", [])
                            if any("unauthorized" in (e.get("message", "").lower())
                                   or e.get("errorType") == "UnauthorizedException"
                                   for e in errs):
                                self._force_refresh = True
                            _LOGGER.warning("AppSync error: %s", errs)
                            break
                        elif mtype == "complete":
                            break
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("AppSync stream error: %s; retry in %ss", err, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF)
