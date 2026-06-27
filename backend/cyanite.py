"""
Cyanite API client — mocked for hackathon.

Every function has the REAL signature and return shape.
To go live: replace the body of each function with the actual HTTP call.
The mock returns realistic data drawn from the Jamendo-style 357k catalog.

Real endpoints:
  POST /private-alpha/library-tracks/search   → search_tracks()
  GET  /library-tracks/{id}/models             → fetch_track_models()
  GET  /library-tracks/{id}/similar            → fetch_similar_tracks()
"""

import random
from schemas import TrackModels

# ── Deterministic seed so results are reproducible within a session ───────────
_RNG = random.Random(42)

_GENRES = ["pop", "electronic", "hip-hop", "r&b", "indie-pop", "dance", "synth-pop"]
_MOODS = ["happy", "energetic", "romantic", "melancholic", "aggressive", "dreamy", "euphoric"]
_TEMPOS = ["slow", "medium", "fast"]
_MOVEMENTS = ["driving", "floating", "bouncy", "steady", "explosive"]
_CHARACTERS = [
    ["uplifting", "bright"],
    ["dark", "intense"],
    ["smooth", "mellow"],
    ["aggressive", "raw"],
    ["playful", "light"],
]

_ARTIST_POOL = [
    "Dua Lipa", "Charli XCX", "Olivia Rodrigo", "Sabrina Carpenter",
    "Ariana Grande", "Billie Eilish", "Carly Rae Jepsen", "Kim Petras",
    "Ava Max", "Bebe Rexha", "Doja Cat", "Lizzo", "Meghan Trainor",
    "Nicki Minaj", "Katy Perry", "Lady Gaga", "Cardi B", "Kesha",
]

_TITLE_POOL = [
    "Levitating", "Good 4 U", "Espresso", "Flowers", "As It Was",
    "Anti-Hero", "Unholy", "About Damn Time", "Break My Soul", "Industry Baby",
    "Stay", "Watermelon Sugar", "Blinding Lights", "Save Your Tears", "Peaches",
    "Montero", "Butter", "Dynamite", "Permission to Dance", "DNA",
    "Physical", "Don't Start Now", "Hallucinate", "Bop to the Top",
    "Made You Look", "Karma", "Cruel Summer", "Shake It Off", "Bad Blood",
    "Blank Space", "Style", "Wildest Dreams", "Out of the Woods", "Clean",
    "New Romantics", "Getaway Car", "Delicate", "Gorgeous", "King of My Heart",
    "Dancing With Our Hands Tied", "Dress", "This Is Why We Can't Have Nice Things",
    "Call It What You Want", "New Year's Day", "Ready for It", "End Game",
    "Gorgeous", "Sparks Fly", "Mine", "Fearless",
]


def _make_track(seed_id: int, score: float) -> TrackModels:
    """Generate a realistic-looking Cyanite track from a numeric seed."""
    rng = random.Random(seed_id)
    energy = round(rng.uniform(0.3, 1.0), 2)
    return TrackModels(
        id=f"jamendo_{seed_id:06d}",
        title=rng.choice(_TITLE_POOL) + f" (#{seed_id})",
        artist=rng.choice(_ARTIST_POOL),
        duration_seconds=rng.randint(150, 240),
        genre=rng.choice(_GENRES),
        moods=rng.sample(_MOODS, k=2),
        energy=energy,
        valence=round(rng.uniform(0.4, 1.0), 2),
        arousal=round(energy * rng.uniform(0.8, 1.1), 2),
        tempo_tag=rng.choice(_TEMPOS),
        bpm=round(rng.uniform(90, 160), 1),
        movement=rng.choice(_MOVEMENTS),
        character=rng.choice(_CHARACTERS),
        description=f"An upbeat {rng.choice(_GENRES)} track with {rng.choice(_MOODS)} qualities.",
        cyanite_score=round(score, 3),
    )


# ── Public API ────────────────────────────────────────────────────────────────

def search_tracks(query: str, limit: int = 50) -> list[TrackModels]:
    """
    Mock of POST /private-alpha/library-tracks/search.

    Real call:
        POST https://api.cyanite.ai/private-alpha/library-tracks/search
        Authorization: Bearer {CYANITE_API_KEY}
        { "query": query, "limit": limit }

    Returns top-N tracks ordered by relevance score (descending).
    """
    # Scores decay from ~0.98 down — simulates ranked search results
    scores = [round(0.98 - i * 0.009, 3) for i in range(limit)]
    seed_ids = _RNG.sample(range(1, 357_001), limit)
    return [_make_track(sid, sc) for sid, sc in zip(seed_ids, scores)]


def fetch_track_models(track_id: str) -> TrackModels | None:
    """
    Mock of GET /library-tracks/{id}/models.

    Real call:
        GET https://api.cyanite.ai/library-tracks/{track_id}/models
        Authorization: Bearer {CYANITE_API_KEY}

    Returns full model outputs: genre, mood, BPM, valence/arousal, etc.
    Already embedded in search results for the mock; in production this
    gives richer data than the search payload.
    """
    # In the mock the search already returns full models — this is a no-op.
    # In production: make the GET call, parse, return TrackModels.
    return None


def fetch_similar_tracks(track_id: str, limit: int = 5) -> list[TrackModels]:
    """
    Mock of GET /library-tracks/{id}/similar (Cyanite Similar Search).

    Real call:
        GET https://api.cyanite.ai/library-tracks/{track_id}/similar?limit={limit}
        Authorization: Bearer {CYANITE_API_KEY}

    Returns tracks similar to the given track, used to build graph edges.
    """
    seed = int(track_id.split("_")[-1]) if "_" in track_id else _RNG.randint(1, 9999)
    rng = random.Random(seed)
    similar_ids = rng.sample(range(1, 357_001), limit)
    scores = [round(0.88 - i * 0.04, 3) for i in range(limit)]
    return [_make_track(sid, sc) for sid, sc in zip(similar_ids, scores)]
