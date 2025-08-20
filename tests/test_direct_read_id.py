#!/usr/bin/env python3
"""
Integration: direct streaming from existing read_id. RUN_INTEGRATION=1 required.
"""

import asyncio
import os
import sys
from pathlib import Path

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from elevenlabs_tts_client import ElevenLabsTTSClient
from token_manager import TokenManager


async def test_direct_read_id_streaming():
    if os.environ.get("RUN_INTEGRATION") != "1":
        print("Skipping integration test. Set RUN_INTEGRATION=1 to run.")
        return

    token_manager = TokenManager(verbose=True)
    helper_rt = Path(__file__).resolve().parents[1] / 'get_refresh_token.py'
    refresh_token = ""
    if helper_rt.exists():
        import subprocess
        rt_out = subprocess.run([sys.executable, str(helper_rt)], capture_output=True, text=True)
        refresh_token = (rt_out.stdout or '').strip()
    bearer_token = token_manager.get_fresh_bearer_token(refresh_token) if refresh_token else None

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

    read_ids_to_test = [
        "pacfq4PKIuAhSUsqaORE",
        "u:V4KUQARi0E1ZvQ7Wd0Tx",
    ]
    voice_id = "nPczCjzI2devNBz1zQrb"

    import websockets, json, uuid, base64
    for read_id in read_ids_to_test:
        print(f"Testing direct streaming from read_id: {read_id}")
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
                stream_id = str(uuid.uuid4()).upper()
                await websocket.send(json.dumps({"stream_id": stream_id, "position": 0}))
                print("Sent init")
                message_count = 0
                audio_data = b""
                while True:
                    try:
                        message = await asyncio.wait_for(websocket.recv(), timeout=10)
                    except asyncio.TimeoutError:
                        print("Timeout waiting for WS message; stopping test loop")
                        break
                    try:
                        data = json.loads(message)
                        message_count += 1
                        if "audio" in data and data["audio"]:
                            audio_data += base64.b64decode(data["audio"])  # noqa: F821
                        if data.get("isFinal", False) or message_count >= 5:
                            break
                    except json.JSONDecodeError:
                        break
                print(f"Streamed {len(audio_data)} bytes from {read_id}")
        except Exception as e:
            print(f"Failed with read_id {read_id}: {e}")


if __name__ == "__main__":
    asyncio.run(test_direct_read_id_streaming())
