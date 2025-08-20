#!/usr/bin/env python3
"""
ElevenLabs Token Extractor

Extracts authentication tokens and identifiers from mitmproxy flows for use
with the ElevenLabs TTS client. Prefer parsing via mitmproxy's FlowReader for
accurate header extraction; fall back to textual scanning (strings/regex).
"""

import re
import sys
import json
from pathlib import Path
import subprocess


def extract_bearer_token(flows_data):
    """Extract ElevenLabs Bearer token from flows"""
    # Look for Bearer tokens in Authorization headers
    bearer_pattern = r'Bearer\s+(eyJ[A-Za-z0-9\-_=]+\.eyJ[A-Za-z0-9\-_=]+\.[A-Za-z0-9\-_=]+)'
    
    matches = re.findall(bearer_pattern, flows_data)
    if matches:
        # Return the first (and likely only) Bearer token found
        return matches[0]
    
    return None


def extract_firebase_refresh_token(flows_data):
    """Extract Firebase refresh token from flows"""
    # Look for Firebase refresh token in requests
    refresh_pattern = r'"refreshToken":\s*"([A-Za-z0-9\-_]+)"'
    
    matches = re.findall(refresh_pattern, flows_data)
    if matches:
        return matches[0]
    
    return None


def extract_device_id(flows_data, flows_path: Path = None):
    """Extract device ID from flows; fall back to strings scan."""
    device_pattern = r'device-id["\s:]+([A-F0-9\-]{36})'
    matches = re.findall(device_pattern, flows_data, re.IGNORECASE)
    if matches:
        return matches[0].upper()
    # Fallback: strings scan
    try:
        if flows_path and flows_path.exists():
            res = subprocess.run(["strings", "-n", "6", str(flows_path)], capture_output=True, text=True)
            if res.returncode == 0 and res.stdout:
                m = re.search(r"device-id.*?([A-F0-9]{8}-[A-F0-9]{4}-[A-F0-9]{4}-[A-F0-9]{4}-[A-F0-9]{12})", res.stdout, re.IGNORECASE)
                if m:
                    return m.group(1).upper()
    except Exception:
        pass
    return None


def extract_voice_endpoints(flows_data):
    """Extract voice-related API endpoints from flows"""
    voice_endpoints = []
    
    # Look for voice endpoints
    endpoint_patterns = [
        r'/v1/reader/voices',
        r'/v1/reader/voices/explore',
        r'/v1/reader/voices/v2/home',
        r'/v1/coreapp/voices'
    ]
    
    for pattern in endpoint_patterns:
        if pattern in flows_data:
            voice_endpoints.append(pattern)
    
    return list(set(voice_endpoints))  # Remove duplicates


def extract_app_check_token(flows_data, flows_path: Path = None):
    """Extract xi-app-check-token from flows"""
    m = re.search(r"xi-app-check-token\s*:\s*([A-Za-z0-9_\-\.]+)\b", flows_data)
    if m:
        return m.group(1)
    # Fallback: strings scan
    try:
        if flows_path and flows_path.exists():
            res = subprocess.run(["strings", "-n", "6", str(flows_path)], capture_output=True, text=True)
            if res.returncode == 0 and res.stdout:
                for line in res.stdout.splitlines():
                    if "xi-app-check-token" in line:
                        parts = re.split(r"xi-app-check-token\s*[:\s]+", line, maxsplit=1)
                        if len(parts) == 2:
                            cand = parts[1].strip()
                            m2 = re.match(r"([A-Za-z0-9_\-\.]+)", cand)
                            if m2:
                                return m2.group(1)
    except Exception:
        pass
    return None


def extract_firebase_api_key(flows_data):
    """Extract Firebase API key from flows"""
    api_key_pattern = r'key=([A-Za-z0-9\-_]+)'
    
    matches = re.findall(api_key_pattern, flows_data)
    if matches:
        # Look for the specific Firebase API key pattern
        for match in matches:
            if match.startswith('AIza'):
                return match
    
    return None


