"""
Cyanite REST API client.

Base URL: https://rest-api.cyanite.ai/v1
Auth:     x-api-key: <cyaniteApiKey>

Real endpoints:
  POST /private-alpha/library-tracks/search        → search_tracks()
  GET  /library-tracks/{id}/models                 → _fetch_models_for_item()
  POST /private-alpha/library-tracks/{id}/similar  → fetch_similar_tracks()

Falls back to deterministic mock data when cyaniteApiKey is not set.
"""

import json
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from schemas import TrackModels

# ── Config ────────────────────────────────────────────────────────────────────
_RAW_KEY = os.getenv("cyaniteApiKey", "")
_API_KEY = _RAW_KEY.strip('"').strip("'")
_BASE_URL = "https://rest-api.cyanite.ai/v1"
_USE_MOCK = not _API_KEY

_MODELS_TO_FETCH = [
    "MoodSimpleV2",
    "MainGenreV2",
    "BpmV2",
    "ValenceArousalV2",
    "CharacterV2",
    "MovementV2",
    "AutoDescriptionV2",
]


# ── Internal helpers ──────────────────────────────────────────────────────────

def _with_retry(request_fn, max_retries: int = 4, base_delay: float = 5.0):
    """
    Call request_fn() and retry on HTTP 429 with exponential backoff.
    Non-429 HTTP errors are raised immediately.
    """
    for attempt in range(max_retries + 1):
        resp = request_fn()
        if resp.status_code != 429:
            resp.raise_for_status()
            return resp
        if attempt == max_retries:
            resp.raise_for_status()   # raises requests.HTTPError
        wait = base_delay * (2 ** attempt)   # 5, 10, 20, 40 s
        print(f"[cyanite] rate limited (429), retrying in {wait:.0f}s (attempt {attempt + 1}/{max_retries})")
        time.sleep(wait)


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"x-api-key": _API_KEY})
    return s


def _bpm_to_tempo(bpm: float) -> str:
    if bpm < 90:
        return "slow"
    if bpm <= 120:
        return "medium"
    return "fast"


def _energy_level_to_float(tag: str) -> float:
    return {"low": 0.2, "medium": 0.5, "high": 0.85, "varying": 0.6}.get(str(tag).lower(), 0.5)


def _parse_model_items(items: list) -> dict:
    """Collapse a list of Cyanite model output dicts into one feature dict."""
    out = {
        "moods": ["energetic"],
        "genre": "electronic",
        "bpm": 120.0,
        "valence": 0.5,
        "arousal": 0.5,
        "energy": 0.5,
        "movement": "steady",
        "character": ["smooth"],
        "description": "",
    }
    for item in items:
        model = item.get("version", "")  # Cyanite uses "version", not "model"

        if model == "MoodSimpleV2":
            tags = item.get("tags") or []
            if tags:
                out["moods"] = [t.lower() for t in tags[:3]]

        elif model == "MainGenreV2":
            tags = item.get("tags") or []  # MainGenreV2 uses "tags" list, not "tag"
            if tags:
                out["genre"] = tags[0].lower()

        elif model == "BpmV2":
            tag = item.get("tag")
            if tag is not None:
                try:
                    out["bpm"] = float(tag)
                except (TypeError, ValueError):
                    pass

        elif model == "ValenceArousalV2":
            scores = item.get("scores") or {}
            if "valence" in scores:
                out["valence"] = round(float(scores["valence"]), 3)
            if "arousal" in scores:
                out["arousal"] = round(float(scores["arousal"]), 3)
            el = item.get("energyLevel") or ""  # energyLevel is a plain string e.g. "high"
            if isinstance(el, str) and el:
                out["energy"] = _energy_level_to_float(el)
            else:
                out["energy"] = out["arousal"]

        elif model == "CharacterV2":
            tags = item.get("tags") or []
            if tags:
                out["character"] = [t.lower() for t in tags[:2]]

        elif model == "MovementV2":
            tags = item.get("tags") or []  # MovementV2 uses "tags" list, not "tag"
            if tags:
                out["movement"] = tags[0].lower()

        elif model == "AutoDescriptionV2":
            out["description"] = item.get("description") or ""

    return out


