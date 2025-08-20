#!/usr/bin/env python3
"""
Get Device ID helper

Attempts to retrieve a stable Device ID used by the Reader app requests.
Prefers tokens_cache.json, then extracted_tokens.json, then scans flows via `strings`.

Usage:
  python get_device_id.py [flows.elevenlabsio]
"""

import re
import sys
import json
from pathlib import Path


def get_from_cache():
    for cache in ["tokens_cache.json", "extracted_tokens.json"]:
        p = Path(cache)
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text())
            for key in ("device_id", "Device-ID", "deviceId"):
                if key in data and data[key]:
                    return str(data[key])
        except Exception:
            continue
    return None


def get_from_flows(path: Path):
    if not path.exists():
        return None
    # Use `strings` to extract text and look for device-id header
    try:
        import subprocess
        res = subprocess.run(["strings", "-n", "6", str(path)], capture_output=True, text=True)
    except Exception:
        return None
    if res.returncode != 0 or not res.stdout:
        return None
    # Find a UUID-like pattern on a line that mentions device-id
    uuid_re = re.compile(r"[A-F0-9]{8}-[A-F0-9]{4}-[A-F0-9]{4}-[A-F0-9]{4}-[A-F0-9]{12}", re.IGNORECASE)
    for line in res.stdout.splitlines():
        if "device-id" in line.lower():
            m = uuid_re.search(line)
            if m:
                return m.group(0).upper()
    # Fallback: first UUID in the dump
    m = uuid_re.search(res.stdout)
    if m:
        return m.group(0).upper()
    return None


def main():
    # 1) Cache
    did = get_from_cache()
    if did:
        print(did)
        return

    # 2) Flows (if provided or default)
    flows = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("flows.elevenlabsio")
    did = get_from_flows(flows)
    if did:
        # Also persist
        try:
            existing = {}
            p = Path("extracted_tokens.json")
            if p.exists():
                existing = json.loads(p.read_text())
            existing["device_id"] = did
            p.write_text(json.dumps(existing, indent=2))
        except Exception:
            pass
        print(did)
        return

    print("", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()

