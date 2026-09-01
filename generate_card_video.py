"""Animate today's published artwork with subtle Seedance micro-effects."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from urllib.parse import quote, urljoin

import requests


API_BASE = "https://openrouter.ai/api/v1/"
VIDEO_URL = urljoin(API_BASE, "videos")
VIDEO_MODEL = os.environ.get(
    "VIDEO_MODEL", "bytedance/seedance-1-5-pro"
).strip()
FRAME_BASE_URL = os.environ.get(
    "VIDEO_FRAME_BASE_URL",
    "https://raw.githubusercontent.com/yulechkaa/yulechkaa.github.io/main/",
).rstrip("/") + "/"
POLL_SECONDS = 20
TIMEOUT_SECONDS = 25 * 60


def log(message: str) -> None:
    print(message, flush=True)


def api_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://yulechkaa.github.io/",
        "X-Title": "Yulechka subtle daily video background",
    }


def build_prompt(card: dict) -> str:
    verse = " ".join(card.get("verse") or [])
    return f"""
Turn this exact illustration into a seamless 4-second living-poster loop. This
is not a scene: there must be no plot, action, progression, or camera movement.
At least 95% of the image must appear completely static at every moment. Preserve
the exact composition, silhouettes, colors, and quiet readable center.

Mood: {card.get('mood', '')}.
Visual concept: {card.get('concept', '')}.
Poem meaning: {verse}.

Choose only one or two tiny decorative effects that naturally fit the visible
artwork and poetic context: restrained specular glints, a few softly twinkling
sparkles, delicate iridescence on existing glass/candy/water/metal details,
very slow dust motes, faint breathing glow, or minimal movement of a few leaves.
Keep effects localized near existing objects, low-amplitude and elegant. The
center must remain calm, still, and fully readable.

