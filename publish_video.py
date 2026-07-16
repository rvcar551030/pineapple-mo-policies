"""
Step 2 of the demo flow: upload a finished video to the TikTok inbox
(video.upload scope) using the access token saved by oauth_login.py.

Usage: python publish_video.py path\to\video.mp4 "Caption text here"
"""
import json
import os
import sys
import time

import requests

def load_token():
    token_path = os.path.join(os.path.dirname(__file__), "token.json")
    with open(token_path) as f:
        return json.load(f)

def main():
    if len(sys.argv) < 3:
        raise SystemExit('Usage: python publish_video.py <video_path> "<caption>"')

    video_path = sys.argv[1]
    caption = sys.argv[2]
    token = load_token()
    access_token = token["access_token"]

    video_size = os.path.getsize(video_path)
    print(f"Video size: {video_size} bytes")

    init_resp = requests.post(
        "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        },
        json={
            "post_info": {"title": caption},
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": video_size,
                "chunk_size": video_size,
                "total_chunk_count": 1,
            },
        },
    )
    init_data = init_resp.json()
    print("Init response:", json.dumps(init_data, indent=2))

    if "data" not in init_data or "upload_url" not in init_data["data"]:
        raise SystemExit("Init failed, see response above.")

    publish_id = init_data["data"]["publish_id"]
    upload_url = init_data["data"]["upload_url"]

    with open(video_path, "rb") as f:
        video_bytes = f.read()

    upload_resp = requests.put(
        upload_url,
        headers={
            "Content-Type": "video/mp4",
            "Content-Range": f"bytes 0-{video_size - 1}/{video_size}",
        },
        data=video_bytes,
    )
    print("Upload status:", upload_resp.status_code)

    print("Polling publish status...")
    for _ in range(10):
        status_resp = requests.post(
            "https://open.tiktokapis.com/v2/post/publish/status/fetch/",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            json={"publish_id": publish_id},
        )
        status_data = status_resp.json()
        status = status_data.get("data", {}).get("status")
        print("Status:", status)
        if status in ("PUBLISH_COMPLETE", "FAILED"):
            print(json.dumps(status_data, indent=2))
            break
        time.sleep(3)

if __name__ == "__main__":
    main()
