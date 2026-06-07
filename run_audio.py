"""
Phase 1: Audio Generation + Transcription
==========================================
Generates TTS for all shots, combines into voiceover.wav,
transcribes with word-level timestamps -> timing.json

Supported voice_settings.tts values (read from the scenario JSON):
  "voicer"      - Voicer API cloud TTS, ElevenLabs proxy (needs VOICER_API_KEY in env/.env)
  "elevenlabs"  - ElevenLabs cloud TTS (needs ELEVENLABS_API_KEY in env/.env)
  "kokoro"      - local Kokoro
  "chatterbox"  - local Chatterbox (falls back to Kokoro)
  "edge"        - Microsoft Edge cloud TTS (free)
  "manual"      - do NOT generate; use sXX.wav files you placed yourself
  "prerecorded" - do NOT generate; use a single merged voiceover.wav you placed
                  in the project dir; we transcribe and align it to the shots.

Usage:
  python run_audio.py scenarios/<name>.json [voicer|edge|elevenlabs|kokoro|chatterbox|manual|prerecorded]
"""
import os
import sys
import json
import wave
import subprocess
import re
import difflib
import bisect
import time
from pathlib import Path
from datetime import datetime

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

BASE_DIR = Path(__file__).parent

# --- Dead-air cleanup -------------------------------------------------------
TRIM_LEADING_SILENCE = True          # strip silence before the first word
SILENCE_THRESHOLD_DB = -40           # below this level counts as silence
DROP_LEADING_SILENT_SHOTS = True     # don't open on visual-only (mute) shots


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def load_scenario(path):
    with open(path, "r", encoding="utf-8") as f:
        sc = json.load(f)
    shots = []
    for ch in sc.get("chapters", []):
        shots.extend(ch.get("shots", []))
    return sc, shots


def get_wav_duration(path):
    try:
        with wave.open(str(path), "rb") as w:
            return w.getnframes() / w.getframerate()
    except Exception:
        try:
            r = subprocess.run(
                ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                capture_output=True, text=True
            )
            return float(r.stdout.strip())
        except Exception:
            return 0.0


def trim_leading_silence(in_path, out_path, threshold_db=SILENCE_THRESHOLD_DB):
    """Strip leading silence so audio starts on the first word."""
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(in_path),
            "-af", f"silenceremove=start_periods=1:start_threshold={threshold_db}dB:start_silence=0.05",
            "-ar", "24000", "-ac", "1", "-sample_fmt", "s16",
            str(out_path),
        ],
        capture_output=True,
    )
    return out_path.exists() and out_path.stat().st_size > 0


def generate_elevenlabs(text, wav_path, vs):
    """Generate one shot via the ElevenLabs REST API and save it as 24k mono WAV."""
    import requests
    api_key = os.getenv("ELEVENLABS_API_KEY", "")
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY is not set (put it in your .env)")

    voice_id = vs.get("voice_id") or "nPczCjzI2devNBz1zQrb"  # default: Brian
    model_id = vs.get("model_id", "eleven_multilingual_v2")

    vsettings = {
        "stability": float(vs.get("stability", 0.45)),
        "similarity_boost": float(vs.get("similarity_boost", 0.8)),
        "style": float(vs.get("style", 0.15)),
        "use_speaker_boost": bool(vs.get("use_speaker_boost", True)),
    }
    spd = vs.get("speed")
    if spd is not None and float(spd) != 1.0:
        vsettings["speed"] = float(spd)

    url = "https://api.elevenlabs.io/v1/text-to-speech/" + voice_id
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    body = {"text": text, "model_id": model_id, "voice_settings": vsettings}

    r = requests.post(
        url, headers=headers, params={"output_format": "mp3_44100_128"},
        json=body, timeout=180,
    )
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")

    mp3_path = wav_path.with_suffix(".mp3")
    mp3_path.write_bytes(r.content)
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(mp3_path), "-ar", "24000", "-ac", "1", "-sample_fmt", "s16", str(wav_path)],
        capture_output=True,
    )
    mp3_path.unlink(missing_ok=True)
    return wav_path.exists() and wav_path.stat().st_size > 0