The last frame must match the first frame exactly. No story, character action,
object travel, full-frame animation, light ribbons, sweeping rays, energy trails,
large particles, wind, parallax, pan, tilt, zoom, cuts, morphing, warping,
exposure pulses, flicker, text, or logos.
""".strip()


def frame_url(image_path: str) -> str:
    safe_path = "/".join(quote(part) for part in image_path.split("/"))
    return urljoin(FRAME_BASE_URL, safe_path)


def verify_frame(url: str) -> bool:
    try:
        response = requests.head(url, allow_redirects=True, timeout=30)
    except requests.RequestException as error:
        log(f"Video frame is unavailable: {error}")
        return False
    content_type = response.headers.get("Content-Type", "")
    if not response.ok or not content_type.startswith("image/"):
        log(f"Video frame HTTP {response.status_code}, type={content_type or 'unknown'}")
        return False
    return True


def submit(api_key: str, card: dict, source_url: str) -> dict | None:
    payload = {
        "model": VIDEO_MODEL,
        "prompt": build_prompt(card),
        "duration": 4,
        "resolution": "480p",
        "aspect_ratio": "9:16",
        "generate_audio": False,
        "frame_images": [
            {
                "type": "image_url",
                "image_url": {"url": source_url},
                "frame_type": "first_frame",
            },
            {
                "type": "image_url",
                "image_url": {"url": source_url},
                "frame_type": "last_frame",
            },
        ],
    }
    try:
        response = requests.post(
            VIDEO_URL, headers=api_headers(api_key), json=payload, timeout=90
        )
    except requests.RequestException as error:
        log(f"Video submit network error: {error}")
        return None
    if not response.ok:
        log(f"Video submit HTTP {response.status_code}: {response.text[:500]}")
        return None
    job = response.json()
    if not job.get("id"):
        log(f"Video API returned no job id: {job}")
        return None
    log(f"Submitted {VIDEO_MODEL}: {job['id']}")
    return job


def wait_for_video(api_key: str, job: dict) -> dict | None:
    deadline = time.monotonic() + TIMEOUT_SECONDS
    polling_url = job.get("polling_url") or urljoin(API_BASE, f"videos/{job['id']}")
    previous_status = None
    while time.monotonic() < deadline:
        try:
            response = requests.get(
                polling_url, headers=api_headers(api_key), timeout=60
            )
        except requests.RequestException as error:
            log(f"Video poll network error: {error}")
            time.sleep(POLL_SECONDS)
            continue
        if not response.ok:
            log(f"Video poll HTTP {response.status_code}: {response.text[:300]}")
            return None
        result = response.json()
        status = result.get("status", "unknown")
        if status != previous_status:
            log(f"Video status: {status}")
            previous_status = status
        if status == "completed":
            return result
        if status in {"failed", "cancelled", "expired"}:
            reason = result.get("error") or result.get("failure_reason") or "unknown"
            log(f"Video generation {status}: {str(reason)[:1000]}")
            return None
        time.sleep(POLL_SECONDS)
    log("Video generation timed out")
    return None


def download_video(api_key: str, result: dict, output_path: Path) -> bool:
    urls = result.get("unsigned_urls") or []
    if not urls and isinstance(result.get("output"), dict):
        urls = result["output"].get("unsigned_urls") or []
    url = urls[0] if urls else urljoin(
        API_BASE, f"videos/{result['id']}/content?index=0"
    )
    download_headers = api_headers(api_key) if url.startswith(API_BASE) else {}
    try:
        response = requests.get(url, headers=download_headers, timeout=180)
    except requests.RequestException as error:
        log(f"Video download network error: {error}")
        return False
    if not response.ok:
        log(f"Video download HTTP {response.status_code}: {response.text[:300]}")
        return False
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(response.content)
    log(f"Saved {output_path} ({output_path.stat().st_size:,} bytes)")
    return True


def polish_seamless_loop(video_path: Path) -> None:
    """Blend the final 0.45s back to the opening motion for a reliable loop."""
    temporary_path = video_path.with_name(f"{video_path.stem}.loop.mp4")
    try:
        probe = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(video_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        duration = float(probe.stdout.strip())
        fade = min(0.45, duration / 5)
        offset = max(0.0, duration - fade)
        filter_graph = (
            "[0:v]split=2[full][head];"
            f"[head]trim=start=0:end={fade:.6f},setpts=PTS-STARTPTS,reverse[rev];"
            f"[full][rev]xfade=transition=fade:duration={fade:.6f}:"
            f"offset={offset:.6f},format=yuv420p[v]"
        )
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(video_path), "-filter_complex", filter_graph,
                "-map", "[v]", "-an", "-c:v", "libx264", "-crf", "20",
                "-preset", "medium", "-movflags", "+faststart", str(temporary_path),
            ],
            check=True,
        )
        os.replace(temporary_path, video_path)
        log(f"Polished seamless loop ({fade:.2f}s transition)")
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        log(f"Seamless post-process skipped: {error}")
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass


def update_card_files(card: dict, video_path: str) -> None:
    card["video"] = video_path
    card["video_model"] = VIDEO_MODEL
    Path("data.json").write_text(
        json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    archive_path = Path("archive.json")
    try:
        archive = json.loads(archive_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        archive = []
    for item in reversed(archive if isinstance(archive, list) else []):
        if item.get("date") == card.get("date") and item.get("rhyme") == card.get("rhyme"):
            item["video"] = video_path
            item["video_model"] = VIDEO_MODEL
            break
    archive_path.write_text(
        json.dumps(archive, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        log("OPENROUTER_API_KEY is missing; keeping the static image fallback")
        return

    try:
        card = json.loads(Path("data.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        log(f"Cannot read data.json: {error}")
        return
    image_path = card.get("image") or ""
    if not image_path.startswith("art/") or not image_path.endswith(".webp"):
        log("Today's card has no suitable source image; video skipped")
        return

    source_url = frame_url(image_path)
    log(f"Video source: {source_url}")
    if not verify_frame(source_url):
        return
    job = submit(api_key, card, source_url)
    if not job:
        return
    result = wait_for_video(api_key, job)
    if not result:
        return

    output_path = Path("art") / f"{card.get('date', 'today')}.mp4"
    if not download_video(api_key, result, output_path):
        return
    polish_seamless_loop(output_path)
    video_path = output_path.as_posix()
    update_card_files(card, video_path)
    log(f"Video background ready: {video_path}")


if __name__ == "__main__":
    main()
