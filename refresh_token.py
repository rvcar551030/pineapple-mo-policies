"""
Refreshes the TikTok access token using the stored refresh_token, so the
connection never actually expires as long as this runs periodically
(access_token: 24h, refresh_token: 365d — refreshing rolls both forward).

Usage: python refresh_token.py
Reads token.json, calls the refresh endpoint, overwrites token.json.
"""
import json
import os

import requests

def load_env():
    client_key = client_secret = None
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("TIKTOK_CLIENT_KEY="):
                client_key = line.split("=", 1)[1]
            elif line.startswith("TIKTOK_CLIENT_SECRET="):
                client_secret = line.split("=", 1)[1]
    return client_key, client_secret

def main():
    client_key, client_secret = load_env()
    token_path = os.path.join(os.path.dirname(__file__), "token.json")

    with open(token_path) as f:
        token = json.load(f)

    resp = requests.post(
        "https://open.tiktokapis.com/v2/oauth/token/",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": token["refresh_token"],
        },
    )
    data = resp.json()

    if "access_token" not in data:
        print("Refresh failed:", json.dumps(data, indent=2))
        raise SystemExit(1)

    with open(token_path, "w") as f:
        json.dump(data, f, indent=2)

    print(f"Refreshed. New access_token expires in {data['expires_in']}s, "
          f"refresh_token expires in {data['refresh_expires_in']}s.")

if __name__ == "__main__":
    main()
