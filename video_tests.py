"""Generate three comparable seamless-loop background video candidates."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from urllib.parse import urljoin

import requests


API_BASE = "https://openrouter.ai/api/v1/"
VIDEO_URL = urljoin(API_BASE, "videos")
FRAME_URL = os.environ.get(
    "VIDEO_TEST_FRAME_URL",
    "https://yulechkaa.github.io/art/2026-09-01.webp",
)
OUTPUT_DIR = Path("video-tests")
POLL_SECONDS = 20
TIMEOUT_SECONDS = 30 * 60

MODELS = (
    {
        "slug": "seedance-1-5-pro",
        "model": "bytedance/seedance-1-5-pro",
        "resolution": "480p",
    },
    {
        "slug": "seedance-2-0-mini",
        "model": "bytedance/seedance-2.0-mini",
        "resolution": "480p",
    },
    {
        "slug": "veo-3-1-lite",
        "model": "google/veo-3.1-lite",
        "resolution": "720p",
    },
)

PROMPT = """
Create a subtle seamless animated background loop from this exact artwork.
Keep the camera completely locked and preserve the original composition, colors,
objects, and empty readable center. Animate only delicate atmospheric motion:
soft drifting glow, tiny dust or sparkle particles, a very gentle breeze, and
barely perceptible parallax. The final frame must return exactly to the first
frame so the 4-second clip loops without a visible jump. No text, no new objects,
no cuts, no zoom, no camera movement, no warping, no morphing, no flicker.
""".strip()


def headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://yulechkaa.github.io/",
        "X-Title": "Yulechka background video comparison",
    }


def submit(api_key: str, spec: dict[str, str]) -> dict:
    payload = {
        "model": spec["model"],
        "prompt": PROMPT,
        "duration": 4,
        "resolution": spec["resolution"],
        "aspect_ratio": "9:16",
        "generate_audio": False,
        "frame_images": [
            {
                "type": "image_url",
                "image_url": {"url": FRAME_URL},
                "frame_type": "first_frame",
            },
            {
                "type": "image_url",
                "image_url": {"url": FRAME_URL},
                "frame_type": "last_frame",
            },
        ],
    }
    response = requests.post(
        VIDEO_URL, headers=headers(api_key), json=payload, timeout=90
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("id"):
        raise RuntimeError(f"OpenRouter did not return a video id: {data}")
    data["slug"] = spec["slug"]
    data["model"] = spec["model"]
    data["resolution"] = spec["resolution"]
    print(f"Submitted {spec['model']}: {data['id']}", flush=True)
    return data


def poll(api_key: str, jobs: list[dict]) -> None:
    deadline = time.monotonic() + TIMEOUT_SECONDS
    pending = {job["id"]: job for job in jobs}
    terminal_failures = {"failed", "cancelled", "expired"}

    while pending and time.monotonic() < deadline:
        for job_id, job in list(pending.items()):
            polling_url = job.get("polling_url") or urljoin(API_BASE, f"videos/{job_id}")
            response = requests.get(
                polling_url, headers=headers(api_key), timeout=60
            )
            response.raise_for_status()
            state = response.json()
            status = state.get("status", "unknown")
            if status != job.get("last_status"):
                print(f"{job['model']}: {status}", flush=True)
                job["last_status"] = status
            job["result"] = state
            if status == "completed":
                del pending[job_id]
            elif status in terminal_failures:
                del pending[job_id]
        if pending:
            time.sleep(POLL_SECONDS)

    if pending:
        names = ", ".join(job["model"] for job in pending.values())
        raise TimeoutError(f"Video generation timed out: {names}")


def download(api_key: str, job: dict) -> Path:
    result = job["result"]
    urls = result.get("unsigned_urls") or []
    if not urls and isinstance(result.get("output"), dict):
        urls = result["output"].get("unsigned_urls") or []
    url = urls[0] if urls else urljoin(API_BASE, f"videos/{job['id']}/content?index=0")
    response = requests.get(url, headers=headers(api_key), timeout=180)
    response.raise_for_status()
    path = OUTPUT_DIR / f"{job['slug']}.mp4"
    path.write_bytes(response.content)
    print(f"Downloaded {path} ({path.stat().st_size:,} bytes)", flush=True)
    return path


def main() -> None:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is required")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    jobs = [submit(api_key, spec) for spec in MODELS]
    poll(api_key, jobs)

    failures = []
    manifest = {
        "frame_url": FRAME_URL,
        "duration_seconds": 4,
        "aspect_ratio": "9:16",
        "generate_audio": False,
        "prompt": PROMPT,
        "videos": [],
    }
    for job in jobs:
        status = job.get("result", {}).get("status", "unknown")
        item = {
            "model": job["model"],
            "job_id": job["id"],
            "resolution": job["resolution"],
            "status": status,
        }
        if status == "completed":
            item["file"] = str(download(api_key, job)).replace("\\", "/")
        else:
            failures.append(f"{job['model']}: {status}")
        manifest["videos"].append(item)

    (OUTPUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if failures:
        raise RuntimeError("; ".join(failures))


if __name__ == "__main__":
    main()
