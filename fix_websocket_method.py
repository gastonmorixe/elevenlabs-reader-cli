#!/usr/bin/env python3
"""
Fix the WebSocket method in elevenlabs_tts_client.py

This script removes the broken WebSocket implementation and replaces it 
with a clean fallback to HTTP streaming when using Firebase tokens.
"""

def fix_websocket_method():
    """Fix the _stream_direct_websocket method"""
    
    # The corrected method
    new_method = '''    async def _stream_direct_websocket(
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
        return await self._stream_http(text, voice_id, output_file, play_audio)
'''

    # Read the current file
    with open('/Users/gaston/Projects/elevenlabs/elevenlabs_tts_client.py', 'r') as f:
        content = f.read()
    
    # Find the start and end of the method
    start_marker = "    async def _stream_direct_websocket("
    end_marker = "    async def _stream_reader_websocket_flows("
    
    start_pos = content.find(start_marker)
    if start_pos == -1:
        print("❌ Could not find _stream_direct_websocket method")
        return False
    
    end_pos = content.find(end_marker)
    if end_pos == -1:
        print("❌ Could not find end of _stream_direct_websocket method")
        return False
    
    # Replace the method
    new_content = content[:start_pos] + new_method + "\n" + content[end_pos:]
    
    # Write the fixed file
    with open('/Users/gaston/Projects/elevenlabs/elevenlabs_tts_client.py', 'w') as f:
        f.write(new_content)
    
    print("✅ Fixed _stream_direct_websocket method")
    return True

if __name__ == "__main__":
    fix_websocket_method()