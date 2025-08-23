from __future__ import annotations

import shutil
import httpx
import os

from langbot_plugin.cli.commands.login import check_login_status, get_access_token
from langbot_plugin.cli.commands.buildplugin import build_plugin_process

SERVER_URL = os.getenv("CLOUD_SERVICE_URL", "https://space.langbot.app")

NOT_LOGIN_TIPS = """
Not logged in, please login first with `lbp login`
"""

TMP_DIR = 'dist/tmp'

def publish_plugin(plugin_path: str, changelog: str, access_token: str) -> None:
    """
    Publish the plugin to LangBot Marketplace

    POST /api/v1/marketplace/plugins/publish
    form-data:
        - file: plugin.zip
        - changelog: changelog
    """
    url = f"{SERVER_URL}/api/v1/marketplace/plugins/publish"
    files = {
        'file': open(plugin_path, 'rb')
    }
    data = {
        'changelog': changelog
    }

    try:
        with httpx.Client() as client:
            response = client.post(
                url,
                files=files,
                data=data,
                headers={
                    'Authorization': f'Bearer {access_token}'
                }
            )

            response.raise_for_status()

            result = response.json()
            if result['code'] != 0:
                print(f"!!! Failed to publish plugin: {result['msg']}")
                return
            
            print(f"✅ Plugin published successfully. You can check it on https://{SERVER_URL}/market")
            return
    except Exception as e:
        print(f"!!! Failed to publish plugin: {e}")
        return


def publish_process() -> None:
    """
    Implement LangBot CLI publish process
    """
    if not check_login_status():
        print(NOT_LOGIN_TIPS)
        return
    
    access_token = get_access_token()
    if not access_token:
        print(NOT_LOGIN_TIPS)
        return
    
    # build plugin
    plugin_path = build_plugin_process(TMP_DIR)
    
    # publish plugin
    publish_plugin(plugin_path, "", access_token)

    # clean up
    shutil.rmtree(TMP_DIR)