def generate_voicer(text, wav_path, vs):
    """Generate one shot via the Voicer API (ElevenLabs proxy) and save it as 24k mono WAV.

    Flow: POST /tasks -> poll GET /tasks/{id}/status -> GET /tasks/{id}/result (MP3).
    Standard-library ElevenLabs voices need no public_owner_id; set it in voice_settings
    only for non-standard (community) voices.
    """
    import requests
    api_key = os.getenv("VOICER_API_KEY", "")
    if not api_key:
        raise RuntimeError("VOICER_API_KEY is not set (put it in your .env)")

    base_url = os.getenv("VOICER_BASE_URL", "https://voiceapi.csv666.ru")
    voice_id = vs.get("voice_id") or "TX3LPaxmHKxFdv7VOQHJ"  # default: Liam
    model_id = vs.get("model_id", "eleven_multilingual_v2")

    vsettings = {
        "stability": float(vs.get("stability", 0.45)),
        "similarity_boost": float(vs.get("similarity_boost", 0.8)),
        "style": float(vs.get("style", 0.3)),
        "use_speaker_boost": bool(vs.get("use_speaker_boost", True)),
        "speed": float(vs.get("speed", 1.0)),
    }
    template = {"model_id": model_id, "voice_id": voice_id, "voice_settings": vsettings}
    public_owner_id = vs.get("public_owner_id")
    if public_owner_id:
        template["public_owner_id"] = public_owner_id

    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}

    # 1) create the TTS task
    r = requests.post(
        f"{base_url}/tasks", headers=headers,
        json={"text": text, "template": template}, timeout=60,
    )
    if r.status_code != 200:
        raise RuntimeError(f"create HTTP {r.status_code}: {r.text[:300]}")
    task_id = r.json()["task_id"]

    # 2) poll until the result is ready
    deadline = time.time() + 300
    while time.time() < deadline:
        s = requests.get(
            f"{base_url}/tasks/{task_id}/status",
            headers={"X-API-Key": api_key}, timeout=30,
        )
        status = s.json().get("status")
        if status == "ending":
            break
        if status in ("error", "error_handled"):
            raise RuntimeError(f"task {task_id} failed: {s.json().get('error')}")
        time.sleep(3)
    else:
        raise TimeoutError(f"task {task_id} timed out")

    # 3) download the MP3 result
    d = requests.get(
        f"{base_url}/tasks/{task_id}/result",
        headers={"X-API-Key": api_key}, timeout=120,
    )
    if d.status_code != 200:
        raise RuntimeError(f"download HTTP {d.status_code}: {d.text[:300]}")

    mp3_path = wav_path.with_suffix(".mp3")
    mp3_path.write_bytes(d.content)
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(mp3_path), "-ar", "24000", "-ac", "1", "-sample_fmt", "s16", str(wav_path)],
        capture_output=True,
    )
    mp3_path.unlink(missing_ok=True)
    return wav_path.exists() and wav_path.stat().st_size > 0


