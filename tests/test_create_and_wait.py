#!/usr/bin/env python3
"""
Integration: document creation + status polling. RUN_INTEGRATION=1 required.
"""

import asyncio
import os
import sys
from pathlib import Path

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from elevenlabs_tts_client import ElevenLabsTTSClient
from token_manager import TokenManager


async def test_document_lifecycle():
    if os.environ.get("RUN_INTEGRATION") != "1":
        print("Skipping integration test. Set RUN_INTEGRATION=1 to run.")
        return

    token_manager = TokenManager(verbose=True)
    helper = Path(__file__).resolve().parents[1] / 'get_refresh_token.py'
    refresh_token = ""
    if helper.exists():
        import subprocess
        out = subprocess.run([sys.executable, str(helper)], capture_output=True, text=True)
        refresh_token = (out.stdout or '').strip()
    bearer_token = token_manager.get_fresh_bearer_token(refresh_token) if refresh_token else None
    if not bearer_token:
        print("Failed to get Bearer token")
        return

    client = ElevenLabsTTSClient(bearer_token, verbose=True)
    test_text = "Hello world, document creation and processing test."

    try:
        print("Creating document…")
        read_id = await client._create_read_document(test_text)
        print(f"Created document: {read_id}")
        print("Polling status via simple-html…")
        await client._wait_for_document_processing(read_id, max_wait_time=30)
        print("Status OK.")
    except Exception as e:
        print(f"Lifecycle test failed: {e}")


if __name__ == "__main__":
    asyncio.run(test_document_lifecycle())
