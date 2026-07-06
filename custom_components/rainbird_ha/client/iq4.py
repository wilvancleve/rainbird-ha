"""Self-hosted client for the Rain Bird IQ4 cloud API.

Reverse-engineered from the Rain Bird 2.0 app traffic. Unlike pyrainbird.cloud
and the rainbird_iq4 HACS integration -- both of which re-scrape the fragile
OIDC HTML login every ~2 hours (WAF-prone, a likely source of the "unavailable"
flapping) -- this uses the app's own ``refresh_token`` grant: one durable token
lineage, refreshed cleanly, persisted across restarts.

Endpoints (base https://iq4server.rainbird.com):
    token   POST  /coreidentityserver/connect/token   (form: grant_type=refresh_token)
    sats    GET   /coreapi/api/Satellite/GetSatelliteList
    online  GET   /coreapi/api/Satellite/isConnected?satelliteIds=ID
    zones   GET   /coreapi/api/Station/GetStationListForSatellite?satelliteId=ID
    runstat GET   /coreapi/api/ProgramStep/GetRunStationStatusForSatellite?satelliteId=ID
    start   POST  /coreapi/api/ManualOps/StartStations
    stop    POST  /coreapi/api/ManualOps/AdvanceStations?isProgramIndex=true
    rain    PATCH /coreapi/api/Satellite/v2/UpdateBatches
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import json
import logging
import re
import secrets
import time
import urllib.parse
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

AUTH_BASE = "https://iq4server.rainbird.com/coreidentityserver"
API_BASE = "https://iq4server.rainbird.com/coreapi/api"
TOKEN_URL = f"{AUTH_BASE}/connect/token"
# The 2.0 app's own User-Agent, to blend in with normal traffic / avoid WAF quirks.
USER_AGENT = "Rain Bird 2.0/1 CFNetwork/3860.700.1 Darwin/25.6.0"
EXPIRY_MARGIN = 120  # refresh this many seconds before the token actually expires

# The OAuth client credentials the Rain Bird 2.0 app sends as HTTP Basic auth on
# the token endpoint are NOT shipped with this project. Capture your own from the
# app with the proxy in tools/ and provide them at setup. See tools/README.md.


class IQ4Error(Exception):
    """Base error."""


class IQ4AuthError(IQ4Error):
    """Authentication/token error (bad or expired refresh token)."""


class IQ4ApiError(IQ4Error):
    """Non-2xx API response."""


@dataclass
class IQ4Auth:
    """Holds and refreshes the OAuth token lineage for one account.

    Bootstrap with a ``refresh_token`` (from a login or captured from the app).
    On each rotation the tokens are handed to the async ``on_token_update`` hook
    (if set) so the caller can persist them however it likes -- the client itself
    does no file I/O, keeping it safe to run inside an event loop.
    """

    session: aiohttp.ClientSession
    refresh_token: str
    client_id: str
    client_secret: str
    on_token_update: Callable[[dict[str, Any]], Awaitable[None]] | None = None
    _access_token: str | None = field(default=None, repr=False)
    _expires_at: float = 0.0

    def apply_tokens(self, data: dict[str, Any]) -> None:
        """Seed cached tokens from a previously persisted dict."""
        if data.get("refresh_token"):
            self.refresh_token = data["refresh_token"]
        self._access_token = data.get("access_token")
        self._expires_at = data.get("expires_at", 0.0)

    @property
    def token_data(self) -> dict[str, Any]:
        return {
            "refresh_token": self.refresh_token,
            "access_token": self._access_token,
            "expires_at": self._expires_at,
        }

    async def _persist(self) -> None:
        if self.on_token_update:
            await self.on_token_update(self.token_data)

    async def async_access_token(self, force_refresh: bool = False) -> str:
        """Return a valid bearer access token, refreshing if needed."""
        if (not force_refresh and self._access_token
                and time.time() < self._expires_at - EXPIRY_MARGIN):
            return self._access_token
        return await self._refresh()

    async def _refresh(self) -> str:
        data = {"grant_type": "refresh_token", "refresh_token": self.refresh_token}
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        # The app authenticates the OAuth client via HTTP Basic (client_id:secret).
        basic = aiohttp.BasicAuth(self.client_id, self.client_secret)
        try:
            async with self.session.post(
                TOKEN_URL, data=data, headers=headers, auth=basic
            ) as resp:
                body = await resp.text()
                if resp.status != 200:
                    raise IQ4AuthError(
                        f"Token refresh failed (HTTP {resp.status}): {body[:300]}"
                    )
                tok = json.loads(body)
        except aiohttp.ClientError as err:
            raise IQ4Error(f"Connection error during token refresh: {err}") from err

        self._access_token = tok["access_token"]
        self._expires_at = time.time() + int(tok.get("expires_in", 3600))
        # IdentityServer rotates the refresh token on each use -- persist the new one
        # or the next refresh will fail.
        if tok.get("refresh_token"):
            self.refresh_token = tok["refresh_token"]
        await self._persist()
        _LOGGER.debug("Refreshed IQ4 access token; expires in %ss", tok.get("expires_in"))
        return self._access_token


def load_token_file(path: str | Path) -> dict[str, Any] | None:
    """Read a persisted token dict (blocking; for standalone/dev use only)."""
    p = Path(path)
    return json.loads(p.read_text()) if p.exists() else None


def file_token_saver(path: str | Path) -> Callable[[dict[str, Any]], Awaitable[None]]:
    """An on_token_update hook that writes to a file (blocking write; dev use)."""
    async def _save(data: dict[str, Any]) -> None:
        Path(path).write_text(json.dumps(data))
    return _save


OFFLINE_SCOPE = "coreAPI.read coreAPI.write openid profile offline_access"
REDIRECT_URI = "com.rainbird.mobile://auth"
_ANTIFORGERY_RE = re.compile(
    r'name="__RequestVerificationToken"[^>]*value="([^"]+)"'
)


def _pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")
    return verifier, challenge


async def login_with_password(
    session: aiohttp.ClientSession,
    username: str,
    password: str,
    client_id: str,
    client_secret: str,
) -> IQ4Auth:
    """Mint a fresh, independent refresh token from account credentials.

    Drives the app's OIDC **authorization-code + PKCE** flow (ROPC is disabled
    server-side). Home Assistant thus gets its own token lineage, separate from
    the phone app's -- they coexist without logging each other out.

    The interactive login runs in a private cookie jar; the returned IQ4Auth is
    bound to ``session`` for ongoing use.
    """
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)
    nonce = secrets.token_urlsafe(16)
    authorize_params = {
        "prompt": "login",
        "nonce": nonce,
        "response_type": "code",
        "code_challenge_method": "S256",
        "scope": OFFLINE_SCOPE,
        "code_challenge": challenge,
        "redirect_uri": REDIRECT_URI,
        "client_id": client_id,
        "state": state,
    }
    base_headers = {"User-Agent": USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"}

    # Private cookie jar for the login handshake (antiforgery + session cookies).
    async with aiohttp.ClientSession() as login_session:
        try:
            # 1. Start the authorize flow -> redirected to the login page.
            authorize_url = f"{AUTH_BASE}/connect/authorize?{urllib.parse.urlencode(authorize_params)}"
            async with login_session.get(
                authorize_url, headers=base_headers, allow_redirects=False
            ) as resp:
                login_location = resp.headers.get("Location")
            if not login_location:
                raise IQ4AuthError("Authorize did not redirect to the login page.")
            login_url = urllib.parse.urljoin(f"{AUTH_BASE}/", login_location)
            return_url = urllib.parse.parse_qs(
                urllib.parse.urlparse(login_url).query
            ).get("ReturnUrl", [""])[0]

            # 2. Fetch the login page for the antiforgery token (cookie set in jar).
            async with login_session.get(login_url, headers=base_headers) as resp:
                html = await resp.text()
            m = _ANTIFORGERY_RE.search(html)
            if not m:
                raise IQ4AuthError("Could not find antiforgery token on login page.")
            csrf = m.group(1)

            # 3. Submit credentials -> 302 back to the authorize callback.
            form = {
                "ReturnUrl": return_url,
                "Username": username,
                "Password": password,
                "__RequestVerificationToken": csrf,
            }
            async with login_session.post(
                login_url, data=form, headers=base_headers, allow_redirects=False
            ) as resp:
                if resp.status not in (301, 302):
                    raise IQ4AuthError(
                        "Login rejected (bad credentials?). "
                        f"HTTP {resp.status}."
                    )
                callback_location = resp.headers.get("Location")

            # 4. Follow the callback -> 302 to redirect_uri with the auth code.
            code = None
            for _ in range(6):
                if not callback_location:
                    break
                if callback_location.startswith(REDIRECT_URI):
                    frag = urllib.parse.urlparse(callback_location)
                    code = urllib.parse.parse_qs(frag.query).get("code", [None])[0]
                    break
                nxt = urllib.parse.urljoin(f"{AUTH_BASE}/", callback_location)
                async with login_session.get(
                    nxt, headers=base_headers, allow_redirects=False
                ) as resp:
                    callback_location = resp.headers.get("Location")
            if not code:
                raise IQ4AuthError("Did not receive an authorization code.")

            # 5. Exchange the code for tokens (Basic client auth + PKCE verifier).
            data = {
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": REDIRECT_URI,
                "grant_type": "authorization_code",
            }
            async with login_session.post(
                TOKEN_URL, data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded",
                         "Accept": "application/json", "User-Agent": USER_AGENT},
                auth=aiohttp.BasicAuth(client_id, client_secret),
            ) as resp:
                text = await resp.text()
                if resp.status != 200:
                    raise IQ4AuthError(
                        f"Code exchange failed (HTTP {resp.status}): {text[:300]}")
                tok = json.loads(text)
        except aiohttp.ClientError as err:
            raise IQ4Error(f"Connection error during login: {err}") from err

    if not tok.get("refresh_token"):
        raise IQ4AuthError("Login returned no refresh_token (offline_access missing).")
    auth = IQ4Auth(session, tok["refresh_token"],
                   client_id=client_id, client_secret=client_secret)
    auth._access_token = tok["access_token"]
    auth._expires_at = time.time() + int(tok.get("expires_in", 3600))
    return auth


@dataclass
class Station:
    """One irrigation station/zone."""

    id: int
    name: str
    terminal: int
    satellite_id: int
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Station":
        return cls(id=d["id"], name=d.get("name", f"Station {d.get('terminal')}"),
                   terminal=d.get("terminal", 0), satellite_id=d.get("satelliteId", 0),
                   raw=d)


@dataclass
class Satellite:
    """One controller."""

    id: int
    name: str
    device_uuid: str
    station_count: int
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Satellite":
        return cls(id=d["id"], name=d.get("name", str(d["id"])),
                   device_uuid=d.get("deviceUUID", ""),
                   station_count=d.get("stationCount", 0), raw=d)


class IQ4Client:
    """REST client for controlling and reading IQ4 controllers."""

    def __init__(self, auth: IQ4Auth) -> None:
        self._auth = auth
        self._session = auth.session

    async def _request(self, method: str, path: str, *,
                       params: dict[str, Any] | None = None,
                       json_body: Any = None) -> Any:
        """Authenticated request with one automatic 401 -> refresh -> retry."""
        url = f"{API_BASE}/{path}"
        for attempt in (1, 2):
            token = await self._auth.async_access_token(force_refresh=(attempt == 2))
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            }
            if json_body is not None:
                headers["Content-Type"] = "application/json"
            try:
                async with self._session.request(
                    method, url, params=params, json=json_body, headers=headers,
                ) as resp:
                    if resp.status == 401 and attempt == 1:
                        _LOGGER.info("IQ4 401 on %s; refreshing token and retrying", path)
                        continue
                    text = await resp.text()
                    if resp.status not in (200, 201, 204):
                        raise IQ4ApiError(f"{method} {path} -> HTTP {resp.status}: {text[:300]}")
                    if resp.status == 204 or not text:
                        return None
                    return json.loads(text)
            except aiohttp.ClientError as err:
                raise IQ4Error(f"Connection error on {method} {path}: {err}") from err
        raise IQ4AuthError(f"Unauthorized on {method} {path} after token refresh")

    # ---- reads ----
    async def get_satellites(self) -> list[Satellite]:
        data = await self._request("GET", "Satellite/GetSatelliteList",
                                   params={"includeInvisibleToCurrentUser": "false"})
        return [Satellite.from_dict(d) for d in (data or [])]

    async def is_connected(self, satellite_id: int) -> bool:
        data = await self._request("GET", "Satellite/isConnected",
                                   params={"satelliteIds": satellite_id})
        for s in (data or {}).get("satellites", []):
            if s.get("id") == satellite_id:
                return bool(s.get("isConnected"))
        return False

    async def get_stations(self, satellite_id: int) -> list[Station]:
        data = await self._request("GET", "Station/GetStationListForSatellite",
                                   params={"satelliteId": satellite_id})
        return [Station.from_dict(d) for d in (data or [])]

    async def get_run_status(self, satellite_id: int) -> Any:
        """Currently-running station status for a controller."""
        return await self._request("GET", "ProgramStep/GetRunStationStatusForSatellite",
                                   params={"satelliteId": satellite_id})

    # ---- controls ----
    async def start_stations(self, station_ids: list[int], seconds: list[int]) -> None:
        if len(station_ids) != len(seconds):
            raise ValueError("station_ids and seconds must be the same length")
        await self._request("POST", "ManualOps/StartStations", json_body={
            "stationIds": station_ids, "seconds": seconds, "isGroupStart": False,
        })

    async def start_station(self, station_id: int, minutes: int) -> None:
        await self.start_stations([station_id], [int(minutes) * 60])

    async def stop_stations(self, station_ids: list[int]) -> None:
        """Stop stations by advancing them past the current program step."""
        await self._request("POST", "ManualOps/AdvanceStations",
                            params={"isProgramIndex": "true"},
                            json_body=[{"programId": -1, "stationId": sid}
                                       for sid in station_ids])

    async def stop_all(self, satellite_id: int) -> None:
        stations = await self.get_stations(satellite_id)
        await self.stop_stations([s.id for s in stations])

    # ---- rain delay ----
    async def get_rain_delay(self, satellite_id: int) -> int:
        """Current rain delay in days (0 = none)."""
        for s in await self.get_satellites():
            if s.id == satellite_id:
                return int(s.raw.get("rainDelay") or 0)
        return 0

    async def set_rain_delay(self, satellite_id: int, days: int) -> None:
        """Set rain delay in whole days. 0 clears it.

        ``rainDelayLong`` is expressed in .NET ticks (100-nanosecond intervals).
        """
        ticks = int(days) * 24 * 3600 * 10_000_000
        start = datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        await self._request("PATCH", "Satellite/v2/UpdateBatches", json_body={
            "ids": [satellite_id],
            "patch": [
                {"op": "replace", "path": "/rainDelayLong", "value": ticks},
                {"op": "replace", "path": "/rainDelayStart", "value": start},
            ],
        })

    # ---- controller power (physical dial position) ----
    async def set_power(self, satellite_id: int, on: bool) -> None:
        """Turn the whole controller On (Auto) or Off. logicalDialPos 2=On, 1=Off."""
        await self._request("PATCH", "Satellite/V2/UpdateBatches", json_body={
            "ids": [satellite_id],
            "patch": [{"op": "replace", "path": "/logicalDialPos",
                       "value": 2 if on else 1}],
        })

    # ---- schedule reads ----
    async def get_programs(self, satellite_id: int) -> list[dict[str, Any]]:
        return await self._request("GET", "Program/GetPrograms",
                                   params={"satelliteId": satellite_id}) or []

    async def get_program_steps(self, program_id: int) -> list[dict[str, Any]]:
        return await self._request("GET", "ProgramStep/GetProgramSteps",
                                   params={"programId": program_id}) or []

    async def get_start_times(self, program_id: int) -> list[dict[str, Any]]:
        return await self._request("GET", "StartTime/GetStartTimes",
                                   params={"programId": program_id}) or []

    # ---- schedule writes ----
    async def update_program(self, program_id: int, fields: dict[str, Any]) -> None:
        """Patch program metadata (name, weekDays, hybridWeekDays, programAdjust, ...)."""
        await self._request("PATCH", "Program/UpdateBatches", json_body={
            "ids": [program_id],
            "patch": [{"op": "replace", "path": f"/{k}", "value": v}
                      for k, v in fields.items()],
        })

    async def set_program_days(self, program_id: int, week_days: str) -> None:
        """week_days is a 7-char mask 'SMTWTFS', e.g. '1111111' daily, '0000000' off."""
        await self.update_program(program_id, {
            "weekDays": week_days, "hybridWeekDays": week_days,
        })

    async def create_program_steps(
        self, program_id: int, steps: list[tuple[int, int]]
    ) -> None:
        """Add station steps. Each step is (station_id, minutes)."""
        body = [{
            "programId": program_id, "stationId": sid,
            "runTimeLong": int(minutes) * 60 * 10_000_000,  # ticks
            "actionId": "RunStation",
        } for sid, minutes in steps]
        await self._request("POST", "ProgramStep/CreateProgramSteps", json_body=body)

    async def delete_program_steps(self, step_ids: list[int]) -> None:
        await self._request("DELETE", "ProgramStep/DeleteProgramSteps",
                            params={"downlink": "true"},
                            json_body=[int(s) for s in step_ids])

    async def add_start_time(self, program_id: int, hh_mm: str) -> None:
        """Add a daily start time, hh_mm like '06:30' (24h local)."""
        await self._request("PATCH", "StartTime/v2/UpdateBatches", json_body={
            "add": [{"id": 0, "patch": [
                {"op": "add", "path": "/dateTime", "value": f"2000-01-01T{hh_mm}:00"},
                {"op": "add", "path": "/enabled", "value": True},
                {"op": "add", "path": "/programId", "value": program_id},
            ]}],
            "update": [],
            "delete": {"id": program_id, "ids": []},
        })

    async def delete_start_time(self, program_id: int, start_time_id: int) -> None:
        await self._request("PATCH", "StartTime/v2/UpdateBatches", json_body={
            "add": [], "update": [],
            "delete": {"id": program_id, "ids": [int(start_time_id)]},
        })

    async def clear_program(self, program_id: int) -> None:
        """Empty a program slot: remove all steps + start times and zero its days."""
        steps = await self.get_program_steps(program_id)
        if steps:
            await self.delete_program_steps([s["id"] for s in steps])
        for st in await self.get_start_times(program_id):
            await self.delete_start_time(program_id, st["id"])
        await self.set_program_days(program_id, "0000000")
