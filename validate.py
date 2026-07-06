"""Validate the IQ4 client against the live API using a bootstrap refresh_token.

    .venv/bin/python validate.py --refresh-token <TOKEN>
    .venv/bin/python validate.py --token-file captures/iq4_token.json

Read-only: lists satellites, connectivity, stations, and run status. Does NOT
start/stop anything.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "custom_components" / "rainbird_ha"))

import aiohttp  # noqa: E402

from client.iq4 import IQ4Auth, IQ4Client, file_token_saver, load_token_file  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh-token")
    ap.add_argument("--token-file", default="captures/iq4_token.json")
    args = ap.parse_args()

    token_path = Path(args.token_file)
    if args.refresh_token:
        token_path.write_text(json.dumps({"refresh_token": args.refresh_token}))
        print(f"Wrote bootstrap token -> {token_path}")

    async with aiohttp.ClientSession() as session:
        data = load_token_file(token_path)
        auth = IQ4Auth(session, data["refresh_token"])
        auth.apply_tokens(data)
        auth.on_token_update = file_token_saver(token_path)
        client = IQ4Client(auth)

        print("\n== refreshing access token ==")
        tok = await auth.async_access_token()
        print(f"  OK, got access token (len {len(tok)}); rotated refresh persisted")

        print("\n== satellites ==")
        sats = await client.get_satellites()
        for s in sats:
            print(f"  [{s.id}] {s.name!r}  uuid={s.device_uuid}  stations={s.station_count}")

        for s in sats:
            print(f"\n== controller {s.id} ({s.name}) ==")
            online = await client.is_connected(s.id)
            print(f"  connected: {online}")
            stations = await client.get_stations(s.id)
            print(f"  stations ({len(stations)}):")
            for st in stations:
                print(f"    id={st.id} term={st.terminal} name={st.name!r}")
            try:
                run = await client.get_run_status(s.id)
                print(f"  run status: {json.dumps(run)[:400]}")
            except Exception as exc:  # noqa: BLE001
                print(f"  run status ERROR: {type(exc).__name__}: {exc}")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
