#!/usr/bin/env python3
"""
Token Manager for ElevenLabs TTS Client

Handles token storage, refresh, and expiration management.
Simplifies authentication by only requiring Firebase refresh token.
"""

import json
import time
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any


class TokenManager:
    """Manages ElevenLabs authentication tokens with automatic refresh"""
    
    def __init__(self, cache_file: str = "tokens_cache.json", verbose: bool = False):
        self.cache_file = Path(cache_file)
        self.verbose = verbose
        self.firebase_api_key = "AIzaSyDhSxLJa_WaR8I69a1BmlUG7ckfZHu7-ig"
    
    def log(self, message: str):
        """Log message if verbose mode is enabled"""
        if self.verbose:
            timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"[{timestamp}] {message}")
    
    def load_cache(self) -> Dict[str, Any]:
        """Load cached tokens from file"""
        if not self.cache_file.exists():
            return {}
        
        try:
            with open(self.cache_file, 'r') as f:
                cache = json.load(f)
            self.log(f"📂 Loaded token cache from {self.cache_file}")
            return cache
        except (json.JSONDecodeError, IOError) as e:
            self.log(f"⚠️ Failed to load cache: {e}")
            return {}
    
    def save_cache(self, cache: Dict[str, Any]):
        """Save tokens to cache file"""
        try:
            with open(self.cache_file, 'w') as f:
                json.dump(cache, f, indent=2)
            self.log(f"💾 Saved token cache to {self.cache_file}")
        except IOError as e:
            self.log(f"⚠️ Failed to save cache: {e}")

    def get_app_check_token(self) -> Optional[str]:
        """Return cached xi-app-check-token if available."""
        cache = self.load_cache()
        return cache.get('xi_app_check_token')

    def set_app_check_token(self, token: str):
        """Persist xi-app-check-token to cache for future runs."""
        if not token:
            return
        cache = self.load_cache()
        cache['xi_app_check_token'] = token
        cache['last_updated'] = datetime.now().isoformat()
        self.save_cache(cache)

    def get_device_id(self) -> Optional[str]:
        """Return cached Device ID if available."""
        cache = self.load_cache()
        return cache.get('device_id')

    def set_device_id(self, device_id: str):
        """Persist Device ID to cache for consistent identification across runs."""
        if not device_id:
            return
        cache = self.load_cache()
        cache['device_id'] = device_id
        cache['last_updated'] = datetime.now().isoformat()
        self.save_cache(cache)
    
    def is_token_expired(self, token_data: Dict[str, Any]) -> bool:
        """Check if a Bearer token is expired"""
        if not token_data.get('expires_at'):
            return True
        
        expires_at = datetime.fromisoformat(token_data['expires_at'])
        # Consider expired if less than 5 minutes remaining
        buffer = timedelta(minutes=5)
        return datetime.now() + buffer >= expires_at
    
    def refresh_bearer_token(self, firebase_refresh_token: str) -> Optional[Dict[str, Any]]:
        """Refresh Bearer token via Firebase Secure Token API.

        Matches captured flows: form-encoded body with keys grant_type and refresh_token.
        """
        url = f"https://securetoken.googleapis.com/v1/token?key={self.firebase_api_key}"
        
        data = {
            "grant_type": "refresh_token",
            "refresh_token": firebase_refresh_token,
        }
        
        # Headers similar to captured mobile flows
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "FirebaseAuth.iOS/11.14.0 io.elevenlabs.readerapp/1.4.45 iPhone/26.0 hw/iPhone16_2",
            "X-Client-Version": "iOS/FirebaseSDK/11.14.0/FirebaseCore-iOS",
            "X-iOS-Bundle-Identifier": "io.elevenlabs.readerapp",
            "Accept": "*/*",
        }
        
        self.log("🔄 Refreshing Bearer token via Firebase API...")
        
        try:
            import requests
            resp = requests.post(url, data=data, headers=headers, timeout=20)
            if resp.status_code != 200:
                self.log(f"❌ Token refresh HTTP {resp.status_code}: {resp.text[:200]}")
                return None
            response_data = resp.json()
            
            access_token = response_data.get('access_token')
            if not access_token:
                self.log(f"❌ No access_token in response: {response_data}")
                return None
            
            # Calculate expiration time
            expires_in = int(response_data.get('expires_in', 3600))
            # Refresh a bit early: store true expiry, and is_token_expired adds buffer
            expires_at = datetime.now() + timedelta(seconds=expires_in)
            
            token_data = {
                'bearer_token': access_token,
                'expires_in': expires_in,
                'expires_at': expires_at.isoformat(),
                'refreshed_at': datetime.now().isoformat(),
                'token_type': response_data.get('token_type', 'Bearer')
            }
            
            self.log(f"✅ Bearer token refreshed successfully (expires in {expires_in}s)")
            return token_data
            
        except Exception as e:
            self.log(f"❌ Token refresh failed: {e}")
            return None
    
    def get_fresh_bearer_token(self, firebase_refresh_token: str) -> Optional[str]:
        """Get a fresh Bearer token, using cache if valid"""
        cache = self.load_cache()
        
        # Check if we have a valid cached token
        cached_token = cache.get('bearer_token_data')
        if cached_token and not self.is_token_expired(cached_token):
            self.log("✅ Using valid cached Bearer token")
            return cached_token['bearer_token']
        
        # Refresh token
        self.log("🔄 Cached token expired or missing, refreshing...")
        fresh_token_data = self.refresh_bearer_token(firebase_refresh_token)
        
        if not fresh_token_data:
            return None
        
        # Update cache
        cache['firebase_refresh_token'] = firebase_refresh_token
        cache['bearer_token_data'] = fresh_token_data
        cache['last_updated'] = datetime.now().isoformat()
        self.save_cache(cache)
        
        return fresh_token_data['bearer_token']

    def force_refresh_bearer_token(self, firebase_refresh_token: str) -> Optional[str]:
        """Force-refresh the Bearer token and update cache regardless of current validity."""
        fresh_token_data = self.refresh_bearer_token(firebase_refresh_token)
        if not fresh_token_data:
            return None
        cache = self.load_cache()
        cache['firebase_refresh_token'] = firebase_refresh_token
        cache['bearer_token_data'] = fresh_token_data
        cache['last_updated'] = datetime.now().isoformat()
        self.save_cache(cache)
        return fresh_token_data['bearer_token']
    
    def get_cache_info(self) -> Dict[str, Any]:
        """Get information about cached tokens"""
        cache = self.load_cache()
        
        info = {
            'cache_file': str(self.cache_file),
            'cache_exists': self.cache_file.exists(),
            'has_firebase_token': bool(cache.get('firebase_refresh_token')),
            'has_bearer_token': bool(cache.get('bearer_token_data')),
        }
        
        if cache.get('bearer_token_data'):
            token_data = cache['bearer_token_data']
            info['bearer_token_expires_at'] = token_data.get('expires_at')
            info['bearer_token_expired'] = self.is_token_expired(token_data)
            
        if cache.get('last_updated'):
            info['last_updated'] = cache['last_updated']
        if cache.get('xi_app_check_token'):
            info['has_app_check_token'] = True
        else:
            info['has_app_check_token'] = False
        
        return info
    
    def clear_cache(self):
        """Clear the token cache"""
        if self.cache_file.exists():
            self.cache_file.unlink()
            self.log(f"🗑️ Cleared token cache: {self.cache_file}")
        else:
            self.log("ℹ️ No cache file to clear")


