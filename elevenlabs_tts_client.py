#!/usr/bin/env python3
"""
ElevenLabs TTS Client
Matches the captured network flows with Firebase auth and real-time streaming
"""

import argparse
import asyncio
import base64
import json
import logging
import ssl
import re
import html as html_module
import sys
import subprocess
import tempfile
import time
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Union, AsyncIterator
import uuid

import aiohttp
import websockets
from elevenlabs.client import ElevenLabs as ElevenLabsClient
from token_manager import TokenManager


class FirebaseAuth:
    """Handle Firebase authentication matching the captured flows"""

    def __init__(self, refresh_token: str, verbose: bool = False):
        self.refresh_token = refresh_token
        self.access_token: Optional[str] = None
        self.token_expires: Optional[datetime] = None
        self.api_key = "AIzaSyDhSxLJa_WaR8I69a1BmlUG7ckfZHu7-ig"  # From captured flows
        self.verbose = verbose
        self.logger = logging.getLogger("FirebaseAuth")

    async def get_access_token(self) -> str:
        """Get valid access token, refreshing if needed"""
        if (
            self.access_token
            and self.token_expires
            and datetime.now() < self.token_expires
        ):
            return self.access_token

        await self._refresh_token()
        return self.access_token

    async def _refresh_token(self):
        """Refresh Firebase token matching captured request"""
        url = f"https://securetoken.googleapis.com/v1/token?key={self.api_key}"

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "FirebaseAuth.iOS/11.14.0 io.elevenlabs.readerapp/1.4.45 iPhone/26.0 hw/iPhone16_2",
            "X-Client-Version": "iOS/FirebaseSDK/11.14.0/FirebaseCore-iOS",
            "X-iOS-Bundle-Identifier": "io.elevenlabs.readerapp",
            "Accept": "*/*",
            "Accept-Language": "en",
            "Accept-Encoding": "gzip, deflate, br",
        }

        payload = {"grantType": "refresh_token", "refreshToken": self.refresh_token}

        if self.verbose:
            self.logger.info(f"🔄 Refreshing Firebase token")
            self.logger.debug(f"Request URL: {url}")
            self.logger.debug(f"Request headers: {json.dumps(headers, indent=2)}")
            self.logger.debug(f"Request payload: {json.dumps({k: v[:20] + '...' if k == 'refreshToken' else v for k, v in payload.items()}, indent=2)}")

        # Configure aiohttp tracing if verbose
        trace_config = None
        if self.verbose:
            trace_config = aiohttp.TraceConfig()
            trace_config.on_request_start.append(self._on_request_start)
            trace_config.on_request_end.append(self._on_request_end)

        # Create SSL context to fix connection issues
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = True
        ssl_context.verify_mode = ssl.CERT_REQUIRED
        
        connector = aiohttp.TCPConnector(ssl=ssl_context, limit=100, limit_per_host=30)
        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        session_kwargs = {'connector': connector, 'timeout': timeout}
        if trace_config:
            session_kwargs['trace_configs'] = [trace_config]

        async with aiohttp.ClientSession(**session_kwargs) as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if self.verbose:
                    self.logger.debug(f"Response status: {response.status}")
                    self.logger.debug(f"Response headers: {dict(response.headers)}")
                
                if response.status == 200:
                    data = await response.json()
                    self.access_token = data["access_token"]
                    expires_in = int(data["expires_in"])
                    self.token_expires = datetime.now() + timedelta(
                        seconds=expires_in - 60
                    )  # Refresh 1 min early
                    
                    if self.verbose:
                        self.logger.info(f"✅ Firebase token refreshed successfully")
                        self.logger.debug(f"New token expires in {expires_in} seconds")
                        self.logger.debug(f"Token preview: {self.access_token[:50]}...")
                    else:
                        print(f"✓ Firebase token refreshed, expires in {expires_in} seconds")
                else:
                    error_text = await response.text()
                    if self.verbose:
                        self.logger.error(f"❌ Firebase auth failed: {response.status}")
                        self.logger.error(f"Error response: {error_text}")
                    raise Exception(f"Firebase auth failed: {response.status} {error_text}")

    async def _on_request_start(self, session, trace_config_ctx, params):
        """Log request start for verbose mode"""
        self.logger.debug(f"🚀 Starting request to {params.url}")
        self.logger.debug(f"Method: {params.method}")

    async def _on_request_end(self, session, trace_config_ctx, params):
        """Log request end for verbose mode"""
        self.logger.debug(f"✅ Request completed to {params.url}")
        self.logger.debug(f"Response status: {params.response.status}")


