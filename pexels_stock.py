"""
Pexels + Pixabay Stock Video — параллельный поиск и скачивание B-roll
=====================================================================
Использование:
  from pexels_stock import fetch_stock_clips
  clips = fetch_stock_clips("your voiceover text", count=5, out_dir=Path("videos/xxx"))

Ключи берутся из .env (PEXELS_API_KEY / PIXABAY_API_KEY). Да, Pixabay ТОЖЕ требует
свой (бесплатный) API-ключ — он не захардкожен, а читается из .env
(PIXABAY_API_KEY), поэтому в коде его не видно, но он нужен и работает.

DUAL-SOURCE RACE
----------------
На каждый запрос стучимся СРАЗУ в оба сервиса параллельно и берём ПЕРВЫЙ
нормальный клип. Проигравший поток докачивается в фоне, его лишний файл удаляется.

PROXY-DEAD HANDLING
-------------------
После PEXELS_DEAD_LIMIT подряд connection-фейлов помечаем Pexels мёртвым до
конца процесса и идём только в Pixabay-direct (trust_env=False, мимо прокси).
"""
import os
import requests
import time
import random
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED

# Load secrets from .env (kept out of source / git history)
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except Exception:
    pass

PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
HEADERS = {"Authorization": PEXELS_API_KEY}
BASE_URL = "https://api.pexels.com/videos/search"

PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY", "")
PIXABAY_URL = "https://pixabay.com/api/videos/"

VIDEOS_DIR = Path(__file__).parent / "videos"

# --- Direct (no-proxy) session for Pixabay -----------------------------------
_DIRECT = requests.Session()
_DIRECT.trust_env = False

# --- Fail-fast networking knobs (flaky proxy friendly) ----------------------
SEARCH_TIMEOUT = 8            # seconds per search API call
SEARCH_RETRIES = 2           # attempts per search
DOWNLOAD_TIMEOUT = (8, 25)   # (connect, read) per clip download
DOWNLOAD_RETRIES = 2
MAX_SEARCH_PAGES = 3         # result pages scanned per query on Pexels

# --- Pexels circuit breaker --------------------------------------------------
_PEXELS_FAILS = 0
_PEXELS_DEAD = False
PEXELS_DEAD_LIMIT = 3
_LOCK = threading.Lock()


def _pexels_mark_fail():
    global _PEXELS_FAILS, _PEXELS_DEAD
    with _LOCK:
        _PEXELS_FAILS += 1
        if _PEXELS_FAILS >= PEXELS_DEAD_LIMIT and not _PEXELS_DEAD:
            _PEXELS_DEAD = True
            print("  [pexels] proxy unreachable -> Pixabay-direct only for the rest of this run")


def _pexels_mark_ok():
    global _PEXELS_FAILS
    with _LOCK:
        _PEXELS_FAILS = 0


def _claim(used_ids, vid_id):
    """Atomically reserve a clip id so two racing threads never grab the same clip."""
    with _LOCK:
        if vid_id in used_ids:
            return False
        used_ids.add(vid_id)
        return True


def _unclaim(used_ids, vid_id):
    """Release a reservation when the download didn't pan out."""
    with _LOCK:
        used_ids.discard(vid_id)


def load_global_used_ids() -> set:
    """Scan all project folders for stock clips already used, return set of ids."""
    used = set()
    if not VIDEOS_DIR.exists():
        return used
    cache = VIDEOS_DIR / "_global_stock_hashes.json"
    if cache.exists():
        import json
        try:
            return set(json.loads(cache.read_text()))
        except Exception:
            return used
    return used


def save_global_used_ids(ids: set):
    """Persist global used IDs."""
    import json
    cache = VIDEOS_DIR / "_global_stock_hashes.json"
    existing = set()
    if cache.exists():
        try:
            existing = set(json.loads(cache.read_text()))
        except Exception:
            existing = set()
    existing.update(ids)
    try:
        cache.write_text(json.dumps(list(existing)))
    except Exception:
        pass


