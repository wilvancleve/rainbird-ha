"""Live write-control test: start zone 1, observe realtime, stop it.

Runs real water briefly (~20s). Confirms StartStations + AdvanceStations work and
reveals whether the stream's activeStation is a station id or a terminal number.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "custom_components" / "rainbird_ha"))

import aiohttp  # noqa: E402

from client.iq4 import IQ4Auth, IQ4Client, file_token_saver, load_token_file  # noqa: E402
from client.stream import IQ4Stream  # noqa: E402

ZONE1_ID = 15239592  # Station 001, terminal 1


async def main() -> int:
    async with aiohttp.ClientSession() as session:
        auth = IQ4Auth(session, load_token_file("captures/iq4_token.json")["refresh_token"])
        auth.apply_tokens(load_token_file("captures/iq4_token.json"))
        auth.on_token_update = file_token_saver("captures/iq4_token.json")
        client = IQ4Client(auth)
        sat = (await client.get_satellites())[0]
        events: list = []

        stream = IQ4Stream(auth, sat.device_uuid)

        async def listen():
            async for ev in stream.listen():
                print(f"  >>> STREAM: active_station={ev.active_station!r} "
                      f"remain={ev.remain_seconds!r} state={ev.state!r}")
                events.append(ev)

        task = asyncio.create_task(listen())
        await asyncio.sleep(2)  # let the subscription register

        print(f"\nSTARTING zone 1 (id={ZONE1_ID}) for 1 minute...")
        await client.start_station(ZONE1_ID, 1)
        print("  start command returned (204 expected)")

        print("\nWatching for ~18s...")
        for i in range(6):
            await asyncio.sleep(3)
            run = await client.get_run_status(sat.satellite_id if hasattr(sat,'satellite_id') else sat.id)
            # find any station reporting active
            active = []
            for prog in (run or []):
                for rs in prog.get("runStationStatuses", []):
                    st = rs.get("status")
                    if st and st not in ("-",):
                        active.append((rs.get("stationId"), rs.get("stationTerminal"), st))
            print(f"  [{(i+1)*3}s] run-status active entries: {active}")

        print("\nSTOPPING zone 1...")
        await client.stop_stations([ZONE1_ID])
        print("  stop command returned")
        await asyncio.sleep(4)

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        print(f"\n=== Summary: {len(events)} stream events ===")
        vals = {e.active_station for e in events if e.active_station is not None}
        print(f"  distinct non-null activeStation values seen: {vals}")
        if ZONE1_ID in vals:
            print("  -> activeStation is the STATION ID")
        elif 1 in vals:
            print("  -> activeStation is the TERMINAL number")
        else:
            print("  -> inconclusive (check raw events above)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
