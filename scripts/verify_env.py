#!/usr/bin/env python3
"""Sanity-check every credential in .env with one cheap call per provider.

Run this yourself after filling in .env - the Google check opens a real
browser for the OAuth consent screen, so it can't run non-interactively.

    python scripts/verify_env.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

from clipforge.config import load_config
from clipforge.publish.youtube_auth import get_credentials


def check_openai(api_key: str) -> None:
    if not api_key:
        print("[SKIP] OPENAI_API_KEY not set")
        return
    resp = requests.get(
        "https://api.openai.com/v1/models",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=15,
    )
    if resp.status_code == 200:
        print("[ OK ] OpenAI key works")
    else:
        print(f"[FAIL] OpenAI key rejected: {resp.status_code} {resp.text[:200]}")


def check_replicate(api_token: str) -> None:
    if not api_token:
        print("[SKIP] REPLICATE_API_TOKEN not set")
        return
    resp = requests.get(
        "https://api.replicate.com/v1/account",
        headers={"Authorization": f"Token {api_token}"},
        timeout=15,
    )
    if resp.status_code == 200:
        username = resp.json().get("username", "?")
        print(f"[ OK ] Replicate token works (account: {username})")
    else:
        print(f"[FAIL] Replicate token rejected: {resp.status_code} {resp.text[:200]}")


def check_google(config) -> None:
    if not config.google_client_id or not config.google_client_secret:
        print("[SKIP] GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET not set")
        return
    try:
        creds = get_credentials(config)
    except Exception as e:
        print(f"[FAIL] Google OAuth flow failed: {e}")
        return

    resp = requests.get(
        "https://www.googleapis.com/youtube/v3/channels",
        params={"part": "snippet", "mine": "true"},
        headers={"Authorization": f"Bearer {creds.token}"},
        timeout=15,
    )
    if resp.status_code == 200:
        items = resp.json().get("items", [])
        channel = items[0]["snippet"]["title"] if items else "(no channel found)"
        print(f"[ OK ] Google/YouTube auth works (channel: {channel})")
    else:
        print(f"[FAIL] YouTube API call rejected: {resp.status_code} {resp.text[:200]}")


def main() -> None:
    config = load_config()
    check_openai(config.openai_api_key)
    check_replicate(config.replicate_api_token)
    check_google(config)


if __name__ == "__main__":
    main()