def search_videos(query: str, per_page: int = 5, orientation: str = "landscape", page: int = 1):
    """Поиск видео на Pexels (через прокси). Следит за живостью прокси."""
    if not PEXELS_API_KEY or _PEXELS_DEAD:
        return []
    params = {
        "query": query,
        "per_page": per_page,
        "orientation": orientation,
        "size": "medium",
        "page": page,
    }
    for attempt in range(SEARCH_RETRIES):
        try:
            r = requests.get(BASE_URL, headers=HEADERS, params=params, timeout=SEARCH_TIMEOUT)
            _pexels_mark_ok()
            if r.status_code != 200:
                return []
            return r.json().get("videos", [])
        except Exception as e:
            print(f"  [pexels] search '{query}' attempt {attempt + 1} failed: {e}")
            time.sleep(1.0)
    _pexels_mark_fail()
    return []


def search_pixabay(query: str, per_page: int = 10, orientation: str = "horizontal", page: int = 1):
    """Поиск видео на Pixabay НАПРЯМУЮ (мимо прокси)."""
    if not PIXABAY_API_KEY:
        return []
    params = {
        "key": PIXABAY_API_KEY,
        "q": query,
        "per_page": per_page,
        "page": page,
        "orientation": orientation,
        "safesearch": "true",
    }
    for attempt in range(SEARCH_RETRIES):
        try:
            r = _DIRECT.get(PIXABAY_URL, params=params, timeout=SEARCH_TIMEOUT)
            if r.status_code != 200:
                return []
            return r.json().get("hits", [])
        except Exception as e:
            print(f"  [pixabay] search '{query}' attempt {attempt + 1} failed: {e}")
            time.sleep(1.0)
    return []


def download_pixabay_clip(video_data: dict, out_path: Path, max_duration: int = 15,
                          min_height: int = None) -> bool:
    """Скачивает видео с Pixabay НАПРЯМУЮ (large -> medium)."""
    if video_data.get("duration", 999) > max_duration:
        return False
    videos = video_data.get("videos", {})
    best = videos.get("large", {})
    if min_height and best.get("height", 0) < min_height:
        best = {}
    if not best.get("url"):
        best = videos.get("medium", {})
    if not best.get("url"):
        return False
    for attempt in range(DOWNLOAD_RETRIES):
        try:
            r = _DIRECT.get(best["url"], timeout=DOWNLOAD_TIMEOUT)
            if r.status_code == 200 and len(r.content) > 10000:
                out_path.write_bytes(r.content)
                return True
            return False
        except Exception as e:
            print(f"  [pixabay] download attempt {attempt + 1} failed: {e}")
            time.sleep(1.0)
    return False


def download_clip(video_data: dict, out_path: Path, max_duration: int = 15,
                  min_height: int = None) -> bool:
    """Скачивает лучший файл с Pexels (HD, до max_duration сек)."""
    if video_data.get("duration", 999) > max_duration:
        return False

    files = video_data.get("video_files", [])
    floor = min_height or 720
    ceil = 1080

    banded = [f for f in files
              if f.get("width", 0) >= 1280 and floor <= f.get("height", 0) <= ceil]
    banded.sort(key=lambda f: f.get("height", 0), reverse=True)
    best = banded[0] if banded else None

    if not best:
        hd = [f for f in files
              if f.get("width", 0) >= 1280 and f.get("height", 0) >= floor]
        hd.sort(key=lambda f: f.get("height", 0))
        best = hd[0] if hd else None

    if not best:
        best = files[0] if files else None
    if not best:
        return False

    url = best["link"]
    for attempt in range(DOWNLOAD_RETRIES):
        try:
            r = requests.get(url, timeout=DOWNLOAD_TIMEOUT)
            if r.status_code == 200 and len(r.content) > 10000:
                out_path.write_bytes(r.content)
                _pexels_mark_ok()
                return True
            return False
        except Exception as e:
            print(f"  [pexels] download attempt {attempt + 1} failed: {e}")
            time.sleep(1.0)
    _pexels_mark_fail()
    return False