def extract_workspace_id(flows_data):
    """Extract workspace ID from JWT token payload"""
    bearer_token = extract_bearer_token(flows_data)
    if not bearer_token:
        return None
    
    try:
        # JWT tokens have three parts separated by dots
        parts = bearer_token.split('.')
        if len(parts) >= 2:
            # Decode the payload (second part)
            import base64
            # Add padding if needed
            payload = parts[1]
            padding = 4 - len(payload) % 4
            if padding != 4:
                payload += '=' * padding
            
            decoded = base64.b64decode(payload)
            payload_data = json.loads(decoded)
            
            return payload_data.get('workspace_id')
    except:
        pass
    
    return None


def try_parse_with_mitmproxy(flows_file: Path):
    """Try to parse flows via mitmproxy to get exact headers.

    Returns dict with any of: bearer_token, device_id, xi_app_check_token
    """
    try:
        from mitmproxy import io, http
    except Exception:
        return {}

    result = {}
    try:
        with open(flows_file, "rb") as f:
            reader = io.FlowReader(f)
            for flow in reader.stream():
                if not isinstance(flow, http.HTTPFlow):
                    continue
                # Prefer WebSocket stream requests
                path = flow.request.path or ""
                headers = flow.request.headers or {}
                lower = {k.lower(): v for k, v in headers.items()}
                if "/v1/reader/reads/stream/" in path:
                    # Authorization bearer
                    auth = lower.get("authorization")
                    if auth and auth.lower().startswith("bearer "):
                        result.setdefault("bearer_token", auth.split(" ", 1)[1])
                    # Device ID
                    did = lower.get("device-id")
                    if did:
                        result.setdefault("device_id", did)
                    # App Check token
                    appchk = lower.get("xi-app-check-token")
                    if appchk:
                        result.setdefault("xi_app_check_token", appchk)
                # Fallback: any request may include device-id/app-check
                if "device-id" in lower and "device_id" not in result:
                    result["device_id"] = lower["device-id"]
                if "xi-app-check-token" in lower and "xi_app_check_token" not in result:
                    result["xi_app_check_token"] = lower["xi-app-check-token"]
    except Exception:
        return result
    return result


def print_summary(extracted_data):
    """Print a summary of extracted data"""
    print("🔍 ElevenLabs Token Extraction Results")
    print("=" * 50)
    
    if extracted_data['bearer_token']:
        print(f"✅ Bearer Token: {extracted_data['bearer_token'][:50]}...")
        print(f"   Full Length: {len(extracted_data['bearer_token'])} characters")
    else:
        print("❌ Bearer Token: Not found")
    
    if extracted_data['firebase_refresh_token']:
        print(f"✅ Firebase Refresh Token: {extracted_data['firebase_refresh_token'][:50]}...")
        print(f"   Full Length: {len(extracted_data['firebase_refresh_token'])} characters")
    else:
        print("❌ Firebase Refresh Token: Not found")
    
    if extracted_data['firebase_api_key']:
        print(f"✅ Firebase API Key: {extracted_data['firebase_api_key']}")
    else:
        print("❌ Firebase API Key: Not found")
    
    if extracted_data['device_id']:
        print(f"✅ Device ID: {extracted_data['device_id']}")
    else:
        print("❌ Device ID: Not found")
    
    if extracted_data['workspace_id']:
        print(f"✅ Workspace ID: {extracted_data['workspace_id']}")
    else:
        print("❌ Workspace ID: Not found")
    
    if extracted_data['voice_endpoints']:
        print("✅ Voice Endpoints Found:")
        for endpoint in extracted_data['voice_endpoints']:
            print(f"   • {endpoint}")
    else:
        print("❌ Voice Endpoints: Not found")


