# 🎤 elevenlabs-reader-cli - Unofficial ElevenLabs Reader for the terminal

A command-line client for interacting with ElevenLabs Reader using the same backend the iOS app uses (unofficial). It supports creating Reader documents, streaming them over WebSocket with real-time playback, and basic library operations. Authentication mirrors the app (Firebase refresh token, App Check token, device-id) and uses your ElevenLabs account via the Reader pipeline.

---

## Table of Contents

- [Overview](#overview)
- [⚠️ Technical Requirements](#technical-requirements)
- [Features](#features)
- [Project Structure](#project-structure)
- [Installation](#installation)
- [Quick Start](#quick-start)
  - [1. Get Firebase Refresh Token](#1-get-firebase-refresh-token)
  - [2. Easy Usage (No Token Typing!)](#2-easy-usage-no-token-typing)
  - [3. Manual Usage (If You Want Full Control)](#3-manual-usage-if-you-want-full-control)
  - [4. Test the Implementation](#4-test-the-implementation)
  - [5. App Check Token and Device ID (Reader WS)](#5-app-check-token-and-device-id-reader-ws)
- [Local API Server](#local-api-server)
- [Browser Integration (Userscript)](#browser-integration-userscript)
- [How It Works](#how-it-works)
  - [Reader App Workflow](#reader-app-workflow)
  - [Reader Streaming Internals (Multi‑Connection)](#reader-streaming-internals-multi-connection)
  - [Karaoke Preview](#karaoke-preview)
  - [Key Differences from Official API](#key-differences-from-official-api)
- [Arguments](#arguments)
- [Streaming Methods](#streaming-methods)
  - [Reader WebSocket (unofficial) — default](#reader-websocket-unofficial--default)
  - [HTTP Streaming](#http-streaming)
  - [Direct WebSocket](#direct-websocket)
  - [Auto Fallback](#auto-fallback)
- [Token Management](#token-management)
  - [Practical Usage](#practical-usage)
  - [TokenManager Class API](#tokenmanager-class-api)
  - [Token Security Considerations](#token-security-considerations)
- [Verbose Logging](#verbose-logging)
- [Authentication Flow Details](#authentication-flow-details)
  - [Firebase Token Architecture](#firebase-token-architecture)
  - [Firebase Token Refresh Implementation](#firebase-token-refresh-implementation)
  - [Reader API Headers](#reader-api-headers)
- [Error Handling](#error-handling)
- [Security Considerations](#security-considerations)
- [Security & Ethics](#security--ethics)
- [Troubleshooting](#troubleshooting)
  - [Common Issues](#common-issues)
  - [Debug Mode](#debug-mode)
- [What We Fixed (Reader Streaming)](#what-we-fixed-reader-streaming)
- [Recent Improvements](#recent-improvements)
- [Limitations](#limitations)
- [Development Status](#development-status)
- [Contributing](#contributing)

---

## Overview

Command-line utility for the ElevenLabs Reader workflow:

- Create documents and stream them via the Reader WebSocket protocol
- Stream existing Reader documents from your library
- Real-time playback and optional text preview (karaoke-style)
- Token management matching the app’s authentication flow

## ⚠️ Technical Requirements

This tool reverse engineers the **private Reader app API** (not the official public API). It requires:

- Firebase refresh tokens from the Reader mobile app
- Proper authentication flow matching the captured network traffic
- Document processing workflow (create → process → stream)

## Features

- Reader WebSocket streaming (unofficial; mirrors the app)
  - Firebase access tokens + Firebase App Check token (xi-app-check-token)
  - Reader-specific headers including `device-id` and `Origin`
  - Multi-connection streaming pattern with rollover
- Authentication and token management (Firebase refresh → access token)
- Multiple streaming methods: Reader WebSocket (default), HTTP, official WebSocket, Auto fallback
- Document creation and voice listing
- Real-time playback using `mpv` (preferred) or `ffplay`
- Audio export to MP3
- Verbose logging for debugging
- Live text preview (karaoke) with `--karaoke` and `--karaoke-before/--karaoke-after`

## Project Structure

```
elevenlabs-reader-cli/
├── elevenlabs_tts_client.py        # Main CLI client
├── api_server.py                   # FastAPI server for browser/external integrations
├── tts                             # Wrapper script (auto-extracts/caches tokens)
├── token_manager.py                # Firebase token caching and refresh
├── extensions/
│   └── userscript/
│       └── eleven-reader.user.js   # Tampermonkey/Violentmonkey userscript
├── utils/                          # Flow processing/analysis helpers
│   ├── ws_dump.py
│   ├── ws_dump2.py
│   └── ws_flows_to_jsonl_redact.py
├── mitm_firebase_token_sniffer.py  # mitmproxy script for token capture
├── get_refresh_token.py            # Refresh token extraction helper
├── get_app_check_token.py          # Extract Firebase App Check token
├── get_device_id.py                # Extract device-id
├── extract_tokens.py               # Full token extractor from flows
├── tests/                          # Test suite (script-style)
│   ├── test_basic.py
│   ├── test_client.py
│   └── ...
├── examples.sh                     # Usage examples and methods
├── requirements.txt                # Python dependencies
├── AGENTS.md                       # Contributor guidelines
└── README.md                       # Main documentation
```

Note: Temporary and large captured data should live under `tmp/` (git-ignored). Sensitive artifacts like `tokens_cache.json`, `flows.*`, and `*.elevenlabsio` are ignored via `.gitignore`.

## Installation

```bash
pip install -r requirements.txt
chmod +x elevenlabs_tts_client.py
chmod +x tts
```

## Quick Start

### 1. Get Firebase Refresh Token

You need a Firebase refresh token from the ElevenLabs Reader mobile app. This can be extracted from network traffic or device storage.

#### Option: Capture via mitmproxy

We ship `mitm_firebase_token_sniffer.py`, a mitmproxy inline script that watches Reader traffic and dumps Firebase tokens in real time.

1. Install [mitmproxy](https://mitmproxy.org/) (macOS: `brew install mitmproxy`, Linux: `pipx install mitmproxy` or distro package).
2. Run the sniffer and save flows for later analysis:
   ```bash
   mitmdump -q -s mitm_firebase_token_sniffer.py -w tmp/flows.elevenlabsio
   ```
3. Point your mobile device at the proxy, trust the mitmproxy certificate, then open/sign in to the ElevenLabs Reader app.
4. Watch the mitmproxy log or `tmp/firebase_tokens.jsonl` for lines such as:
   ```
   {"ts": 1732729830.11, "source": "response", "url": "...securetoken.googleapis.com...",
    "refresh_token": "AMf-vBw6ZWBpOHOOs-iI7...", "access_token": "eyJhbGciOiJSUzI1NiIs...", "expires_in": "3600"}
   ```
5. Copy the `refresh_token` into `./tts`/`api_server.py` and keep the capture file (`flows.elevenlabsio`) for token/app-check/device extraction via the existing helpers.

Security tip: stop mitmproxy once you have the token, since all device traffic transits the proxy while it’s enabled.

### 2. Easy Usage (No Token Typing!)

We provide multiple convenient ways to avoid typing the long Firebase refresh token every time:

#### Method 1: TTS wrapper script (easiest)

```bash
# Auto-extracts token from cache - just run once to set up tokens
./tts --list-voices

# List your Reader documents
./tts --list-reads

# Reader WebSocket streaming
./tts --voice-id "nPczCjzI2devNBz1zQrb" --text "Hello world!" --method reader --play

# HTTP streaming (instant)
./tts --voice-id "2EiwWnXFnvU5JabPnv8n" --text "Instant results" --method http --play

# Auto method (tries Reader, falls back to HTTP)
./tts --voice-id "nPczCjzI2devNBz1zQrb" --text "Auto selection" --method auto --play
```

#### Method 2: Command substitution

```bash
# Extract token inline with $(command):
python elevenlabs_tts_client.py \
  --firebase-refresh-token "$(python get_refresh_token.py)" \
  --voice-id "nPczCjzI2devNBz1zQrb" \
  --text "Command substitution test" \
  --method reader \
  --play
```

#### Method 3: Environment variable

```bash
# Set once in your session:
export FIREBASE_REFRESH_TOKEN=$(python get_refresh_token.py)

# Then use it multiple times:
python elevenlabs_tts_client.py \
  --firebase-refresh-token "$FIREBASE_REFRESH_TOKEN" \
  --voice-id "nPczCjzI2devNBz1zQrb" \
  --text "Environment variable test" \
  --method auto \
  --play
```

#### Method 4: Shell alias (permanent)

```bash
# Add to ~/.bashrc or ~/.zshrc:
alias tts11='python elevenlabs_tts_client.py --firebase-refresh-token "$(python get_refresh_token.py)"'

# Then use anywhere:
tts11 --voice-id "nPczCjzI2devNBz1zQrb" --text "Alias test" --play
```

### 3. Manual Usage (If You Want Full Control)

```bash
# List available voices
./elevenlabs_tts_client.py --firebase-refresh-token "your_token" --list-voices

# List your Reader documents (reads)
./elevenlabs_tts_client.py --firebase-refresh-token "your_token" --list-reads

# Reader WebSocket streaming (default — create and stream documents)
./elevenlabs_tts_client.py \
  --firebase-refresh-token "your_token" \
  --voice-id "voice_id_from_list" \
  --text "Any text you want" \
  --method reader \
  --play

# Live text preview (karaoke-like) while streaming a document (new or existing)
./elevenlabs_tts_client.py \
  --firebase-refresh-token "your_token" \
  --read-id "u:READ_ID" \
  --voice-id "voice_id_from_list" \
  --method reader \
  --play \
  --karaoke

# Or create from new text and preview karaoke live (stdin)
pbpaste | ./tts --voice-id "voice_id_from_list" --method reader --play --karaoke

# Tip: start without saving chunks for best real-time preview
# ./elevenlabs_tts_client.py ... --karaoke   # (no --save-chunks)

# HTTP streaming (official API)
./elevenlabs_tts_client.py \
  --firebase-refresh-token "your_token" \
  --voice-id "voice_id" \
  --text "Instant audio generation" \
  --method http \
  --output speech.mp3

# Auto method selection (tries Reader first, then falls back)
./elevenlabs_tts_client.py \
  --firebase-refresh-token "your_token" \
  --voice-id "voice_id" \
  --file input.txt \
  --method auto \
  --output speech.mp3

# Batch processing (recommended workflow)
echo "Chapter 1 content..." > chapter1.txt
echo "Chapter 2 content..." > chapter2.txt
./elevenlabs_tts_client.py --firebase-refresh-token "your_token" --voice-id "voice_id" --file chapter1.txt --method reader --output chapter1.mp3
./elevenlabs_tts_client.py --firebase-refresh-token "your_token" --voice-id "voice_id" --file chapter2.txt --method reader --output chapter2.mp3
```

### 4. Test the Implementation

```bash
# Quick test using wrapper
./tts --list-voices

# Or run comprehensive tests
python tests/test_basic.py
python tests/test_reader_api.py
```

### 5. App Check Token and Device ID (Reader WS)

The Reader WebSocket requires an additional Firebase App Check token header:

- Header: `xi-app-check-token: <JWT>`
- Also include: `device-id: <UUID>` and `Origin: https://elevenlabs.io`

The wrapper `./tts` will try to auto-extract both from `flows.elevenlabsio` and cache them in `tokens_cache.json`:

- App Check: `python get_app_check_token.py [flows.elevenlabsio]`
- Device ID: `python get_device_id.py [flows.elevenlabsio]`

Pass manually if needed: `--app-check-token "<token>" --device-id "<uuid>"`. Tokens expire; update periodically from fresh captures.

#### Firebase App Check Token

- Header name: `xi-app-check-token`
- Purpose: short‑lived attestation generated by the Reader app via Firebase App Check SDK
- Requirement: mandatory for Reader WebSocket; missing/expired → 403
- How to obtain: capture with mitmproxy from the Reader app or use `get_app_check_token.py`; `./tts` auto-extracts from `flows.elevenlabsio`
- Caching: persisted in `tokens_cache.json` once provided

#### Device ID

- Header name: `device-id`
- Purpose: stable UUID used by the Reader app; keep consistent across requests
- How to obtain: captured from flows or generated on first run and cached; override with `--device-id`

## Local API Server

Use `api_server.py` to expose a localhost HTTP interface for new integrations (browser add-ons, stream decks, etc.) without invoking the CLI manually.

### 1. Configure and launch

```bash
pip install -r requirements.txt
export FIREBASE_REFRESH_TOKEN="your_refresh_token"
export ELEVEN_DEFAULT_VOICE_ID="nPczCjzI2devNBz1zQrb"
# Optional env: XI_APP_CHECK_TOKEN, ELEVEN_DEVICE_ID, ELEVEN_DEFAULT_METHOD, ELEVEN_API_PORT
python api_server.py --port 8011
```

- `FIREBASE_REFRESH_TOKEN` is required (falls back to `tokens_cache.json` if you already ran `./tts`).
- `ELEVEN_DEFAULT_VOICE_ID` provides the server-side default `voice_id` when requests omit one.
- `ELEVEN_DEFAULT_METHOD` defaults to `reader` but accepts `http`, `websocket`, or `auto`.
- `ELEVEN_API_ALLOWED_ORIGINS` lets you restrict CORS (defaults to localhost + `moz-extension://*`).

### 2. Call the API

```bash
curl -X POST http://127.0.0.1:8011/api/read \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello from the local API!"}'
```

Example response:

```json
{
  "voice_id": "nPczCjzI2devNBz1zQrb",
  "method": "reader",
  "byte_length": 58234,
  "mime_type": "audio/mpeg",
  "audio_base64": "SUQzAwAAAAAAF1RTU0UAA...",
  "duration_seconds": 8.412,
  "text_preview": "Hello from the local API..."
}
```

Helper endpoints:

- `GET /healthz` → readiness + default configuration snapshot.
- `GET /api/voices` → mirrors `./tts --list-voices`.

## Browser Integration (Userscript)

A Tampermonkey/Violentmonkey userscript provides a floating speaker button for reading selected text. It uses **real-time SSE streaming** for instant playback as audio generates.

### Features

- 🔊 **Floating speaker button** appears when you select text on any page
- ⚡ **True streaming playback** — audio starts playing within seconds, not after full generation
- 🎯 **Smart positioning** — button always appears within the viewport, even for long selections
- 🔄 **Gapless playback** — chunks are preloaded and concatenated for seamless audio
- 📊 **Progress toasts** — shows status (creating, streaming, chunk count)
- ⌨️ **Keyboard support** — press Escape to stop playback

### Installation

1. Install [Tampermonkey](https://www.tampermonkey.net/) (Firefox/Chrome) or [Violentmonkey](https://violentmonkey.github.io/)
2. Open the userscript file: `extensions/userscript/eleven-reader.user.js`
3. Click "Install" when prompted by your userscript manager
4. Ensure the API server is running on `http://127.0.0.1:8011`

### Usage

1. Start the API server:
   ```bash
   FIREBASE_REFRESH_TOKEN="..." python api_server.py --port 8011
   ```
2. Select any text on a webpage
3. Click the 🔊 speaker button that appears
4. Audio streams and plays in real-time

### Configuration

Edit the constants at the top of `eleven-reader.user.js`:

```javascript
const API_BASE = "http://127.0.0.1:8011";  // API server URL
const PRELOAD_SECONDS = 5;                  // Seconds before end to preload next chunk
```

### How It Works

1. Selected text is sent to `/api/stream` (Server-Sent Events endpoint)
2. Server creates a Reader document and streams audio chunks as they generate
3. Userscript receives chunks via native `fetch` ReadableStream for true streaming
4. Audio chunks are queued and played sequentially with preloading for gapless playback
5. Each chunk is a complete MP3 segment that plays immediately

## How It Works

### Reader App Workflow

1. **Firebase Authentication**

   ```
   Firebase Refresh Token → securetoken.googleapis.com → Bearer Token
   ```

2. **Content Creation**

   ```
   POST /v1/reader/reads → Create read content → Get read_id
   ```

3. **Audio Streaming**

```
WebSocket /v1/reader/reads/stream/{read_id}?voice_id={voice_id}
Headers:
  Authorization: Bearer <firebase access_token>
  xi-app-check-token: <Firebase App Check JWT>
  device-id: <UUID>
  Origin: https://elevenlabs.io
  User-Agent: readerapp/405 CFNetwork/3860.100.1 Darwin/25.0.0
→ Audio chunks (base64 in JSON)
```

### Reader Streaming Internals (Multi‑Connection)

- The Reader app streams long documents across multiple WebSocket connections.
- Each connection streams a segment; server messages include `alignment` with per‑message character spans.
- The client accumulates processed characters in the connection, PATCHes progress to the REST API, and proactively reconnects:
  - at a budget boundary (~1.3–1.4k chars), or
  - on short idle (≈1.5s) after receiving content in the current connection (reduces audible gaps).
- The server may send `isFinal: true` to end a connection; the client keeps reconnecting from the last played position until the document end.

Observed positions from the real app for a 4,227‑char doc:

- 0 → 1,348 → 2,750 → 4,085 → final (isFinal: true)

What this client does:

- Accepts only non‑overlapping aligned blocks for playback and progress.
- Advances durable position (`abs_char_pos`) strictly from audio actually accepted/played (prevents skips).
- PATCHes `last_listened_char_offset` mid‑connection after accepted blocks and between connections.
- Proactively rolls the WebSocket when cumulative chars cross ~1,348 or when short idle occurs after receiving content.
- Reconnects with `{"stream_id": "UUID", "position": <abs_char_pos>}` until reaching the document `char_count`.

Flags to help debug/validate:

- `--save-chunks`: writes each received audio chunk to `chunk_XXX_<read>_connY_posZ.mp3` with connection/position metadata.
- `--verbose`: logs exact WS headers, messages, alignment counts, and PATCH progress.

### Karaoke Preview

- Overview: Shows a live, word-by-word subtitle in your terminal during streaming.
- Styling: Current word is bold white; surrounding context is gray. Single-line in-place updates (no scrolling).
- Source of truth: Uses the WebSocket `alignment` (per‑block `chars` + timing) for exact spoken content; does not rely on global HTML.
- Timing: A centralized ticker chains timing between blocks to avoid drift or “missing words” at boundaries.
- Best practice: For tightest sync, avoid `--save-chunks` (file I/O can compete for compute); use only `--karaoke`.

Usage (works for both newly created documents via --text/--file/stdin and existing --read-id):

```bash
./tts --read-id "u:READ_ID" --voice-id "VOICE" --method reader --play --karaoke
# or pipe new text
pbpaste | ./tts --voice-id "VOICE" --method reader --play --karaoke
# Optional: widen context
./tts ... --karaoke --karaoke-before 12 --karaoke-after 12
```

Notes:

- ANSI colors must be supported by your terminal.
- If your terminal is not color-capable or strips ANSI, you may see raw escapes; try another terminal or disable colors.

### Key Differences from Official API

| Feature        | Official API            | Reader API                                    |
| -------------- | ----------------------- | --------------------------------------------- |
| Authentication | API Keys (`xi-api-key`) | Firebase Bearer tokens                        |
| Endpoints      | `/v1/text-to-speech/`   | `/v1/reader/`                                 |
| Workflow       | Direct streaming        | Content creation → Streaming                  |
| WebSocket URL  | `/stream-input`         | `/reads/stream/{read_id}`                     |
| Headers        | Standard API headers    | Reader app headers with Device-ID + App Check |

## Arguments

| Argument                   | Required | Description                                                             |
| -------------------------- | -------- | ----------------------------------------------------------------------- |
| `--firebase-refresh-token` | one of   | Firebase refresh token from Reader app                                  |
| `--bearer-token`           | one of   | Manually provide a Bearer token (mutually exclusive with refresh token) |
| `--voice-id`               | required | Voice ID (use --list-voices to see options)                             |
| `--text`                   | ❌       | Text to convert (or use --file/stdin)                                   |
| `--file`                   | ❌       | File containing text to convert                                         |
| `--output`                 | ❌       | Output audio file path                                                  |
| `--play`                   | ❌       | Play audio after generation (real-time via mpv/ffplay)                  |
| `--save-chunks`            | ❌       | Save each audio chunk to separate files                                 |
| `--position`               | ❌       | Start position for existing reads (default: 0)                          |
| `--read-id`                | ❌       | Stream from an existing read document ID                                |
| `--list-voices`            | ❌       | List available voices                                                   |
| `--list-reads`             | ❌       | List your Reader documents (library)                                    |
| `--verbose`, `-v`          | ❌       | Enable detailed logging                                                 |
| `--cache-file`             | ❌       | Token cache file (default: tokens_cache.json)                           |
| `--clear-cache`            | ❌       | Clear token cache and exit                                              |
| `--method`                 | ❌       | Streaming method: `reader` (default), `http`, `websocket`, `auto`       |
| `--app-check-token`        | ❌       | Firebase App Check token for Reader WS (xi-app-check-token)             |
| `--karaoke`                | ❌       | Show live text preview (karaoke-like) during streaming                  |
| `--karaoke-before`         | ❌       | Words to show before current word (default: 8)                          |
| `--karaoke-after`          | ❌       | Words to show after current word (default: 8)                           |
| `--device-id`              | ❌       | Override the Reader Device ID (UUID)                                    |

Notes: Provide exactly one of `--firebase-refresh-token` or `--bearer-token`.

## Streaming Methods

### Reader WebSocket (unofficial) — default

- **Command**: `--method reader` (default)
- Use case: Any text → document creation → WebSocket streaming
- Workflow: Create document → wait for processing → stream
- Real-time playback: streams to `mpv`/`ffplay` when `--play` is set
- Streaming: multi‑connection with rollover and periodic progress PATCH
- Auth requirements: Firebase access token + xi-app-check-token + device-id

### HTTP Streaming

- **Command**: `--method http`
- Use case: Any custom text generation
- Real-time playback: streams chunks live to `mpv`/`ffplay` when `--play` is set
- Limitations: standard API rate limits
- Reliability: official API method

### Direct WebSocket

- **Command**: `--method websocket`
- Use case: Real-time streaming with official API
- Limitations: standard API rate limits
- Reliability: official API method

### Auto Fallback

- **Command**: `--method auto`
- Behavior: Tries Reader → HTTP → WebSocket in order
- Use case: Maximum compatibility
- Recommendation: useful for development/testing

## Token Management

### Practical Usage

**You only need to provide the Firebase Refresh Token once:**

```bash
# First time - provide refresh token
./elevenlabs_tts_client.py \
  --firebase-refresh-token "AMf-vBw6ZWBpOHOOs-iI7..." \
  --voice-id "nPczCjzI2devNBz1zQrb" \
  --text "Hello world" \
  --method reader \
  --play

# All subsequent runs - uses cached tokens automatically
./elevenlabs_tts_client.py \
  --firebase-refresh-token "AMf-vBw6ZWBpOHOOs-iI7..." \
  --voice-id "voice_id" \
  --text "More text" \
  --play
```

**What happens behind the scenes:**

- Creates a Bearer token and caches it (valid ~1 hour)
- Automatically refreshes the Bearer token when expired
- Refresh token remains valid long-term and is reused to obtain new access tokens

### TokenManager Class API

```python
from token_manager import TokenManager

# Create manager
manager = TokenManager(verbose=True)

# Get fresh Bearer token (auto-refreshes if needed)
bearer_token = manager.get_fresh_bearer_token("firebase_refresh_token")

# Check cache status
info = manager.get_cache_info()
print(f"Bearer token expires at: {info['bearer_token_expires_at']}")
print(f"Token expired: {info['bearer_token_expired']}")

# Clear cache if needed
manager.clear_cache()
```

### Token Security Considerations

| Token Type        | Sensitivity   | Best Practices                                                             |
| ----------------- | ------------- | -------------------------------------------------------------------------- |
| **Refresh Token** | 🔴 **HIGH**   | • Store securely<br>• Don't share publicly<br>• Treat like a password      |
| **Bearer Token**  | 🟡 **MEDIUM** | • Auto-expires in 1 hour<br>• Cached temporarily<br>• Lower risk if leaked |

**Security Notes:**

- 🔒 Refresh tokens are more sensitive than Bearer tokens
- ⚠️ Command line arguments are visible in process lists
- 💡 Consider using environment variables for automation:

  ```bash
  export FIREBASE_REFRESH_TOKEN="your_token_here"
  ./elevenlabs_tts_client.py --firebase-refresh-token "$FIREBASE_REFRESH_TOKEN" ...
  ```

## Verbose Logging

Enable detailed logging to debug API calls:

```bash
./elevenlabs_tts_client.py --verbose --firebase-refresh-token "token" --list-voices
```

Logs include:

- Firebase token refresh operations
- Content creation requests/responses
- WebSocket connection details (authorization preview, headers)
- Audio chunk reception progress
- Network timing and error details

## Authentication Flow Details

### Firebase Token Architecture

The ElevenLabs Reader app uses Firebase's standard authentication system with three token types:

#### **1. Firebase Refresh Token** 🔑

- **Purpose**: Long-lived credential for getting new access tokens
- **Lifetime**: **Months/Years** (doesn't expire automatically)
- **Storage**: **Persistent** - cached in `tokens_cache.json`
- **Usage**: You provide this once via `--firebase-refresh-token`
- **Security**: High sensitivity - acts like a "master key"

#### **2. Bearer Token (Firebase Access Token)** ⏰

- **Purpose**: Short-lived JWT for API authentication
- **Lifetime**: **1 hour** (`expires_in: 3600` seconds)
- **Storage**: **Temporary cache** with automatic expiration tracking
- **Usage**: Automatically generated/refreshed using refresh token
- **Security**: Medium sensitivity - expires quickly

#### **3. Token Management Flow**

```
Firebase Refresh Token (long-lived, you provide once)
        ↓ (when Bearer token expires)
Firebase API refresh call
        ↓ (returns new 1-hour token)
Bearer Token (used for all API calls)
        ↓ (in Authorization header)
ElevenLabs Reader API access
```

#### **Cache Structure Example**

```json
{
  "firebase_refresh_token": "AMf-vBw6ZWBpOHOOs-iI7...", // 🔑 PERSISTENT
  "bearer_token_data": {
    "bearer_token": "eyJhbGciOiJSUzI1NiIs...", // ⏰ 1-HOUR EXPIRY
    "expires_in": 3600,
    "expires_at": "2025-08-17T19:37:51.161875",
    "refreshed_at": "2025-08-17T18:37:51.161937",
    "token_type": "Bearer"
  }
}
```

#### **Automatic Token Refresh**

- **First run**: Creates Bearer token (valid 1 hour)
- **Subsequent runs**: Reuses cached Bearer token if valid
- **After expiry**: Auto-refreshes Bearer token using Refresh token
- **No user action needed**: Completely transparent

### Firebase Token Refresh Implementation

```python
# Endpoint matching Reader app
url = "https://securetoken.googleapis.com/v1/token?key=AIzaSyDhSxLJa_WaR8I69a1BmlUG7ckfZHu7-ig"

# Headers matching captured traffic
headers = {
    "User-Agent": "FirebaseAuth.iOS/11.14.0 io.elevenlabs.readerapp/1.4.45 iPhone/26.0 hw/iPhone16_2",
    "X-Client-Version": "iOS/FirebaseSDK/11.14.0/FirebaseCore-iOS",
    "X-iOS-Bundle-Identifier": "io.elevenlabs.readerapp"
}

# Payload for refresh
{
  "grant_type": "refresh_token",
  "refresh_token": "your_firebase_refresh_token"
}
```

### Reader API Headers

```python
headers = {
    "User-Agent": "readerapp/405 CFNetwork/3860.100.1 Darwin/25.0.0",
    "App-Version": "1.4.45",
    "Device-ID": "generated-uuid",
    "Language": "en",
    "User-Timezone": "America/Montevideo",
    "Authorization": "Bearer firebase_access_token"
}
```

## Error Handling

- Automatic token refresh when expired
- Network retry logic for transient failures
- Detailed error messages with troubleshooting hints
- Graceful fallback between authentication methods

## Security Considerations

- 🔒 Firebase refresh tokens cached securely
- 🔒 Bearer tokens auto-expire (1 hour)
- 🔒 All API calls use TLS encryption
- ⚠️ Tokens visible in command line history

## Security & Ethics

- Legitimate use cases: stream content from your own Reader library and documents you have permission to access.
- Private API: this integrates the Reader app’s private endpoints; stability is not guaranteed.
- Token handling: keep refresh tokens secret; rotate if leaked; prefer environment variables over plain CLI args.
- Responsibility: ensure your usage complies with ElevenLabs’ Terms and applicable law.

## Troubleshooting

### Common Issues

1. **Authentication Failed**

   ```bash
   # Clear token cache and retry
   ./elevenlabs_tts_client.py --clear-cache
   ```

2. **WebSocket Connection Failed**

```bash
# Enable verbose logging to debug
./elevenlabs_tts_client.py --verbose ...
```

- 403 Forbidden causes:
  - Missing xi-app-check-token (pass via --app-check-token)
  - Expired App Check token (capture a fresh one)
  - Mismatched or missing device-id (ensure stable UUID)
  - Token about to expire (tool force-refreshes pre-WS; check logs)

3. **Audio Playback Failed**
   - Ensure `mpv` (preferred) or `ffplay` is installed and in PATH
   - Otherwise, use `--output` to save audio and play with your system player

### Debug Mode

```bash
# Maximum verbosity for troubleshooting
./elevenlabs_tts_client.py --verbose --firebase-refresh-token "token" --text "test" --voice-id "voice"
```

## What We Fixed (Reader Streaming)

- Fix: Streaming stopped after ~2 chunks with an early `isFinal: true`.
- Cause: We didn’t mirror the mobile app’s multi‑connection rollover; stayed on the first WS too long.
- Solution:
  - Accept/play only non‑overlapping aligned blocks; advance durable position from audio actually played.
  - PATCH `last_listened_char_offset` during streaming and between connections.
  - Proactively reconnect after ~1.3–1.4k chars per connection or on short idle (≈1.5s) to avoid long gaps.
  - Stop when reaching the document `char_count` (queried from REST), not solely on `isFinal`.
- Result: Full document streams smoothly over multiple WS connections (31 chunks observed), with clean real‑time playback and saved chunk files when `--save-chunks` is used.

## Recent Improvements

- Multi-connection streaming: Implemented budget-based (~1.3–1.4k chars) and idle-based (~1.5s) rollovers with mid‑connection PATCH updates and safe retries. Prevents long gaps and ensures seamless continuation.
- Ordered alignment playback: Karaoke preview is driven by a central ticker that chains timing across blocks, avoiding gaps or overlaps at boundaries (no “missing early words” on joins).
- Non-blocking I/O: Audio feeding, base64 decode, and chunk saving are moved off the event loop to keep timing accurate.
- Clean preview UX: In-place single-line updates (bold white current word, gray context) without noisy progress dots.

## Limitations

- Reader app private API (not officially supported)
- Requires reverse-engineered Firebase tokens
- Real-time playback requires `mpv` or `ffplay` (else save to file)
- No official warranty or support

## Development Status

- Reader WebSocket streaming implemented with multi-connection rollover and progress PATCH
- Authentication via Firebase refresh token → access token, with caching and refresh
- Document creation workflow working against `/v1/reader/reads/add/v2`
- Multiple methods supported: Reader, HTTP, official WebSocket, Auto
- Karaoke preview driven by alignment data
- Ongoing: optimize new document processing readiness/polling

## Contributing

Contributions are welcome. High-impact areas:

- Processing timing optimization for new documents (reduce initial 403s)
- Cross-platform audio playback improvements and fallbacks
- Additional Reader API endpoints and capabilities
- Performance improvements (I/O, buffering, concurrency)
- Documentation, examples, and test coverage

Open an issue to discuss approach before larger changes.