# ============================================================================
# Concrete visual subjects -> cinematic stock queries.
# ============================================================================
SUBJECT_QUERIES = [
    (("vault", "safe deposit", "safe door"), ["bank vault door", "steel bank vault closing"]),
    (("trading floor", "stock exchange", "wall street", "trader", "traders"),
     ["stock exchange trading floor", "wall street street sign", "traders watching monitors"]),
    (("skyscraper", "high-rise", "high rise", "glass tower", "glass building", "tower", "skyscrapers"),
     ["corporate skyscraper low angle", "glass office tower aerial"]),
    (("bank branch", "branch", "teller", "lobby", "candy bowl"),
     ["bank branch interior", "bank teller counter"]),
    (("bank", "banking"), ["bank building facade", "financial district buildings"]),
    (("atm", "cash machine"), ["atm machine at night", "person using atm on street"]),
    (("data center", "server", "servers", "control room", "dashboard", "data screen", "monitors", "screens"),
     ["data center server room", "financial data screens dark room"]),
    (("ticker", "market data", "stock market", "charts", "chart"),
     ["stock market ticker board", "financial charts on monitor"]),
    (("windows at night", "windows night", "grid of windows", "apartment lights", "city at night", "lit windows"),
     ["city buildings at night aerial", "apartment windows lit at night"]),
    (("skyline", "downtown", "metropolis", "cityscape", "urban"),
     ["city skyline aerial drone", "downtown skyscrapers at dusk"]),
    (("commuters", "crowd", "pedestrians", "busy street", "rush hour", "crossing street"),
     ["city street crowd from above", "busy intersection crosswalk aerial"]),
    (("subway", "train station", "metro", "platform"),
     ["subway station rush hour", "metro train arriving platform"]),
    (("highway", "traffic", "freeway", "cars driving"),
     ["highway traffic timelapse night", "aerial city traffic"]),
    (("cubicle", "corporate", "meeting", "coworker", "colleague", "office", "desk", "workers", "employee", "boardroom"),
     ["empty modern office at night", "corporate office tower lobby"]),
    (("laptop", "typing", "computer", "keyboard"),
     ["hands typing laptop closeup", "person working on laptop"]),
    (("credit card", "swipe", "card payment", "terminal", "contactless"),
     ["contactless credit card payment", "card swipe store terminal"]),
    (("supermarket", "grocery", "groceries", "shopping cart", "checkout", "aisle"),
     ["supermarket aisle empty", "grocery checkout scanner closeup"]),
    (("mall", "shopping bags", "retail", "shopper", "boutique"),
     ["shopping mall interior architecture", "retail storefront at night"]),
    (("suburb", "neighborhood", "real estate", "for sale", "mortgage", "home", "house", "houses"),
     ["suburban neighborhood aerial", "house exterior for sale sign"]),
    (("apartment", "rent", "rental", "flat"),
     ["apartment building exterior", "city apartment facade"]),
    (("dealership", "luxury car", "sports car", "vehicle", "bmw", "mercedes"),
     ["luxury car showroom", "sports car dealership"]),
    (("car", "driving", "parking"), ["car driving city street", "car interior driving pov"]),
    (("warehouse", "crates", "inventory", "logistics", "barcode"),
     ["large warehouse interior aisles", "logistics warehouse forklift"]),
    (("factory", "industrial", "manufacturing", "assembly", "machinery", "gears", "machine"),
     ["factory assembly line", "industrial machinery working"]),
    (("construction", "crane", "building site"),
     ["construction cranes on skyline", "building construction site workers"]),
    (("port", "cargo", "container", "shipping", "ship", "ships"),
     ["cargo port containers aerial", "shipping container crane"]),
    (("receipt", "invoice", "statement", "paperwork", "documents", "bills", "envelope", "mail"),
     ["printing receipt closeup", "stack of paperwork on desk"]),
    (("phone", "smartphone", "app", "notification", "scrolling", "screen glow"),
     ["person using smartphone at night", "smartphone screen closeup"]),
    (("cafe", "coffee", "restaurant", "dining", "diner", "bar"),
     ["cozy cafe interior warm light", "restaurant table setting closeup"]),
    (("sunrise", "sunset", "golden hour", "horizon", "dawn"),
     ["city sunrise timelapse", "golden hour skyline drone"]),
    (("hospital", "medical", "doctor", "clinic", "er"),
     ["hospital building exterior at night", "empty hospital corridor"]),
    (("daycare", "childcare", "children", "kids", "school"),
     ["empty school classroom", "school building exterior morning"]),
    (("whiteboard", "marker", "chalkboard"),
     ["writing on whiteboard closeup", "person writing on glass board"]),
    (("map", "united states map", "globe", "world map"),
     ["united states map graphic", "spinning globe at night"]),
    (("scale", "balance scale"), ["old balance scale closeup"]),
    (("chess",), ["chess board pieces close up"]),
    (("river", "waterfall", "stream", "flowing water"),
     ["fast river flowing", "waterfall slow motion"]),
    (("road", "fork in the road", "path", "crossroads"),
     ["empty highway road sunset", "winding road aerial"]),
]

