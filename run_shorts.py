"""
Shorts pipeline (faceless / alternate-history): AI narrator + character + scene
shots, optional Pexels/Pixabay stock B-roll, music bed and burned-in subtitles.

Run order:
  1) python run_audio.py scenarios/<name>.json [edge|elevenlabs|kokoro|chatterbox]
        -> videos/<id>/voiceover.wav + timing.json
     (or: python make_timing.py scenarios/<name>.json if voiceover.wav exists)
  2) python run_shorts.py scenarios/<name>.json
        -> videos/<id>/final_v3.mp4  (+ final_v3_subs.mp4 with subtitles)

Secrets load from .env (see .env.example):
  FASTGEN_API_KEY                  - image generation (required for AI shots)
  PEXELS_API_KEY / PIXABAY_API_KEY - stock B-roll (optional)

Scenario shot types:
  narrator_shot   - recurring on-screen guide (persona.NARRATOR_POSES)
  character_shot  - POV protagonist (persona.PROTAGONIST_POSES) or custom prompt
  scene_shot      - AI scene from \"prompt\"; set \"source\":\"stock\" to use B-roll
  text_card / infographic_shot - local typewriter text card
"""
import os, sys, json, subprocess, time, re, base64, requests
from pathlib import Path
from datetime import datetime

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except Exception:
    pass

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))
from pexels_stock import fetch_stock_clips, load_global_used_ids
from persona import NARRATOR_POSES, PROTAGONIST_POSES

API_URL = os.getenv("FASTGEN_BASE_URL", "https://googler.fast-gen.ai")
STORAGE_URL = os.getenv("FASTGEN_STORAGE_URL", "https://storage.fast-gen.ai")
API_KEY = os.getenv("FASTGEN_API_KEY", "")
HEADERS = {"X-API-Key": API_KEY, "Content-Type": "application/json"}

SCENE_STYLE = ("9:16 vertical, photorealistic, cinematic chiaroscuro lighting, "
               "muted desaturated tones, film grain, ultra realistic, 4K")


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def api_generate_image(prompt):
    """Generate one 9:16 image via Fast Gen AI. Returns bytes or None."""
    if not API_KEY:
        log("  FASTGEN_API_KEY missing -> cannot generate AI image (set it in .env)")
        return None
    try:
        r = requests.post(f"{API_URL}/api/v4/openai/image/generate", headers=HEADERS,
                          json={"prompt": prompt, "aspect_ratio": "9:16"}, timeout=60)
        op_id = r.json().get("operation_id")
        if not op_id:
            return None
        for _ in range(20):
            time.sleep(10)
            d = requests.get(f"{API_URL}/api/v4/operations/{op_id}", headers=HEADERS, timeout=30).json()
            if d.get("status") == "success":
                img = d["result"]
                if isinstance(img, list):
                    img = img[0]
                if img.startswith("http"):
                    return requests.get(img, timeout=60).content
                elif img.startswith("file:"):
                    return requests.get(f"{STORAGE_URL}/file/{img[5:]}/raw", timeout=60).content
                elif img.startswith("data:image"):
                    m = re.match(r"data:image/[^;]+;base64,(.+)", img)
                    if m:
                        return base64.b64decode(m.group(1))
            elif d.get("status") == "error":
                return None
        return None
    except Exception:
        return None


