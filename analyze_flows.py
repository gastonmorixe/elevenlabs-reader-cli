#!/usr/bin/env python3
"""
Mitmproxy Flow Analyzer for ElevenLabs Reader App

This script analyzes captured mitmproxy flows to understand the WebSocket
streaming protocol used by the ElevenLabs Reader app for free audio generation.
"""

import json
import sys
import base64
import re
from pathlib import Path
from typing import Dict, List, Any, Optional
from mitmproxy import io, http
from mitmproxy.exceptions import FlowReadException


class FlowAnalyzer:
    """Analyzes mitmproxy flows to extract WebSocket streaming patterns"""
    
    def __init__(self, flows_file: str, verbose: bool = False):
        self.flows_file = flows_file
        self.verbose = verbose
        self.websocket_flows = []
        self.http_flows = []
        self.audio_chunks = []
        self.json_messages = []
        
    def load_flows(self) -> bool:
        """Load flows from mitmproxy dump file"""
        try:
            with open(self.flows_file, "rb") as f:
                flow_reader = io.FlowReader(f)
                
                for flow in flow_reader.stream():
                    if isinstance(flow, http.HTTPFlow):
                        # Check if this is a WebSocket flow
                        if hasattr(flow, 'websocket') and flow.websocket:
                            self.websocket_flows.append(flow)
                            if self.verbose:
                                print(f"🔍 Found WebSocket flow: {flow.request.pretty_url}")
                        else:
                            # Regular HTTP flow
                            if 'elevenlabs' in flow.request.host:
                                self.http_flows.append(flow)
                                if self.verbose:
                                    print(f"🌐 Found HTTP flow: {flow.request.pretty_url}")
                            
            print(f"📊 Loaded {len(self.websocket_flows)} WebSocket flows and {len(self.http_flows)} HTTP flows")
            return True
            
        except FlowReadException as e:
            print(f"❌ Flow file corrupted: {e}")
            return False
        except Exception as e:
            print(f"❌ Error loading flows: {e}")
            return False
    
    def analyze_websocket_flows(self):
        """Analyze WebSocket flows for audio streaming patterns"""
        print("\n🔍 Analyzing WebSocket Flows")
        print("=" * 50)
        
        for i, flow in enumerate(self.websocket_flows):
            print(f"\n📡 WebSocket Flow {i+1}")
            print(f"URL: {flow.request.pretty_url}")
            print(f"Host: {flow.request.host}")
            print(f"Path: {flow.request.path}")
            
            # Analyze request headers
            print("\n📤 Request Headers:")
            important = ['authorization', 'user-agent', 'origin', 'sec-websocket-protocol', 'xi-app-check-token', 'device-id', 'accept-language', 'accept-encoding']
            for name, value in flow.request.headers.items():
                if name.lower() in important:
                    display_value = value[:80] + "..." if len(value) > 80 else value
                    print(f"  {name}: {display_value}")
            
            # Analyze WebSocket messages
            if flow.websocket and flow.websocket.messages:
                print(f"\n💬 WebSocket Messages: {len(flow.websocket.messages)}")
                
                for j, message in enumerate(flow.websocket.messages):
                    self._analyze_websocket_message(j, message)
                    
                    # Limit output for readability
                    if j >= 10 and not self.verbose:
                        remaining = len(flow.websocket.messages) - j - 1
                        if remaining > 0:
                            print(f"  ... and {remaining} more messages")
                        break
    
    def _analyze_websocket_message(self, index: int, message):
        """Analyze individual WebSocket message"""
        try:
            content = message.content
            from_client = message.from_client
            direction = "→" if from_client else "←"
            
            print(f"  {direction} Message {index+1} ({'client' if from_client else 'server'})")
            print(f"    Type: {message.type.name if hasattr(message.type, 'name') else message.type}")
            print(f"    Size: {len(content)} bytes")
            
            # Try to parse as JSON if it's a text message
            if message.is_text:
                try:
                    json_data = json.loads(message.text)
                    self.json_messages.append(json_data)
                    
                    print(f"    JSON keys: {list(json_data.keys())}")
                    
                    # Look for audio data
                    if 'audio' in json_data:
                        audio_b64 = json_data['audio']
                        if audio_b64:
                            try:
                                audio_data = base64.b64decode(audio_b64)
                                print(f"    🎵 Audio chunk: {len(audio_data)} bytes")
                                self.audio_chunks.append({
                                    'size': len(audio_data),
                                    'b64_length': len(audio_b64),
                                    'message_index': index,
                                    'from_client': from_client,
                                    'stream_id': json_data.get('streamId') or json_data.get('stream_id'),
                                    'position': json_data.get('position'),
                                    'timestamp': message.timestamp
                                })
                            except Exception:
                                print(f"    ⚠️ Invalid base64 audio data")
                    
                    # Look for stream metadata
                    if 'streamId' in json_data or 'stream_id' in json_data:
                        stream_id = json_data.get('streamId') or json_data.get('stream_id')
                        print(f"    🆔 Stream ID: {stream_id}")
                    
                    if 'position' in json_data:
                        print(f"    📍 Position: {json_data['position']}")
                    
                    # Print important fields
                    important_fields = ['text', 'voice_id', 'model_id', 'isFinal', 'error']
                    for field in important_fields:
                        if field in json_data:
                            value = json_data[field]
                            if isinstance(value, str) and len(value) > 100:
                                value = value[:100] + "..."
                            print(f"    {field}: {value}")
                            
                except json.JSONDecodeError:
                    # Text but not JSON
                    text_preview = message.text[:200] + "..." if len(message.text) > 200 else message.text
                    print(f"    Text: {text_preview}")
            else:
                # Binary message
                print(f"    Binary data: {len(content)} bytes")
                # Check if it might be audio data
                if content.startswith(b'ID3') or content.startswith(b'\xff\xfb'):
                    print(f"    🎵 Possible MP3 audio data")
                    
        except Exception as e:
            print(f"    ❌ Error analyzing message: {e}")
    
    def _parse_multipart_names(self, body: bytes) -> Optional[List[str]]:
        """Best-effort extract part names from a multipart body for readability."""
        try:
            text = body.decode('utf-8', errors='ignore')
            names = re.findall(r'Content-Disposition: form-data;\s*name="([^"]+)"', text)
            return names or None
        except Exception:
            return None

    def analyze_http_flows(self):
        """Analyze HTTP flows for ElevenLabs API patterns"""
        print("\n🌐 Analyzing HTTP Flows")
        print("=" * 50)
        
        print(f"Found {len(self.http_flows)} ElevenLabs HTTP requests")
        
        for flow in self.http_flows:
            print(f"\n📡 {flow.request.method} {flow.request.path}")
            print(f"Host: {flow.request.host}")
            
            # Show important headers
            auth_header = flow.request.headers.get('authorization', '')
            if auth_header:
                display_auth = auth_header[:50] + "..." if len(auth_header) > 50 else auth_header
                print(f"Auth: {display_auth}")
            
            # Show request body for POST/PUT/PATCH
            if flow.request.method in ['POST', 'PUT', 'PATCH'] and hasattr(flow.request, 'content'):
                try:
                    if flow.request.content:
                        ctype = flow.request.headers.get('content-type', '')
                        if 'multipart/form-data' in ctype.lower():
                            names = self._parse_multipart_names(flow.request.content)
                            if names:
                                print(f"Request multipart fields: {names}")
                            # print a short preview
                            preview = flow.request.content[:200].decode('utf-8', errors='ignore')
                            print(f"Request body: {preview}...")
                        else:
                            body = flow.request.content.decode('utf-8', errors='ignore')
                            if body:
                                try:
                                    json_body = json.loads(body)
                                    print(f"Request body keys: {list(json_body.keys())}")
                                    if 'text' in json_body:
                                        text = json_body['text'][:100] + "..." if len(json_body['text']) > 100 else json_body['text']
                                        print(f"Text: {text}")
                                except Exception:
                                    print(f"Request body: {body[:200]}...")
                except:
                    print("Request body: <binary data>")
            
            # Show response info
            if hasattr(flow, 'response') and flow.response:
                print(f"Response: {flow.response.status_code}")
                content_type = flow.response.headers.get('content-type', '')
                if content_type:
                    print(f"Content-Type: {content_type}")
                # Print JSON response body for relevant endpoints
                try:
                    if flow.response.content and 'application/json' in content_type.lower():
                        resp_text = flow.response.content.decode('utf-8', errors='ignore')
                        # Only dump full JSON for key endpoints to reduce noise
                        if '/v1/reader/reads/add' in flow.request.path or '/v1/reader/reads/' in flow.request.path:
                            try:
                                parsed = json.loads(resp_text)
                                print(f"Response JSON: {json.dumps(parsed, indent=2)[:2000]}")
                            except Exception:
                                print(f"Response body: {resp_text[:1000]}...")
                except Exception:
                    pass
    
    def extract_websocket_protocol(self):
        """Extract the exact WebSocket protocol used by Reader app"""
        print("\n🔧 Extracting WebSocket Protocol")
        print("=" * 50)
        
        if not self.websocket_flows:
            print("❌ No WebSocket flows found")
            return None
        
        protocol_info = {
            'url_patterns': set(),
            'headers': {},
            'message_patterns': [],
            'audio_streaming': {
                'total_chunks': len(self.audio_chunks),
                'total_audio_bytes': sum(chunk['size'] for chunk in self.audio_chunks),
                'stream_ids': set()
            }
        }
        
        # Extract URL patterns
        for flow in self.websocket_flows:
            protocol_info['url_patterns'].add(flow.request.path)
            
            # Extract common headers
            for name, value in flow.request.headers.items():
                if name.lower() in ['authorization', 'user-agent', 'origin', 'sec-websocket-protocol']:
                    protocol_info['headers'][name] = value
        
        # Extract stream IDs and patterns
        for chunk in self.audio_chunks:
            if chunk['stream_id']:
                protocol_info['audio_streaming']['stream_ids'].add(chunk['stream_id'])
        
        # Analyze message patterns
        message_types = {}
        for msg in self.json_messages:
            keys = tuple(sorted(msg.keys()))
            message_types[keys] = message_types.get(keys, 0) + 1
        
        protocol_info['message_patterns'] = message_types
        
        # Print extracted protocol
        print("🔍 Extracted Protocol Information:")
        print(f"WebSocket URLs: {list(protocol_info['url_patterns'])}")
        print(f"Audio chunks: {protocol_info['audio_streaming']['total_chunks']}")
        print(f"Total audio data: {protocol_info['audio_streaming']['total_audio_bytes']} bytes")
        print(f"Unique stream IDs: {len(protocol_info['audio_streaming']['stream_ids'])}")
        
        if protocol_info['audio_streaming']['stream_ids']:
            print(f"Stream ID examples: {list(protocol_info['audio_streaming']['stream_ids'])[:3]}")
        
        print(f"\nMessage patterns found:")
        for keys, count in message_types.items():
            print(f"  {keys}: {count} messages")
        
        return protocol_info
    
    def generate_implementation_code(self):
        """Generate Python code to implement the discovered WebSocket protocol"""
        print("\n🔧 Generating Implementation Code")
        print("=" * 50)
        
        if not self.audio_chunks:
            print("❌ No audio streaming data found - cannot generate implementation")
            return
        
        # Find the most common WebSocket URL pattern
        url_patterns = [flow.request.path for flow in self.websocket_flows]
        if not url_patterns:
            print("❌ No WebSocket URL patterns found")
            return
        
        most_common_url = max(set(url_patterns), key=url_patterns.count) if url_patterns else ""
        
        # Generate sample implementation based on discovered patterns
        impl_code = f'''
async def stream_with_reader_websocket(self, text: str, voice_id: str, output_file: Optional[str] = None, play_audio: bool = False) -> Optional[bytes]:
    """Stream TTS using the exact Reader app WebSocket protocol discovered from flows"""
    
    # Use the WebSocket URL pattern from captured flows
    ws_url = f"wss://api.elevenlabs.io{most_common_url}"
    if "{{voice_id}}" in ws_url:
        ws_url = ws_url.replace("{{voice_id}}", voice_id)
    
    headers = {{
        "Authorization": f"Bearer {{self.bearer_token}}",
        "User-Agent": self.headers["User-Agent"],
        "Origin": "https://elevenlabs.io"
    }}
    
    audio_data = b""
    stream_id = str(uuid.uuid4()).upper()
    
    try:
        async with websockets.connect(ws_url, additional_headers=headers) as websocket:
            print(f"🔗 Connected to Reader WebSocket")
            
            # Send initial message based on discovered patterns
            # Analysis found {len(self.json_messages)} JSON messages with patterns:
            # {list(set(tuple(sorted(msg.keys())) for msg in self.json_messages[:5]))}
            
            init_message = {{
                "text": text,
                "voice_settings": {{"stability": 0.5, "similarity_boost": 0.8}},
                "model_id": "eleven_multilingual_v2"
            }}
            
            # Add stream_id if the pattern uses it
            if any('streamId' in msg or 'stream_id' in msg for msg in self.json_messages):
                init_message["streamId"] = stream_id
            
            await websocket.send(json.dumps(init_message))
            print("📤 Sent initial message")
            
            # Receive audio chunks
            async for message in websocket:
                try:
                    data = json.loads(message)
                    
                    if "audio" in data and data["audio"]:
                        chunk = base64.b64decode(data["audio"])
                        audio_data += chunk
                        print(".", end="", flush=True)
                    
                    if data.get("isFinal", False):
                        break
                        
                except json.JSONDecodeError:
                    # Handle binary audio data
                    if isinstance(message, bytes):
                        audio_data += message
                        print(".", end="", flush=True)
            
            print(f"\\n✓ Generated {{len(audio_data)}} bytes of audio")
            
            # Handle output
            if output_file:
                with open(output_file, "wb") as f:
                    f.write(audio_data)
                print(f"💾 Saved audio to {{output_file}}")
            
            if play_audio:
                await self._play_audio(audio_data)
            
            return audio_data
            
    except Exception as e:
        print(f"❌ WebSocket streaming failed: {{e}}")
        return None
'''
        
        print("📝 Generated implementation code based on flow analysis:")
        print(impl_code)
        
        # Save to file
        with open("reader_websocket_implementation.py", "w") as f:
            f.write(f"# WebSocket implementation based on flow analysis\n")
            f.write(f"# Generated from: {self.flows_file}\n")
            f.write(f"# WebSocket flows analyzed: {len(self.websocket_flows)}\n")
            f.write(f"# Audio chunks found: {len(self.audio_chunks)}\n")
            f.write(f"# JSON messages analyzed: {len(self.json_messages)}\n\n")
            f.write(impl_code)
        
        print("💾 Implementation saved to: reader_websocket_implementation.py")