def generate_tts(shots, project_dir, voice_settings):
    """Generate per-shot WAV files. Returns list of (shot_id, wav_path, duration)."""
    tts_engine = (voice_settings.get("tts_engine") or voice_settings.get("tts") or "chatterbox").lower()
    speed = voice_settings.get("speed", 1.0)
    exaggeration = voice_settings.get("exaggeration", 0.5)
    ref_audio_name = voice_settings.get("ref_audio")

    use_eleven = (tts_engine == "elevenlabs")
    use_voicer = (tts_engine == "voicer")
    manual = (tts_engine == "manual")

    tts = None

    if manual:
        log("  TTS: MANUAL - using pre-recorded sXX.wav files, no generation")
    elif use_eleven:
        vname = voice_settings.get("voice_name", voice_settings.get("voice_id", "Brian"))
        log(f"  TTS: ElevenLabs (voice={vname}, model={voice_settings.get('model_id', 'eleven_multilingual_v2')})")
    elif use_voicer:
        vname = voice_settings.get("voice_name", voice_settings.get("voice_id", "Liam"))
        log(f"  TTS: Voicer API (voice={vname}, model={voice_settings.get('model_id', 'eleven_multilingual_v2')})")
    else:
        if tts_engine == "chatterbox":
            try:
                from chatterbox_tts import ChatterboxTTS
                ref_path = BASE_DIR / ref_audio_name if ref_audio_name else None
                tts = ChatterboxTTS(exaggeration=exaggeration, speed=speed, ref_audio=ref_path)
                log(f"  TTS: Chatterbox (exag={exaggeration}, speed={speed})")
            except Exception as e:
                log(f"  Chatterbox failed: {e}, trying Kokoro")

        if not tts and tts_engine in ("kokoro", "chatterbox"):
            try:
                from kokoro_tts import KokoroTTS
                voice = voice_settings.get("voice", "am_michael")
                tts = KokoroTTS(voice=voice, speed=speed)
                log(f"  TTS: Kokoro (voice={voice})")
            except Exception as e:
                log(f"  Kokoro failed: {e}")

    results = []
    for i, shot in enumerate(shots):
        sid = shot["id"]
        text = shot.get("voiceover")
        if not text:
            results.append((sid, None, shot.get("duration", 2.0)))
            continue

        wav_path = project_dir / f"{sid}.wav"
        if wav_path.exists() and wav_path.stat().st_size > 0:
            dur = get_wav_duration(wav_path)
            results.append((sid, wav_path, dur))
            continue

        if manual:
            log(f"  {sid} MISSING: expected pre-recorded {wav_path.name}")
            results.append((sid, None, shot.get("duration", 2.0)))
            continue

        generated = False
        if use_eleven:
            try:
                generated = generate_elevenlabs(text, wav_path, voice_settings)
            except Exception as e:
                log(f"  {sid} ElevenLabs failed: {e}")
        elif use_voicer:
            try:
                generated = generate_voicer(text, wav_path, voice_settings)
            except Exception as e:
                log(f"  {sid} Voicer failed: {e}")
        elif tts:
            try:
                tts.generate_audio(text, wav_path)
                generated = True
            except Exception:
                pass

        # Edge TTS fallback only for local engines, never silently for cloud voices.
        if not generated and not use_eleven and not use_voicer:
            try:
                import edge_tts, asyncio
                async def gen(t, p):
                    c = edge_tts.Communicate(t, "en-US-GuyNeural", rate="+12%")
                    await c.save(str(p))
                asyncio.run(gen(text, wav_path))
                generated = True
            except Exception as e:
                log(f"  {sid} FAILED: {e}")

        if wav_path.exists() and wav_path.stat().st_size > 0:
            dur = get_wav_duration(wav_path)
            results.append((sid, wav_path, dur))
            if (i + 1) % 10 == 0:
                log(f"  [{i+1}/{len(shots)}] generated")
        else:
            results.append((sid, None, shot.get("duration", 2.0)))

    return results


def combine_audio(results, project_dir):
    """Combine per-shot WAVs into voiceover.wav, trim leading silence."""
    combined = project_dir / "voiceover.wav"

    wav_files = [(sid, p, d) for sid, p, d in results if p and p.exists()]
    if not wav_files:
        log("  No WAV files to combine!")
        return None, 0.0, results

    # Normalize all to same format
    norm_paths = []
    for sid, wf, _ in wav_files:
        norm = project_dir / f"_norm_{sid}.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(wf), "-ar", "24000", "-ac", "1", "-sample_fmt", "s16", str(norm)],
            capture_output=True
        )
        norm_paths.append(norm if norm.exists() and norm.stat().st_size > 0 else wf)

    # Concatenate
    try:
        with wave.open(str(combined), "wb") as out:
            for i, nf in enumerate(norm_paths):
                with wave.open(str(nf), "rb") as inp:
                    if i == 0:
                        out.setparams(inp.getparams())
                    out.writeframes(inp.readframes(inp.getnframes()))
    except Exception as e:
        log(f"  Combine failed: {e}")
        return None, 0.0, results

    # Cleanup
    for nf in norm_paths:
        if nf.name.startswith("_norm_"):
            nf.unlink(missing_ok=True)

    total = get_wav_duration(combined)
    adjusted = list(results)

    # Strip dead air before the first spoken word and re-align the first shot.
    if TRIM_LEADING_SILENCE and total > 0:
        trimmed = project_dir / "_voiceover_trimmed.wav"
        if trim_leading_silence(combined, trimmed):
            new_total = get_wav_duration(trimmed)
            removed = total - new_total
            if removed > 0.02:
                trimmed.replace(combined)
                for i, (sid, p, d) in enumerate(adjusted):
                    if p is not None:
                        adjusted[i] = (sid, p, max(0.05, round(d - removed, 3)))
                        break
                total = new_total
                log(f"  Trimmed {removed:.2f}s of leading silence")
            else:
                trimmed.unlink(missing_ok=True)
        else:
            trimmed.unlink(missing_ok=True)

    log(f"  voiceover.wav: {total:.1f}s")
    return combined, total, adjusted


