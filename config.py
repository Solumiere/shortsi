"""
Alternate History Shorts - central configuration.
All secrets are read from .env (see .env.example). NEVER hardcode keys here.
"""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except Exception:
    pass

# --- API keys (from .env) ---------------------------------------------------
FASTGEN_API_KEY = os.getenv("FASTGEN_API_KEY", "")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY", "")

# --- Fast Gen AI (image generation) -----------------------------------------
FASTGEN_BASE_URL = os.getenv("FASTGEN_BASE_URL", "https://googler.fast-gen.ai")
FASTGEN_STORAGE_URL = os.getenv("FASTGEN_STORAGE_URL", "https://storage.fast-gen.ai")
IMAGE_ASPECT = "9:16"

# --- Channel ----------------------------------------------------------------
CHANNEL_NAME = "Alternate History Shorts"
CHANNEL_LANGUAGE = "English"
TARGET_AUDIENCE = "US, 18-34, history / what-if / POV survival fans"
CHANNEL_NICHE = "Alternate history & 'what if' POV survival shorts (faceless)"

# --- Video ------------------------------------------------------------------
SHORT_FORM_DURATION = (45, 75)   # target length in seconds
VIDEO_W, VIDEO_H = 1080, 1920
FPS = 30

# --- Voice ------------------------------------------------------------------
# Default free engine: edge. Set to elevenlabs for premium narration.
VOICE_PROVIDER = os.getenv("VOICE_PROVIDER", "edge")
EDGE_TTS_SETTINGS = {"voice": "en-US-GuyNeural", "rate": "+12%"}
KOKORO_SETTINGS = {"voice": "am_michael", "speed": 1.15, "sample_rate": 24000}
ELEVENLABS_SETTINGS = {
    "voice_id": "nPczCjzI2devNBz1zQrb",  # Brian (deep narrator)
    "model_id": "eleven_multilingual_v2",
    "stability": 0.45, "similarity_boost": 0.8, "style": 0.2, "speed": 1.0,
}

# --- Paths ------------------------------------------------------------------
BASE_DIR = Path(__file__).parent
SCENARIOS_DIR = BASE_DIR / "scenarios"
VIDEOS_DIR = BASE_DIR / "videos"
ASSETS_DIR = BASE_DIR / "assets"
for _d in (SCENARIOS_DIR, VIDEOS_DIR, ASSETS_DIR):
    _d.mkdir(exist_ok=True)

# --- Image-gen polling ------------------------------------------------------
POLL_INTERVAL = 10
MAX_POLL_ATTEMPTS = 20