class ElevenLabsTTSClient:
    """ElevenLabs TTS client matching captured flows"""

    def __init__(self, bearer_token: str, verbose: bool = False, app_check_token: Optional[str] = None, device_id: Optional[str] = None):
        self.bearer_token = bearer_token
        self.device_id = (device_id or str(uuid.uuid4())).upper()
        self.app_check_token = app_check_token
        self.session_id = uuid.uuid4().hex
        self.verbose = verbose
        self.logger = logging.getLogger("ElevenLabsTTSClient")

        # Headers matching captured flows
        self.headers = {
            "Content-Type": "application/json",
            "User-Agent": "readerapp/405 CFNetwork/3860.100.1 Darwin/25.0.0",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "App-Version": "1.4.45",
            "Device-ID": self.device_id,
            "Language": "en",
            "User-Timezone": "America/Montevideo",
            "Priority": "u=3",
            "Baggage": "sentry-environment=Prod,sentry-public_key=142ef938ca18ce748094cb64c27596a8,sentry-release=io.elevenlabs.readerapp%401.4.45%2B404",
        }

        # Skip official SDK for Firebase Bearer tokens (they use different format)
        # Only use official SDK if token looks like a standard ElevenLabs API key
        if bearer_token.startswith('sk-') or bearer_token.startswith('el-'):
            try:
                self.official_client = ElevenLabsClient(api_key=bearer_token)
                if self.verbose:
                    self.logger.info("✅ Official ElevenLabs SDK client initialized")
            except Exception as e:
                if self.verbose:
                    self.logger.warning(f"⚠️ Failed to initialize official SDK: {e}")
                self.official_client = None
        else:
            # Firebase Bearer tokens need manual implementation
            self.official_client = None
            if self.verbose:
                self.logger.info("🔧 Using manual implementation for Firebase Bearer token")

    async def get_voices(self) -> list:
        """Get available voices from ElevenLabs"""
        url = "https://api.elevenlabs.io/v1/reader/voices"

        headers = self.headers.copy()
        headers["Authorization"] = f"Bearer {self.bearer_token}"

        if self.verbose:
            self.logger.info(f"🎭 Fetching voices from {url}")
            self.logger.debug(f"Request headers: {json.dumps({k: v[:20] + '...' if k == 'Authorization' else v for k, v in headers.items()}, indent=2)}")

        # Configure aiohttp tracing if verbose
        trace_config = None
        if self.verbose:
            trace_config = aiohttp.TraceConfig()
            trace_config.on_request_start.append(self._on_request_start)
            trace_config.on_request_end.append(self._on_request_end)

        # Create SSL context to fix connection issues
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = True
        ssl_context.verify_mode = ssl.CERT_REQUIRED
        
        connector = aiohttp.TCPConnector(ssl=ssl_context, limit=100, limit_per_host=30)
        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        session_kwargs = {'connector': connector, 'timeout': timeout}
        if trace_config:
            session_kwargs['trace_configs'] = [trace_config]

        async with aiohttp.ClientSession(**session_kwargs) as session:
            async with session.get(url, headers=headers) as response:
                if self.verbose:
                    self.logger.debug(f"Response status: {response.status}")
                    self.logger.debug(f"Response headers: {dict(response.headers)}")
                
                if response.status == 200:
                    data = await response.json()
                    if self.verbose:
                        voice_count = len(data.get('voices', []))
                        self.logger.info(f"✅ Successfully fetched {voice_count} voices")
                        self.logger.debug(f"Response data keys: {list(data.keys())}")
                    return data
                else:
                    error_text = await response.text()
                    if self.verbose:
                        self.logger.error(f"❌ Failed to get voices: {response.status}")
                        self.logger.error(f"Error response: {error_text}")
                    raise Exception(f"Failed to get voices: {response.status}")

    async def list_reads(self, updated_since_unix: int = 0) -> list:
        """List user's Reader documents (reads) via changes endpoint.

        Returns a list of read dicts (as returned by the API) sorted by updated_at.
        """
        url = f"https://api.elevenlabs.io/v1/reader/reads/changes?last_updated_at_unix={updated_since_unix}"

        headers = self.headers.copy()
        headers["Authorization"] = f"Bearer {self.bearer_token}"

        if self.verbose:
            self.logger.info(f"📚 Fetching user reads from {url}")

        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = True
        ssl_context.verify_mode = ssl.CERT_REQUIRED

        connector = aiohttp.TCPConnector(ssl=ssl_context, limit=100, limit_per_host=30)
        timeout = aiohttp.ClientTimeout(total=30, connect=10)

        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    reads = data.get("reads", []) or []
                    # Sort newest updated first if fields exist
                    try:
                        reads.sort(key=lambda r: r.get("updated_at_unix") or r.get("updated_at") or 0, reverse=True)
                    except Exception:
                        pass
                    if self.verbose:
                        self.logger.info(f"✅ Retrieved {len(reads)} reads")
                    return reads
                else:
                    txt = await response.text()
                    if self.verbose:
                        self.logger.error(f"❌ Failed to list reads: {response.status} {txt[:200]}")
                    raise Exception(f"Failed to list reads: {response.status}")

    async def get_read_simple_text(self, read_id: str) -> Optional[str]:
        """Fetch simple HTML for a read and convert to plain text.

        Uses: GET /v1/reader/reads/{read_id}/simple-html?make_pageable=false
        """
        url = f"https://api.elevenlabs.io/v1/reader/reads/{read_id}/simple-html?make_pageable=false"
        headers = self.headers.copy()
        headers["Authorization"] = f"Bearer {self.bearer_token}"

        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = True
        ssl_context.verify_mode = ssl.CERT_REQUIRED
        connector = aiohttp.TCPConnector(ssl=ssl_context, limit=100, limit_per_host=30)
        timeout = aiohttp.ClientTimeout(total=30, connect=10)

        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    html = await response.text()
                    # Strip tags and unescape entities for a readable preview
                    text = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", html, flags=re.I)
                    text = re.sub(r"<[^>]+>", " ", text)
                    text = html_module.unescape(text)
                    # Normalize whitespace
                    text = re.sub(r"\s+", " ", text).strip()
                    return text
                else:
                    return None

    class KaraokePreview:
        def __init__(self, text: str, before_words: int = 8, after_words: int = 8, in_place: bool = True):
            self.text = text or ""
            self.before = before_words
            self.after = after_words
            # Build word boundaries and char->word map
            self.words = []  # list of (start,end)
            self.char_to_word = [-1] * len(self.text)
            self._build_index()
            self._last_print = ""
            self._in_place = in_place
            self._last_len = 0
            self._ansi_gray = "\033[90m"
            self._ansi_white_bold = "\033[1;97m"
            self._ansi_reset = "\033[0m"

        def _build_index(self):
            idx = 0
            i = 0
            n = len(self.text)
            while i < n:
                # skip spaces
                while i < n and self.text[i].isspace():
                    i += 1
                if i >= n:
                    break
                start = i
                while i < n and not self.text[i].isspace():
                    i += 1
                end = i
                self.words.append((start, end))
                for j in range(start, end):
                    self.char_to_word[j] = idx
                idx += 1

        def _slice_for_word(self, widx: int) -> tuple[str, int, int]:
            if widx < 0 or widx >= len(self.words):
                return ("", -1, -1)
            start_idx = max(0, widx - self.before)
            end_idx = min(len(self.words) - 1, widx + self.after)
            seg_start = self.words[start_idx][0]
            seg_end = self.words[end_idx][1]
            segment = self.text[seg_start:seg_end]
            # compute highlight offsets relative to segment
            cur_start, cur_end = self.words[widx]
            rel_start = cur_start - seg_start
            rel_end = cur_end - seg_start
            return (segment, rel_start, rel_end)

        def render_at_char(self, abs_char_index: int):
            if abs_char_index < 0 or abs_char_index >= len(self.char_to_word):
                return
            widx = self.char_to_word[abs_char_index]
            if widx < 0:
                return
            segment, rel_start, rel_end = self._slice_for_word(widx)
            # Build a simple highlighted line using brackets
            line = segment[:rel_start] + "[" + segment[rel_start:rel_end] + "]" + segment[rel_end:]
            # Avoid spamming identical lines
            if line == self._last_print:
                return
            self._last_print = line
            # Print on its own line (stdout) prefixed tag
            self._emit(line)

        def render_block(self, chars: list[str], local_index: int, before_words: int = None, after_words: int = None):
            """Render a preview using only the current alignment block (no global mapping).

            Highlights the word containing local_index inside the block, and prints a
            window of a few words before/after for subtitle-like output.
            """
            if not chars:
                return
            block = ''.join(chars)
            n = len(block)
            if n == 0 or local_index < 0 or local_index >= len(chars):
                return
            # Build word boundaries for the block
            words = []  # list of (start,end)
            char_to_word = [-1] * n
            i = 0
            widx = 0
            while i < n:
                while i < n and block[i].isspace():
                    i += 1
                if i >= n:
                    break
                start = i
                while i < n and not block[i].isspace():
                    i += 1
                end = i
                words.append((start, end))
                for j in range(start, end):
                    char_to_word[j] = widx
                widx += 1
            # Determine current word index from local char index
            cur_word = -1
            # Map local_index (in chars list) to char position in block (same index)
            if 0 <= local_index < n:
                cur_word = char_to_word[local_index]
            if cur_word < 0:
                # Find nearest non-space to the right then left
                r = local_index
                while r < n and block[r].isspace():
                    r += 1
                if r < n:
                    cur_word = char_to_word[r]
                else:
                    l = local_index
                    while l >= 0 and block[l].isspace():
                        l -= 1
                    if l >= 0:
                        cur_word = char_to_word[l]
            if cur_word is None or cur_word < 0 or cur_word >= len(words):
                return
            bw = self.before if before_words is None else before_words
            aw = self.after if after_words is None else after_words
            start_w = max(0, cur_word - bw)
            end_w = min(len(words) - 1, cur_word + aw)
            seg_start = words[start_w][0]
            seg_end = words[end_w][1]
            segment = block[seg_start:seg_end]
            cur_start, cur_end = words[cur_word]
            rel_start = max(0, cur_start - seg_start)
            rel_end = max(rel_start, cur_end - seg_start)
            # Colorize: non-current text gray, current word bold white
            pre = segment[:rel_start]
            cur = segment[rel_start:rel_end]
            post = segment[rel_end:]
            colored = f"{self._ansi_gray}{pre}{self._ansi_reset}{self._ansi_white_bold}{cur}{self._ansi_reset}{self._ansi_gray}{post}{self._ansi_reset}"
            if colored == self._last_print:
                return
            self._last_print = colored
            self._emit(colored)

        def _emit(self, line: str):
            out = f"📝 {line}"
            if self._in_place:
                try:
                    import sys
                    # Carriage return to overwrite the same line
                    pad = max(0, self._last_len - self._visible_len(out))
                    sys.stdout.write("\r" + out + (" " * pad))
                    sys.stdout.flush()
                    self._last_len = self._visible_len(out)
                except Exception:
                    print(out, flush=True)
            else:
                print(out, flush=True)

        def _visible_len(self, s: str) -> int:
            import re
            # Strip ANSI escape sequences for length calculation
            return len(re.sub(r"\x1b\[[0-9;]*m", "", s))

    class KaraokeController:
        """Centralized, word-level karaoke ticker with chained anchors between blocks.

        - add_block(chars, starts_ms, durations_ms) enqueues a block with an anchor time
          chained after the previous block's end to ensure continuity (no gaps or overlaps).
        - A single ticker task updates the preview at ~30 Hz, computing the current word
          based on elapsed time relative to the block's anchor.
        """

        def __init__(self, preview: 'ElevenLabsTTSClient.KaraokePreview', tick_hz: int = 30):
            import asyncio
            self.preview = preview
            self.tick_dt = 1.0 / max(10, tick_hz)
            self.blocks = []  # list of dicts: {chars, starts, durs, anchor, duration}
            self._running = False
            self._task = None
            self._next_anchor = None
            self._lock = asyncio.Lock()
            self._stop_event = asyncio.Event()
            self._last_line_len = 0

        async def start(self):
            import asyncio
            if self._running:
                return
            self._running = True
            self._task = asyncio.create_task(self._run())

        async def stop(self):
            import asyncio
            self._running = False
            self._stop_event.set()
            if self._task:
                try:
                    await self._task
                except Exception:
                    pass

        async def add_block(self, chars: list, starts_ms: list, durs_ms: list):
            import asyncio
            # Normalize starts to begin at 0 for the block
            if starts_ms:
                first = starts_ms[0]
                starts = [(max(0, s - first)) / 1000.0 for s in starts_ms]
            else:
                starts = []
            # Compute duration from last start + duration; fallback to len(chars)*40ms
            if starts_ms and durs_ms:
                duration = max(0.0, (starts_ms[-1] - (starts_ms[0] if starts_ms else 0)) / 1000.0) + (durs_ms[-1] / 1000.0)
            else:
                duration = max(0.1, len(chars) * 0.04)
            # Chain anchor after the previous block end to prevent overlaps/gaps
            now = time.monotonic()
            if self._next_anchor is None:
                anchor = now
            else:
                anchor = max(now, self._next_anchor)
            # slight padding to absorb rounding jitter
            pad = 0.05
            self._next_anchor = anchor + duration + pad
            block = {
                'chars': chars or [],
                'starts': starts,
                'duration': duration,
                'anchor': anchor,
            }
            async with self._lock:
                self.blocks.append(block)

        async def _run(self):
            import asyncio
            last_word = -2
            cur_block_idx = 0
            while self._running:
                # Exit if requested
                if self._stop_event.is_set() and cur_block_idx >= len(self.blocks):
                    break
                # Get current block
                async with self._lock:
                    if cur_block_idx < len(self.blocks):
                        blk = self.blocks[cur_block_idx]
                    else:
                        blk = None
                if blk is None:
                    # No blocks yet; wait a tick
                    try:
                        await asyncio.wait_for(self._stop_event.wait(), timeout=self.tick_dt)
                    except asyncio.TimeoutError:
                        pass
                    continue
                # Compute elapsed
                now = time.monotonic()
                elapsed = now - blk['anchor']
                # If before start, wait a tick
                if elapsed < 0:
                    await asyncio.sleep(min(self.tick_dt, max(0.0, -elapsed)))
                    continue
                chars = blk['chars']
                starts = blk['starts']
                # Initial render if required
                if elapsed < 0.02:
                    if chars:
                        self.preview.render_block(chars, 0)
                    else:
                        # nothing to do without chars; skip
                        pass
                # Determine current char index i for elapsed
                i = 0
                if starts:
                    # Linear scan is fine (blocks are ~10-16s); could bisect
                    while i + 1 < len(starts) and starts[i + 1] <= elapsed:
                        i += 1
                # Render only if word changed
                if chars:
                    # Build a simple word boundary around i
                    block_str = ''.join(chars)
                    # Find word index by scanning left/right
                    # Quick heuristic: find nearest non-space at/after i
                    j = min(i, len(block_str) - 1)
                    while j < len(block_str) and block_str[j].isspace():
                        j += 1
                    if j >= len(block_str):
                        j = i
                        while j >= 0 and block_str[j].isspace():
                            j -= 1
                    # Compute word index by counting spaces up to j
                    # (This is approximate but stable for preview)
                    w = 0
                    k = 0
                    in_word = False
                    while k <= j and k < len(block_str):
                        if not block_str[k].isspace():
                            if not in_word:
                                in_word = True
                                if k != 0:
                                    w += 1
                        else:
                            in_word = False
                        k += 1
                    if w != last_word:
                        self.preview.render_block(chars, i)
                        last_word = w
                # Advance to next block if done
                if elapsed >= blk['duration']:
                    cur_block_idx += 1
                    last_word = -2
                    continue
                await asyncio.sleep(self.tick_dt)

    async def _animate_alignment(self, preview, block_start_abs: int, alignment: dict):
        try:
            starts = alignment.get("charStartTimesMs") or []
            durs = alignment.get("charDurationsMs") or []
            chars = alignment.get("chars") or []
            n = len(chars)
            # Build a local char->word map for fewer updates (word-level)
            char_to_word = []
            if chars:
                block_str = ''.join(chars)
                char_to_word = [-1] * len(block_str)
                widx = 0
                i = 0
                while i < len(block_str):
                    while i < len(block_str) and block_str[i].isspace():
                        i += 1
                    if i >= len(block_str):
                        break
                    ws = i
                    while i < len(block_str) and not block_str[i].isspace():
                        i += 1
                    we = i
                    for j in range(ws, we):
                        char_to_word[j] = widx
                    widx += 1
            if not starts:
                # Fallback: step through chars at a constant small delay
                step = 0.03
                for i in range(n):
                    preview.render_block(chars, i)
                    await asyncio.sleep(step)
                return
            # Normalize timeline so first char shows immediately (no long initial gap)
            first = starts[0] if starts else 0
            anchor = time.monotonic()
            # Show initial position right away for immediate feedback
            preview.render_block(chars, 0) if chars else preview.render_at_char(block_start_abs)
            last_word = -2
            for i, tms in enumerate(starts):
                tnorm = max(0.0, (tms - first) / 1000.0)
                target = anchor + tnorm
                now = time.monotonic()
                delay = target - now
                if delay > 0:
                    await asyncio.sleep(delay)
                if chars:
                    # Reduce noise: advance only when word changes
                    w = char_to_word[i] if char_to_word else i
                    if w != last_word and w is not None:
                        preview.render_block(chars, i)
                        last_word = w
                else:
                    preview.render_at_char(block_start_abs + i)
        except Exception:
            return

    async def _on_request_start(self, session, trace_config_ctx, params):
        """Log request start for verbose mode"""
        self.logger.debug(f"🚀 Starting request to {params.url}")
        self.logger.debug(f"Method: {params.method}")

    async def _on_request_end(self, session, trace_config_ctx, params):
        """Log request end for verbose mode"""
        self.logger.debug(f"✅ Request completed to {params.url}")
        self.logger.debug(f"Response status: {params.response.status}")

    async def create_read_content(self, text: str) -> Optional[str]:
        """Create read content and return read_id for streaming - uses correct endpoint"""
        # Use the working endpoint discovered from flow analysis
        return await self._create_read_document(text)

    async def stream_with_websocket(
        self,
        text: str = None,
        voice_id: str = None,
        output_file: Optional[str] = None,
        play_audio: bool = False,
        method: str = "reader",
        read_id: str = None,
        position: int = 0,
        save_chunks: bool = False
        , show_karaoke: bool = False, karaoke_before: int = 8, karaoke_after: int = 8) -> Optional[bytes]:
        """Stream TTS using various methods, defaulting to free Reader WebSocket streaming"""
        
        # Handle read_id streaming (bypass document creation)
        if read_id:
            print(f"🎤 Streaming from existing document {read_id} with voice {voice_id}")
            return await self._stream_existing_read_id(
                read_id, voice_id, output_file, play_audio, position, save_chunks,
                show_karaoke=show_karaoke, karaoke_before=karaoke_before, karaoke_after=karaoke_after
            )
        
        # Handle text streaming (requires document creation for reader method)
        print(f"🎤 Streaming '{text[:50]}...' with voice {voice_id}")

        if method == "reader":
            # Default: Use Reader app WebSocket streaming (FREE method from flows analysis)
            try:
                return await self._stream_reader_websocket_flows(
                    text, voice_id, output_file, play_audio,
                    show_karaoke=show_karaoke, karaoke_before=karaoke_before, karaoke_after=karaoke_after
                )
            except Exception as e:
                print(f"❌ Reader WebSocket streaming failed: {e}")
                return None
                
        elif method == "http":
            # HTTP streaming using official API
            try:
                return await self._stream_http_direct(
                    text, voice_id, output_file, play_audio
                )
            except Exception as e:
                print(f"❌ HTTP streaming failed: {e}")
                return None
                
        elif method == "websocket":
            # Direct WebSocket streaming using official API
            try:
                return await self._stream_direct_websocket(
                    text, voice_id, output_file, play_audio
                )
            except Exception as e:
                print(f"❌ Direct WebSocket streaming failed: {e}")
                return None
                
        elif method == "auto":
            # Auto mode: Try all methods in order of preference
            methods_to_try = [
                ("reader", "Reader WebSocket (FREE)", self._stream_reader_websocket_flows),
                ("http", "HTTP streaming", self._stream_http_direct),
                ("websocket", "Direct WebSocket", self._stream_direct_websocket)
            ]
            
            for method_name, method_desc, method_func in methods_to_try:
                try:
                    print(f"🔧 Trying {method_desc}...")
                    return await method_func(text, voice_id, output_file, play_audio)
                except Exception as e:
                    print(f"❌ {method_desc} failed: {e}")
                    continue
            
            print("❌ All streaming methods failed")
            return None
        else:
            print(f"❌ Unknown streaming method: {method}")
            print("Available methods: reader, http, websocket, auto")
            return None

    async def _stream_with_official_sdk(
        self,
        text: str,
        voice_id: str,
        output_file: Optional[str] = None,
        play_audio: bool = False,
    ) -> Optional[bytes]:
        """Use official ElevenLabs SDK for streaming"""
        print("📡 Using official ElevenLabs SDK for streaming...")

        # Generate audio stream
        audio_stream = self.official_client.text_to_speech.stream(
            text=text, voice_id=voice_id, model_id="eleven_multilingual_v2"
        )

        audio_data = b""

        # Collect audio chunks
        for chunk in audio_stream:
            audio_data += chunk
            print(".", end="", flush=True)

        print(f"\n✓ Generated {len(audio_data)} bytes of audio")

        # Handle output
        if output_file:
            with open(output_file, "wb") as f:
                f.write(audio_data)
            print(f"💾 Saved audio to {output_file}")

        if play_audio:
            await self._play_audio(audio_data)

        return audio_data

    async def _stream_http_direct(
        self,
        text: str,
        voice_id: str,
        output_file: Optional[str] = None,
        play_audio: bool = False,
    ) -> Optional[bytes]:
        """HTTP streaming using official API with Reader headers"""
        if self.verbose:
            self.logger.info("🔧 Using HTTP streaming with Reader headers...")
        else:
            print("🔧 Using HTTP streaming...")

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"

        headers = self.headers.copy()
        headers["Authorization"] = f"Bearer {self.bearer_token}"

        payload = {
            "text": text,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.8},
            "model_id": "eleven_multilingual_v2",
        }

        if self.verbose:
            self.logger.info(f"🌐 Making HTTP request to: {url}")
            self.logger.debug(f"Request headers: {json.dumps({k: v[:20] + '...' if k == 'Authorization' else v for k, v in headers.items()}, indent=2)}")
            self.logger.debug(f"Request payload: {json.dumps(payload, indent=2)}")

        # Configure aiohttp session
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = True
        ssl_context.verify_mode = ssl.CERT_REQUIRED
        
        connector = aiohttp.TCPConnector(ssl=ssl_context, limit=100, limit_per_host=30)
        timeout = aiohttp.ClientTimeout(total=120, connect=10)  # Longer timeout for streaming

        # Start real-time audio player if requested
        realtime_player = None
        player_name = None
        if play_audio:
            realtime_player, player_name = self._start_realtime_player()

        try:
            async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                async with session.post(url, headers=headers, json=payload) as response:
                    if self.verbose:
                        self.logger.debug(f"Response status: {response.status}")
                        self.logger.debug(f"Response headers: {dict(response.headers)}")
                    
                    if response.status == 200:
                        audio_data = b""
                        chunk_count = 0
                        
                        if self.verbose:
                            self.logger.info("🎧 Starting to receive audio stream...")
                        else:
                            print("🎧 Receiving audio stream", end="", flush=True)
                        
                        async for chunk in response.content.iter_chunked(8192):
                            audio_data += chunk
                            chunk_count += 1
                            
                            # Stream chunk to real-time player immediately
                            if realtime_player:
                                if not self._stream_audio_chunk_to_player(realtime_player, chunk):
                                    print(f"\n❌ Real-time audio streaming stopped")
                                    realtime_player = None
                                    player_name = None
                            
                            if self.verbose:
                                self.logger.debug(f"Audio chunk {chunk_count}: {len(chunk)} bytes (total: {len(audio_data)} bytes)")
                            else:
                                print(".", end="", flush=True)
                        
                        if not self.verbose:
                            print()  # New line after dots
                        
                        if self.verbose:
                            self.logger.info(f"🎵 HTTP streaming complete: {len(audio_data)} bytes in {chunk_count} chunks")
                        else:
                            print(f"✓ Generated {len(audio_data)} bytes of audio")

                        # Stop real-time player if active
                        if realtime_player:
                            self._stop_realtime_player(realtime_player)

                        # Handle output
                        if output_file:
                            with open(output_file, "wb") as f:
                                f.write(audio_data)
                            print(f"💾 Saved audio to {output_file}")

                        # If real-time player was not started, optionally play at end
                        if play_audio and not player_name:
                            await self._play_audio(audio_data)

                        return audio_data
                    else:
                        error_text = await response.text()
                        if self.verbose:
                            self.logger.error(f"❌ HTTP streaming failed: {response.status}")
                            self.logger.error(f"Error response: {error_text}")
                        raise Exception(f"HTTP streaming failed: {response.status} {error_text}")

        except Exception as e:
            if self.verbose:
                self.logger.error(f"❌ HTTP streaming error: {e}")
            raise

    async def _stream_direct_websocket(
        self,
        text: str,
        voice_id: str,
        output_file: Optional[str] = None,
        play_audio: bool = False,
    ) -> Optional[bytes]:
        """WebSocket streaming - falls back to HTTP when using Firebase tokens"""
        if self.verbose:
            self.logger.info("🔧 WebSocket method with Firebase tokens - using HTTP streaming...")
        else:
            print("🔧 WebSocket method detected Firebase token - using HTTP streaming...")

        # Firebase tokens don't work with official WebSocket API
        # Fall back to HTTP streaming which works with Firebase tokens
        return await self._stream_http_direct(text, voice_id, output_file, play_audio)

    async def _stream_reader_websocket_flows(
        self,
        text: str,
        voice_id: str,
        output_file: Optional[str] = None,
        play_audio: bool = False,
        show_karaoke: bool = False,
        karaoke_before: int = 8,
        karaoke_after: int = 8,
    ) -> Optional[bytes]:
        """Stream TTS using exact Reader app WebSocket protocol discovered from flows (FREE METHOD)"""
        if self.verbose:
            self.logger.info("🎭 Using exact Reader app WebSocket protocol from flows analysis...")
        else:
            print("🎭 Using Reader app WebSocket streaming (FREE method)...")

        # Step 1: Create a read document first (required for Reader WebSocket streaming)
        try:
            read_id = await self._create_read_document(text)
            if not read_id:
                raise Exception("Failed to create read document")
        except Exception as e:
            if self.verbose:
                self.logger.error(f"❌ Failed to create read document: {e}")
            else:
                print(f"❌ Failed to create read document: {e}")
            raise

        # Wait until the document is ready based on flow behavior
        try:
            await self._wait_for_document_processing(read_id, max_wait_time=90)
        except Exception as e:
            if self.verbose:
                self.logger.warning(f"⚠️ Read readiness check encountered an issue: {e}; proceeding to try streaming")
            else:
                print(f"\n⚠️ Read readiness check issue: {e}. Trying to stream anyway...")

        # Step 2: Inform backend which voice will be used (mirrors app PATCH behavior)
        try:
            await self._prepare_read_for_streaming(read_id, voice_id)
        except Exception as e:
            if self.verbose:
                self.logger.warning(f"⚠️ Failed to PATCH read before streaming: {e}")

        # Step 3: Connect to Reader WebSocket with the read_id
        ws_url = f"wss://api.elevenlabs.io/v1/reader/reads/stream/{read_id}?voice_id={voice_id}"

        headers = {
            "Authorization": f"Bearer {self.bearer_token}",
            "User-Agent": self.headers["User-Agent"],
            "accept": "*/*",
            "accept-language": "en-US,en;q=0.9",
            "accept-encoding": "gzip, deflate",
            "device-id": self.device_id,
            "Origin": "https://elevenlabs.io",
        }
        if self.app_check_token:
            headers["xi-app-check-token"] = self.app_check_token

        if self.verbose:
            self.logger.info(f"🌐 Connecting to Reader WebSocket: {ws_url}")
            auth_preview = (self.bearer_token[:20] + '...') if self.bearer_token else 'None'
            self.logger.debug(f"Authorization (preview): Bearer {auth_preview}")
            self.logger.debug(f"WS extra headers: { {k: v for k,v in headers.items() if k != 'Authorization'} }")

        audio_data = b""
        chunk_count = 0
        stream_id = str(uuid.uuid4()).upper()
        
        # Start real-time audio player if needed
        realtime_player = None
        player_name = None
        if play_audio:
            realtime_player, player_name = self._start_realtime_player()

        # Prepare karaoke preview if requested
        preview = None
        if show_karaoke:
            try:
                text = await self.get_read_simple_text(read_id)
                if text:
                    preview = self.KaraokePreview(text, before_words=karaoke_before, after_words=karaoke_after)
                    if self.verbose:
                        self.logger.info("📝 Karaoke preview enabled")
            except Exception as e:
                if self.verbose:
                    self.logger.warning(f"⚠️ Failed to fetch simple text for karaoke: {e}")

        # Reuse the complete-document streamer for consistent alignment/karaoke
        try:
            if self.verbose:
                self.logger.info("🎧 Streaming complete document...")
            else:
                print("🎧 Streaming document", end="", flush=True)

            audio_data = await self._stream_complete_document(
                read_id, voice_id, headers, output_file, play_audio,
                save_chunks=False, realtime_player=realtime_player, position=0, preview=preview
            )

            # Common completion handling
            if not self.verbose:
                print()  # New line after dots
            else:
                self.logger.info(f"🎵 Complete document streaming finished: {len(audio_data)} bytes")

            # Stop real-time player
            if realtime_player:
                self._stop_realtime_player(realtime_player)

            # Handle output
            if output_file:
                with open(output_file, "wb") as f:
                    f.write(audio_data)
                print(f"💾 Saved audio to {output_file}")

            return audio_data
        except Exception as e:
            if self.verbose:
                self.logger.error(f"❌ Reader streaming error: {e}")
            raise

    async def _prepare_read_for_streaming(self, read_id: str, voice_id: str):
        """PATCH the read with voice context to mirror app behavior before streaming."""
        url = f"https://api.elevenlabs.io/v1/reader/reads/{read_id}"
        headers = self.headers.copy()
        headers["Authorization"] = f"Bearer {self.bearer_token}"
        payload = {
            "last_used_voice_id": voice_id,
            "last_listened_char_offset": 0,
        }

        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = True
        ssl_context.verify_mode = ssl.CERT_REQUIRED

        connector = aiohttp.TCPConnector(ssl=ssl_context, limit=100, limit_per_host=30)
        timeout = aiohttp.ClientTimeout(total=15, connect=10)

        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            async with session.patch(url, headers=headers, json=payload) as response:
                if response.status != 200:
                    text = await response.text()
                    raise Exception(f"PATCH {url} failed: {response.status} {text[:200]}")

    async def _update_reading_position(self, read_id: str, position: int):
        """Update reading position via PATCH request between WebSocket connections"""
        url = f"https://api.elevenlabs.io/v1/reader/reads/{read_id}"
        headers = self.headers.copy()
        headers["Authorization"] = f"Bearer {self.bearer_token}"
        payload = {
            "last_listened_char_offset": position,
            "marked_as_unread": False
        }

        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = True
        ssl_context.verify_mode = ssl.CERT_REQUIRED
        connector = aiohttp.TCPConnector(ssl=ssl_context, limit=100, limit_per_host=30)
        timeout = aiohttp.ClientTimeout(total=15, connect=10)

        try:
            async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                async with session.patch(url, headers=headers, json=payload) as response:
                    if response.status == 200:
                        if self.verbose:
                            self.logger.debug(f"🔄 Updated reading position to {position}")
                    else:
                        text = await response.text()
                        if self.verbose:
                            self.logger.warning(f"⚠️ Failed to update reading position: {response.status} {text[:200]}")
        except Exception as e:
            if self.verbose:
                self.logger.warning(f"⚠️ Failed to update reading position: {e}")

    async def _get_read_char_count(self, read_id: str) -> Optional[int]:
        """Fetch the document's total character count to know when to stop reconnecting."""
        url = f"https://api.elevenlabs.io/v1/reader/reads/{read_id}"
        headers = self.headers.copy()
        headers["Authorization"] = f"Bearer {self.bearer_token}"

        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = True
        ssl_context.verify_mode = ssl.CERT_REQUIRED
        connector = aiohttp.TCPConnector(ssl=ssl_context, limit=100, limit_per_host=30)
        timeout = aiohttp.ClientTimeout(total=15, connect=10)

        try:
            async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                async with session.get(url, headers=headers) as response:
                    if response.status != 200:
                        return None
                    data = await response.json()
                    # Try common locations for char count
                    char_count = (
                        data.get("char_count")
                        or (data.get("chapters") or [{}])[0].get("char_count")
                        or data.get("word_count")  # fallback proxy if needed
                    )
                    try:
                        return int(char_count) if char_count is not None else None
                    except Exception:
                        return None
        except Exception:
            return None

    async def _stream_complete_document(self, read_id: str, voice_id: str, headers: dict,
                                       output_file: str, play_audio: bool, save_chunks: bool,
                                       realtime_player, position: int = 0, preview: Optional[object] = None) -> bytes:
        """Stream complete document using multi-connection pattern from flow analysis"""
        audio_data = b""
        chunk_count = 0
        current_position = position  # absolute char offset for next WS
        abs_char_pos = position      # durable absolute progress already played
        ws_url = f"wss://api.elevenlabs.io/v1/reader/reads/stream/{read_id}?voice_id={voice_id}"
        connection_number = 1
        
        # Backoff for abnormal closes
        base_backoff = 0.5
        max_backoff = 10.0
        backoff = base_backoff

        # Karaoke controller (single ticker) if preview enabled
        controller = None
        if preview:
            controller = self.KaraokeController(preview)
            await controller.start()

        # Determine document length (when available) to know when to stop
        total_chars = await self._get_read_char_count(read_id)
        if self.verbose:
            self.logger.debug(f"📏 Document length (chars): {total_chars}")

        while True:
            if self.verbose:
                self.logger.info(f"📤 Starting WebSocket connection #{connection_number} from position {current_position}")
            
            connection_chunk_count = 0
            cumulative_chars_in_connection = 0  # Sum of alignment chars in this connection
            accepted_blocks = 0
            dropped_blocks = 0
            last_reported_position = abs_char_pos
            # Server may close each connection with isFinal=true for that segment; not end-of-document.

            # Natural rollover controls
            BUDGET_TARGET = 1348  # observed per-connection size in flows
            HARD_CAP = 1600       # safety cap if no separator appears
            budget_reached = False
            separators_seen = 0
            idle_timeout = 1.5  # seconds without messages → rollover if we already streamed something
            
            try:
                async with websockets.connect(ws_url, additional_headers=headers, ping_timeout=300) as websocket:
                    message = {"stream_id": str(uuid.uuid4()).upper(), "position": current_position}
                    await websocket.send(json.dumps(message))
                    
                    if self.verbose:
                        self.logger.info(f"📤 Sent stream request for position {current_position}")
                    
                    # Stream all chunks from this WebSocket connection with idle-based rollover
                    while True:
                        try:
                            msg = await asyncio.wait_for(websocket.recv(), timeout=idle_timeout)
                        except asyncio.TimeoutError:
                            # If we already streamed some aligned content on this connection, rollover to reduce gaps
                            if cumulative_chars_in_connection > 0 and not budget_reached:
                                if self.verbose:
                                    self.logger.info(f"⏱️ Idle {idle_timeout}s with data this connection → rollover")
                                break
                            # No data yet; continue waiting
                            continue
                        try:
                            data = json.loads(msg)
                            have_audio = ("audio" in data and data["audio"]) or False
                            alignment = data.get("alignment")

                            # Decode audio if present (may be dropped later by gating)
                            chunk = await self._b64decode_async(data["audio"]) if have_audio else b""

                            # Separator detection: alignment explicitly null
                            is_separator = have_audio and (alignment is None)
                            if is_separator:
                                separators_seen += 1

                            # Character count for aligned blocks
                            seg_count = 0
                            if isinstance(alignment, dict) and alignment is not None and "chars" in alignment:
                                seg_count = len(alignment["chars"]) or 0

                            # Compute absolute block range
                            block_start = current_position + cumulative_chars_in_connection
                            block_end = block_start + seg_count

                            # Update cumulative chars regardless of gating
                            if seg_count > 0:
                                cumulative_chars_in_connection += seg_count
                                if self.verbose:
                                    self.logger.debug(
                                        f"🎯 Block {connection_chunk_count+1}: [{block_start}, {block_end}) +{seg_count} (conn_total={cumulative_chars_in_connection})"
                                    )
                                if not budget_reached and cumulative_chars_in_connection >= BUDGET_TARGET:
                                    budget_reached = True

                            # Duplicate-free gating: drop whole overlapped aligned blocks
                            accept_audio = True
                            if seg_count > 0:
                                if block_end <= abs_char_pos:
                                    accept_audio = False
                                elif block_start < abs_char_pos < block_end:
                                    accept_audio = False

                            # Add karaoke block ONLY for accepted audio
                            if controller and isinstance(alignment, dict) and alignment is not None and seg_count > 0 and have_audio and accept_audio:
                                try:
                                    await controller.add_block(
                                        alignment.get("chars") or [],
                                        alignment.get("charStartTimesMs") or [],
                                        alignment.get("charDurationsMs") or [],
                                    )
                                except Exception:
                                    pass

                            # Pipe audio if accepted
                            if have_audio and accept_audio:
                                audio_data += chunk
                                chunk_count += 1
                                connection_chunk_count += 1
                                accepted_blocks += 1
                                if save_chunks:
                                    chunk_filename = f"chunk_{chunk_count:03d}_{read_id}_conn{connection_number}_pos{current_position}.mp3"
                                    await self._save_chunk_async(chunk_filename, chunk)
                                    if self.verbose:
                                        self.logger.debug(f"💾 Saved chunk {chunk_count} to {chunk_filename}")
                                if realtime_player:
                                    if not await self._stream_audio_chunk_to_player_async(realtime_player, chunk):
                                        print(f"\n❌ Real-time audio streaming stopped")
                                        realtime_player = None
                                if self.verbose:
                                    self.logger.debug(f"Audio chunk {chunk_count}: {len(chunk)} bytes (total: {len(audio_data)} bytes)")
                                else:
                                    if not preview:
                                        print(".", end="", flush=True)
                                # Let the event loop run scheduled tasks
                                await asyncio.sleep(0)
                            else:
                                if self.verbose and have_audio and not accept_audio:
                                    self.logger.debug(f"🚫 Dropped overlapped block audio [{block_start}, {block_end}) vs abs_pos={abs_char_pos}")
                                if seg_count > 0:
                                    dropped_blocks += 1

                            # Advance durable position after aligned blocks
                            if seg_count > 0 and accept_audio:
                                abs_char_pos = max(abs_char_pos, block_end)
                                if abs_char_pos > last_reported_position:
                                    try:
                                        await self._update_reading_position(read_id, abs_char_pos)
                                        last_reported_position = abs_char_pos
                                    except Exception as e:
                                        if self.verbose:
                                            self.logger.debug(f"PATCH progress failed (non-fatal): {e}")

                            # Rollover immediately once budget is reached (prevents premature EOS on server)
                            if cumulative_chars_in_connection >= BUDGET_TARGET and not data.get("isFinal", False):
                                if self.verbose:
                                    self.logger.info(
                                        f"🔁 Rollover at budget → next position {current_position + cumulative_chars_in_connection}"
                                    )
                                break

                            # Server signals end of THIS WS stream with isFinal; we reconnect to continue.
                            if data.get("isFinal", False):
                                if self.verbose:
                                    self.logger.info("🏁 Received isFinal=true for this connection")
                                break
                                
                        except json.JSONDecodeError:
                            # Handle potential binary messages
                            if isinstance(msg, bytes):
                                audio_data += msg
                                chunk_count += 1
                                connection_chunk_count += 1
                                if self.verbose:
                                    self.logger.debug(f"Binary chunk {chunk_count}: {len(msg)} bytes")
                                else:
                                    print(".", end="", flush=True)
                    
                    # Connection ended naturally
                    if self.verbose:
                        self.logger.info(
                            f"📋 Connection #{connection_number} ended with {connection_chunk_count} chunks | conn_chars={cumulative_chars_in_connection} | abs_pos={abs_char_pos} | accepted_blocks={accepted_blocks} dropped_blocks={dropped_blocks}"
                        )

                    # Reset backoff after a healthy connection
                    backoff = base_backoff
            
            except Exception as e:
                if self.verbose:
                    self.logger.error(f"❌ WebSocket error on connection #{connection_number} at position {current_position}: {e}")
                    self.logger.info(f"⏳ Backing off {backoff:.1f}s before reconnect")
                await asyncio.sleep(backoff + random.uniform(0, 0.25))
                backoff = min(max_backoff, backoff * 2)
                # retry same connection number and current position
                continue
            
            # Determine next position strictly from actually played content
            next_position = abs_char_pos
            if self.verbose:
                self.logger.debug(f"🎯 Next connection will start at position {next_position}")
            
            # If no next position found or no progress, decide whether to stop
            if next_position is None or next_position <= current_position:
                # If we know total size and we've reached/passed it, we are done
                if total_chars is not None and abs_char_pos >= total_chars:
                    if self.verbose:
                        self.logger.info("🎉 Document streaming complete (reached total char count)")
                    break
                if self.verbose:
                    self.logger.warning(f"🏁 No valid next position found (last: {next_position}, current: {current_position}), ending stream")
                break
            
            # If we know total size and next_position already covers it, stop
            if total_chars is not None and next_position >= total_chars:
                await self._update_reading_position(read_id, total_chars)
                if self.verbose:
                    self.logger.info("🎉 Document streaming complete (next position >= total)")
                break

            # Update reading position via PATCH request (like the real app does)
            await self._update_reading_position(read_id, next_position)
            
            # Continue with next WebSocket connection
            current_position = next_position
            abs_char_pos = max(abs_char_pos, current_position)
            connection_number += 1
        # Attempt to end karaoke worker gracefully
        try:
            if karaoke_queue:
                await karaoke_queue.put(None)
        except Exception:
            pass
        # Stop karaoke controller
        if controller:
            try:
                await controller.stop()
            except Exception:
                pass
        
        return audio_data

    async def _stream_existing_read_id(
        self,
        read_id: str,
        voice_id: str,
        output_file: Optional[str] = None,
        play_audio: bool = False,
        position: int = 0,
        save_chunks: bool = False,
        show_karaoke: bool = False,
        karaoke_before: int = 8,
        karaoke_after: int = 8,
    ) -> Optional[bytes]:
        """Stream from existing read_id directly (like flows show)"""
        if self.verbose:
            self.logger.info(f"🎭 Streaming directly from existing read_id: {read_id}")
        else:
            print(f"🎭 Streaming from existing document: {read_id}")

        # Connect directly to WebSocket with existing read_id (no document creation needed)
        ws_url = f"wss://api.elevenlabs.io/v1/reader/reads/stream/{read_id}?voice_id={voice_id}"

        headers = {
            "Authorization": f"Bearer {self.bearer_token}",
            "User-Agent": self.headers["User-Agent"],
            "accept": "*/*",
            "accept-language": "en-US,en;q=0.9",
            "accept-encoding": "gzip, deflate",
            "device-id": self.device_id,
            "Origin": "https://elevenlabs.io",
        }
        if self.app_check_token:
            headers["xi-app-check-token"] = self.app_check_token

        if self.verbose:
            self.logger.info(f"🌐 Connecting to existing read WebSocket: {ws_url}")
            auth_preview = (self.bearer_token[:20] + '...') if self.bearer_token else 'None'
            self.logger.debug(f"Authorization (preview): Bearer {auth_preview}")

        # Reset reading position before streaming (like web app does)
        try:
            await self._prepare_read_for_streaming(read_id, voice_id)
            if self.verbose:
                self.logger.info("🔄 Reset document reading position to beginning")
        except Exception as e:
            if self.verbose:
                self.logger.warning(f"⚠️ Failed to reset reading position: {e}")

        audio_data = b""
        chunk_count = 0
        stream_id = str(uuid.uuid4()).upper()
        current_position = position
        
        # Start real-time audio player if needed
        realtime_player = None
        player_name = None
        if play_audio:
            realtime_player, player_name = self._start_realtime_player()

        # Prepare karaoke preview if requested
        preview = None
        if show_karaoke:
            try:
                text = await self.get_read_simple_text(read_id)
                if text:
                    preview = self.KaraokePreview(text, before_words=karaoke_before, after_words=karaoke_after)
                    if self.verbose:
                        self.logger.info("📝 Karaoke preview enabled")
            except Exception as e:
                if self.verbose:
                    self.logger.warning(f"⚠️ Failed to fetch simple text for karaoke: {e}")

        # Use the complete document streaming method
        try:
            if self.verbose:
                self.logger.info("🎧 Streaming complete document...")
            else:
                print("🎧 Streaming document", end="", flush=True)
                
            audio_data = await self._stream_complete_document(
                read_id, voice_id, headers, output_file, play_audio, 
                save_chunks, realtime_player, current_position, preview
            )
            
            # Common completion handling
            if not self.verbose:
                print()  # New line after dots
            else:
                self.logger.info(f"🎵 Complete document streaming finished: {len(audio_data)} bytes")

            # Stop real-time player
            if realtime_player:
                self._stop_realtime_player(realtime_player)

            # Handle output
            if output_file:
                with open(output_file, "wb") as f:
                    f.write(audio_data)
                print(f"💾 Saved audio to {output_file}")

            return audio_data

        except Exception as e:
            if self.verbose:
                self.logger.error(f"❌ Existing read streaming error: {e}")
            print(f"❌ Failed to stream from existing document: {e}")
            raise

    async def _create_read_document(self, text: str) -> Optional[str]:
        """Create a read document for Reader WebSocket streaming (required step)"""
        url = "https://api.elevenlabs.io/v1/reader/reads/add/v2"
        
        headers = self.headers.copy()
        headers["Authorization"] = f"Bearer {self.bearer_token}"
        headers["Content-Type"] = "multipart/form-data; boundary=XI-COOL-BOUNDARY"
        
        # Use multipart form data exactly as discovered in flows
        boundary = "XI-COOL-BOUNDARY"
        # The mobile app uploads the content as a file part named 'from_document'
        title = f"Generated Read {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        form_data = (
            f"--{boundary}\r\n"
            f"Content-Disposition: form-data; name=\"source\"\r\n\r\n"
            f"text\r\n"
            f"--{boundary}\r\n"
            f"Content-Disposition: form-data; name=\"title\"\r\n\r\n"
            f"{title}\r\n"
            f"--{boundary}\r\n"
            f"Content-Disposition: form-data; name=\"from_document\"; filename=\"generated.txt\"\r\n"
            f"Content-Type: text/plain\r\n\r\n"
            f"{text}\r\n"
            f"--{boundary}--\r\n"
        ).encode('utf-8')
        
        if self.verbose:
            self.logger.info(f"📄 Creating read document: {len(text)} characters")
            self.logger.debug(f"Request URL: {url}")
        
        # Configure aiohttp session
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = True
        ssl_context.verify_mode = ssl.CERT_REQUIRED
        
        connector = aiohttp.TCPConnector(ssl=ssl_context, limit=100, limit_per_host=30)
        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        
        try:
            async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                async with session.post(url, headers=headers, data=form_data) as response:
                    if self.verbose:
                        self.logger.debug(f"Response status: {response.status}")
                        self.logger.debug(f"Response headers: {dict(response.headers)}")
                    
                    if response.status == 200 or response.status == 201:
                        data = await response.json()
                        if self.verbose:
                            self.logger.debug(f"Read document response data: {data}")
                        
                        # Try different possible field names for the read ID
                        read_id = data.get('id') or data.get('read_id') or data.get('_id')
                        
                        if not read_id and isinstance(data, dict):
                            # If no direct ID field, look for nested data
                            if 'data' in data and isinstance(data['data'], dict):
                                read_id = data['data'].get('id') or data['data'].get('read_id') or data['data'].get('_id')
                            # Look for any field that looks like an ID
                            for key, value in data.items():
                                if 'id' in key.lower() and isinstance(value, str):
                                    read_id = value
                                    break
                        
                        if self.verbose:
                            self.logger.info(f"✅ Read document created successfully with read_id: {read_id}")
                        else:
                            print(f"✅ Created read document: {read_id}")
                        
                        if not read_id:
                            if self.verbose:
                                self.logger.error(f"❌ No read_id found in response: {data}")
                            raise Exception(f"No read_id found in response")
                        
                        return read_id
                    else:
                        error_text = await response.text()
                        if self.verbose:
                            self.logger.error(f"❌ Failed to create read document: {response.status}")
                            self.logger.error(f"Error response: {error_text}")
                        raise Exception(f"Failed to create read document: {response.status} {error_text}")
        except Exception as e:
            if self.verbose:
                self.logger.error(f"❌ Read document creation error: {e}")
            raise

    async def _wait_for_document_processing(self, read_id: str, max_wait_time: int = 60):
        """Wait for read document to be ready for streaming.

        Based on flow analysis, the app hits `GET /v1/reader/reads/{id}/simple-html` and
        issues several PATCH updates. We avoid PATCH and instead poll the simple-html endpoint
        until it returns 200 to indicate the read is ingested and ready to stream.
        """
        url = f"https://api.elevenlabs.io/v1/reader/reads/{read_id}/simple-html?make_pageable=false"
        
        headers = self.headers.copy()
        headers["Authorization"] = f"Bearer {self.bearer_token}"
        
        if self.verbose:
            self.logger.info(f"⏳ Waiting for document processing: {read_id}")
        else:
            print(f"⏳ Waiting for document processing...", end="", flush=True)
        
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = True
        ssl_context.verify_mode = ssl.CERT_REQUIRED
        
        connector = aiohttp.TCPConnector(ssl=ssl_context, limit=100, limit_per_host=30)
        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        
        start_time = time.time()
        poll_interval = 2  # Poll every 2 seconds
        
        try:
            async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                while True:
                    elapsed = time.time() - start_time
                    if elapsed > max_wait_time:
                        raise Exception(f"Document processing timeout after {max_wait_time}s")
                    
                    async with session.get(url, headers=headers) as response:
                        if response.status == 200:
                            # Simple HTML available -> ready
                            if self.verbose:
                                self.logger.info("✅ Read simple-html available; document is ready for streaming")
                            else:
                                print(f"\n✅ Document ready!")
                            return
                        elif response.status in (202, 204, 404):
                            # Not ready yet or not found yet; keep polling
                            if not self.verbose:
                                print(".", end="", flush=True)
                            await asyncio.sleep(poll_interval)
                            continue
                        else:
                            error_text = await response.text()
                            if self.verbose:
                                self.logger.debug(f"Check response {response.status}: {error_text[:200]}")
                            await asyncio.sleep(poll_interval)
                            continue
                            
        except Exception as e:
            if self.verbose:
                self.logger.error(f"❌ Document processing check error: {e}")
            raise

    def _start_realtime_player(self):
        """Start real-time audio player (mpv or ffplay) that reads from stdin"""
        import subprocess
        import shutil
        
        # Try mpv first (like official SDK), then ffplay
        if shutil.which("mpv"):
            cmd = ["mpv", "--no-cache", "--no-terminal", "--", "fd://0"]
            player_name = "mpv"
        elif shutil.which("ffplay"):
            cmd = ["ffplay", "-autoexit", "-", "-nodisp"]
            player_name = "ffplay"
        else:
            print("❌ No real-time audio player found. Install mpv (brew install mpv) or ffmpeg for streaming playback")
            return None, None
        
        try:
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print(f"🎵 Started real-time audio player: {player_name}")
            return process, player_name
        except Exception as e:
            print(f"❌ Failed to start {player_name}: {e}")
            return None, None

    def _stream_audio_chunk_to_player(self, process, chunk: bytes):
        """Stream audio chunk to real-time player"""
        if process and process.stdin and chunk:
            try:
                process.stdin.write(chunk)
                process.stdin.flush()
                return True
            except (BrokenPipeError, OSError):
                return False
        return False

    async def _stream_audio_chunk_to_player_async(self, process, chunk: bytes):
        """Async wrapper to stream audio without blocking the event loop."""
        try:
            import asyncio
            return await asyncio.to_thread(self._stream_audio_chunk_to_player, process, chunk)
        except Exception:
            return False

    async def _b64decode_async(self, b64s: str) -> bytes:
        try:
            import asyncio
            return await asyncio.to_thread(base64.b64decode, b64s)
        except Exception:
            return b""

    async def _json_loads_async(self, s: str) -> dict:
        try:
            import asyncio
            return await asyncio.to_thread(json.loads, s)
        except Exception:
            return {}

    async def _karaoke_worker(self, preview, queue: "asyncio.Queue"):
        try:
            import asyncio
            while True:
                item = await queue.get()
                if item is None:
                    queue.task_done()
                    break
                chars = item.get("chars") or []
                starts = item.get("starts") or []
                anchor = item.get("anchor") or time.monotonic()
                # Normalize starts
                if starts:
                    first = starts[0]
                else:
                    first = 0
                # Initial render
                if chars:
                    preview.render_block(chars, 0)
                else:
                    preview.render_at_char(item.get("abs_start", 0))

                # Word-level stepping
                block_str = ''.join(chars)
                # Compute simple char->word map
                char_to_word = []
                if block_str:
                    char_to_word = [-1] * len(block_str)
                    i = 0
                    widx = 0
                    while i < len(block_str):
                        while i < len(block_str) and block_str[i].isspace():
                            i += 1
                        if i >= len(block_str):
                            break
                        ws = i
                        while i < len(block_str) and not block_str[i].isspace():
                            i += 1
                        we = i
                        for j in range(ws, we):
                            char_to_word[j] = widx
                        widx += 1
                last_word = -2
                for i, tms in enumerate(starts):
                    tnorm = max(0.0, (tms - first) / 1000.0)
                    target = anchor + tnorm
                    now = time.monotonic()
                    delay = target - now
                    if delay > 0:
                        await asyncio.sleep(delay)
                    if chars:
                        w = char_to_word[i] if char_to_word else i
                        if w != last_word and w is not None:
                            preview.render_block(chars, i)
                            last_word = w
                    else:
                        preview.render_at_char(item.get("abs_start", 0) + i)
                queue.task_done()
        except Exception:
            # Fail silent to not affect audio
            return

    async def _save_chunk_async(self, filename: str, data: bytes):
        try:
            import asyncio
            def _write():
                with open(filename, "wb") as f:
                    f.write(data)
            await asyncio.to_thread(_write)
        except Exception:
            pass

    def _stop_realtime_player(self, process):
        """Stop real-time audio player"""
        if process and process.stdin:
            try:
                process.stdin.close()
                process.wait(timeout=5)
                print("🎵 Audio playback completed")
            except subprocess.TimeoutExpired:
                process.kill()
                print("🎵 Audio player stopped")

    async def _play_audio(self, audio_data: bytes):
        """Play audio using macOS afplay command (fallback for complete audio)"""
        if not audio_data:
            print("❌ No audio data to play")
            return
        
        try:
            import tempfile
            import subprocess
            import os
            
            # Create temporary file for audio
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_file:
                tmp_file.write(audio_data)
                tmp_file_path = tmp_file.name
            
            # Play audio using afplay (macOS)
            try:
                subprocess.run(["afplay", tmp_file_path], check=True)
                print("🎵 Audio playback completed")
            except subprocess.CalledProcessError as e:
                print(f"❌ Audio playback failed: {e}")
            except FileNotFoundError:
                print("❌ afplay not found (macOS only)")
            finally:
                # Clean up temporary file
                try:
                    os.unlink(tmp_file_path)
                except OSError:
                    pass
                    
        except Exception as e:
            print(f"❌ Audio playback error: {e}")


