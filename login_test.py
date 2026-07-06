"""Test onboarding login (ROPC password grant) without exposing your password.

Run it and type your Rain Bird 2.0 app email + password at the prompts (input is
hidden). It mints an INDEPENDENT token lineage for Home Assistant -- it does NOT
disturb the phone app -- and saves it to captures/iq4_token.json on success.

    .venv/bin/python login_test.py

If ROPC is disabled server-side you'll get HTTP 400 'unsupported_grant_type' or
similar; tell me and I'll implement the browser-login fallback instead.
"""

from __future__ import annotations

import asyncio
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "custom_components" / "rainbird_ha"))

import aiohttp  # noqa: E402

from client.iq4 import IQ4Client, file_token_saver, login_with_password  # noqa: E402


async def main() -> int:
    username = input("Rain Bird account email: ").strip()
    password = getpass.getpass("Rain Bird password (hidden): ")

    async with aiohttp.ClientSession() as session:
        try:
            auth = await login_with_password(session, username, password)
            await file_token_saver("captures/iq4_token.json")(auth.token_data)
        except Exception as exc:  # noqa: BLE001
            print(f"\nLOGIN FAILED: {type(exc).__name__}: {exc}")
            return 1
        print("\nLOGIN OK -- independent refresh token minted and saved.")
        client = IQ4Client(auth)
        sats = await client.get_satellites()
        for s in sats:
            print(f"  controller [{s.id}] {s.name!r}, {s.station_count} stations, "
                  f"connected={await client.is_connected(s.id)}")
    print("\nThe phone app is unaffected. Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