def _build_track_model(item: dict, features: dict) -> TrackModels:
    track = item.get("track", {})
    raw_title = track.get("title", "Unknown")
    title = os.path.splitext(raw_title)[0]
    return TrackModels(
        id=track.get("id", "unknown"),
        title=title,
        artist=features.get("description", "Unknown"),
        duration_seconds=int(track.get("duration") or 180),
        genre=features["genre"],
        moods=features["moods"],
        energy=round(min(max(features["energy"], 0.0), 1.0), 2),
        valence=round(min(max(features["valence"], 0.0), 1.0), 2),
        arousal=round(min(max(features["arousal"], 0.0), 1.0), 2),
        tempo_tag=_bpm_to_tempo(features["bpm"]),
        bpm=round(features["bpm"], 1),
        movement=features["movement"],
        character=features["character"],
        description=features["description"],
        cyanite_score=round(float(item.get("score", 0.5)), 3),
    )


def _fetch_models_for_item(sess: requests.Session, item: dict) -> TrackModels | None:
    """Fetch model tags for one search result; returns TrackModels or None on error."""
    cyanite_id = item.get("track", {}).get("id", "")
    if not cyanite_id:
        return None
    params = [("model", m) for m in _MODELS_TO_FETCH]
    try:
        resp = _with_retry(
            lambda: sess.get(
                f"{_BASE_URL}/library-tracks/{cyanite_id}/models",
                params=params,
                timeout=15,
            )
        )
        model_resp = resp.json()
        features = _parse_model_items(model_resp.get("items", []))
        return _build_track_model(item, features)
    except Exception as exc:
        print(f"[cyanite] model fetch failed for {cyanite_id}: {exc}")
        return None


# ── Cyanite filter builder (used by app.py) ───────────────────────────────────

def build_cyanite_filter(intent) -> dict:
    """
    Construct a Cyanite metadataFilter from the extracted intent.
    Kept lenient (low score thresholds, few constraints) to avoid empty result sets.
    """
    f: dict = {}

    # Metadata filters are omitted — the Cyanite library may be small and
    # any hard filter risks returning 0 results. The text query carries all
    # intent (genre, mood, tempo). Re-enable filters once the catalog size
    # and exact Cyanite field semantics are confirmed.
    return f


# ── Real API implementation ───────────────────────────────────────────────────

def _real_search_tracks(query: str, metadata_filter: dict, limit: int) -> list[TrackModels]:
    sess = _session()
    body: dict = {"query": query}
    if metadata_filter:
        body["metadataFilter"] = metadata_filter

    print(f"[cyanite] search query={query!r} filter={metadata_filter} limit={limit}")
    try:
        resp = _with_retry(
            lambda: sess.post(
                f"{_BASE_URL}/private-alpha/library-tracks/search",
                params={"limit": limit},
                json=body,
                timeout=30,
            )
        )
        items = resp.json().get("items", [])
    except Exception as exc:
        print(f"[cyanite] search failed: {exc}")
        return []

    print(f"[cyanite] search returned {len(items)} raw items")
    if items:
        print(f"[cyanite] first track: {json.dumps(items[0].get('track', {}))}")
    if not items:
        return []

    tracks: list[TrackModels] = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(_fetch_models_for_item, sess, item): item for item in items}
        for future in as_completed(futures):
            result = future.result()
            if result:
                tracks.append(result)

    tracks.sort(key=lambda t: t.cyanite_score, reverse=True)
    print(f"[cyanite] resolved {len(tracks)} tracks after model fetch")
    return tracks


def _real_fetch_similar(track_id: str, limit: int) -> list[TrackModels]:
    sess = _session()
    try:
        resp = _with_retry(
            lambda: sess.post(
                f"{_BASE_URL}/private-alpha/library-tracks/{track_id}/similar",
                params={"limit": limit},
                json={},
                timeout=15,
            )
        )
        items = resp.json().get("items", [])
    except Exception as exc:
        print(f"[cyanite] similar failed for {track_id}: {exc}")
        return []

    tracks: list[TrackModels] = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(_fetch_models_for_item, sess, item): item for item in items}
        for future in as_completed(futures):
            result = future.result()
            if result:
                tracks.append(result)

    tracks.sort(key=lambda t: t.cyanite_score, reverse=True)
    return tracks


# ── Mock fallback ─────────────────────────────────────────────────────────────

_MOCK_KEYS = [
    "C Major", "G Major", "D Major", "A Major", "E Major", "F Major", "Bb Major",
    "A Minor", "E Minor", "D Minor", "B Minor", "F# Minor", "G Minor", "C Minor",
]
_MOCK_GENRES = ["pop", "electronic", "hip-hop", "r&b", "indie-pop", "dance", "ambient"]
_MOCK_MOODS = [["happy", "energetic"], ["calm", "chill"], ["dark", "sad"],
               ["uplifting", "euphoric"], ["dreamy", "ethereal"]]
