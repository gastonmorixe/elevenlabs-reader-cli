#!/bin/bash

# ElevenLabs TTS Client Usage Examples
# Different ways to avoid typing the Firebase refresh token every time

echo "🎯 ElevenLabs TTS Client - No More Long Token Typing!"
echo "============================================================"

# Method 1: Use the wrapper script (EASIEST)
echo ""
echo "📌 Method 1: Use the TTS wrapper script (easiest)"
echo "--------------------------------------------------"
echo "# Simple wrapper that auto-extracts token:"
echo "./tts --voice-id \"nPczCjzI2devNBz1zQrb\" --text \"Hello world\" --play"
echo "./tts --voice-id \"2EiwWnXFnvU5JabPnv8n\" --text \"FREE streaming test\" --method reader --play"
echo "./tts --list-voices"
echo ""

# Method 2: Command substitution
echo "📌 Method 2: Command substitution (flexible)"
echo "--------------------------------------------"
echo "# Extract token inline with \$(command):"
echo "python elevenlabs_tts_client.py \\"
echo "  --firebase-refresh-token \"\$(python get_refresh_token.py)\" \\"
echo "  --voice-id \"nPczCjzI2devNBz1zQrb\" \\"
echo "  --text \"Command substitution test\" \\"
echo "  --method reader \\"
echo "  --play"
echo ""

# Method 3: Environment variable
echo "📌 Method 3: Environment variable (for scripts)"
echo "-----------------------------------------------"
echo "# Set once in your session:"
echo "export FIREBASE_REFRESH_TOKEN=\$(python get_refresh_token.py)"
echo ""
echo "# Then use it:"
echo "python elevenlabs_tts_client.py \\"
echo "  --firebase-refresh-token \"\$FIREBASE_REFRESH_TOKEN\" \\"
echo "  --voice-id \"nPczCjzI2devNBz1zQrb\" \\"
echo "  --text \"Environment variable test\" \\"
echo "  --play"
echo ""

# Method 4: Shell alias
echo "📌 Method 4: Shell alias (add to ~/.bashrc or ~/.zshrc)"
echo "------------------------------------------------------"
echo "# Add this to your shell config:"
echo "alias tts11='python elevenlabs_tts_client.py --firebase-refresh-token \"\$(python get_refresh_token.py)\"'"
echo ""
echo "# Then use it:"
echo "tts11 --voice-id \"nPczCjzI2devNBz1zQrb\" --text \"Alias test\" --play"
echo ""

# Method 5: Batch processing
echo "📌 Method 5: Batch processing with variables"
echo "--------------------------------------------"
echo "# For processing multiple files:"
echo "TOKEN=\$(python get_refresh_token.py)"
echo "VOICE=\"nPczCjzI2devNBz1zQrb\""
echo ""
echo "python elevenlabs_tts_client.py --firebase-refresh-token \"\$TOKEN\" --voice-id \"\$VOICE\" --file chapter1.txt --output chapter1.mp3"
echo "python elevenlabs_tts_client.py --firebase-refresh-token \"\$TOKEN\" --voice-id \"\$VOICE\" --file chapter2.txt --output chapter2.mp3"
echo "python elevenlabs_tts_client.py --firebase-refresh-token \"\$TOKEN\" --voice-id \"\$VOICE\" --file chapter3.txt --output chapter3.mp3"
echo ""

# Quick commands section
echo "🚀 Quick Commands (copy & paste ready)"
echo "======================================="
echo ""
echo "# List voices (quick):"
echo "./tts --list-voices"
echo ""
echo "# FREE streaming (flows voice):"
echo "./tts --voice-id \"nPczCjzI2devNBz1zQrb\" --text \"Testing FREE WebSocket streaming!\" --method reader --play"
echo ""
echo "# HTTP streaming (instant):"
echo "./tts --voice-id \"2EiwWnXFnvU5JabPnv8n\" --text \"Instant HTTP streaming\" --method http --play"
echo ""
echo "# Auto method (tries FREE first):"
echo "./tts --voice-id \"nPczCjzI2devNBz1zQrb\" --text \"Smart method selection\" --method auto --play"
echo ""
echo "# File input with output:"
echo "echo \"Long text content here...\" > input.txt"
echo "./tts --voice-id \"nPczCjzI2devNBz1zQrb\" --file input.txt --output speech.mp3 --method reader"
echo ""

