"""
Voice audition: generate side-by-side TTS samples for several candidate voices
via the Voicer API (ElevenLabs proxy). Listen to the MP3s and pick your favorite,
then put its voice_id into your scenario's voice_settings.

Usage:
  # put VOICER_API_KEY in .env (or export it), then:
  python make_voice_tests.py                      # all candidate voices
  python make_voice_tests.py --voice Bill --voice Eric   # only a subset
  python make_voice_tests.py --text \"Your own test line.\"

Output: voice_tests/<Name>_<voice_id>.mp3

Docs: https://voiceapi.csv666.ru/llm.md
  - Standard-library ElevenLabs voices need NO public_owner_id.
  - Find fresher (less-trending) voices yourself:
      GET /api/voices?library=public&gender=male&accent=american&use_case=narration&sort=newest
"""
import os
import sys
import time
import argparse
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

BASE_DIR = Path(__file__).parent
# Main domain; if blocked in your region use the backup voiceapiru.csv666.ru
BASE_URL = os.getenv("VOICER_BASE_URL", "https://voiceapi.csv666.ru")
API_KEY = os.getenv("VOICER_API_KEY", "")
OUT_DIR = BASE_DIR / "voice_tests"

# --- Candidate voices -------------------------------------------------------
# name -> (voice_id, note). All are standard-library ElevenLabs voices
# (public_owner_id not required). Edit freely / add your own finds.
VOICES = {
    "Bill":   ("pqHfZKP75CvOlQylNhV4", "warm mature US narrator - fresh, top pick"),
    "Eric":   ("cjVigY5qzO86Huf0OWal", "smooth modern US male - fresh"),
    "George": ("JBFqnCBsd6RMkjVDRZzb", "warm raspy narrator - atmospheric"),
    "Will":   ("bIHbv24MWmeRgasZH58o", "friendly young US male - fresh"),
    "Chris":  ("iP95p4xoKVk53GoZ742B", "casual natural US male"),
    "Callum": ("N2lVS1w4EtoT3dr4eOWO", "intense gravelly - dramatic tension"),
    "Liam":   ("TX3LPaxmHKxFdv7VOQHJ", "young articulate US male"),
}

MODEL_ID = "eleven_multilingual_v2"
VOICE_SETTINGS = {
    "stability": 0.45,
    "similarity_boost": 0.8,
    "style": 0.3,
    "use_speaker_boost": True,
    "speed": 1.0,
}

# Dramatic narration line from the flagship scenario (good stress test).
SAMPLE_TEXT = (
    "You're a special forces soldier in 2026. One second you're on patrol. "
    "The next, you're face down in cold mud. You look up - stone aqueducts, "
    "men in armor. This is Rome, seventy-nine A D. And you do not belong here. "
    "So let's run it: how long does a modern soldier actually survive in the ancient world?"
)

HEADERS = {"X-API-Key": API_KEY, "Content-Type": "application/json"}


def create_task(text, voice_id):
    r = requests.post(
        f"{BASE_URL}/tasks",
        headers=HEADERS,
        json={
            "text": text,
            "template": {
                "model_id": MODEL_ID,
                "voice_id": voice_id,
                "voice_settings": VOICE_SETTINGS,
            },
        },
        timeout=60,
    )
    if r.status_code != 200:
        raise RuntimeError(f"create failed HTTP {r.status_code}: {r.text[:200]}")
    data = r.json()
    return data["task_id"], data.get("message", "")


def wait_result(task_id, timeout=300):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = requests.get(f"{BASE_URL}/tasks/{task_id}/status", headers={"X-API-Key": API_KEY}, timeout=30)
        status = r.json().get("status")
        if status == "ending":
            return
        if status in ("error", "error_handled"):
            raise RuntimeError(f"task {task_id} failed: {r.json().get('error')}")
        time.sleep(3)
    raise TimeoutError(f"task {task_id} timed out after {timeout}s")


def download(task_id, out_path):
    r = requests.get(f"{BASE_URL}/tasks/{task_id}/result", headers={"X-API-Key": API_KEY}, timeout=120)
    if r.status_code != 200:
        raise RuntimeError(f"download failed HTTP {r.status_code}: {r.text[:200]}")
    out_path.write_bytes(r.content)


def main():
    ap = argparse.ArgumentParser(description="Generate TTS voice samples via Voicer API")
    ap.add_argument("--text", default=SAMPLE_TEXT, help="custom test line")
    ap.add_argument("--voice", action="append", help="voice name(s) to test (repeatable)")
    args = ap.parse_args()

    if not API_KEY:
        print("ERROR: VOICER_API_KEY is not set (put it in .env or export it)")
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    names = args.voice or list(VOICES.keys())
    print(f"Generating {len(names)} sample(s) -> {OUT_DIR}\n")

    ok = 0
    for name in names:
        if name not in VOICES:
            print(f"  ? unknown voice '{name}', skipping (known: {', '.join(VOICES)})")
            continue
        voice_id, note = VOICES[name]
        print(f"  [{name}] {note}")
        try:
            task_id, msg = create_task(args.text, voice_id)
            print(f"    task {task_id} created ({msg})")
            wait_result(task_id)
            out = OUT_DIR / f"{name}_{voice_id}.mp3"
            download(task_id, out)
            print(f"    saved -> {out.name}\n")
            ok += 1
        except Exception as e:
            print(f"    FAILED: {e}\n")

    print(f"Done: {ok}/{len(names)} samples in {OUT_DIR}")
    print("Pick a voice, then set its voice_id in your scenario's voice_settings.")


if __name__ == "__main__":
    main()
