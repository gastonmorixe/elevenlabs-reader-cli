#!/usr/bin/env python3
"""
Basic non-interactive checks (no network required).

Validates imports, TokenManager behavior with mock data, and client init.
"""

import asyncio
import sys
from pathlib import Path

# Ensure project root is on path when running as a script
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def have_third_party():
    try:
        import aiohttp  # noqa: F401
        import websockets  # noqa: F401
        return True
    except Exception:
        return False


def test_imports():
    try:
        # TokenManager should import without third-party deps
        from token_manager import TokenManager  # noqa: F401
        # Only require third-party libs if available
        if have_third_party():
            from elevenlabs_tts_client import ElevenLabsTTSClient, FirebaseAuth  # noqa: F401
        return True
    except Exception:
        return False


def test_token_manager():
    try:
        from token_manager import TokenManager
        manager = TokenManager(cache_file="test_cache.json", verbose=False)
        info = manager.get_cache_info()
        assert isinstance(info, dict)
        # Expired mock
        assert manager.is_token_expired({'expires_at': '2020-01-01T00:00:00'}) is True
        # Clean up
        cache = Path("test_cache.json")
        if cache.exists():
            cache.unlink()
        return True
    except Exception:
        return False


def test_client_initialization():
    if not have_third_party():
        # Skip if deps not installed in environment
        return True
    try:
        from elevenlabs_tts_client import ElevenLabsTTSClient
        mock_bearer_token = "mock_bearer_token_for_testing"
        client = ElevenLabsTTSClient(mock_bearer_token, verbose=False)
        assert client.bearer_token == mock_bearer_token
        assert client.device_id
        assert client.session_id
        assert "readerapp" in client.headers.get("User-Agent", "")
        return True
    except Exception:
        return False


def test_file_structure():
    # Core files present
    required = [
        Path("elevenlabs_tts_client.py"),
        Path("token_manager.py"),
        Path("requirements.txt"),
        Path("README.md"),
    ]
    return all(p.exists() for p in required)


async def run_basic_tests():
    results = [
        ("Imports", test_imports()),
        ("TokenManager", test_token_manager()),
        ("Client init", test_client_initialization()),
        ("File structure", test_file_structure()),
    ]
    passed = sum(1 for _, ok in results if ok)
    for name, ok in results:
        print(f"{name}: {'OK' if ok else 'FAIL'}")
    print(f"Summary: {passed}/{len(results)} passed")
    return passed == len(results)


if __name__ == "__main__":
    ok = asyncio.run(run_basic_tests())
    sys.exit(0 if ok else 1)
