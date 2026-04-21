"""Pushover provider for the claude-workbench notify plugin.

HTTPS-only. 5-second timeout (hooks must not stall Claude). Uses the Python
stdlib — no third-party deps required.

API reference: https://pushover.net/api
"""
from __future__ import annotations

import json
import ssl
import urllib.parse
import urllib.request

API_URL = "https://api.pushover.net/1/messages.json"
TIMEOUT = 5  # seconds

# Pushover's numeric priority range is -2..2. We map our levels.
_PRIORITY_MAP = {-2: -2, -1: -1, 0: 0, 1: 1, 2: 2}

_DEFAULT_SOUND_MAP = {
    "permission_prompt": "siren",
    "elicitation_dialog": "cosmic",
    "idle_prompt": "pushover",
    "auth_success": "none",
    "cli": "pushover",
}


def send(*, config, title, message, priority, event_type, url=None) -> bool:
    user_key = config.get("user_key") or ""
    app_token = config.get("app_token") or ""
    if not user_key or not app_token:
        return False

    pushover_priority = _PRIORITY_MAP.get(int(priority), 0)

    sound_map = config.get("sound_map") or _DEFAULT_SOUND_MAP
    sound = sound_map.get(event_type) or sound_map.get("cli") or "pushover"

    params = {
        "token": app_token,
        "user": user_key,
        "title": title[:250],           # Pushover title cap
        "message": (message or " ")[:1024],  # body cap
        "priority": str(pushover_priority),
    }
    if sound and sound != "none":
        params["sound"] = sound
    device = config.get("device")
    if device:
        params["device"] = device
    if url:
        params["url"] = url[:512]
        params["url_title"] = "Open"

    # Emergency priority requires retry+expire — clamp to 1 if not provided,
    # since setting 2 without retry/expire is a Pushover API error.
    if params["priority"] == "2":
        params["priority"] = "1"

    data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(
        API_URL, data=data, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    ctx = ssl.create_default_context()

    with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as resp:
        body = resp.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body)
        except Exception:
            return resp.status == 200
        return parsed.get("status") == 1