def generate_usage_examples(extracted_data):
    """Generate usage examples for the TTS client"""
    print("\n🚀 Usage Examples")
    print("=" * 50)
    
    bearer_token = extracted_data['bearer_token']
    firebase_token = extracted_data['firebase_refresh_token']
    
    if bearer_token:
        print("# Basic usage with Bearer token:")
        print(f'./elevenlabs_tts_client.py \\')
        print(f'  --bearer-token "{bearer_token}" \\')
        print(f'  --voice-id "JBFqnCBsd6RMkjVDRZzb" \\')
        print(f'  --text "Hello world" \\')
        print(f'  --play')
        print()
        
        if firebase_token:
            print("# Advanced usage with Firebase authentication:")
            print(f'./elevenlabs_tts_client.py \\')
            print(f'  --bearer-token "{bearer_token}" \\')
            print(f'  --firebase-refresh-token "{firebase_token}" \\')
            print(f'  --voice-id "JBFqnCBsd6RMkjVDRZzb" \\')
            print(f'  --text "Hello world" \\')
            print(f'  --output "output.mp3" \\')
            print(f'  --play')
            print()
        
        print("# List available voices:")
        print(f'./elevenlabs_tts_client.py \\')
        print(f'  --bearer-token "{bearer_token}" \\')
        print(f'  --voice-id "dummy" \\')
        print(f'  --list-voices')
        print()
        
        print("# Read from file:")
        print(f'echo "Your text here" > input.txt')
        print(f'./elevenlabs_tts_client.py \\')
        print(f'  --bearer-token "{bearer_token}" \\')
        print(f'  --voice-id "JBFqnCBsd6RMkjVDRZzb" \\')
        print(f'  --file input.txt \\')
        print(f'  --output "speech.mp3"')
        print()
    else:
        print("❌ Cannot generate examples - Bearer token not found")


def save_tokens_to_file(extracted_data, output_file):
    """Save extracted tokens to a JSON file"""
    with open(output_file, 'w') as f:
        json.dump(extracted_data, f, indent=2)
    print(f"\n💾 Tokens saved to: {output_file}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python extract_tokens.py <flows_file> [output.json]")
        print("Example: python extract_tokens.py flows.elevenlabsio tokens.json")
        sys.exit(1)
    
    flows_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else "extracted_tokens.json"
    
    if not Path(flows_file).exists():
        print(f"❌ Error: Flows file '{flows_file}' not found")
        sys.exit(1)
    
    print(f"📄 Reading flows from: {flows_file}")
    
    # Read the flows file as binary to handle any encoding issues
    try:
        with open(flows_file, 'rb') as f:
            flows_data = f.read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"❌ Error reading flows file: {e}")
        sys.exit(1)

    # Extract all the data
    flows_path = Path(flows_file)
    extracted_data = {
        'bearer_token': extract_bearer_token(flows_data),
        'firebase_refresh_token': extract_firebase_refresh_token(flows_data),
        'firebase_api_key': extract_firebase_api_key(flows_data),
        'device_id': extract_device_id(flows_data, flows_path),
        'workspace_id': extract_workspace_id(flows_data),
        'voice_endpoints': extract_voice_endpoints(flows_data),
        'xi_app_check_token': extract_app_check_token(flows_data, flows_path),
        'extraction_timestamp': int(flows_path.stat().st_mtime),
        'flows_file': flows_file
    }

    # Try mitmproxy header extraction if App Check or Device ID missing
    if not extracted_data.get('device_id') or not extracted_data.get('xi_app_check_token'):
        via_mitm = try_parse_with_mitmproxy(flows_path)
        # Only fill missing fields
        for k in ('device_id', 'xi_app_check_token', 'bearer_token'):
            if via_mitm.get(k) and not extracted_data.get(k):
                extracted_data[k] = via_mitm[k]
    
    # Print summary
    print_summary(extracted_data)
    
    # Generate usage examples
    generate_usage_examples(extracted_data)
    
    # Save to file
    save_tokens_to_file(extracted_data, output_file)
    
    print("\n🎉 Token extraction completed!")
    print(f"📋 Next steps:")
    print(f"   1. Use the Bearer token with the TTS client")
    print(f"   2. Optional: Use Firebase refresh token for auto-renewal")
    print(f"   3. Run --list-voices to see available voice IDs")
    print(f"   4. Start generating speech with your preferred voice!")


if __name__ == "__main__":
    main()
