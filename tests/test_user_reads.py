#!/usr/bin/env python3
"""
Integration: list user reads, create document, verify listing, and WS test.
RUN_INTEGRATION=1 required.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import aiohttp
import ssl

from elevenlabs_tts_client import ElevenLabsTTSClient
from token_manager import TokenManager


async def test_user_reads():
    if os.environ.get("RUN_INTEGRATION") != "1":
        print("Skipping integration test. Set RUN_INTEGRATION=1 to run.")
        return

    # Token
    token_manager = TokenManager(verbose=True)
    helper_rt = Path(__file__).resolve().parents[1] / 'get_refresh_token.py'
    refresh_token = ""
    if helper_rt.exists():
        import subprocess
        rt_out = subprocess.run([sys.executable, str(helper_rt)], capture_output=True, text=True)
        refresh_token = (rt_out.stdout or '').strip()
    bearer_token = token_manager.get_fresh_bearer_token(refresh_token) if refresh_token else None
    if not bearer_token:
        print("Failed to get Bearer token")
        return

    # App Check / Device
    def _get(name):
        p = Path(__file__).resolve().parents[1] / name
        if not p.exists():
            return ""
        import subprocess
        r = subprocess.run([sys.executable, str(p)], capture_output=True, text=True)
        return (r.stdout or '').strip()
    app_check = _get('get_app_check_token.py')
    device_id = _get('get_device_id.py')
    client = ElevenLabsTTSClient(bearer_token, verbose=True, app_check_token=(app_check or None), device_id=(device_id or None))

    print("List current user reads…")
    read_ids = await list_user_reads(client)
    print(f"Found {len(read_ids)} existing reads")

    print("Create new document…")
    test_text = "Test document for streaming analysis."
    read_id = await client._create_read_document(test_text)
    print(f"Created document: {read_id}")

    print("List reads again…")
    await asyncio.sleep(2)
    new_read_ids = await list_user_reads(client)
    if read_id in new_read_ids:
        print("New document found in user reads")
        await get_read_details(client, read_id)
        await test_websocket_streaming(client, read_id, "nPczCjzI2devNBz1zQrb", app_check, device_id)
    else:
        print("New document not found in user reads")


async def list_user_reads(client):
    url = "https://api.elevenlabs.io/v1/reader/reads/changes?last_updated_at_unix=0"
    headers = client.headers.copy()
    headers["Authorization"] = f"Bearer {client.bearer_token}"
    ssl_context = ssl.create_default_context()
    connector = aiohttp.TCPConnector(ssl=ssl_context)
    timeout = aiohttp.ClientTimeout(total=30)
    try:
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    reads = data.get('reads', [])
                    return [r.get('read_id') for r in reads if r.get('read_id')]
                else:
                    return []
    except Exception:
        return []


async def get_read_details(client, read_id):
    url = f"https://api.elevenlabs.io/v1/reader/reads/{read_id}"
    headers = client.headers.copy()
    headers["Authorization"] = f"Bearer {client.bearer_token}"
    ssl_context = ssl.create_default_context()
    connector = aiohttp.TCPConnector(ssl=ssl_context)
    timeout = aiohttp.ClientTimeout(total=30)
    try:
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    print(f"Read details: {data.get('creation_status')} {data.get('char_count')}")
                    return data
                return None
    except Exception:
        return None


async def test_websocket_streaming(client, read_id, voice_id, app_check: str, device_id: str):
    import websockets, uuid
    ws_url = f"wss://api.elevenlabs.io/v1/reader/reads/stream/{read_id}?voice_id={voice_id}"
    headers = {
        "Authorization": f"Bearer {client.bearer_token}",
        "User-Agent": client.headers["User-Agent"],
        "Origin": "https://elevenlabs.io",
        "device-id": device_id or client.device_id,
    }
    if app_check:
        headers["xi-app-check-token"] = app_check
    try:
        async with websockets.connect(ws_url, additional_headers=headers) as websocket:
            stream_id = str(uuid.uuid4()).upper()
            await websocket.send(json.dumps({"stream_id": stream_id, "position": 0}))
            msg = await asyncio.wait_for(websocket.recv(), timeout=10)
            data = json.loads(msg)
            print(f"WS keys: {list(data.keys())}")
            return True
    except Exception:
        return False


if __name__ == "__main__":
    asyncio.run(test_user_reads())
