#!/usr/bin/env python3
"""
Quick Firebase Refresh Token Extractor

Extracts just the Firebase refresh token for inline use.
Usage: 
  python get_refresh_token.py flows.elevenlabsio
  $(python get_refresh_token.py flows.elevenlabsio)
"""

import sys
import json
from pathlib import Path

def get_refresh_token_from_cache():
    """Get refresh token from existing cache"""
    cache_files = ["tokens_cache.json", "extracted_tokens.json"]
    
    for cache_file in cache_files:
        if Path(cache_file).exists():
            try:
                with open(cache_file, 'r') as f:
                    data = json.load(f)
                
                # Try different possible keys
                token = (data.get('firebase_refresh_token') or 
                        data.get('refresh_token'))
                
                if token:
                    return token
            except:
                continue
    
    return None

def get_refresh_token_from_flows(flows_file):
    """Extract refresh token from flows file"""
    import re
    
    if not Path(flows_file).exists():
        return None
    
    try:
        with open(flows_file, 'rb') as f:
            flows_data = f.read().decode('utf-8', errors='ignore')
        
        # Look for Firebase refresh token patterns
        patterns = [
            r'"refreshToken":\s*"([A-Za-z0-9\-_]+)"',
            r'"firebase_refresh_token":\s*"([A-Za-z0-9\-_]+)"',
            r'refreshToken["\s:]+([A-Za-z0-9\-_]+)'
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, flows_data)
            if matches:
                return matches[0]
    except:
        pass
    
    return None

def main():
    # First try cache
    token = get_refresh_token_from_cache()
    if token:
        print(token)
        return
    
    # Then try flows file if provided
    if len(sys.argv) > 1:
        flows_file = sys.argv[1]
        token = get_refresh_token_from_flows(flows_file)
        if token:
            print(token)
            return
    
    # No token found
    print("", file=sys.stderr)  # Empty string to stdout, error to stderr
    exit(1)

if __name__ == "__main__":
    main()