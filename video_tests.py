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
        "reuse_env": "VIDEO_TEST_REUSE_SEEDANCE_1_5_PRO",
    },
    {
        "slug": "seedance-2-0-mini",
        "model": "bytedance/seedance-2.0-mini",
        "resolution": "480p",
        "reuse_env": "VIDEO_TEST_REUSE_SEEDANCE_2_0_MINI",
    },
    {
        "slug": "veo-3-1-lite",
        "model": "google/veo-3.1-lite",
        "resolution": "720p",
        "reuse_env": "VIDEO_TEST_REUSE_VEO_3_1_LITE",
    },
)


def load_context() -> str:
    explicit = os.environ.get("VIDEO_TEST_CONTEXT", "").strip()
    if explicit:
        return explicit
    try:
        data = json.loads(Path("data.json").read_text(encoding="utf-8"))
        verse = " ".join(data.get("verse") or [])
        return (
            f"Mood: {data.get('mood', '')}. "
            f"Visual concept: {data.get('concept', '')}. "
            f"Poem: {verse}"
        ).strip()
    except (OSError, ValueError, TypeError):
        return "A refined poetic greeting-card background."


CONTEXT = load_context()
PROMPT = f"""
Turn this exact artwork into a seamless 4-second living-poster loop. This is not
a scene and must contain no plot, action, or progression. At least 95% of the
image must appear completely static at every moment. Lock the camera and retain
the exact composition, silhouettes, colors, and clean readable center.

Context: {CONTEXT}

Choose only one or two tiny decorative effects that naturally fit the visible
artwork and context. Examples: restrained specular glints on glass or candy,
a few softly twinkling sparkles, a delicate shimmer on water or metallic detail,
very slow dust motes, faint breathing glow, or minimal movement of a few leaves.
Effects must stay localized near existing objects, be low-amplitude and elegant,
and merely add polish. Keep the center quiet and fully readable.

The last frame must match the first frame exactly. No story, character action,
object movement across the frame, new objects, full-frame animation, light
ribbons, sweeping beams, energy trails, large particles, wind gusts, parallax,
camera movement, pan, tilt, zoom, cuts, morphing, warping, pulsing exposure,
flicker, text, or logos.
""".strip()


def headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://yulechkaa.github.io/",
        "X-Title": "Yulechka background video comparison",
    }


def submit(api_key: str, spec: dict[str, str]) -> dict:
    reused_id = os.environ.get(spec["reuse_env"], "").strip()
    if reused_id:
        print(f"Reusing {spec['model']}: {reused_id}", flush=True)
        return {
            "id": reused_id,
            "slug": spec["slug"],
            "model": spec["model"],
            "resolution": spec["resolution"],
        }

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
                reason = state.get("error") or state.get("failure_reason")
                if reason:
                    print(
                        f"{job['model']} failure details: {str(reason)[:1000]}",
                        flush=True,
                    )
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
