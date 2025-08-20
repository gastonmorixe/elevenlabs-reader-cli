# ws_flows_to_jsonl.py
import sys, json
from mitmproxy.io import FlowReader

if len(sys.argv) < 3:
    print("Usage: python ws_flows_to_jsonl.py <flows-file> <out-jsonl> [host_filter] [path_prefix]")
    sys.exit(1)

flows_path = sys.argv[1]
out_path   = sys.argv[2]
host_filter = sys.argv[3] if len(sys.argv) > 3 else ""
path_prefix = sys.argv[4] if len(sys.argv) > 4 else ""

def want(flow):
    if host_filter and getattr(flow.request, "host", "") != host_filter:
        return False
    if path_prefix and not getattr(flow.request, "path", "").startswith(path_prefix):
        return False
    return True

count = 0
with open(flows_path, "rb") as f, open(out_path, "w", encoding="utf-8") as out:
    for flow in FlowReader(f).stream():
        ws = getattr(flow, "websocket", None)
        if not ws or not want(flow):
            continue
        for msg in ws.messages:
            try:
                text = msg.content.decode("utf-8")
                obj = json.loads(text)
            except Exception:
                continue
            obj["_dir"] = "out" if getattr(msg, "from_client", False) else "in"
            ts = getattr(msg, "timestamp", None) or getattr(msg, "time", None)
            if ts is not None:
                obj["_ts"] = ts
            out.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n")
            count += 1

print(f"Wrote {count} JSON frames to {out_path}")