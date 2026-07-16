"""
Step 1 of the demo flow: authorize this app against your TikTok account
(@pineapple_mo, added as a Sandbox target user) and save the access token.

Usage: python oauth_login.py
Opens a browser to TikTok's authorization page. After you approve, TikTok
redirects to the callback.html page on GitHub Pages, which displays the
authorization code. Paste that code back into this script when prompted.
"""
import json
import os
import urllib.parse
import webbrowser

import requests

CLIENT_KEY = None
CLIENT_SECRET = None
REDIRECT_URI = "https://rvcar551030.github.io/pineapple-mo-policies/callback.html"
SCOPES = "user.info.basic,video.upload"
STATE = "demo123"

def load_env():
    global CLIENT_KEY, CLIENT_SECRET
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("TIKTOK_CLIENT_KEY="):
                CLIENT_KEY = line.split("=", 1)[1]
            elif line.startswith("TIKTOK_CLIENT_SECRET="):
                CLIENT_SECRET = line.split("=", 1)[1]

def main():
    load_env()
    if not CLIENT_KEY or not CLIENT_SECRET:
        raise SystemExit("Missing TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET in .env")

    auth_url = "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode({
        "client_key": CLIENT_KEY,
        "scope": SCOPES,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "state": STATE,
    })
    print("Opening browser for TikTok authorization...")
    print(auth_url)
    webbrowser.open(auth_url)

    code = input("\nAfter approving, paste the authorization code shown on the callback page here: ").strip()

    token_resp = requests.post(
        "https://open.tiktokapis.com/v2/oauth/token/",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": CLIENT_KEY,
            "client_secret": CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
        },
    )
    data = token_resp.json()
    print("Token response:", data)

    if "access_token" in data:
        with open(os.path.join(os.path.dirname(__file__), "token.json"), "w") as f:
            json.dump(data, f, indent=2)
        print("Saved token.json")
    else:
        raise SystemExit(f"Token exchange failed: {data}")

if __name__ == "__main__":
    main()