def main():
    if len(sys.argv) < 2:
        print("Usage: python analyze_flows.py <flows_file> [--verbose]")
        print("Example: python analyze_flows.py flows.elevenlabsio --verbose")
        sys.exit(1)
    
    flows_file = sys.argv[1]
    verbose = "--verbose" in sys.argv
    
    if not Path(flows_file).exists():
        print(f"❌ Error: Flows file '{flows_file}' not found")
        sys.exit(1)
    
    print(f"🔍 Analyzing mitmproxy flows: {flows_file}")
    print(f"Using mitmproxy API to parse WebSocket flows...")
    
    analyzer = FlowAnalyzer(flows_file, verbose=verbose)
    
    # Load flows
    if not analyzer.load_flows():
        sys.exit(1)
    
    # Analyze WebSocket flows (this is what we're most interested in)
    analyzer.analyze_websocket_flows()
    
    # Analyze HTTP flows for context
    analyzer.analyze_http_flows()
    
    # Extract protocol information
    protocol = analyzer.extract_websocket_protocol()
    
    # Generate implementation code
    analyzer.generate_implementation_code()
    
    print("\n🎉 Flow analysis completed!")
    print("📋 Next steps:")
    print("   1. Review the WebSocket message patterns above")
    print("   2. Use the generated implementation code")
    print("   3. Test the WebSocket streaming with real tokens")


if __name__ == "__main__":
    main()
