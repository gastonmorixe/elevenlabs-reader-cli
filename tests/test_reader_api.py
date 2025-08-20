#!/usr/bin/env python3
"""
Integration test suite for the Reader workflow. Requires network and tokens.
Enable with RUN_INTEGRATION=1.
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from elevenlabs_tts_client import ElevenLabsTTSClient
from token_manager import TokenManager


async def _get_token_via_helper() -> str:
    helper = Path(__file__).resolve().parents[1] / 'get_refresh_token.py'
    if not helper.exists():
        return ""
    try:
        import subprocess
        res = subprocess.run([sys.executable, str(helper)], capture_output=True, text=True)
        return (res.stdout or '').strip()
    except Exception:
        return ""


async def test_firebase_authentication():
    print("Auth test…")
    firebase_token = await _get_token_via_helper()
    if not firebase_token:
        print("No refresh token; skipping.")
        return None
    tm = TokenManager(verbose=True)
    tm.clear_cache()
    bearer = tm.get_fresh_bearer_token(firebase_token)
    if not bearer:
        print("Failed to get bearer token")
        return None
    return bearer


async def test_voice_listing(client):
    voices = await client.get_voices()
    v = voices.get("voices", [])
    if not v:
        return None
    return v[0]["voice_id"], v[0].get("name", "")


async def test_content_creation(client, text):
    return await client._create_read_document(text)


async def test_websocket_streaming(client, voice_id, text):
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        out = tmp.name
    data = await client.stream_with_websocket(text=text, voice_id=voice_id, output_file=out, play_audio=False)
    Path(out).unlink(missing_ok=True)
    return bool(data)


async def run_all_tests():
    if os.environ.get("RUN_INTEGRATION") != "1":
        print("Skipping integration tests. Set RUN_INTEGRATION=1 to run.")
        return

    bearer = await test_firebase_authentication()
    if not bearer:
        return

    # Optional App Check / Device ID
    def _get(name):
        p = Path(__file__).resolve().parents[1] / name
        if not p.exists():
            return ""
        import subprocess
        r = subprocess.run([sys.executable, str(p)], capture_output=True, text=True)
        return (r.stdout or '').strip()

    app_check = _get('get_app_check_token.py')
    device_id = _get('get_device_id.py')
    client = ElevenLabsTTSClient(bearer, verbose=True, app_check_token=(app_check or None), device_id=(device_id or None))

    v = await test_voice_listing(client)
    if not v:
        print("No voices; abort.")
        return
    voice_id, _ = v
    text = "Hello, this is a comprehensive test of the Reader client."
    rid = await test_content_creation(client, text)
    if not rid:
        print("Content creation failed")
        return
    ok = await test_websocket_streaming(client, voice_id, text)
    print(f"Streaming: {'OK' if ok else 'FAIL'}")


if __name__ == "__main__":
    asyncio.run(run_all_tests())
