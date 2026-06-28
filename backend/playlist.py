"""
Deterministic playlist scoring and selection.

No ML training. Pure weighted feature matching.
Weights are tunable constants at the top of this file.

Score formula:
  final = 0.35 * prompt_similarity
        + 0.20 * mood_match
        + 0.20 * energy_match
        + 0.10 * tempo_match
        + 0.10 * transition_score
        + 0.05 * cyanite_score
"""

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
from schemas import ExtractedIntent, TrackModels, TrackScore

# ── Scoring weights (must sum to 1.0) ────────────────────────────────────────
W_PROMPT      = 0.35
W_MOOD        = 0.20
W_ENERGY      = 0.20
W_TEMPO       = 0.10
W_TRANSITION  = 0.10
W_CYANITE     = 0.05

_TEMPO_ORDER = {"slow": 0, "medium": 1, "fast": 2}


# ── Feature helpers ───────────────────────────────────────────────────────────

def _prompt_similarity(query: str, track: TrackModels) -> float:
    """TF-IDF cosine similarity between search query and track text."""
    corpus = [query, f"{track.title} {track.artist} {track.genre} {track.description} {' '.join(track.moods)}"]
    try:
        vecs = TfidfVectorizer().fit_transform(corpus)
        return float(cosine_similarity(vecs[0:1], vecs[1:2])[0][0])
    except Exception:
        return 0.0


def _mood_match(intent: ExtractedIntent, track: TrackModels) -> float:
    """
    Score how well the track's moods match the intent.
    'bang' ending pushes toward energetic/euphoric moods.
    """
    positive_moods = {"happy", "energetic", "euphoric", "uplifting"}
    calm_moods = {"melancholic", "dreamy", "mellow"}
    track_moods = set(track.moods)

    if intent.ending == "bang":
        overlap = len(track_moods & positive_moods) / max(len(positive_moods), 1)
        return min(overlap + 0.2, 1.0)
    elif intent.ending == "calm":
        overlap = len(track_moods & calm_moods) / max(len(calm_moods), 1)
        return min(overlap + 0.2, 1.0)
    return 0.5  # neutral: no preference


def _energy_match(intent: ExtractedIntent, track: TrackModels, position: int, total: int) -> float:
    """
    Energy match considering position in the arc.
    'bang': ramp energy toward 1.0 at the end.
    'calm': ramp energy down toward 0.2 at the end.
    """
    progress = position / max(total - 1, 1)  # 0.0 → 1.0

    if intent.ending == "bang":
        target_energy = 0.5 + 0.5 * progress
    elif intent.ending == "calm":
        target_energy = 0.9 - 0.6 * progress
    else:
        target_energy = 0.6  # flat neutral target

    # Apply metadata energy constraints if present
    mf = intent.metadata_filter
    if mf.min_energy and track.energy < mf.min_energy:
        return 0.0
    if mf.max_energy and track.energy > mf.max_energy:
        return 0.0

    return 1.0 - abs(track.energy - target_energy)


def _tempo_match(intent: ExtractedIntent, track: TrackModels) -> float:
    """Score tempo compatibility with the metadata filter."""
    if intent.metadata_filter.tempo_tag is None:
        return 0.7  # no preference → neutral score
    if track.tempo_tag == intent.metadata_filter.tempo_tag:
        return 1.0
    delta = abs(_TEMPO_ORDER.get(track.tempo_tag, 1) - _TEMPO_ORDER.get(intent.metadata_filter.tempo_tag, 1))
    return max(0.0, 1.0 - delta * 0.5)


# ── Transition scoring ────────────────────────────────────────────────────────

def score_transition(a: TrackModels, b: TrackModels) -> tuple[float, dict[str, float]]:
    """
    Score the transition smoothness from track a to track b.

    Returns:
        (transition_score, feature_deltas_dict)
    """
    energy_delta   = abs(a.energy - b.energy)
    tempo_delta    = abs(_TEMPO_ORDER.get(a.tempo_tag, 1) - _TEMPO_ORDER.get(b.tempo_tag, 1)) / 2
    mood_overlap   = len(set(a.moods) & set(b.moods)) / max(len(set(a.moods) | set(b.moods)), 1)
    char_overlap   = len(set(a.character) & set(b.character)) / max(len(set(a.character) | set(b.character)), 1)
    genre_match    = 1.0 if a.genre == b.genre else 0.0
    movement_match = 1.0 if a.movement == b.movement else 0.0

    features = {
        "energy_delta":    round(-energy_delta, 3),   # negative = bigger penalty
        "tempo_delta":     round(-tempo_delta, 3),
        "mood_overlap":    round(mood_overlap, 3),
        "char_overlap":    round(char_overlap, 3),
        "genre_match":     round(genre_match, 3),
        "movement_match":  round(movement_match, 3),
    }

    score = (
        0.35 * (1 - energy_delta)
        + 0.25 * (1 - tempo_delta)
        + 0.20 * mood_overlap
        + 0.10 * char_overlap
        + 0.05 * genre_match
        + 0.05 * movement_match
    )
    return round(min(max(score, 0.0), 1.0), 3), features


# ── Main ranking ──────────────────────────────────────────────────────────────

def score_track(
    track: TrackModels,
    intent: ExtractedIntent,
    position: int,
    total: int,
    prev_track: TrackModels | None,
) -> tuple[float, dict[str, float], float]:
    """
    Compute the final score for a single track at a given position.

    Returns:
        (final_score, feature_contributions, transition_score)
    """
    ps  = _prompt_similarity(intent.query, track)
    mm  = _mood_match(intent, track)
    em  = _energy_match(intent, track, position, total)
    tm  = _tempo_match(intent, track)
    ts  = score_transition(prev_track, track)[0] if prev_track else 0.7
    cs  = track.cyanite_score

    final = (
        W_PROMPT     * ps
        + W_MOOD     * mm
        + W_ENERGY   * em
        + W_TEMPO    * tm
        + W_TRANSITION * ts
        + W_CYANITE  * cs
    )

    contributions = {
        "prompt_similarity": round(W_PROMPT * ps, 4),
        "mood_match":        round(W_MOOD * mm, 4),
        "energy_match":      round(W_ENERGY * em, 4),
        "tempo_match":       round(W_TEMPO * tm, 4),
        "transition_score":  round(W_TRANSITION * ts, 4),
        "cyanite_score":     round(W_CYANITE * cs, 4),
    }
    return round(min(final, 1.0), 4), contributions, ts


def build_playlist(
    candidates: list[TrackModels],
    intent: ExtractedIntent,
    used_ids: set[str] | None = None,
) -> list[tuple[TrackModels, float, dict[str, float], float]]:
    """
    Greedy sequential selection: pick the best track for each position
    without replacement.

    Args:
        candidates:  Candidate tracks from Cyanite search.
        intent:      Structured search intent.
        used_ids:    Track IDs already used (for alternative playlist deduplication).

    Returns:
        List of (track, final_score, feature_contributions, transition_score).
    """
    n = min(intent.num_tracks, len(candidates))
    pool = [t for t in candidates if not used_ids or t.id not in used_ids]
    selected: list[tuple[TrackModels, float, dict[str, float], float]] = []
    prev: TrackModels | None = None

    for pos in range(n):
        if not pool:
            break
        best = max(
            pool,
            key=lambda t: score_track(t, intent, pos, n, prev)[0],
        )
        final, contribs, ts = score_track(best, intent, pos, n, prev)
        selected.append((best, final, contribs, ts))
        pool.remove(best)
        prev = best

    return selected