def setup_logging(verbose: bool):
    """Setup logging configuration based on verbose flag"""
    if verbose:
        # Set up detailed logging
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # Enable specific library loggers
        loggers_to_enable = [
            'aiohttp.access',
            'aiohttp.client', 
            'aiohttp.connector',
            'websockets.client',
            'websockets.protocol',
            'elevenlabs'
        ]
        
        for logger_name in loggers_to_enable:
            logger = logging.getLogger(logger_name)
            logger.setLevel(logging.DEBUG)
        
        # Create a custom handler for network-specific logs
        network_logger = logging.getLogger('NetworkTraffic')
        network_logger.setLevel(logging.DEBUG)
        
        print("🔍 Verbose logging enabled - detailed network traffic will be logged")
    else:
        # Suppress most logging
        logging.basicConfig(level=logging.WARNING)
        # Specifically suppress noisy libraries
        logging.getLogger('aiohttp').setLevel(logging.WARNING)
        logging.getLogger('websockets').setLevel(logging.WARNING)
        logging.getLogger('elevenlabs').setLevel(logging.WARNING)


async def main():
    parser = argparse.ArgumentParser(
        description="ElevenLabs TTS Client (matching captured flows)"
    )
    
    # Simplified authentication - only need Firebase refresh token
    auth_group = parser.add_mutually_exclusive_group(required=True)
    auth_group.add_argument("--firebase-refresh-token", help="Firebase refresh token (recommended)")
    auth_group.add_argument("--bearer-token", help="ElevenLabs Bearer token (manual)")
    
    parser.add_argument("--voice-id", help="Voice ID to use (required for TTS)")
    parser.add_argument("--text", help="Text to convert (or use stdin)")
    parser.add_argument("--file", help="File containing text to convert")
    parser.add_argument("--read-id", help="Existing read document ID to stream from (bypasses document creation)")
    parser.add_argument("--position", type=int, default=0, help="Starting position in document (0=current, -1=force restart)")
    parser.add_argument("--output", help="Output audio file path")
    parser.add_argument("--save-chunks", action="store_true", help="Save each audio chunk to separate files")
    parser.add_argument(
        "--play", action="store_true", help="Play audio after generation"
    )
    parser.add_argument(
        "--list-voices", action="store_true", help="List available voices"
    )
    parser.add_argument(
        "--list-reads", action="store_true", help="List your Reader documents"
    )
    parser.add_argument(
        "--verbose", "-v", 
        action="store_true", 
        help="Enable verbose logging for network requests and responses"
    )
    parser.add_argument(
        "--cache-file", default="tokens_cache.json", help="Token cache file path"
    )
    parser.add_argument(
        "--clear-cache", action="store_true", help="Clear token cache and exit"
    )
    parser.add_argument(
        "--method", 
        choices=["reader", "http", "websocket", "auto"], 
        default="reader",
        help="Streaming method to use (default: reader - FREE WebSocket method from flows analysis)"
    )
    parser.add_argument(
        "--app-check-token", help="Firebase App Check token for Reader WebSocket (xi-app-check-token)"
    )
    parser.add_argument(
        "--device-id", help="Override device ID header (UUID). Default: random UUID"
    )
    parser.add_argument(
        "--karaoke", action="store_true", help="Show live text preview (karaoke-like) while streaming"
    )
    parser.add_argument(
        "--karaoke-before", type=int, default=8, help="Words to show before current word in karaoke preview (default: 8)"
    )
    parser.add_argument(
        "--karaoke-after", type=int, default=8, help="Words to show after current word in karaoke preview (default: 8)"
    )

    args = parser.parse_args()
    
    # Setup logging based on verbose flag
    setup_logging(args.verbose)
    
    if args.verbose:
        logger = logging.getLogger('MainApp')
        logger.info("🚀 Starting ElevenLabs TTS Client with verbose logging")
        logger.debug(f"Arguments: {vars(args)}")

    # Handle cache clearing
    if args.clear_cache:
        token_manager = TokenManager(cache_file=args.cache_file, verbose=args.verbose)
        token_manager.clear_cache()
        return

    # Get Bearer token using simplified flow
    bearer_token = None
    if args.firebase_refresh_token:
        if args.verbose:
            logger.info("🔑 Using Firebase refresh token for authentication")
        token_manager = TokenManager(cache_file=args.cache_file, verbose=args.verbose)
        bearer_token = token_manager.get_fresh_bearer_token(args.firebase_refresh_token)
        if not bearer_token:
            print("❌ Failed to get Bearer token from Firebase refresh token")
            return
        if args.verbose:
            logger.debug(f"Bearer token preview: {bearer_token[:50]}...")
    else:
        bearer_token = args.bearer_token
        if args.verbose:
            logger.info("🔑 Using manually provided Bearer token")
            logger.debug(f"Bearer token preview: {bearer_token[:50]}...")

    # Resolve App Check token and Device ID via cache/CLI
    tm_app = TokenManager(cache_file=args.cache_file, verbose=args.verbose)
    if args.app_check_token:
        tm_app.set_app_check_token(args.app_check_token)
    app_check_token_value = args.app_check_token or tm_app.get_app_check_token()

    # Device ID: prefer CLI value, else cached, else generate and cache
    device_id_value = args.device_id or tm_app.get_device_id()
    if not device_id_value:
        device_id_value = str(uuid.uuid4()).upper()
        tm_app.set_device_id(device_id_value)
    elif args.device_id:
        tm_app.set_device_id(args.device_id)

    # Create client
    client = ElevenLabsTTSClient(
        bearer_token,
        verbose=args.verbose,
        app_check_token=app_check_token_value,
        device_id=device_id_value,
    )
    if args.verbose:
        logger = logging.getLogger('MainApp')
        logger.info(f"🛡️ App Check token present: {bool(app_check_token_value)} | Device-ID: {device_id_value}")

    # Just-in-time token freshness check before network-intensive ops
    # If the token is close to expiry (<10m), refresh it so WS doesn't 403 mid-handshake
    if args.firebase_refresh_token:
        try:
            tm = TokenManager(cache_file=args.cache_file, verbose=args.verbose)
            info = tm.get_cache_info()
            expires_at = info.get('bearer_token_expires_at')
            if expires_at:
                from datetime import datetime, timezone
                import dateutil.parser as dparser
                exp_dt = dparser.isoparse(expires_at)
                now = datetime.now(exp_dt.tzinfo or timezone.utc)
                seconds_left = (exp_dt - now).total_seconds()
                if args.verbose:
                    logger = logging.getLogger('MainApp')
                    logger.info(f"🔐 Token time left before WS: {int(seconds_left)}s")
                # If < 10 minutes left, proactively refresh
                if seconds_left < 600:  # < 10 minutes left
                    fresh = tm.get_fresh_bearer_token(args.firebase_refresh_token)
                    if fresh and fresh != client.bearer_token:
                        client.bearer_token = fresh
                        if args.verbose:
                            logger.info("🔐 Refreshed bearer token pre-WS due to low remaining time")
                # If using reader method, force refresh to ensure the newest token (avoids 403)
                if args.method == 'reader':
                    fresh2 = tm.force_refresh_bearer_token(args.firebase_refresh_token)
                    if fresh2 and fresh2 != client.bearer_token:
                        client.bearer_token = fresh2
                        if args.verbose:
                            logger.info("🔐 Force-refreshed bearer token for Reader WS")
        except Exception:
            pass

    # List voices if requested
    if args.list_voices:
        try:
            voices = await client.get_voices()
            print("🎭 Available voices:")
            for voice in voices.get("voices", []):
                print(
                    f"  {voice['voice_id']}: {voice['name']} ({voice.get('category', 'unknown')})"
                )
            return
        except Exception as e:
            print(f"❌ Failed to list voices: {e}")
            return

    # List reads if requested
    if args.list_reads:
        try:
            reads = await client.list_reads(updated_since_unix=0)
            if not reads:
                print("📚 No reads found")
                return
            print("📚 Your Reader documents:")
            for r in reads:
                rid = r.get("read_id") or r.get("id") or "<unknown>"
                title = r.get("title") or r.get("read_slug") or "<untitled>"
                chars = r.get("char_count") or r.get("chapters", [{}])[0].get("char_count") or "?"
                last = r.get("last_listened_char_offset")
                lang = r.get("language") or ""; lang = f" [{lang}]" if lang else ""
                print(f"  {rid}  —  {title}{lang}  (chars: {chars}, progress: {last})")
            return
        except Exception as e:
            print(f"❌ Failed to list reads: {e}")
            return

    # Check for voice ID if doing TTS
    if not args.voice_id:
        print("❌ --voice-id is required for text-to-speech conversion")
        print("Use --list-voices to see available voices")
        return

    # Handle read_id vs text input
    if args.read_id:
        print(f"📋 Using existing read document: {args.read_id}")
        # Generate audio from existing read_id
        try:
            audio_data = await client.stream_with_websocket(
                read_id=args.read_id,
                voice_id=args.voice_id,
                output_file=args.output,
                play_audio=args.play,
                position=args.position,
                save_chunks=args.save_chunks,
                method=args.method,
                show_karaoke=args.karaoke,
                karaoke_before=args.karaoke_before,
                karaoke_after=args.karaoke_after,
            )
        except Exception as e:
            print(f"❌ Error streaming from read_id: {e}")
            return
    else:
        # Get text input
        text = None
        if args.text:
            text = args.text
        elif args.file:
            with open(args.file, "r") as f:
                text = f.read()
        else:
            print("📝 Reading from stdin (Ctrl+D to finish)...")
            text = sys.stdin.read()

        if not text:
            print("❌ No text provided")
            return

        text = text.strip()
        if not text:
            print("❌ Empty text")
            return

        print(f"📄 Text length: {len(text)} characters")

        # Generate audio from text
        try:
            audio_data = await client.stream_with_websocket(
                text=text,
                voice_id=args.voice_id,
                output_file=args.output,
                play_audio=args.play,
                method=args.method,
                show_karaoke=args.karaoke,
                karaoke_before=args.karaoke_before,
                karaoke_after=args.karaoke_after,
            )
        except Exception as e:
            print(f"❌ Error: {e}")
            return

    if audio_data:
        print(f"✅ Successfully generated {len(audio_data)} bytes of audio")
    else:
        print("❌ Audio generation failed")


if __name__ == "__main__":
    asyncio.run(main())
