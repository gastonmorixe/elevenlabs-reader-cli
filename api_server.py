#!/usr/bin/env python3
"""
Local FastAPI server that exposes a lightweight HTTP API for the ElevenLabs
Reader workflow. It wraps the existing CLI client so other tools (e.g. browser
extensions) can push text to the Reader pipeline without shelling out.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import logging
import os
import textwrap
import time
import uuid
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import json as json_module
import ssl
import aiohttp
import websockets

from elevenlabs_tts_client import ElevenLabsTTSClient
from token_manager import TokenManager

ALLOWED_METHODS = {"reader", "http", "websocket", "auto"}
DEFAULT_METHOD = os.environ.get("ELEVEN_DEFAULT_METHOD", "reader").lower()  # reader uses Reader subscription (24hr/day)
DEFAULT_VOICE_ID = os.environ.get("ELEVEN_DEFAULT_VOICE_ID", 'nPczCjzI2devNBz1zQrb')
MAX_TEXT_LENGTH = int(os.environ.get("ELEVEN_API_MAX_TEXT", "500000"))  # Reader handles any length
CACHE_FILE = os.environ.get("ELEVEN_CACHE_FILE", "tokens_cache.json")
AUDIO_CACHE_DIR = Path(os.environ.get("ELEVEN_AUDIO_CACHE_DIR", "tmp/audio"))
SAVE_AUDIO = os.environ.get("ELEVEN_SAVE_AUDIO", "1").lower() in {"1", "true", "yes"}
VERBOSE_LOGS = os.environ.get("ELEVEN_API_VERBOSE", "0").lower() in {"1", "true", "yes"}
ALLOWED_ORIGINS_RAW = os.environ.get(
    "ELEVEN_API_ALLOWED_ORIGINS", "http://localhost:8011,http://127.0.0.1:8011,moz-extension://*,*"
)
ALLOWED_ORIGINS = [origin.strip() for origin in ALLOWED_ORIGINS_RAW.split(",") if origin.strip()]

LOG_LEVEL = os.environ.get("ELEVEN_API_LOG_LEVEL", "INFO").upper()
logger = logging.getLogger("elevenlabs.api")
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))

token_manager = TokenManager(cache_file=CACHE_FILE, verbose=VERBOSE_LOGS)
token_lock = asyncio.Lock()


class ReadRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_TEXT_LENGTH, description="Plain text to send to Eleven Reader")
    voice_id: Optional[str] = Field(
        None, description="Override the default voice id configured on the server"
    )
    method: Optional[str] = Field(
        None, description="Streaming method: http (default, uses Pro), reader, websocket, auto"
    )
    save_audio: Optional[bool] = Field(
        None, description="Save audio to tmp/audio/ (defaults to server setting ELEVEN_SAVE_AUDIO)"
    )
    karaoke: bool = Field(False, description="Enable karaoke preview in the server logs")
    karaoke_before: int = Field(8, ge=0, le=50, description="Words to show before current word when karaoke is on")
    karaoke_after: int = Field(8, ge=0, le=50, description="Words to show after current word when karaoke is on")


class ReadResponse(BaseModel):
    voice_id: str
    method: str
    byte_length: int
    mime_type: str
    audio_base64: str = Field(description="Base64 encoded audio (MP3)")
    duration_seconds: float
    text_preview: str
    saved_path: Optional[str] = Field(None, description="Path to saved audio file (if save_audio enabled)")


app = FastAPI(
    title="ElevenLabs Reader Local API",
    version="0.1.0",
    description="Expose ElevenLabs Reader features over HTTP for local integrations.",
)

allow_all = "*" in ALLOWED_ORIGINS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if allow_all else ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _get_refresh_token() -> str:
    env_token = os.environ.get("FIREBASE_REFRESH_TOKEN")
    if env_token:
        return env_token.strip()
    cache = token_manager.load_cache()
    cached = cache.get("firebase_refresh_token")
    if cached:
        return cached
    raise RuntimeError(
        "FIREBASE_REFRESH_TOKEN is not set and no cached token was found. "
        "Either export FIREBASE_REFRESH_TOKEN or populate the cache via ./tts first."
    )


async def _get_bearer_token(refresh_token: str) -> str:
    async with token_lock:
        bearer = await asyncio.to_thread(token_manager.get_fresh_bearer_token, refresh_token)
    if not bearer:
        raise RuntimeError("Unable to refresh Firebase bearer token. Check your FIREBASE_REFRESH_TOKEN value.")
    return bearer


async def _get_app_check_token() -> Optional[str]:
    env_token = os.environ.get("XI_APP_CHECK_TOKEN")
    if env_token:
        await asyncio.to_thread(token_manager.set_app_check_token, env_token)
        return env_token
    return await asyncio.to_thread(token_manager.get_app_check_token)


async def _get_device_id() -> str:
    env_device = os.environ.get("ELEVEN_DEVICE_ID")
    if env_device:
        upper = env_device.strip().upper()
        await asyncio.to_thread(token_manager.set_device_id, upper)
        return upper

    cached = await asyncio.to_thread(token_manager.get_device_id)
    if cached:
        return cached

    generated = str(uuid.uuid4()).upper()
    await asyncio.to_thread(token_manager.set_device_id, generated)
    return generated


async def _build_client() -> ElevenLabsTTSClient:
    refresh_token = _get_refresh_token()
    bearer_token = await _get_bearer_token(refresh_token)
    app_check_token = await _get_app_check_token()
    device_id = await _get_device_id()
    return ElevenLabsTTSClient(
        bearer_token=bearer_token,
        verbose=VERBOSE_LOGS,
        app_check_token=app_check_token,
        device_id=device_id,
    )


@app.get("/healthz")
async def healthcheck():
    """Lightweight readiness endpoint so the browser add-on can verify connectivity."""
    try:
        refresh_present = bool(_get_refresh_token())
    except RuntimeError:
        refresh_present = False

    return {
        "status": "ok" if refresh_present else "missing-refresh-token",
        "default_voice_id": DEFAULT_VOICE_ID,
        "default_method": DEFAULT_METHOD,
        "max_text_length": MAX_TEXT_LENGTH,
        "refresh_token_configured": refresh_present,
    }


@app.get("/api/voices")
async def list_voices():
    """Proxy the CLI voice listing endpoint."""
    client = await _build_client()
    try:
        voices = await client.get_voices()
    except Exception as exc:  # pragma: no cover - network errors are surfaced
        logger.exception("Failed to fetch voices from ElevenLabs")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return voices


@app.post("/api/read", response_model=ReadResponse)
async def create_read(request: ReadRequest):
    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text payload is empty.")

    if len(text) > MAX_TEXT_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Text must be <= {MAX_TEXT_LENGTH} characters (received {len(text)}).",
        )

    voice_id = request.voice_id or DEFAULT_VOICE_ID
    if not voice_id:
        raise HTTPException(
            status_code=400,
            detail="voice_id is required. Provide it in the request or set ELEVEN_DEFAULT_VOICE_ID.",
        )

    method = (request.method or DEFAULT_METHOD).lower()
    if method not in ALLOWED_METHODS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported method '{method}'. Allowed values: {sorted(ALLOWED_METHODS)}",
        )

    # Determine output file path if saving is enabled
    saved_path: Optional[str] = None
    should_save = request.save_audio if request.save_audio is not None else SAVE_AUDIO
    output_file: Optional[str] = None
    if should_save:
        AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        text_hash = hashlib.sha256(text.encode()).hexdigest()[:12]
        timestamp = int(time.time())
        filename = f"{timestamp}_{text_hash}_{voice_id[:8]}.mp3"
        output_file = str(AUDIO_CACHE_DIR / filename)

    client = await _build_client()
    started = time.perf_counter()
    try:
        audio_bytes = await client.stream_with_websocket(
            text=text,
            voice_id=voice_id,
            output_file=output_file,  # Let CLI save during streaming
            method=method,
            play_audio=False,
            show_karaoke=request.karaoke,
            karaoke_before=request.karaoke_before,
            karaoke_after=request.karaoke_after,
        )
    except Exception as exc:  # pragma: no cover - network errors are surfaced
        logger.exception("Reader streaming failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if not audio_bytes:
        raise HTTPException(status_code=500, detail="ElevenLabs returned no audio data.")

    elapsed = round(time.perf_counter() - started, 3)
    preview = textwrap.shorten(text, width=140, placeholder="...")
    audio_base64 = base64.b64encode(audio_bytes).decode("ascii")

    if output_file:
        saved_path = output_file
        logger.info("Saved audio to %s", saved_path)

    logger.info(
        "Generated %s bytes via %s in %ss",
        len(audio_bytes),
        method,
        elapsed,
    )

    return ReadResponse(
        voice_id=voice_id,
        method=method,
        byte_length=len(audio_bytes),
        mime_type="audio/mpeg",
        audio_base64=audio_base64,
        duration_seconds=elapsed,
        text_preview=preview,
        saved_path=saved_path,
    )


class StreamRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_TEXT_LENGTH, description="Plain text to stream")
    voice_id: Optional[str] = Field(None, description="Override the default voice id")
    save_audio: Optional[bool] = Field(None, description="Save audio to tmp/audio/")


async def _stream_reader_chunks(text: str, voice_id: str, save_path: Optional[str] = None):
    """
    Generator that yields SSE events with audio chunks as they arrive from ElevenLabs Reader.
    Each event is: data: {"type": "chunk"|"done"|"error", ...}\n\n
    """
    refresh_token = _get_refresh_token()
    bearer_token = await _get_bearer_token(refresh_token)
    app_check_token = await _get_app_check_token()
    device_id = await _get_device_id()
    
    # Build headers for Reader API
    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "User-Agent": "readerapp/405 CFNetwork/3860.100.1 Darwin/25.0.0",
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9",
        "device-id": device_id,
        "Origin": "https://elevenlabs.io",
    }
    if app_check_token:
        headers["xi-app-check-token"] = app_check_token
    
    # Step 1: Create the read document
    try:
        read_id = await _create_read_document(text, bearer_token)
        if not read_id:
            yield f"data: {json_module.dumps({'type': 'error', 'message': 'Failed to create read document'})}\n\n"
            return
        yield f"data: {json_module.dumps({'type': 'status', 'message': 'Document created', 'read_id': read_id})}\n\n"
    except Exception as e:
        yield f"data: {json_module.dumps({'type': 'error', 'message': str(e)})}\n\n"
        return
    
    # Step 2: Wait for document processing
    try:
        await _wait_for_document_ready(read_id, bearer_token, max_wait=60)
        yield f"data: {json_module.dumps({'type': 'status', 'message': 'Document ready'})}\n\n"
    except Exception as e:
        yield f"data: {json_module.dumps({'type': 'error', 'message': f'Document processing failed: {e}'})}\n\n"
        return
    
    # Step 3: Stream audio via WebSocket with multi-connection support (like the CLI)
    ws_url = f"wss://api.elevenlabs.io/v1/reader/reads/stream/{read_id}?voice_id={voice_id}"
    all_audio = b""
    chunk_count = 0
    current_position = 0
    abs_char_pos = 0  # Track character position for multi-connection
    connection_number = 0
    
    # Get document length to know when we're done
    total_chars = None
    try:
        doc_url = f"https://api.elevenlabs.io/v1/reader/reads/{read_id}"
        ssl_ctx = ssl.create_default_context()
        conn = aiohttp.TCPConnector(ssl=ssl_ctx)
        async with aiohttp.ClientSession(connector=conn) as session:
            async with session.get(doc_url, headers={"Authorization": f"Bearer {bearer_token}", "User-Agent": "readerapp/405"}) as resp:
                if resp.status == 200:
                    doc_data = await resp.json()
                    total_chars = doc_data.get("char_count") or doc_data.get("content_length")
    except Exception:
        pass  # Continue without knowing total length
    
    BUDGET_TARGET = 1348  # Per-connection character budget from flow analysis
    idle_timeout = 1.5
    max_connections = 50  # Safety limit
    
    while connection_number < max_connections:
        connection_number += 1
        cumulative_chars = 0
        connection_chunks = 0
        
        try:
            async with websockets.connect(ws_url, additional_headers=headers, ping_timeout=300) as websocket:
                message = {"stream_id": str(uuid.uuid4()).upper(), "position": current_position}
                await websocket.send(json_module.dumps(message))
                
                while True:
                    try:
                        msg = await asyncio.wait_for(websocket.recv(), timeout=idle_timeout)
                    except asyncio.TimeoutError:
                        # Idle timeout - if we got data this connection, rollover
                        if cumulative_chars > 0:
                            break
                        continue
                    
                    try:
                        data = json_module.loads(msg)
                        
                        # Track alignment for position
                        alignment = data.get("alignment")
                        seg_chars = 0
                        if isinstance(alignment, dict) and "chars" in alignment:
                            seg_chars = len(alignment.get("chars") or [])
                            cumulative_chars += seg_chars
                        
                        # Check for audio chunk
                        if "audio" in data and data["audio"]:
                            chunk = base64.b64decode(data["audio"])
                            all_audio += chunk
                            chunk_count += 1
                            connection_chunks += 1
                            
                            # Yield the chunk immediately
                            chunk_b64 = base64.b64encode(chunk).decode("ascii")
                            yield f"data: {json_module.dumps({'type': 'chunk', 'audio': chunk_b64, 'chunk_num': chunk_count, 'bytes': len(chunk)})}\n\n"
                            
                            # Update position
                            if seg_chars > 0:
                                abs_char_pos = current_position + cumulative_chars
                        
                        # Check for final message
                        if data.get("isFinal", False):
                            break
                        
                        # Budget-based rollover
                        if cumulative_chars >= BUDGET_TARGET:
                            break
                            
                    except json_module.JSONDecodeError:
                        if isinstance(msg, bytes):
                            all_audio += msg
                            chunk_count += 1
                            chunk_b64 = base64.b64encode(msg).decode("ascii")
                            yield f"data: {json_module.dumps({'type': 'chunk', 'audio': chunk_b64, 'chunk_num': chunk_count, 'bytes': len(msg)})}\n\n"
                
                # Update position for next connection
                current_position = abs_char_pos if abs_char_pos > current_position else current_position + cumulative_chars
                
                # Check if we're done
                if total_chars and current_position >= total_chars:
                    break
                    
                # If no chunks this connection and we've had some before, we're done
                if connection_chunks == 0 and chunk_count > 0:
                    break
                    
        except websockets.exceptions.ConnectionClosed:
            # Connection closed, try to reconnect if we haven't finished
            if total_chars and current_position >= total_chars:
                break
            if chunk_count > 0 and connection_chunks == 0:
                break
            continue
        except Exception as e:
            yield f"data: {json_module.dumps({'type': 'error', 'message': f'WebSocket error: {e}'})}\n\n"
            break
    
    # Save audio if requested
    saved_path = None
    if save_path and all_audio:
        try:
            Path(save_path).parent.mkdir(parents=True, exist_ok=True)
            Path(save_path).write_bytes(all_audio)
            saved_path = save_path
        except Exception as e:
            logger.warning(f"Failed to save audio: {e}")
    
    # Final event
    yield f"data: {json_module.dumps({'type': 'done', 'total_bytes': len(all_audio), 'chunks': chunk_count, 'saved_path': saved_path})}\n\n"


async def _create_read_document(text: str, bearer_token: str) -> Optional[str]:
    """Create a read document in the Reader library."""
    url = "https://api.elevenlabs.io/v1/reader/reads/add/v2"
    
    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "User-Agent": "readerapp/405 CFNetwork/3860.100.1 Darwin/25.0.0",
        "Content-Type": "multipart/form-data; boundary=XI-COOL-BOUNDARY",
    }
    
    from datetime import datetime
    boundary = "XI-COOL-BOUNDARY"
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
    )
    
    ssl_context = ssl.create_default_context()
    connector = aiohttp.TCPConnector(ssl=ssl_context)
    timeout = aiohttp.ClientTimeout(total=30)
    
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        async with session.post(url, headers=headers, data=form_data.encode()) as response:
            if response.status not in (200, 201):
                text_resp = await response.text()
                raise Exception(f"Create read failed: {response.status} {text_resp[:200]}")
            data = await response.json()
            return data.get("read_id") or data.get("id")


async def _wait_for_document_ready(read_id: str, bearer_token: str, max_wait: int = 60):
    """Poll until document is ready for streaming using simple-html endpoint."""
    url = f"https://api.elevenlabs.io/v1/reader/reads/{read_id}/simple-html?make_pageable=false"
    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "User-Agent": "readerapp/405 CFNetwork/3860.100.1 Darwin/25.0.0",
    }
    
    ssl_context = ssl.create_default_context()
    connector = aiohttp.TCPConnector(ssl=ssl_context)
    timeout = aiohttp.ClientTimeout(total=10)
    
    start = time.time()
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        while time.time() - start < max_wait:
            try:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        # simple-html available means document is ready
                        return
            except Exception:
                pass  # Retry on connection errors
            await asyncio.sleep(1.0)
    raise Exception("Document processing timeout")


@app.post("/api/stream")
async def stream_read(request: StreamRequest):
    """
    SSE endpoint that streams audio chunks as they arrive from ElevenLabs Reader.
    Returns Server-Sent Events with JSON payloads.
    """
    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text payload is empty.")
    
    if len(text) > MAX_TEXT_LENGTH:
        raise HTTPException(status_code=400, detail=f"Text must be <= {MAX_TEXT_LENGTH} characters.")
    
    voice_id = request.voice_id or DEFAULT_VOICE_ID
    if not voice_id:
        raise HTTPException(status_code=400, detail="voice_id is required.")
    
    # Determine save path
    save_path = None
    should_save = request.save_audio if request.save_audio is not None else SAVE_AUDIO
    if should_save:
        AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        text_hash = hashlib.sha256(text.encode()).hexdigest()[:12]
        timestamp = int(time.time())
        filename = f"{timestamp}_{text_hash}_{voice_id[:8]}.mp3"
        save_path = str(AUDIO_CACHE_DIR / filename)
    
    return StreamingResponse(
        _stream_reader_chunks(text, voice_id, save_path),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def main():
    parser = argparse.ArgumentParser(description="Run the ElevenLabs Reader FastAPI server.")
    parser.add_argument("--host", default=os.environ.get("ELEVEN_API_HOST", "127.0.0.1"), help="Bind host")
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("ELEVEN_API_PORT", "8011")), help="Port to listen on"
    )
    parser.add_argument(
        "--log-level", default=os.environ.get("ELEVEN_API_LOG_LEVEL", "info"), help="Uvicorn log level"
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        default=os.environ.get("ELEVEN_API_RELOAD", "0").lower() in {"1", "true", "yes"},
        help="Enable auto-reload (dev only)",
    )
    args = parser.parse_args()

    logger.info("Starting ElevenLabs Reader API on %s:%s", args.host, args.port)
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level=args.log_level,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()

