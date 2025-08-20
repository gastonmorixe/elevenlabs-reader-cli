#!/usr/bin/env python3
"""
Quick Firebase App Check Token Extractor

Extracts the xi-app-check-token value from cache or flows dump.
Usage:
  python get_app_check_token.py [flows.elevenlabsio]
"""

import sys
import json
import re
from pathlib import Path


def get_from_cache():
    for cache_file in ["tokens_cache.json", "extracted_tokens.json"]:
        p = Path(cache_file)
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text())
            token = data.get("xi_app_check_token") or data.get("app_check_token")
            if token:
                return token
        except Exception:
            continue
    return None


def get_from_flows(flows_path: Path):
    if not flows_path.exists():
        return None
    try:
        text = flows_path.read_bytes().decode("utf-8", errors="ignore")
    except Exception:
        text = None
    # Try plain text first
    if text:
        m = re.search(r"xi-app-check-token\s*:\s*([A-Za-z0-9_\-\.]+)", text)
        if m:
            return m.group(1)
    # Fallback: use `strings` output to normalize lines
    try:
        import subprocess
        res = subprocess.run(["strings", "-n", "6", str(flows_path)], capture_output=True, text=True)
        if res.returncode == 0 and res.stdout:
            # Find the line containing the header and extract token-looking value after it
            for line in res.stdout.splitlines():
                if "xi-app-check-token" in line:
                    # Split on token header and take the next token-like chunk
                    parts = re.split(r"xi-app-check-token\s*[:\s]+", line, maxsplit=1)
                    if len(parts) == 2:
                        candidate = parts[1].strip()
                        m2 = re.match(r"([A-Za-z0-9_\-\.]+)", candidate)
                        if m2:
                            return m2.group(1)
    except Exception:
        pass
    return None


def main():
    # Try cache first
    token = get_from_cache()
    if token:
        print(token)
        return

    # Try flows file if provided or default name
    flows_file = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("flows.elevenlabsio")
    token = get_from_flows(flows_file)
    if token:
        # Also persist to extracted_tokens.json for reuse
        out = {"xi_app_check_token": token, "source": str(flows_file)}
        try:
            Path("extracted_tokens.json").write_text(json.dumps(out, indent=2))
        except Exception:
            pass
        print(token)
        return

    print("", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