def main():
    if len(sys.argv) < 2:
        print("Usage: python run_shorts.py scenarios/<name>.json")
        sys.exit(1)

    sc_path = BASE_DIR / sys.argv[1]
    with open(sc_path, "r", encoding="utf-8") as f:
        sc = json.load(f)

    proj = BASE_DIR / "videos" / sc["video_id"]
    proj.mkdir(parents=True, exist_ok=True)
    timing_path = proj / "timing.json"

    if not timing_path.exists():
        log("ERROR: timing.json missing. Run run_audio.py (or make_timing.py) first!")
        return

    with open(timing_path, "r", encoding="utf-8") as f:
        timing = json.load(f)

    shots = timing["shots"]
    all_sc_shots = {s["id"]: s for ch in sc["chapters"] for s in ch["shots"]}
    log(f"Project: {sc['title']} | {len(shots)} shots | {timing['total_duration']:.0f}s")

    # === GENERATE VISUALS ===
    log("=== Generating visuals ===")
    narr_idx = 0
    prot_idx = 0
    used_stock = load_global_used_ids()
    for f in proj.glob("stock_*"):
        used_stock.add(f.stem.replace("stock_", "").replace("_px", ""))

    for i, shot in enumerate(shots):
        sid = shot["id"]
        sc_shot = all_sc_shots.get(sid, {})
        shot_type = sc_shot.get("type", "scene_shot")
        source = sc_shot.get("source")
        dur = shot.get("duration", 2)

        img_path = proj / f"{sid}.png"
        stock_path = proj / f"{sid}_stock.mp4"
        text_path = proj / f"{sid}_text.mp4"
        if img_path.exists() or stock_path.exists() or text_path.exists():
            continue

        if shot_type in ("text_card", "infographic_shot"):
            from create_text_video import create_text_video
            visual = {"id": sid, "prompt": sc_shot.get("prompt", ""),
                      "words": shot.get("words", []), "duration": dur}
            create_text_video(visual, text_path, "9:16")
            log(f"  [{i+1}/{len(shots)}] {sid} TEXT")

        elif shot_type == "narrator_shot":
            prompt = sc_shot.get("prompt") or NARRATOR_POSES[narr_idx % len(NARRATOR_POSES)]
            narr_idx += 1
            data = api_generate_image(prompt)
            if data:
                img_path.write_bytes(data)
                log(f"  [{i+1}/{len(shots)}] {sid} NARRATOR OK")
            else:
                log(f"  [{i+1}/{len(shots)}] {sid} NARRATOR FAILED")

        elif shot_type == "character_shot":
            prompt = sc_shot.get("prompt") or PROTAGONIST_POSES[prot_idx % len(PROTAGONIST_POSES)]
            prot_idx += 1
            data = api_generate_image(prompt)
            if data:
                img_path.write_bytes(data)
                log(f"  [{i+1}/{len(shots)}] {sid} CHARACTER OK")
            else:
                log(f"  [{i+1}/{len(shots)}] {sid} CHARACTER FAILED")

        elif shot_type == "scene_shot" and source == "stock":
            vo_text = sc_shot.get("voiceover", "")
            clips = fetch_stock_clips(vo_text, count=1, out_dir=proj,
                                      orientation="portrait", used_ids=used_stock,
                                      scene_prompt=sc_shot.get("prompt", ""))
            if clips:
                if stock_path.exists():
                    stock_path.unlink()
                clips[0].rename(stock_path)
                used_stock.add(clips[0].stem.replace("stock_", "").replace("_px", ""))
                log(f"  [{i+1}/{len(shots)}] {sid} STOCK OK")
            else:
                data = api_generate_image((sc_shot.get("prompt") or "cinematic scene") + ", " + SCENE_STYLE)
                if data:
                    img_path.write_bytes(data)
                    log(f"  [{i+1}/{len(shots)}] {sid} AI SCENE OK")

        else:  # scene_shot, AI by default
            prompt = (sc_shot.get("prompt") or "cinematic ancient scene") + ", " + SCENE_STYLE
            data = api_generate_image(prompt)
            if data:
                img_path.write_bytes(data)
                log(f"  [{i+1}/{len(shots)}] {sid} AI SCENE OK")
            else:
                vo_text = sc_shot.get("voiceover", "")
                clips = fetch_stock_clips(vo_text, count=1, out_dir=proj,
                                          orientation="portrait", used_ids=used_stock,
                                          scene_prompt=sc_shot.get("prompt", ""))
                if clips:
                    if stock_path.exists():
                        stock_path.unlink()
                    clips[0].rename(stock_path)
                    used_stock.add(clips[0].stem.replace("stock_", "").replace("_px", ""))
                    log(f"  [{i+1}/{len(shots)}] {sid} STOCK FALLBACK OK")

    # === ASSEMBLE (per-shot ffmpeg clips -> concat -> mux voice + music) ===
    log("=== Assembling ===")
    W, H = 1080, 1920
    clip_paths = []

    for i, shot in enumerate(shots):
        sid = shot["id"]
        dur = shot.get("duration", 2)
        if dur <= 0:
            dur = 2.0

        img = proj / f"{sid}.png"
        stock = proj / f"{sid}_stock.mp4"
        text_mp4 = proj / f"{sid}_text.mp4"
        temp = proj / f"_v{i:04d}.mp4"
        fps = 30
        frames = max(int(dur * fps), 1)

        if text_mp4.exists():
            subprocess.run(["ffmpeg", "-y", "-i", str(text_mp4), "-t", f"{dur:.3f}",
                "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}",
                "-an", "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p", "-r", "30",
                str(temp)], capture_output=True)
        elif stock.exists():
            subprocess.run(["ffmpeg", "-y", "-i", str(stock), "-t", f"{dur:.3f}",
                "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fade=t=in:st=0:d=0.2,fade=t=out:st={max(0,dur-0.2):.3f}:d=0.2",
                "-an", "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p", "-r", "30",
                str(temp)], capture_output=True)
        elif img.exists():
            z = f"z='1+0.03*on/{frames}'" if i % 2 == 0 else f"z='1.03-0.03*on/{frames}'"
            subprocess.run(["ffmpeg", "-y", "-loop", "1", "-i", str(img), "-t", f"{dur:.3f}",
                "-vf", f"scale=8000:-1,zoompan={z}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={W}x{H}:fps={fps},fade=t=in:st=0:d=0.2,fade=t=out:st={max(0,dur-0.2):.3f}:d=0.2",
                "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "fast",
                str(temp)], capture_output=True)
        else:
            subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=black:s={W}x{H}:d={dur:.3f}:r=30",
                "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "fast", str(temp)], capture_output=True)

        if temp.exists() and temp.stat().st_size > 0:
            clip_paths.append(temp)

    concat_file = proj / "_concat.txt"
    concat_file.write_text("\n".join(f"file '{p.name}'" for p in clip_paths), encoding="utf-8")
    vo_file = proj / "_video.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-c:v", "libx264", "-b:v", "5000k", "-preset", "fast", "-pix_fmt", "yuv420p", "-r", "30",
        str(vo_file)], capture_output=True, cwd=str(proj))

    audio = proj / "voiceover.wav"
    music_files = list((BASE_DIR / "assets" / "music").glob("*"))
    music = music_files[0] if music_files else None
    final = proj / "final_v3.mp4"

    if audio.exists() and music:
        subprocess.run(["ffmpeg", "-y", "-i", str(vo_file), "-i", str(audio),
            "-stream_loop", "-1", "-i", str(music),
            "-filter_complex", "[1:a]volume=1.0[voice];[2:a]volume=0.05[bg];[voice][bg]amix=inputs=2:duration=first[a]",
            "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-shortest", str(final)],
            capture_output=True)
    elif audio.exists():
        subprocess.run(["ffmpeg", "-y", "-i", str(vo_file), "-i", str(audio),
            "-c:v", "copy", "-c:a", "aac", "-shortest", str(final)], capture_output=True)

    for f in proj.glob("_*"):
        f.unlink()

    # === SUBTITLES ===
    if final.exists():
        log(f"  final_v3.mp4: {final.stat().st_size // 1024 // 1024} MB")
        try:
            from shorts_subtitles import burn_subtitles
            subbed = burn_subtitles(final)
            if subbed and Path(subbed).exists():
                log(f"  subtitles: {Path(subbed).name}")
        except Exception as e:
            log(f"  subtitles skipped: {e}")

    log("DONE!" if final.exists() else "FAILED")


if __name__ == "__main__":
    main()
