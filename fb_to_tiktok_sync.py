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
import difflib
import json
import os
import platform
import random
import shutil
import subprocess
import tempfile
import time

import requests

DUPLICATE_SIMILARITY_THRESHOLD = 0.8

HERE = os.path.dirname(__file__)
SYNCED_LOG = os.path.join(HERE, "synced_videos.json")

# Cross-platform: env var overrides win; otherwise pick a sane per-OS default.
# Windows needs the drawtext path with an escaped colon; Linux does not.
if platform.system() == "Windows":
    FFMPEG = os.environ.get(
        "FFMPEG_PATH",
        r"C:\Users\ASUS\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.2-full_build\bin\ffmpeg.exe",
    )
    FONT_FILE = os.environ.get("FONT_FILE", r"C\:/Windows/Fonts/tahoma.ttf")
else:
    FFMPEG = os.environ.get("FFMPEG_PATH", shutil.which("ffmpeg") or "ffmpeg")
    FONT_FILE = os.environ.get(
        "FONT_FILE", "/usr/share/fonts/opentype/tlwg/Loma-Bold.otf"
    )

# Opening 3-second hooks — curiosity/benefit-driven, agriculture-themed (Thai).
# A larger, varied pool (questions, bold claims, social proof, urgency) so
# consecutive synced videos rarely repeat the same line.
HOOK_TEMPLATES = [
    "ทำไมต้นไม้คุณไม่โต? ดูนี่ก่อน!",
    "สูตรลับที่ชาวสวนไม่บอกใคร",
    "แค่นี้ผลผลิตเพิ่ม 30%!",
    "ห้ามพลาด! เคล็ดลับดินดี",
    "รากแข็งแรง ต้นโตไว ทำยังไง?",
    "เกษตรกรกว่า 1,000 คนเลือกใช้สูตรนี้",
    "ใส่ผิดวิธี ต้นไม่โตแน่นอน",
    "3 วินาทีนี้ เปลี่ยนสวนคุณได้เลย",
    "ทำไมสวนข้างบ้านถึงผลดกกว่า?",
    "เคล็ดลับที่ทำให้ผลไม้หวานขึ้น",
    "ปัญหานี้แก้ได้ง่ายกว่าที่คิด",
    "ดูก่อนซื้อปุ๋ยครั้งต่อไป",
    "สวนโมทำเอง รับประกันคุณภาพ",
    "เทคนิคที่มืออาชีพใช้จริง",
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
    "กดหัวใจไว้ก่อน แล้วลองทำตามดู",
    "อยากรู้ราคา ทักแชทมาได้เลยค่ะ",
    "แท็กเพื่อนที่กำลังหาปุ๋ยดีๆ อยู่",
    "ติดตามไว้ เดี๋ยวมีสูตรใหม่มาเรื่อยๆ",
]

# Hashtag pool: brand + niche + broad reach tags, rotated per post so the same
# combination doesn't appear on every post.
BRAND_HASHTAGS = ["#สวนโม", "#pineapplefarmmo", "#สวนโมออร์แกนิค"]
NICHE_HASHTAGS = [
    "#ปุ๋ยอินทรีย์", "#เกษตรกรรม", "#ทำสวน", "#ปลูกผลไม้", "#หน่อพันธุ์",
    "#ปุ๋ยชีวภาพ", "#สวนผลไม้", "#เกษตรอินทรีย์", "#ปลูกสับปะรด", "#รักการปลูก",
]
BROAD_HASHTAGS = [
    "#fyp", "#เกษตรไทย", "#ของดีบอกต่อ", "#tiktokshop", "#ติ๊กต็อกช้อป", "#รีวิวสินค้า",
]

