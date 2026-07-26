"""
Syncs one video from the Facebook Page to the TikTok inbox (as a draft) per run.

Logic:
- Fetch the Page's video list from Facebook.
- Prefer the newest video not yet synced.
- If no new video exists, pick a random not-yet-synced video from the existing list.
- Record synced video IDs in synced_videos.json to avoid repeats.
- Upload picked video to TikTok via the Content Posting API (video.upload -> inbox draft).
  The user manually sets timing, adds the shopping cart link, and publishes from
  within the TikTok app.

Usage: python fb_to_tiktok_sync.py
Run on a schedule (e.g. 3x/day via Windows Task Scheduler).
"""
import json
import os
import random
import subprocess
import tempfile

import requests

HERE = os.path.dirname(__file__)
SYNCED_LOG = os.path.join(HERE, "synced_videos.json")

FFMPEG = r"C:\Users\ASUS\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.2-full_build\bin\ffmpeg.exe"
FONT_FILE = r"C\:/Windows/Fonts/tahoma.ttf"

# Opening 3-second hooks — curiosity/benefit-driven, agriculture-themed (Thai).
# Rotated randomly so consecutive synced videos don't repeat the same hook.
HOOK_TEMPLATES = [
    "ทำไมต้นไม้คุณไม่โต? ดูนี่ก่อน!",
    "สูตรลับที่ชาวสวนไม่บอกใคร",
    "แค่นี้ผลผลิตเพิ่ม 30%!",
    "ห้ามพลาด! เคล็ดลับดินดี",
    "รากแข็งแรง ต้นโตไว ทำยังไง?",
]

def pick_hook():
    return random.choice(HOOK_TEMPLATES)

# In-platform interaction CTAs — drive comments/saves, not off-platform clicks
# (TikTok suppresses reach for content that pushes users to other platforms).
CTA_TEMPLATES = [
    "คอมเมนต์บอกเราหน่อยว่าอยากรู้สูตรไหนต่อ",
    "เซฟไว้เลย เดี๋ยวหาไม่เจอ",
    "ใครเคยลองแบบนี้บ้าง คอมเมนต์บอกกันหน่อย",
    "แชร์ให้เพื่อนชาวสวนคนอื่นดูด้วยนะ",
]

# Hashtag pool: brand + niche + broad reach tags, rotated per post.
BRAND_HASHTAGS = ["#สวนโม", "#pineapplefarmmo"]
NICHE_HASHTAGS = ["#ปุ๋ยอินทรีย์", "#เกษตรกรรม", "#ทำสวน", "#ปลูกผลไม้", "#หน่อพันธุ์"]
BROAD_HASHTAGS = ["#fyp", "#เกษตรไทย", "#ของดีบอกต่อ"]

def build_hashtags():
    tags = BRAND_HASHTAGS + random.sample(NICHE_HASHTAGS, 2) + random.sample(BROAD_HASHTAGS, 1)
    return " ".join(tags)

def build_caption(base_text, hook_text):
    cta = random.choice(CTA_TEMPLATES)
    hashtags = build_hashtags()
    parts = [hook_text]
    if base_text:
        parts.append(base_text)
    parts.append(cta)
    parts.append(hashtags)
    return "\n".join(parts)[:2200]

def add_opening_hook(src_path, dst_path, hook_text):
    """Burns `hook_text` as bold on-screen text visible only during t=0-3s."""
    escaped = hook_text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "")
    vf = (
        f"drawtext=fontfile='{FONT_FILE}':text='{escaped}':"
        f"fontcolor=white:fontsize=64:borderw=3:bordercolor=black:"
        f"x=(w-text_w)/2:y=h*0.15:"
        f"box=1:boxcolor=black@0.45:boxborderw=24:"
        r"enable='between(t\,0\,3)'"
    )
    subprocess.run(
        [FFMPEG, "-y", "-i", src_path, "-vf", vf, "-c:a", "copy", dst_path],
        check=True, capture_output=True,
    )

