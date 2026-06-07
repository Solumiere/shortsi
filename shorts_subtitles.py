"""
Self-contained subtitle burner for shorts.
Transcribes the final video's audio with whisper-timestamped, builds a styled
ASS file (big bold captions; numbers / ALL-CAPS emphasis highlighted gold) and
burns it into a new file.

    from shorts_subtitles import burn_subtitles
    burn_subtitles(Path("videos/xxx/final_v3.mp4"))   # -> final_v3_subs.mp4
"""
import subprocess
import re
import tempfile
import shutil
from pathlib import Path

WHITE = "&H00FFFFFF&"
GOLD = "&H0000D7FF&"   # #FFD700 in ASS BGR
OUTLINE = "&H00000000&"

EMPHASIS = r"\$\d+|\d+%|\d+,\d+|\b\d{2,}\b"


def _word_timestamps(audio_path):
    import whisper_timestamped as whisper
    model = whisper.load_model("base")
    result = whisper.transcribe(model, str(audio_path), language="en")
    words = []
    for seg in result["segments"]:
        for w in seg.get("words", []):
            words.append({"text": w["text"].strip(), "start": w["start"], "end": w["end"]})
    return words


def _is_emphasis(word):
    if re.search(EMPHASIS, word):
        return True
    stripped = re.sub(r"[^A-Za-z]", "", word)
    return len(stripped) >= 4 and stripped.isupper()


def _ass_time(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _generate_ass(words, output_path, W=1080, H=1920):
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Montserrat ExtraBold,72,{WHITE},{WHITE},{OUTLINE},&H80000000&,-1,0,0,0,100,100,0,0,1,4,2,2,40,40,260,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    phrases = []
    cur = []
    for w in words:
        cur.append(w)
        if len(cur) >= 4 or w["text"].endswith((".", "!", "?", ",")):
            phrases.append(cur)
            cur = []
    if cur:
        phrases.append(cur)

    events = []
    for ph in phrases:
        start = _ass_time(ph[0]["start"])
        end = _ass_time(ph[-1]["end"])
        parts = []
        for w in ph:
            if _is_emphasis(w["text"]):
                parts.append(f"{{\\c{GOLD}}}{w['text']}{{\\c{WHITE}}}")
            else:
                parts.append(w["text"])
        text = "{\\fad(120,120)}" + " ".join(parts)
        events.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")

    Path(output_path).write_text(header + "\n".join(events), encoding="utf-8")
    return output_path


def burn_subtitles(video_path, out_path=None):
    """Transcribe the video's audio, build ASS captions and burn them in.
    Returns the path to the subtitled file, or None on failure."""
    video_path = Path(video_path)
    proj = video_path.parent
    out_path = Path(out_path) if out_path else proj / (video_path.stem + "_subs.mp4")

    audio = proj / "_audio_for_subs.wav"
    subprocess.run(["ffmpeg", "-y", "-i", str(video_path), "-vn", "-acodec", "pcm_s16le",
                    "-ar", "16000", "-ac", "1", str(audio)], capture_output=True)
    try:
        words = _word_timestamps(audio)
    finally:
        audio.unlink(missing_ok=True)
    if not words:
        return None

    ass_file = proj / "subtitles.ass"
    _generate_ass(words, ass_file)

    tmp_ass = Path(tempfile.gettempdir()) / "subs.ass"
    shutil.copy2(ass_file, tmp_ass)
    ass_escaped = str(tmp_ass).replace("\\", "/").replace(":", "\\:")

    subprocess.run(["ffmpeg", "-y", "-i", str(video_path), "-vf", f"ass='{ass_escaped}'",
                    "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-c:a", "copy",
                    str(out_path)], capture_output=True)
    if not out_path.exists() or out_path.stat().st_size == 0:
        subprocess.run(["ffmpeg", "-y", "-i", str(video_path), "-vf", f"subtitles='{ass_escaped}'",
                        "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-c:a", "copy",
                        str(out_path)], capture_output=True)
    tmp_ass.unlink(missing_ok=True)
    return out_path if out_path.exists() else None
