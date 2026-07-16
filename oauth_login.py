"""
Step 1 of the demo flow: authorize this app against your TikTok account
(@pineapple_mo, added as a Sandbox target user) and save the access token.

Usage: python oauth_login.py
Opens a browser to TikTok's authorization page. After you approve, TikTok
redirects to http://localhost:8080/callback and this script exchanges the
code for an access token, saving it to token.json.
"""
import http.server
import os
import urllib.parse
import webbrowser

import requests

CLIENT_KEY = None
CLIENT_SECRET = None
REDIRECT_URI = "http://localhost:8080/callback"
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

class CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        code = params.get("code", [None])[0]

        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()

        if not code:
            self.wfile.write(b"<h1>No authorization code received.</h1>")
            return

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
                import json
                json.dump(data, f, indent=2)
            self.wfile.write(b"<h1>Authorized. You can close this tab and return to the terminal.</h1>")
        else:
            self.wfile.write(f"<h1>Token exchange failed: {data}</h1>".encode())

        threading_stop(self.server)

def threading_stop(server):
    import threading
    threading.Thread(target=server.shutdown, daemon=True).start()

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

    server = http.server.HTTPServer(("localhost", 8080), CallbackHandler)
    print("Waiting for callback on http://localhost:8080/callback ...")
    server.serve_forever()
    print("Done. Token saved to token.json")

if __name__ == "__main__":
    main()
