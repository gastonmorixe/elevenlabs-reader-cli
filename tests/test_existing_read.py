#!/usr/bin/env python3
"""
Integration: stream from existing read IDs captured from flows. RUN_INTEGRATION=1 required.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from elevenlabs_tts_client import ElevenLabsTTSClient
from token_manager import TokenManager


async def test_existing_read():
    if os.environ.get("RUN_INTEGRATION") != "1":
        print("Skipping integration test. Set RUN_INTEGRATION=1 to run.")
        return

    existing_read_ids = [
        "u:V4KUQARi0E1ZvQ7Wd0Tx",
        "pacfq4PKIuAhSUsqaORE",
    ]

    # Get Bearer token via helper
    token_manager = TokenManager(verbose=True)
    helper_rt = Path(__file__).resolve().parents[1] / 'get_refresh_token.py'
    rt_out = None
    if helper_rt.exists():
        import subprocess
        rt_out = subprocess.run([sys.executable, str(helper_rt)], capture_output=True, text=True)
    refresh_token = ((rt_out.stdout or '') if rt_out else '').strip()
    bearer_token = token_manager.get_fresh_bearer_token(refresh_token) if refresh_token else None
    if not bearer_token:
        print("Failed to get Bearer token")
        return

    # App Check & Device ID
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
    voice_id = "nPczCjzI2devNBz1zQrb"

    import websockets
    for read_id in existing_read_ids:
        print(f"Testing existing read_id: {read_id}")
        ws_url = f"wss://api.elevenlabs.io/v1/reader/reads/stream/{read_id}?voice_id={voice_id}"
        headers = {
            "Authorization": f"Bearer {bearer_token}",
            "User-Agent": "readerapp/405 CFNetwork/3860.100.1 Darwin/25.0.0",
            "Origin": "https://elevenlabs.io",
            "device-id": device_id or client.device_id,
        }
        if app_check:
            headers["xi-app-check-token"] = app_check
        try:
            async with websockets.connect(ws_url, additional_headers=headers, max_size=None, open_timeout=10, ping_timeout=20) as websocket:
                print("Connected to existing read WebSocket")
                init_message = {"stream_id": __import__('uuid').uuid4().hex.upper(), "position": 0}
                await websocket.send(json.dumps(init_message))
                print(f"Sent: {init_message}")
                message_count = 0
                while True:
                    try:
                        message = await asyncio.wait_for(websocket.recv(), timeout=10)
                    except asyncio.TimeoutError:
                        print("Timeout waiting for WS message; stopping test loop")
                        break
                    try:
                        data = json.loads(message)
                        message_count += 1
                        print(f"Message {message_count}: {list(data.keys())}")
                        if data.get("isFinal", False) or message_count >= 3:
                            break
                    except json.JSONDecodeError:
                        break
        except Exception as e:
            print(f"Failed with read_id {read_id}: {e}")


if __name__ == "__main__":
    asyncio.run(test_existing_read())
