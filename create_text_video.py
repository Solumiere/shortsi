"""
create_text_video — typewriter text over animated dark grid backgrounds.
Uses video loops from video_refer/ folder as backgrounds.
Text appears letter by letter with glow effect.
"""
import re
import random
import textwrap
import subprocess
import tempfile
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops

BASE_DIR = Path(__file__).parent
BG_DIR = BASE_DIR / "video_refer"


def create_text_video(visual, out_path, aspect_ratio, fps=30):
    """Generate mp4: animated bg + typewriter text with glow."""
    W, H = (1920, 1080) if aspect_ratio == "16:9" else (1080, 1920)
    prompt = visual.get("prompt", "")
    word_text = " ".join(w["text"] for w in visual.get("words", []))
    dur = visual.get("duration", 3.0)
    total_frames = max(int(dur * fps), 1)

    # Extract display text
    display = _extract_display_text(prompt, word_text)

    # Font setup
    try:
        font_big = ImageFont.truetype("arialbd.ttf", 90 if W == 1920 else 72)
        font_med = ImageFont.truetype("arialbd.ttf", 54 if W == 1920 else 44)
    except Exception:
        font_big = ImageFont.load_default()
        font_med = font_big

    lines = []
    for i, text in enumerate(display):
        font = font_big if i == 0 and len(text) < 15 else font_med
        color = (255, 255, 255) if i == 0 else (255, 200, 50)
        lines.append((text, font, color))

    total_chars = sum(len(t) for t, _, _ in lines)
    type_frames = int(total_frames * 0.55)

    # Pick random background video
    bg_video = _pick_bg_video()

    tmp_dir = Path(tempfile.mkdtemp())
    try:
        # Extract bg frames
        bg_frames_dir = tmp_dir / "bg"
        bg_frames_dir.mkdir()

        if bg_video:
            subprocess.run([
                "ffmpeg", "-y", "-stream_loop", "-1",
                "-i", str(bg_video), "-t", f"{dur:.3f}",
                "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}",
                "-r", str(fps), "-pix_fmt", "rgb24",
                str(bg_frames_dir / "bg%05d.png")
            ], capture_output=True)

        # Generate final frames with text overlay
        for frame_idx in range(total_frames):
            chars_visible = min(int((frame_idx / max(type_frames, 1)) * total_chars), total_chars)

            # Load bg frame or create grid
            bg_path = bg_frames_dir / f"bg{frame_idx + 1:05d}.png"
            if bg_path.exists():
                img = Image.open(bg_path).convert("RGB")
            else:
                img = _make_grid_bg(W, H)

            # Draw text
            if chars_visible > 0:
                img = _draw_text_on_bg(img, W, H, lines, chars_visible)

            img.save(tmp_dir / f"f{frame_idx:05d}.png")

        # Encode
        subprocess.run([
            "ffmpeg", "-y", "-framerate", str(fps),
            "-i", str(tmp_dir / "f%05d.png"),
            "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
            str(out_path)
        ], capture_output=True)
    finally:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return out_path.exists()


def _pick_bg_video():
    """Pick a random background video from video_refer/."""
    if not BG_DIR.exists():
        return None
    videos = list(BG_DIR.glob("*.mp4"))
    return random.choice(videos) if videos else None


def _extract_display_text(prompt, word_text):
    """Extract key text to display."""
    display = []
    dollars = re.findall(r'\$[\d,]+(?:K)?', prompt + " " + word_text)
    caps = re.findall(r"[A-Z][A-Z\s']{3,}[A-Z.]", prompt)
    quoted = re.findall(r'["\'](.*?)["\']', prompt)

    if dollars:
        display.append(dollars[0])
    if caps:
        display.extend(c.strip() for c in caps[:2])
    elif quoted:
        display.extend(q.strip() for q in quoted[:2])
    if not display:
        display = textwrap.wrap(word_text or "...", width=25)[:3]
    return display[:4]


def _make_grid_bg(W, H):
    """Fallback: dark background with subtle grid."""
    img = Image.new("RGB", (W, H), (5, 5, 10))
    draw = ImageDraw.Draw(img)
    grid_color = (25, 25, 35)
    spacing = 60
    for x in range(0, W, spacing):
        draw.line([(x, 0), (x, H)], fill=grid_color, width=1)
    for y in range(0, H, spacing):
        draw.line([(0, y), (W, y)], fill=grid_color, width=1)
    return img


def _draw_text_on_bg(img, W, H, lines, chars_visible):
    """Draw partially revealed text with glow."""
    draw = ImageDraw.Draw(img)

    # Measure lines
    line_metrics = []
    for text, font, color in lines:
        bbox = draw.textbbox((0, 0), text, font=font)
        line_metrics.append((bbox[2] - bbox[0], bbox[3] - bbox[1]))

    total_h = sum(lh for _, lh in line_metrics) + 35 * (len(lines) - 1)
    y = (H - total_h) // 2

    chars_used = 0
    for idx, (text, font, color) in enumerate(lines):
        lw, lh = line_metrics[idx]
        remaining = chars_visible - chars_used

        if remaining <= 0:
            chars_used += len(text)
            y += lh + 35
            continue

        visible_text = text[:remaining]
        chars_used += len(text)
        x = (W - lw) // 2

        # Glow layer
        glow = Image.new("RGB", (W, H), (0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gd.text((x, y), visible_text, fill=(color[0]//3, color[1]//3, color[2]//3), font=font)
        glow = glow.filter(ImageFilter.GaussianBlur(radius=12))
        img = ImageChops.add(img, glow)
        draw = ImageDraw.Draw(img)

        # Sharp text
        draw.text((x, y), visible_text, fill=color, font=font)

        y += lh + 35

    return img


if __name__ == "__main__":
    test_visual = {
        "prompt": "Pure black background. Bold white text: $104,215. Smaller gold text below: AVERAGE AMERICAN DEBT.",
        "words": [{"text": "The"}, {"text": "average"}, {"text": "American"}, {"text": "carries"}, {"text": "$104,215"}, {"text": "in"}, {"text": "debt"}],
        "duration": 4.0,
    }
    out = Path("test_text_video.mp4")
    create_text_video(test_visual, out, "16:9")
    if out.exists():
        print(f"Created: {out} ({out.stat().st_size // 1024} KB)")
