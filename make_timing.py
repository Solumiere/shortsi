"""Create timing.json from existing voiceover.wav using Whisper. No TTS."""
import sys, json, wave
from pathlib import Path

BASE_DIR = Path(__file__).parent

def main():
    sc_path = BASE_DIR / sys.argv[1]
    with open(sc_path, "r", encoding="utf-8") as f:
        sc = json.load(f)

    proj = BASE_DIR / "videos" / sc["video_id"]
    wav = proj / "voiceover.wav"
    if not wav.exists():
        print(f"ERROR: {wav} not found")
        return

    with wave.open(str(wav), "rb") as w:
        total_dur = w.getnframes() / w.getframerate()
    print(f"Audio: {total_dur:.1f}s")

    # Transcribe with Whisper
    import whisper
    print("Transcribing...")
    model = whisper.load_model("base")
    result = model.transcribe(str(wav), word_timestamps=True)

    words = []
    for seg in result["segments"]:
        for w in seg.get("words", []):
            words.append({"text": w["word"].strip(), "start": round(w["start"], 3), "end": round(w["end"], 3)})
    print(f"  {len(words)} words")

    # Build shots from scenario
    shots_data = []
    all_shots = [s for ch in sc["chapters"] for s in ch["shots"]]

    # Distribute words across shots based on voiceover text matching
    word_idx = 0
    for shot in all_shots:
        vo = shot.get("voiceover")
        if not vo:
            shots_data.append({"id": shot["id"], "start": 0, "end": 0, "duration": shot.get("duration", 2), "words": []})
            continue

        # Count words in this shot's voiceover
        shot_word_count = len(vo.split())
        shot_words = words[word_idx:word_idx + shot_word_count]
        word_idx += shot_word_count

        if shot_words:
            start = shot_words[0]["start"]
            end = shot_words[-1]["end"]
        else:
            start = 0
            end = 0

        shots_data.append({
            "id": shot["id"],
            "start": start,
            "end": end,
            "duration": round(end - start, 3) if end > start else shot.get("duration", 2),
            "words": shot_words
        })

    timing = {"total_duration": total_dur, "shots": shots_data}
    timing_path = proj / "timing.json"
    with open(timing_path, "w", encoding="utf-8") as f:
        json.dump(timing, f, indent=2)
    print(f"DONE: {timing_path}")

if __name__ == "__main__":
    main()