def transcribe(audio_path, project_dir):
    """Transcribe with word-level timestamps using whisper."""
    try:
        import whisper_timestamped as whisper
    except ImportError:
        log("  whisper-timestamped not installed!")
        return None

    tmp = project_dir / "_whisper_input.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(audio_path), "-ar", "16000", "-ac", "1", str(tmp)],
        capture_output=True
    )

    log("  Transcribing (whisper base)...")
    model = whisper.load_model("base")
    result = whisper.transcribe(model, str(tmp), language="en")

    words = []
    for seg in result["segments"]:
        for w in seg.get("words", []):
            words.append({
                "text": w["text"].strip(),
                "start": round(w["start"], 3),
                "end": round(w["end"], 3)
            })

    tmp.unlink(missing_ok=True)
    log(f"  {len(words)} words transcribed")
    return words


def build_timing(shots, results, all_words):
    """Map word timestamps back to shots based on cumulative audio offsets."""
    timing_shots = []
    audio_offset = 0.0
    seen_audio = False

    for sid, wav_path, dur in results:
        if DROP_LEADING_SILENT_SHOTS and not seen_audio and wav_path is None:
            continue
        if wav_path is not None:
            seen_audio = True

        shot_start = audio_offset
        shot_end = audio_offset + dur

        shot_words = [w for w in all_words if w["start"] >= shot_start - 0.05 and w["end"] <= shot_end + 0.05]

        timing_shots.append({
            "id": sid,
            "start": round(shot_start, 3),
            "end": round(shot_end, 3),
            "duration": round(dur, 3),
            "has_audio": wav_path is not None,
            "words": shot_words
        })

        if wav_path:
            audio_offset += dur

    return timing_shots


# === PRERECORDED MODE =======================================================

def _norm_tok(s):
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def align_prerecorded(shots, all_words, total_dur):
    """Split a single transcribed voiceover into per-shot timing."""
    script_tokens = []
    spans = []
    for shot in shots:
        text = shot.get("voiceover") or ""
        toks = [t for t in (_norm_tok(x) for x in text.split()) if t]
        tok_start = len(script_tokens)
        script_tokens.extend(toks)
        spans.append((shot, tok_start, len(script_tokens)))

    wtok = [_norm_tok(w["text"]) for w in all_words]

    s2w = {}
    if script_tokens and wtok:
        sm = difflib.SequenceMatcher(a=script_tokens, b=wtok, autojunk=False)
        for ai, bi, size in sm.get_matching_blocks():
            for k in range(size):
                s2w[ai + k] = bi + k
    sorted_si = sorted(s2w.keys())

    def whisper_idx_for(si):
        if sorted_si:
            pos = bisect.bisect_left(sorted_si, si)
            if pos < len(sorted_si):
                return s2w[sorted_si[pos]]
        if script_tokens:
            return min(max(0, len(wtok) - 1), round(si / len(script_tokens) * max(1, len(wtok))))
        return 0

    def time_for(si):
        if not all_words:
            return round(total_dur * (si / max(1, len(script_tokens))), 3)
        wi = max(0, min(len(all_words) - 1, whisper_idx_for(si)))
        return all_words[wi]["start"]

    starts = []
    for idx, (shot, ts, te) in enumerate(spans):
        if idx == 0:
            st = 0.0
        elif te > ts:
            st = time_for(ts)
        else:
            st = starts[-1] if starts else 0.0
        starts.append(st)

    for i in range(1, len(starts)):
        if starts[i] < starts[i - 1]:
            starts[i] = starts[i - 1]

    timing_shots = []
    for i, (shot, ts, te) in enumerate(spans):
        start = round(starts[i], 3)
        end = round(starts[i + 1], 3) if i + 1 < len(spans) else round(total_dur, 3)
        if end < start:
            end = start
        dur = round(end - start, 3)
        words = [w for w in all_words if start - 0.05 <= w["start"] < end + 0.05]
        timing_shots.append({
            "id": shot["id"],
            "start": start,
            "end": end,
            "duration": dur,
            "has_audio": te > ts,
            "words": words,
        })
    return timing_shots


