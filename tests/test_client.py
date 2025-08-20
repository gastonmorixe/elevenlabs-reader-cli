#!/usr/bin/env python3
"""
Integration test: basic client flow. Requires network and tokens.

Enable by setting RUN_INTEGRATION=1 and providing a Firebase refresh token
via get_refresh_token.py or by manual input when prompted.
"""

import asyncio
import os
import sys
from pathlib import Path

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from elevenlabs_tts_client import ElevenLabsTTSClient
from token_manager import TokenManager


async def test_client():
    if os.environ.get("RUN_INTEGRATION") != "1":
        print("Skipping integration test. Set RUN_INTEGRATION=1 to run.")
        return

    print("Testing ElevenLabs TTS Client (integration)")

    # Prefer helper for token, else prompt
    firebase_token = ""
    helper = Path(__file__).resolve().parents[1] / 'get_refresh_token.py'
    if helper.exists():
        try:
            import subprocess
            res = subprocess.run([sys.executable, str(helper)], capture_output=True, text=True)
            firebase_token = (res.stdout or '').strip()
        except Exception:
            firebase_token = ""
    if not firebase_token:
        firebase_token = input("Enter Firebase refresh token: ").strip()
    if not firebase_token:
        print("No refresh token provided; aborting.")
        return

    token_manager = TokenManager(verbose=True)
    bearer_token = token_manager.get_fresh_bearer_token(firebase_token)
    if not bearer_token:
        print("Failed to get Bearer token")
        return

    # Optional App Check token and Device ID (improves WS success)
    def _opt(name):
        p = Path(__file__).resolve().parents[1] / name
        if not p.exists():
            return ""
        import subprocess
        r = subprocess.run([sys.executable, str(p)], capture_output=True, text=True)
        return (r.stdout or '').strip()

    app_check = _opt('get_app_check_token.py')
    device_id = _opt('get_device_id.py')
    client = ElevenLabsTTSClient(
        bearer_token,
        verbose=True,
        app_check_token=(app_check or None),
        device_id=(device_id or None),
    )

    # List voices
    try:
        voices = await client.get_voices()
        vlist = voices.get("voices", [])
        print(f"Voices: {len(vlist)}")
        if not vlist:
            return
        voice_id = vlist[0]["voice_id"]
        test_text = "Hello, this is a test of the ElevenLabs TTS client."
        await client.stream_with_websocket(text=test_text, voice_id=voice_id, output_file="test_output.mp3", play_audio=False)
        print("Integration test finished.")
    except Exception as e:
        print(f"Integration test error: {e}")


if __name__ == "__main__":
    asyncio.run(test_client())