def build_hashtags():
    # Keep it lean: 1 brand tag + 1-2 topic tags (niche or broad) = 2-3 total.
    topic_pool = NICHE_HASHTAGS + BROAD_HASHTAGS
    tags = random.sample(BRAND_HASHTAGS, 1) + random.sample(topic_pool, random.choice([1, 2]))
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
    """Burns `hook_text` as an on-screen hook with a smooth fade in/out over t=0-3s."""
    escaped = hook_text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "")
    # Fade in over 0.25s, hold, fade out over the last 0.25s of the 3s window.
    alpha_expr = (
        r"if(lt(t\,0.25)\,t/0.25\,"
        r"if(lt(t\,2.75)\,1\,"
        r"if(lt(t\,3.0)\,(3.0-t)/0.25\,0)))"
    )
    vf = (
        f"drawtext=fontfile='{FONT_FILE}':text='{escaped}':"
        f"fontcolor=0xFFF6D8:fontsize=66:"
        f"shadowcolor=black@0.7:shadowx=2:shadowy=3:"
        f"x=(w-text_w)/2:y=h*0.15:"
        f"box=1:boxcolor=0x1B4D3E@0.72:boxborderw=28:"
        f"alpha='{alpha_expr}'"
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

def fetch_existing_tiktok_captions(tiktok_token):
    """Pages through the account's existing TikTok videos and returns their captions,
    so we can avoid re-posting something that's already up (regardless of how it
    got there — this catches manual uploads too, not just ones we synced)."""
    captions = []
    cursor = None
    for _ in range(20):  # hard cap so a bug can't loop forever
        body = {"max_count": 20}
        if cursor:
            body["cursor"] = cursor
        r = requests.post(
            "https://open.tiktokapis.com/v2/video/list/",
            headers={"Authorization": f"Bearer {tiktok_token}", "Content-Type": "application/json; charset=UTF-8"},
            params={"fields": "title,video_description"},
            json=body,
        )
        data = r.json().get("data", {})
        for v in data.get("videos", []):
            text = (v.get("video_description") or v.get("title") or "").strip()
            if text:
                captions.append(text)
        if not data.get("has_more"):
            break
        cursor = data.get("cursor")
    return captions

def is_duplicate_caption(candidate_text, existing_captions):
    if not candidate_text:
        return False
    for existing in existing_captions:
        ratio = difflib.SequenceMatcher(None, candidate_text, existing).ratio()
        if ratio >= DUPLICATE_SIMILARITY_THRESHOLD:
            return True
    return False

def pick_video(videos, synced_ids, existing_tiktok_captions):
    candidates = [v for v in videos if v["id"] not in synced_ids]
    candidates = [
        v for v in candidates
        if not is_duplicate_caption((v.get("title") or v.get("description") or "").strip(), existing_tiktok_captions)
    ]
    if not candidates:
        return None
    # Random order each run — synced_ids guarantees no repeats across runs,
    # and it's updated within a batch so a single run never repeats either.
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

    for attempt in range(3):
        up = requests.put(
            upload_url,
            headers={
                "Content-Type": "video/mp4",
                "Content-Range": f"bytes 0-{video_size - 1}/{video_size}",
            },
            data=video_bytes,
            timeout=60,
        )
        if up.status_code in (200, 201):
            break
        time.sleep(3)
    else:
        raise SystemExit(f"TikTok upload failed after 3 attempts, last status: {up.status_code}")

    return init_data["data"]["publish_id"]

VIDEOS_PER_RUN = 5

def main():
    env = load_env()
    fb_page_id = env["FB_PAGE_ID"]
    tiktok_token = json.load(open(os.path.join(HERE, "token.json")))["access_token"]

    # Prefer a stored permanent Page Access Token (derived once from a long-lived
    # user token via fb_exchange_token — Page tokens obtained this way never expire).
    # Fall back to deriving one from a short-lived user token if not set.
    page_token = env.get("FB_PAGE_ACCESS_TOKEN")
    if not page_token:
        page_token = get_page_token(env["FB_TOKEN_RAW"], fb_page_id)

    videos = fetch_page_videos(page_token, fb_page_id)

    print("Checking existing TikTok videos to avoid re-posting duplicates...")
    existing_captions = fetch_existing_tiktok_captions(tiktok_token)
    print(f"Found {len(existing_captions)} existing TikTok videos to compare against.")

    synced_ids = load_synced()
    uploaded = 0

    for i in range(VIDEOS_PER_RUN):
        video = pick_video(videos, synced_ids, existing_captions)
        if video is None:
            print(f"[{i+1}/{VIDEOS_PER_RUN}] No eligible videos remain. Stopping early.")
            break

        base_text = (video.get("title") or video.get("description") or "").strip()[:150]
        hook = pick_hook()
        caption = build_caption(base_text, hook)
        print(f"[{i+1}/{VIDEOS_PER_RUN}] Picked video {video['id']} — hook: {hook!r}")
        print(f"Caption:\n{caption}")

        with tempfile.TemporaryDirectory() as tmp:
            raw_path = os.path.join(tmp, "raw.mp4")
            download_video(video["source"], raw_path)
            # Video stays untouched — the hook is text-only, placed in the caption below.
            publish_id = upload_to_tiktok(tiktok_token, raw_path, caption)
            print(f"Uploaded to TikTok inbox. publish_id={publish_id}")

        synced_ids.append(video["id"])
        existing_captions.append(caption)
        save_synced(synced_ids)
        uploaded += 1

    print(f"Done. Uploaded {uploaded}/{VIDEOS_PER_RUN} videos. Go into the TikTok app to set timing, add cart links, and publish.")

if __name__ == "__main__":
    main()