def main():
    """CLI interface for token management"""
    import argparse
    
    parser = argparse.ArgumentParser(description="ElevenLabs Token Manager")
    parser.add_argument("--firebase-refresh-token", help="Firebase refresh token")
    parser.add_argument("--get-bearer-token", action="store_true", help="Get fresh Bearer token")
    parser.add_argument("--cache-info", action="store_true", help="Show cache information")
    parser.add_argument("--clear-cache", action="store_true", help="Clear token cache")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")
    parser.add_argument("--cache-file", default="tokens_cache.json", help="Cache file path")
    
    args = parser.parse_args()
    
    manager = TokenManager(cache_file=args.cache_file, verbose=args.verbose)
    
    if args.clear_cache:
        manager.clear_cache()
        return
    
    if args.cache_info:
        info = manager.get_cache_info()
        print("📊 Token Cache Information:")
        print(json.dumps(info, indent=2))
        return
    
    if args.get_bearer_token:
        if not args.firebase_refresh_token:
            print("❌ --firebase-refresh-token required for --get-bearer-token")
            return
            
        bearer_token = manager.get_fresh_bearer_token(args.firebase_refresh_token)
        if bearer_token:
            print(bearer_token)
        else:
            print("❌ Failed to get Bearer token", file=sys.stderr)
            exit(1)
        return
    
    # Default: show help
    parser.print_help()


if __name__ == "__main__":
    import sys
    main()
