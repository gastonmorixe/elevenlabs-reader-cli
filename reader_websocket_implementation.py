# WebSocket implementation based on flow analysis
# Generated from: flows2.elevenlabs
# WebSocket flows analyzed: 4
# Audio chunks found: 31
# JSON messages analyzed: 36


async def stream_with_reader_websocket(self, text: str, voice_id: str, output_file: Optional[str] = None, play_audio: bool = False) -> Optional[bytes]:
    """Stream TTS using the exact Reader app WebSocket protocol discovered from flows"""
    
    # Use the WebSocket URL pattern from captured flows
    ws_url = f"wss://api.elevenlabs.io/v1/reader/reads/stream/u:Mf7n0chId4EUt2IYwVv8?voice_id=nPczCjzI2devNBz1zQrb"
    if "{voice_id}" in ws_url:
        ws_url = ws_url.replace("{voice_id}", voice_id)
    
    headers = {
        "Authorization": f"Bearer {self.bearer_token}",
        "User-Agent": self.headers["User-Agent"],
        "Origin": "https://elevenlabs.io"
    }
    
    audio_data = b""
    stream_id = str(uuid.uuid4()).upper()
    
    try:
        async with websockets.connect(ws_url, additional_headers=headers) as websocket:
            print(f"🔗 Connected to Reader WebSocket")
            
            # Send initial message based on discovered patterns
            # Analysis found 36 JSON messages with patterns:
            # [('position', 'stream_id'), ('alignment', 'audio', 'isFinal', 'streamId')]
            
            init_message = {
                "text": text,
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.8},
                "model_id": "eleven_multilingual_v2"
            }
            
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
            
            print(f"\n✓ Generated {len(audio_data)} bytes of audio")
            
            # Handle output
            if output_file:
                with open(output_file, "wb") as f:
                    f.write(audio_data)
                print(f"💾 Saved audio to {output_file}")
            
            if play_audio:
                await self._play_audio(audio_data)
            
            return audio_data
            
    except Exception as e:
        print(f"❌ WebSocket streaming failed: {e}")
        return None
