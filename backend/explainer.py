"""
Explainability layer — SHAP feature attribution + LIME counterfactual playlist.

SHAP:
  We train a lightweight sklearn GradientBoosting regressor on the deterministic
  scores to get a model SHAP can introspect. This is the standard pattern for
  explaining scoring functions that aren't themselves ML models.

LIME:
  We perturb the optimization objective (flip ending, change energy target)
  and re-run the playlist builder to generate a genuinely different ordering,
  then highlight which positions changed.
"""

import numpy as np
import shap
from sklearn.ensemble import GradientBoostingRegressor
from schemas import ExtractedIntent, TrackModels
from playlist import build_playlist, score_track


# ── SHAP ──────────────────────────────────────────────────────────────────────

_FEATURE_NAMES = [
    "prompt_similarity",
    "mood_match",
    "energy_match",
    "tempo_match",
    "transition_score",
    "cyanite_score",
]


def _build_feature_matrix(
    candidates: list[TrackModels],
    intent: ExtractedIntent,
    n: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Build X (features) and y (scores) for all candidates at position 0."""
    rows, labels = [], []
    for t in candidates:
        final, contribs, ts = score_track(t, intent, 0, n, None)
        rows.append([contribs[f] for f in _FEATURE_NAMES])
        labels.append(final)
    return np.array(rows), np.array(labels)


def compute_shap(
    track: TrackModels,
    feature_contribs: dict[str, float],
    candidates: list[TrackModels],
    intent: ExtractedIntent,
) -> dict[str, float]:
    """
    Fit a GBR surrogate on all candidates, then compute SHAP values for
    the given track's feature vector.

    Args:
        track:            The track to explain.
        feature_contribs: Pre-computed weighted feature contributions.
        candidates:       Full candidate pool (used to train the surrogate).
        intent:           Current search intent.

    Returns:
        Dict mapping feature name → SHAP contribution value.
    """
    n = intent.num_tracks
    X, y = _build_feature_matrix(candidates, intent, n)

    if len(np.unique(y)) < 2:
        # Degenerate case: all scores identical — return raw contributions
        return {k: round(v, 4) for k, v in feature_contribs.items()}

    model = GradientBoostingRegressor(n_estimators=50, max_depth=3, random_state=0)
    model.fit(X, y)

    explainer = shap.TreeExplainer(model)
    x_track = np.array([[feature_contribs[f] for f in _FEATURE_NAMES]])
    sv = explainer.shap_values(x_track)[0]

    return {f: round(float(v), 4) for f, v in zip(_FEATURE_NAMES, sv)}


# ── LIME / Counterfactual ─────────────────────────────────────────────────────

_ENDING_FLIP = {
    "bang": "calm",
    "calm": "bang",
    "neutral": "calm",
}


def build_alternative_intent(intent: ExtractedIntent) -> ExtractedIntent:
    """
    Perturb the optimization objective to generate a meaningfully different playlist.

    Perturbation strategy:
      - Flip the ending style (bang → calm, calm → bang, neutral → calm).
      - Invert the energy range constraint.
    """
    alt_ending = _ENDING_FLIP.get(intent.ending, "calm")

    from schemas import MetadataFilter
    mf = intent.metadata_filter
    alt_filter = MetadataFilter(
        # Invert energy direction
        min_energy=None if mf.min_energy else 0.0,
        max_energy=0.45 if intent.ending == "bang" else None,
        tempo_tag=mf.tempo_tag,
        genres=mf.genres,
    )

    return ExtractedIntent(
        query=intent.query,
        duration_seconds=intent.duration_seconds,
        ending=alt_ending,
        num_tracks=intent.num_tracks,
        metadata_filter=alt_filter,
    )


def find_changed_positions(
    original: list[TrackModels],
    alternative: list[TrackModels],
) -> list[int]:
    """
    Return 1-indexed positions where the track identity changed between playlists.
    """
    original_ids = [t.id for t in original]
    alt_ids = [t.id for t in alternative]
    return [i + 1 for i, (a, b) in enumerate(zip(original_ids, alt_ids)) if a != b]


def build_alternative_playlist(
    candidates: list[TrackModels],
    intent: ExtractedIntent,
) -> tuple[list[tuple[TrackModels, float, dict[str, float], float]], ExtractedIntent, list[int]]:
    """
    Generate a counterfactual playlist by perturbing the intent.

    Returns:
        (alternative_playlist_items, alt_intent, changed_positions)
    """
    alt_intent = build_alternative_intent(intent)
    original_playlist = build_playlist(candidates, intent)
    original_tracks = [t for t, *_ in original_playlist]

    alt_playlist = build_playlist(candidates, alt_intent)
    alt_tracks = [t for t, *_ in alt_playlist]

    changed = find_changed_positions(original_tracks, alt_tracks)
    return alt_playlist, alt_intent, changed
