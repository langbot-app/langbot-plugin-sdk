from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx

SERVER_URL = "https://space.langbot.app"


def login_process() -> None:
    """
    Implement LangBot CLI login process
    
    Process:
    1. Generate device code
    2. Display user code and verification URI
    3. Wait for user to input user code
    4. Loop check token acquisition status
    5. Save token to config file
    6. Display login success message
    """
    
    # Configuration
    API_BASE = f"{SERVER_URL}/api/v1"
    
    try:
        print("Starting LangBot CLI login process...")
        
        # 1. Generate device code
        print("Generating device code...")
        device_code_response = _generate_device_code(API_BASE)
        
        if device_code_response["code"] != 0:
            print(f"Failed to generate device code: {device_code_response['msg']}")
            return
        
        device_data = device_code_response["data"]
        device_code = device_data["device_code"]
        user_code = device_data["user_code"]
        verification_uri = f"{SERVER_URL}{device_data['verification_uri']}"
        expires_in = device_data["expires_in"]
        
        # 2. Display user code and verification URI
        print("\n" + "="*50)
        print("Please copy the user code and complete verification in your browser:")
        print(f"User Code: {user_code}")
        print(f"Verification URL: {verification_uri}")
        print(f"Device code expires in: {expires_in} seconds")
        print("="*50)
        print("\nWaiting for verification...")
        
        # 3. Loop check token acquisition status
        token_data = _poll_for_token(API_BASE, device_code, user_code, 3, expires_in)
        
        if not token_data:
            print("Login timeout or failed, please try again")
            return
        
        # 4. Save token to config file
        config_dir = Path.home() / ".langbot" / "cli"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_file = config_dir / "config.json"
        
        config = {
            "access_token": token_data["access_token"],
            "refresh_token": token_data["refresh_token"],
            "expires_in": token_data["expires_in"],
            "token_type": token_data["token_type"],
            "login_time": int(time.time())
        }
        
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        
        # 5. Display login success message
        print("\n" + "="*50)
        print("✅ Login successful!")
        print(f"Access token saved to: {config_file}")
        print(f"Token type: {token_data['token_type']}")
        print(f"Expires in: {token_data['expires_in']} seconds")
        print("="*50)
        
    except KeyboardInterrupt:
        print("\nLogin cancelled")
    except Exception as e:
        print(f"Error occurred during login: {e}")


def _generate_device_code(api_base: str) -> dict[str, Any]:
    """Generate device code"""
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(f"{api_base}/accounts/token/generate")
            response.raise_for_status()
            return response.json()
    except httpx.RequestError as e:
        return {"code": -1, "msg": f"Network request failed: {e}"}
    except Exception as e:
        return {"code": -1, "msg": f"Failed to generate device code: {e}"}


def _poll_for_token(
    api_base: str, 
    device_code: str, 
    user_code: str, 
    interval: int, 
    expires_in: int
) -> dict[str, Any] | None:
    """Poll for token acquisition status"""
    start_time = time.time()
    max_wait_time = expires_in + 30  # Extra 30 seconds wait
    
    while time.time() - start_time < max_wait_time:
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    f"{api_base}/accounts/token/get",
                    json={
                        "device_code": device_code,
                        "user_code": user_code
                    }
                )
                response.raise_for_status()
                result = response.json()
                
                if result["code"] == 0:
                    return result["data"]
                elif result["code"] == 425:  # User not yet authorized
                    # print("Waiting for user authorization...")
                    pass
                else:
                    print(f"Failed to get token: {result['msg']}")
                    return None
                    
        except httpx.RequestError as e:
            print(f"Network request failed: {e}")
            return None
        except Exception as e:
            print(f"Failed to check token status: {e}")
            return None
        
        # Wait for specified interval
        time.sleep(interval)
    
    return None


def _load_config() -> dict[str, Any] | None:
    """Load configuration file"""
    config_file = Path.home() / ".langbot" / "cli" / "config.json"
    
    if not config_file.exists():
        return None
    
    try:
        with open(config_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _is_token_valid(config: dict[str, Any]) -> bool:
    """Check if token is valid"""
    if not config:
        return False
    
    login_time = config.get("login_time", 0)
    expires_in = config.get("expires_in", 0)
    
    if not login_time or not expires_in:
        return False
    
    current_time = int(time.time())
    return current_time - login_time < expires_in


def check_login_status() -> bool:
    """Check login status"""
    config = _load_config()
    return _is_token_valid(config)


def get_access_token() -> str | None:
    """Get access token"""
    config = _load_config()
    if _is_token_valid(config):
        return config.get("access_token")
    return None 
