# shortsi — Faceless Alt-History Shorts Pipeline

Automated pipeline for faceless YouTube **Shorts** (9:16, 1080×1920): AI voiceover →
word-level timing → AI narrator/character/scene visuals (+ optional stock B-roll) →
music bed → burned-in subtitles → shareable upload link.

This is a cleaned, **shorts-only** extraction of the `markds` pipeline, re-pointed at
the **alternate history / "what if" POV survival** niche (faceless, US audience).

## Pipeline

```
scenario JSON
   |  run_audio.py      TTS per shot -> voiceover.wav, transcribe -> timing.json
   v
timing.json
   |  run_shorts.py     visuals (AI / stock / text) -> ffmpeg assembly -> music -> subtitles
   v
videos/<id>/final_v3.mp4   (+ final_subs.mp4 with burned-in captions)
```

## Quick start

```bash
pip install -r requirements.txt        # also install ffmpeg on your system PATH
cp .env.example .env                   # then fill in FASTGEN_API_KEY (+ optional keys)

python run_audio.py  scenarios/shorts_soldier_2026_rome.json edge
python run_shorts.py scenarios/shorts_soldier_2026_rome.json
python upload.py     videos/shorts_soldier_2026_rome/final_subs.mp4
```

Already have a recorded `voiceover.wav`? Use `python make_timing.py <scenario>` instead of `run_audio.py`.

## Scenario format

A scenario is JSON: `{ video_id, title, voice_settings, chapters:[{ shots:[ ... ] }] }`.
Each shot has an `id`, a `type`, a `voiceover` line, and a visual `prompt`.

| Shot `type`        | Visual produced |
|--------------------|-----------------|
| `narrator_shot`    | Recurring on-screen guide (see `persona.NARRATOR_POSES`) — the channel's signature face |
| `character_shot`   | The POV protagonist (`persona.PROTAGONIST_POSES`) or a custom `prompt` |
| `scene_shot`       | AI image from `prompt`. Add `"source": "stock"` to pull Pexels/Pixabay B-roll instead |
| `text_card` / `infographic_shot` | Local typewriter text card (no API needed) |

See `scenarios/shorts_soldier_2026_rome.json` for a complete ready-to-run example.

## Files

| File | Role |
|------|------|
| `run_audio.py` | Phase 1 — per-shot TTS (edge/elevenlabs/kokoro/chatterbox), combine, transcribe → `timing.json` |
| `make_timing.py` | Alternative to phase 1 when you already have `voiceover.wav` |
| `run_shorts.py` | Phase 2 — generate visuals, assemble with ffmpeg, mix music, burn subtitles |
| `pexels_stock.py` | Pexels + Pixabay stock B-roll fetcher (dual-source race) |
| `create_text_video.py` | Typewriter text-card generator (Pillow + ffmpeg) |
| `shorts_subtitles.py` | Self-contained ASS subtitle builder + burner |
| `persona.py` | Narrator + protagonist prompt definitions (edit to rebrand) |
| `config.py` | Central config (channel, voice, paths) — all secrets from `.env` |
| `upload.py` | Upload final file, get a 72h share link |

## Branding / persona

Edit `persona.py` to change the recurring narrator and protagonist. The pipeline rotates
through the pose lists so the same face recurs across every video — consistency is the brand.

## Voice

Default free engine is **Edge TTS** (`en-US-GuyNeural`). For premium quality set
`ELEVENLABS_API_KEY` and use `python run_audio.py <scenario> elevenlabs`.

## Security

- All keys load from `.env`, which is gitignored. **Never hardcode keys in source.**
- The original `markds` repo committed a live Fast Gen AI key in `config.py` / `run_shorts.py`.
  Rotate that key and keep it only in `.env`.