# Generic money imagery — LAST resort only, when nothing concrete matched.
GENERIC_FALLBACK = [
    (("money", "cash", "dollars", "dollar bills", "banknotes", "currency"),
     ["cash counting machine closeup", "stack of dollar bills macro"]),
    (("wealth", "rich", "luxury", "fortune"),
     ["luxury penthouse city view", "private jet interior"]),
]


def extract_keywords_from_voiceover(text: str) -> list:
    """Извлекает КОНКРЕТНЫЕ визуальные запросы из текста (prompt + voiceover)."""
    text_lower = (text or "").lower()
    h = abs(hash(text_lower))
    found = []
    seen = set()

    for triggers, qlist in SUBJECT_QUERIES:
        if any(t in text_lower for t in triggers):
            q = qlist[h % len(qlist)]
            if q not in seen:
                seen.add(q)
                found.append(q)
        if len(found) >= 3:
            break

    if not found:
        for triggers, qlist in GENERIC_FALLBACK:
            if any(t in text_lower for t in triggers):
                q = qlist[h % len(qlist)]
                if q not in seen:
                    seen.add(q)
                    found.append(q)

    if not found:
        found = ["financial district aerial", "modern city business b-roll"]

    return found[:3]


# Visual clichés that scream "generic AI finance channel" — avoid querying these.
CLICHE_TERMS = (
    "handshake", "piggy bank", "coins falling", "falling coins", "money rain",
    "gold coins", "businessman pointing", "thumbs up", "rolled banknotes",
    "dollar rain", "bitcoin",
    "smiling", "happy family", "lifestyle", "jumping", "shopping bags",
    "model", "having fun", "celebrating",
)


def _filter_cliches(queries):
    """Drop overly generic / cliché stock queries; keep a sane concrete fallback."""
    cleaned = []
    seen = set()
    for q in queries:
        if not q:
            continue
        ql = q.lower().strip()
        if not ql or ql in seen:
            continue
        if any(c in ql for c in CLICHE_TERMS):
            continue
        seen.add(ql)
        cleaned.append(q.strip())
    if not cleaned:
        cleaned = ["financial district aerial", "city skyline drone"]
    return cleaned[:3]


def _pexels_fetch_one(query, out_dir, orientation, used_ids, max_duration, min_height):
    """Try to grab ONE usable Pexels clip for a query, or None."""
    if not PEXELS_API_KEY or _PEXELS_DEAD:
        return None
    start_page = random.randint(1, 3)
    for page in range(start_page, start_page + MAX_SEARCH_PAGES):
        if _PEXELS_DEAD:
            break
        for vid in search_videos(query, per_page=15, orientation=orientation, page=page):
            vid_id = str(vid["id"])
            clip_path = out_dir / f"stock_{vid['id']}.mp4"
            if clip_path.exists():
                if _claim(used_ids, vid_id):
                    return clip_path
                continue
            if not _claim(used_ids, vid_id):
                continue
            if download_clip(vid, clip_path, max_duration=max_duration, min_height=min_height):
                return clip_path
            _unclaim(used_ids, vid_id)
    return None