echo "💡 Pro Tips:"
echo "- Use './tts' wrapper for daily use (simplest)"
echo "- Use method 2 for one-off commands"
echo "- Use method 3 for automation scripts"
echo "- Use method 4 for permanent shell integration"
echo ""
echo "🎉 No more copying long tokens every time!"

# Original detailed examples continue below for reference

# Example 1: List available voices (Reader API)
echo -e "\n📋 Example 1: List voices via Reader API"
./elevenlabs_tts_client.py --firebase-refresh-token "$FIREBASE_TOKEN" --list-voices

# Example 2: Simple text to speech (Reader workflow)
echo -e "\n🎤 Example 2: Simple TTS via Reader API"
./elevenlabs_tts_client.py \
  --firebase-refresh-token "$FIREBASE_TOKEN" \
  --voice-id "$VOICE_ID" \
  --text "Hello world, this is a test of the ElevenLabs Reader API client!" \
  --play

# Example 2b: Simple TTS with verbose logging
echo -e "\n🔍 Example 2b: TTS with verbose logging (shows Reader API calls)"
./elevenlabs_tts_client.py \
  --firebase-refresh-token "$FIREBASE_TOKEN" \
  --voice-id "$VOICE_ID" \
  --text "This will show detailed Reader API network logs" \
  --verbose \
  --play

# Example 3: Read from file and save audio
echo -e "\n📄 Example 3: File input with audio output"
echo "This is a longer text that will be converted to speech using the Reader API workflow. First the content is created, then streamed via WebSocket." > sample_text.txt
./elevenlabs_tts_client.py \
  --firebase-refresh-token "$FIREBASE_TOKEN" \
  --voice-id "$VOICE_ID" \
  --file sample_text.txt \
  --output "sample_output.mp3"

# Example 4: Stdin input
echo -e "\n📝 Example 4: Stdin input via Reader API"
echo "Reading from standard input with Firebase authentication and Reader API workflow." | \
./elevenlabs_tts_client.py \
  --firebase-refresh-token "$FIREBASE_TOKEN" \
  --voice-id "$VOICE_ID" \
  --output "stdin_output.mp3" \
  --play

# Example 5: Long text processing with Reader workflow
echo -e "\n📚 Example 5: Long text processing (Reader API)"
cat > long_text.txt << EOF
This is a longer example text that demonstrates the Reader API workflow of the ElevenLabs client.
The process follows these steps:
1. Firebase authentication to get Bearer token
2. Content creation via POST /v1/reader/reads
3. WebSocket streaming via /v1/reader/reads/stream/{read_id}
4. Real-time audio chunk reception and playback

This approach exactly matches the network flows captured from the ElevenLabs Reader mobile app,
ensuring compatibility with their private API endpoints. The client handles Firebase token refresh,
content creation, and WebSocket streaming automatically.
EOF

./elevenlabs_tts_client.py \
  --firebase-refresh-token "$FIREBASE_TOKEN" \
  --voice-id "$VOICE_ID" \
  --file long_text.txt \
  --output "long_speech.mp3" \
  --play

# Example 6: Token management
echo -e "\n🔑 Example 6: Token management"
echo "Check token cache status:"
python -c "
from token_manager import TokenManager
manager = TokenManager(verbose=True)
info = manager.get_cache_info()
print('📊 Cache Info:', info)
"

# Example 7: Clear token cache
echo -e "\n🧹 Example 7: Clear token cache"
./elevenlabs_tts_client.py --clear-cache

# Example 8: Run comprehensive tests
echo -e "\n🧪 Example 8: Run test suite"
echo "This will run comprehensive tests of the Reader API implementation:"
python test_reader_api.py

echo -e "\n✅ Examples completed!"
echo "Generated files:"
ls -la *.mp3 *.txt 2>/dev/null || echo "No output files found"

# Cleanup
read -p "🗑️  Delete generated files? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    rm -f sample_text.txt long_text.txt *.mp3
    echo "🧹 Files cleaned up"
fi

echo -e "\n📚 Quick Reference:"
echo "List voices:    ./elevenlabs_tts_client.py --firebase-refresh-token 'token' --list-voices"
echo "Generate TTS:   ./elevenlabs_tts_client.py --firebase-refresh-token 'token' --voice-id 'voice' --text 'Hello' --play"
echo "Test suite:     python test_reader_api.py"
echo "Clear cache:    ./elevenlabs_tts_client.py --clear-cache"