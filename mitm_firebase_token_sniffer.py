#!/usr/bin/env python3
# pyright: reportMissingImports=false
"""
mitm_firebase_token_sniffer.py
---------------------------------

mitmproxy inline script that watches ElevenLabs Reader traffic and dumps
Firebase refresh/access tokens whenever the mobile app authenticates.

Usage:
  mitmdump -q -s mitm_firebase_token_sniffer.py -w flows.elevenlabsio

The script appends JSON lines to tmp/firebase_tokens.jsonl with the tokens and
prints short previews to the mitmproxy event log. Point your iOS/Android device
at the proxy, sign into the ElevenLabs Reader app, then copy the refresh_token
from the output file for use with ./tts or api_server.py.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import parse_qs

from mitmproxy import ctx, http

TARGET_HOST_KEYWORDS = (
    "securetoken.googleapis.com",
    "identitytoolkit.googleapis.com",
    "firebasedynamiclinks.googleapis.com",
)


class FirebaseTokenSniffer:
    """mitmproxy addon that logs Firebase refresh/access tokens."""

    def __init__(self):
        self.output_path: Optional[Path] = None
        self.seen: set[tuple[Optional[str], Optional[str]]] = set()

    def load(self, loader):
        loader.add_option(
            "firebase_token_output",
            str,
            "tmp/firebase_tokens.jsonl",
            "File to append discovered Firebase tokens (JSON lines).",
        )

    def configure(self, updates):
        from mitmproxy import ctx

        output = Path(ctx.options.firebase_token_output).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        self.output_path = output

    def request(self, flow: "http.HTTPFlow"):
        self._maybe_capture(flow, source="request")

    def response(self, flow: "http.HTTPFlow"):
        self._maybe_capture(flow, source="response")

    def _maybe_capture(self, flow: http.HTTPFlow, source: str):
        host = (flow.request.pretty_host or "").lower()
        if not any(keyword in host for keyword in TARGET_HOST_KEYWORDS):
            return

        content_type = ""
        content = b""
        if source == "request":
            content_type = flow.request.headers.get("content-type", "")
            try:
                with flow.request.decoded():
                    content = flow.request.content or b""
            except Exception:
                content = flow.request.raw_content or b""
        else:
            if not flow.response:
                return
            content_type = flow.response.headers.get("content-type", "")
            try:
                with flow.response.decoded():
                    content = flow.response.content or b""
            except Exception:
                content = flow.response.raw_content or b""

        tokens = self._extract_tokens(content, content_type)
        if not tokens:
            return

        normalized = self._normalize(tokens)
        key = (normalized.get("refresh_token"), normalized.get("access_token"))
        if key in self.seen:
            return
        self.seen.add(key)

        payload = {
            "ts": time.time(),
            "source": source,
            "url": flow.request.pretty_url,
        }
        payload.update({k: v for k, v in normalized.items() if v})
        self._emit(payload)

    def _emit(self, payload: Dict[str, str]):
        from mitmproxy import ctx

        refresh_preview = payload.get("refresh_token", "")[:8]
        ctx.log.info(
            f"🔑 Firebase token captured ({payload['source']}): refresh={refresh_preview}… | "
            f"url={payload['url']}"
        )

        if self.output_path:
            with self.output_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload) + "\n")

    def _normalize(self, tokens: Dict[str, str]) -> Dict[str, Optional[str]]:
        mapping = {
            "refresh_token": ["refresh_token", "refreshToken"],
            "access_token": ["access_token", "accessToken"],
            "id_token": ["id_token", "idToken"],
            "expires_in": ["expires_in", "expiresIn"],
            "token_type": ["token_type", "tokenType"],
            "grant_type": ["grant_type", "grantType"],
        }
        normalized: Dict[str, Optional[str]] = {k: None for k in mapping}
        for target, keys in mapping.items():
            for candidate in keys:
                if candidate in tokens:
                    normalized[target] = tokens[candidate]
                    break
        return normalized

    def _extract_tokens(self, content: bytes, content_type: str) -> Dict[str, str]:
        if not content:
            return {}

        text = content.decode("utf-8", errors="ignore")

        # Try JSON first
        try:
            data = json.loads(text)
            return {k: str(v) for k, v in data.items() if "token" in k.lower() or k in {"expires_in", "expiresIn"}}
        except json.JSONDecodeError:
            pass

        # Fallback to form-encoded body
        if "application/x-www-form-urlencoded" in content_type.lower():
            params = parse_qs(text, keep_blank_values=False)
            flat: Dict[str, str] = {}
            for key, values in params.items():
                if not values:
                    continue
                if "token" in key.lower() or key in {"expires_in", "grant_type"}:
                    flat[key] = values[0]
            return flat

        return {}


addons = [FirebaseTokenSniffer()]

