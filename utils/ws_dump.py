# ws_dump.py  (compatible across mitmproxy versions)
from mitmproxy import ctx
import json, base64

def _b64_to_mp3(b64s: str) -> bytes:
    import base64
    return base64.b64decode(b64s)

class WSDump:
    def websocket_start(self, flow):
        # Some versions call this as the WS channel opens
        sc = getattr(flow, "server_conn", None)
        addr = getattr(sc, "address", None)
        ctx.log.info(f"[WS START] {addr or 'unknown'}")

    def websocket_message(self, flow):
        # Works during live capture; in replay, mitmproxy replays messages and still calls this
        try:
            msg = flow.messages[-1]      # last WebSocket message on this flow
        except Exception:
            ctx.log.warn("No messages on this flow yet")
            return

        direction = "->" if getattr(msg, "from_client", False) else "<-"
        content = getattr(msg, "content", b"")
        # Many mitmproxy builds store text frames as 'content' bytes
        try:
            text = content.decode("utf-8", errors="strict")
        except Exception:
            ctx.log.info(f"[{direction}] non-text frame ({len(content)} bytes)")
            return

        try:
            data = json.loads(text)
        except Exception:
            ctx.log.info(f"[{direction}] text frame (non-JSON): {text[:120]}...")
            return

        if isinstance(data, dict) and "audio" in data and isinstance(data["audio"], str):
            try:
                chunk = _b64_to_mp3(data["audio"])
                with open("ws_audio.mp3", "ab") as f:
                    f.write(chunk)
                sid = data.get("streamId") or data.get("stream_id")
                ctx.log.info(f"[{direction}] audio chunk {len(chunk)} bytes streamId={sid}")
            except Exception as e:
                ctx.log.warn(f"audio base64 decode failed: {e}")
        else:
            ctx.log.info(f"[{direction}] event: {data}")

    def websocket_end(self, flow):
        code  = getattr(flow, "close_code", None)
        reason = getattr(flow, "close_reason", None)
        ctx.log.info(f"[WS END] close_code={code} reason={reason!r}")

# Also handle offline replays that may not invoke websocket_* hooks on some versions:
def done():
    """
    Called when mitmdump finishes processing all flows (works with -nr).
    Try to walk flows and extract any WS messages missed by hooks.
    """
    try:
        from mitmproxy import dump
        # Not needed; mitmproxy passes flows to hooks already.
        # This is a no-op safeguard to keep 'done' available.
    except Exception:
        pass

addons = [WSDump()]