_MOCK_TEMPOS = ["slow", "medium", "fast"]
_MOCK_MOVEMENTS = ["driving", "floating", "bouncy", "steady", "explosive"]
_MOCK_CHARACTERS = [["uplifting", "bright"], ["dark", "intense"], ["smooth", "mellow"],
                    ["aggressive", "raw"], ["playful", "light"]]
_MOCK_ARTISTS = [
    "Dua Lipa", "Charli XCX", "Olivia Rodrigo", "Sabrina Carpenter", "Ariana Grande",
    "Billie Eilish", "Carly Rae Jepsen", "Kim Petras", "Ava Max", "Bebe Rexha",
    "Doja Cat", "Lizzo", "Katy Perry", "Lady Gaga", "Kesha",
]
_MOCK_TITLES = [
    "Levitating", "Good 4 U", "Espresso", "Flowers", "As It Was", "Anti-Hero",
    "Unholy", "About Damn Time", "Break My Soul", "Industry Baby", "Stay",
    "Watermelon Sugar", "Blinding Lights", "Save Your Tears", "Peaches",
    "Montero", "Butter", "Dynamite", "Cruel Summer", "Shake It Off",
]


def _make_mock_track(seed_id: int, score: float) -> TrackModels:
    rng = random.Random(seed_id)
    energy = round(rng.uniform(0.3, 1.0), 2)
    return TrackModels(
        id=f"libtr_mock_{seed_id:06d}",
        title=rng.choice(_MOCK_TITLES),
        artist=rng.choice(_MOCK_ARTISTS),
        duration_seconds=rng.randint(150, 240),
        genre=rng.choice(_MOCK_GENRES),
        moods=rng.choice(_MOCK_MOODS),
        energy=energy,
        valence=round(rng.uniform(0.4, 1.0), 2),
        arousal=round(energy * rng.uniform(0.8, 1.1), 2),
        tempo_tag=rng.choice(_MOCK_TEMPOS),
        bpm=round(rng.uniform(90, 160), 1),
        musical_key=rng.choice(_MOCK_KEYS),
        movement=rng.choice(_MOCK_MOVEMENTS),
        character=rng.choice(_MOCK_CHARACTERS),
        description=f"A {rng.choice(_MOCK_GENRES)} track with {rng.choice(_MOCK_MOODS)[0]} qualities.",
        cyanite_score=round(score, 3),
    )


def _mock_search_tracks(query: str, limit: int) -> list[TrackModels]:
    query_seed = sum(ord(c) * (i + 1) for i, c in enumerate(query)) % (2 ** 31)
    rng = random.Random(query_seed)
    scores = [round(0.98 - i * 0.009, 3) for i in range(limit)]
    seed_ids = rng.sample(range(1, 357_001), limit)
    return [_make_mock_track(sid, sc) for sid, sc in zip(seed_ids, scores)]


def _mock_fetch_similar(track_id: str, limit: int) -> list[TrackModels]:
    seed = int(track_id.split("_")[-1]) if "_" in track_id else abs(hash(track_id)) % 9999
    rng = random.Random(seed)
    ids = rng.sample(range(1, 357_001), limit)
    scores = [round(0.88 - i * 0.04, 3) for i in range(limit)]
    return [_make_mock_track(sid, sc) for sid, sc in zip(ids, scores)]


# ── Public interface ──────────────────────────────────────────────────────────

def search_tracks(query: str, metadata_filter: dict | None = None, limit: int = 50) -> list[TrackModels]:
    """Search the Cyanite catalog. Uses mock data when API key is absent or API returns empty."""
    if _USE_MOCK:
        print("[cyanite] No API key — using mock data")
        return _mock_search_tracks(query, limit)
    tracks = _real_search_tracks(query, metadata_filter or {}, limit)
    if not tracks:
        print("[cyanite] real API returned no tracks — falling back to mock data")
        return _mock_search_tracks(query, limit)
    return tracks


def fetch_track_models(track_id: str) -> TrackModels | None:
    """Model data is already embedded during search; kept for API compatibility."""
    return None


def fetch_similar_tracks(track_id: str, limit: int = 5) -> list[TrackModels]:
    """Fetch similar tracks. Uses mock data when API key is absent."""
    if _USE_MOCK:
        return _mock_fetch_similar(track_id, limit)
    return _real_fetch_similar(track_id, limit)