def _pixabay_fetch_one(query, out_dir, pixabay_orient, used_ids, max_duration, min_height):
    """Try to grab ONE usable Pixabay clip for a query, or None (DIRECT, no proxy)."""
    if not PIXABAY_API_KEY:
        return None
    for page in (1, 2):
        for vid in search_pixabay(query, per_page=15, orientation=pixabay_orient, page=page):
            vid_id = f"px_{vid['id']}"
            clip_path = out_dir / f"stock_{vid['id']}_px.mp4"
            if clip_path.exists():
                if _claim(used_ids, vid_id):
                    return clip_path
                continue
            if not _claim(used_ids, vid_id):
                continue
            if download_pixabay_clip(vid, clip_path, max_duration=max_duration, min_height=min_height):
                return clip_path
            _unclaim(used_ids, vid_id)
    return None


def _race_one(query, out_dir, orientation, pixabay_orient, used_ids, max_duration, min_height):
    """Стучимся в Pexels И Pixabay ОДНОВРЕМЕННО, берём ПЕРВЫЙ годный клип."""
    ex = ThreadPoolExecutor(max_workers=2)
    fp = ex.submit(_pexels_fetch_one, query, out_dir, orientation, used_ids, max_duration, min_height)
    fx = ex.submit(_pixabay_fetch_one, query, out_dir, pixabay_orient, used_ids, max_duration, min_height)
    futs = [fp, fx]
    winner = None
    pending = set(futs)
    while pending and winner is None:
        done, pending = wait(pending, return_when=FIRST_COMPLETED)
        for f in done:
            try:
                p = f.result()
            except Exception:
                p = None
            if p:
                winner = p
                break

    def _cleanup(all_futs, keep, pool):
        for f in all_futs:
            try:
                p = f.result()
            except Exception:
                p = None
            if p and p != keep:
                try:
                    Path(p).unlink()
                except Exception:
                    pass
        pool.shutdown(wait=False)

    threading.Thread(target=_cleanup, args=(list(futs), winner, ex), daemon=True).start()
    return winner


def fetch_stock_clips(voiceover_text: str, count: int = 3, out_dir: Path = None,
                      orientation: str = "landscape", used_ids: set = None,
                      scene_prompt: str = "", max_duration: int = 35,
                      min_height: int = None, queries=None) -> list:
    """Ищет и скачивает stock video, стучась СРАЗУ в Pexels + Pixabay. Thread-safe."""
    if out_dir is None:
        out_dir = Path(".")
    out_dir.mkdir(parents=True, exist_ok=True)
    if used_ids is None:
        used_ids = set()
    if min_height is None:
        min_height = 720  # HD floor

    with _LOCK:
        used_ids.update(load_global_used_ids())

    if queries:
        keywords = _filter_cliches([q for q in queries if q and str(q).strip()])
    else:
        query_source = ((voiceover_text or "") + " " + (scene_prompt or "")).strip()
        keywords = _filter_cliches(extract_keywords_from_voiceover(query_source))

    pixabay_orient = "horizontal" if orientation == "landscape" else "vertical"
    downloaded = []
    for query in keywords:
        if len(downloaded) >= count:
            break
        clip = _race_one(query, out_dir, orientation, pixabay_orient,
                         used_ids, max_duration, min_height)
        if clip:
            downloaded.append(clip)

    with _LOCK:
        save_global_used_ids(used_ids)
    return downloaded


if __name__ == "__main__":
    clips = fetch_stock_clips(
        voiceover_text="A glass bank skyscraper at golden hour, crowds of commuters crossing the street, a bank vault door.",
        count=3,
        out_dir=Path("test_stock")
    )
    print(f"Downloaded {len(clips)} clips:")
    for c in clips:
        print(f"  {c} ({c.stat().st_size // 1024} KB)")