def load_env():
    env = {}
    with open(os.path.join(HERE, ".env")) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k] = v
    return env

def get_page_token(user_token, page_id):
    resp = requests.get(
        "https://graph.facebook.com/v25.0/me/accounts",
        params={"access_token": user_token, "fields": "id,name,access_token"},
    )
    data = resp.json()
    for page in data.get("data", []):
        if page["id"] == page_id:
            return page["access_token"]
    raise SystemExit(f"Page {page_id} not found in /me/accounts response: {data}")

def fetch_page_videos(page_token, page_id):
    resp = requests.get(
        f"https://graph.facebook.com/v25.0/{page_id}/videos",
        params={
            "access_token": page_token,
            "fields": "id,title,description,created_time,source",
            "limit": 100,
        },
    )
    data = resp.json()
    if "data" not in data:
        raise SystemExit(f"Failed to fetch videos: {data}")
    return data["data"]

def load_synced():
    if os.path.exists(SYNCED_LOG):
        with open(SYNCED_LOG) as f:
            return json.load(f)
    return []

def save_synced(synced_ids):
    with open(SYNCED_LOG, "w") as f:
        json.dump(synced_ids, f, indent=2)

def pick_video(videos, synced_ids):
    candidates = [v for v in videos if v["id"] not in synced_ids]
    if not candidates:
        return None
    # newest first (FB returns videos newest-first by default)
    candidates.sort(key=lambda v: v.get("created_time", ""), reverse=True)
    newest = candidates[0]
    already_had_newest_before = len(synced_ids) > 0 and videos and videos[0]["id"] in synced_ids
    if not already_had_newest_before:
        return newest
    return random.choice(candidates)

def download_video(source_url, dest_path):
    with requests.get(source_url, stream=True) as r:
        r.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)

def upload_to_tiktok(access_token, video_path, caption):
    video_size = os.path.getsize(video_path)
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
    if "data" not in init_data:
        raise SystemExit(f"TikTok init failed: {init_data}")

    upload_url = init_data["data"]["upload_url"]
    with open(video_path, "rb") as f:
        video_bytes = f.read()
    requests.put(
        upload_url,
        headers={
            "Content-Type": "video/mp4",
            "Content-Range": f"bytes 0-{video_size - 1}/{video_size}",
        },
        data=video_bytes,
    )
    return init_data["data"]["publish_id"]

def main():
    env = load_env()
    fb_user_token = env["FB_TOKEN_RAW"]
    fb_page_id = env["FB_PAGE_ID"]
    tiktok_token = json.load(open(os.path.join(HERE, "token.json")))["access_token"]

    page_token = get_page_token(fb_user_token, fb_page_id)
    videos = fetch_page_videos(page_token, fb_page_id)

    synced_ids = load_synced()
    video = pick_video(videos, synced_ids)
    if video is None:
        print("No unsynced videos remain. Nothing to do.")
        return

    base_text = (video.get("title") or video.get("description") or "").strip()[:150]
    hook = pick_hook()
    caption = build_caption(base_text, hook)
    print(f"Picked video {video['id']} — hook: {hook!r}")
    print(f"Caption:\n{caption}")

    with tempfile.TemporaryDirectory() as tmp:
        raw_path = os.path.join(tmp, "raw.mp4")
        hooked_path = os.path.join(tmp, "hooked.mp4")
        download_video(video["source"], raw_path)
        add_opening_hook(raw_path, hooked_path, hook)
        publish_id = upload_to_tiktok(tiktok_token, hooked_path, caption)
        print(f"Uploaded to TikTok inbox. publish_id={publish_id}")

    synced_ids.append(video["id"])
    save_synced(synced_ids)
    print("Recorded as synced. Go into the TikTok app to set timing, add the cart link, and publish.")

if __name__ == "__main__":
    main()