def run_prerecorded(sc, shots, project_dir):
    """Use an already-merged voiceover.wav: transcribe + align to shots."""
    combined = project_dir / "voiceover.wav"
    if not (combined.exists() and combined.stat().st_size > 0):
        log(f"FAILED: prerecorded mode needs {combined}")
        sys.exit(1)

    total = get_wav_duration(combined)
    log(f"  Found voiceover.wav: {total:.1f}s ({total/60:.1f} min)")

    if TRIM_LEADING_SILENCE and total > 0:
        trimmed = project_dir / "_voiceover_trimmed.wav"
        if trim_leading_silence(combined, trimmed):
            new_total = get_wav_duration(trimmed)
            if total - new_total > 0.02:
                trimmed.replace(combined)
                log(f"  Trimmed {total - new_total:.2f}s of leading silence")
                total = new_total
            else:
                trimmed.unlink(missing_ok=True)
        else:
            trimmed.unlink(missing_ok=True)

    log("=== Transcription ===")
    all_words = transcribe(combined, project_dir) or []
    if not all_words:
        log("WARNING: transcription empty -> shots evenly spaced by word count")

    log("=== Aligning transcript to scenario shots ===")
    timing_shots = align_prerecorded(shots, all_words, total)

    timing = {
        "video_id": sc["video_id"],
        "total_duration": round(total, 3),
        "total_shots": len(timing_shots),
        "shots": timing_shots,
    }
    timing_path = project_dir / "timing.json"
    with open(timing_path, "w", encoding="utf-8") as f:
        json.dump(timing, f, indent=2, ensure_ascii=False)

    spoken = sum(1 for s in timing_shots if s["has_audio"])
    log(f"DONE (prerecorded)! {spoken}/{len(timing_shots)} shots, {len(all_words)} words")


def main():
    if len(sys.argv) < 2:
        print("Usage: python run_audio.py scenarios/<name>.json [engine]")
        print("  engine: voicer | elevenlabs | kokoro | chatterbox | edge | manual | prerecorded")
        sys.exit(1)

    scenario_path = BASE_DIR / sys.argv[1]
    sc, shots = load_scenario(scenario_path)

    project_dir = BASE_DIR / "videos" / sc["video_id"]
    project_dir.mkdir(parents=True, exist_ok=True)

    log(f"Project: {sc['title']}")
    log(f"Shots: {len(shots)}")
    log("")

    voice_settings = sc.get("voice_settings", {})
    engine = (voice_settings.get("tts_engine") or voice_settings.get("tts") or "").lower()
    if len(sys.argv) >= 3:
        engine = sys.argv[2].lower()
        log(f"  (engine override from CLI: {engine})")

    if engine == "prerecorded":
        log("=== PRERECORDED MODE (using your merged voiceover.wav) ===")
        run_prerecorded(sc, shots, project_dir)
        return

    if len(sys.argv) >= 3:
        voice_settings = dict(voice_settings)
        voice_settings["tts"] = sys.argv[2]

    log("=== STEP 1: TTS Generation ===")
    results = generate_tts(shots, project_dir, voice_settings)
    generated = sum(1 for _, p, _ in results if p)
    log(f"  {generated}/{len(shots)} shots have audio")

    log("=== STEP 2: Combining audio ===")
    combined, total_dur, results = combine_audio(results, project_dir)
    if not combined:
        log("FAILED: No audio generated")
        sys.exit(1)

    log("=== STEP 3: Transcription ===")
    all_words = transcribe(combined, project_dir)
    if not all_words:
        log("WARNING: Transcription failed, timing.json will have no word data")
        all_words = []

    log("=== STEP 4: Building timing.json ===")
    timing_shots = build_timing(shots, results, all_words)

    timing = {
        "video_id": sc["video_id"],
        "total_duration": round(total_dur, 3),
        "total_shots": len(timing_shots),
        "shots": timing_shots
    }

    timing_path = project_dir / "timing.json"
    with open(timing_path, "w", encoding="utf-8") as f:
        json.dump(timing, f, indent=2, ensure_ascii=False)

    log(f"\nDONE!")
    log(f"  Total duration: {total_dur:.1f}s ({total_dur/60:.1f} min)")
    log(f"  timing.json: {timing_path}")
    log(f"  Words transcribed: {len(all_words)}")
    log(f"\nNext: python run_shorts.py {sys.argv[1]}")


if __name__ == "__main__":
    main()
