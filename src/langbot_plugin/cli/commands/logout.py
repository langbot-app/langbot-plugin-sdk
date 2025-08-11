from __future__ import annotations

import json
from pathlib import Path


def logout_process() -> None:
    """
    Implement LangBot CLI logout process
    
    Process:
    1. Remove configuration file
    2. Display logout success message
    """
    
    try:
        config_file = Path.home() / ".langbot" / "cli" / "config.json"
        
        if config_file.exists():
            config_file.unlink()
            print("✅ Logout successful!")
            print(f"Configuration file removed: {config_file}")
        else:
            print("Already logged out - no configuration file found")
            
    except Exception as e:
        print(f"Error occurred during logout: {e}")