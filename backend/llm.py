"""
LLM utilities — intent extraction and natural-language explanation generation.

Uses the Anthropic SDK pointed at claude-haiku-4-5 (cheap, fast, sufficient for
structured extraction at hackathon scale).

The LLM NEVER invents songs — it only:
  1. Converts a natural-language prompt into structured ExtractedIntent.
  2. Converts SHAP feature values into a human-readable sentence.
  3. Generates a counterfactual explanation for the alternative playlist.
"""

import json
import os
import anthropic
from schemas import ExtractedIntent, MetadataFilter

_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
_MODEL = "claude-haiku-4-5-20251001"

_INTENT_SYSTEM = """
You are a music search assistant. Extract structured intent from a DJ setlist
request. Return ONLY valid JSON with these exact keys:

{
  "query": "<short keyword search string for the music catalog>",
  "duration_seconds": <integer, total playlist duration>,
  "ending": "<one of: bang | calm | neutral>",
  "num_tracks": <integer, estimated number of tracks>,
  "metadata_filter": {
    "min_energy": <float 0-1 or null>,
    "max_energy": <float 0-1 or null>,
    "tempo_tag": "<slow | medium | fast | null>",
    "genres": [<strings>] or null
  }
}

Rules:
- duration_seconds: if not specified assume 600 (10 min).
- num_tracks: derive from duration assuming ~3 min/track if not stated.
- ending "bang" = last track must be high energy; "calm" = low energy; "neutral" = no constraint.
- query: distill the vibe into 2-5 keywords that match a music catalog.
- Return ONLY JSON, no markdown, no explanation.
""".strip()


def extract_intent(prompt: str) -> ExtractedIntent:
    """
    Convert a natural-language DJ prompt into structured search constraints.

    Args:
        prompt: Raw user input, e.g. "girly pop playlist for a 10 min drive".

    Returns:
        ExtractedIntent with query, duration, track count, ending style,
        and any metadata filters.
    """
    response = _client.messages.create(
        model=_MODEL,
        system=_INTENT_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=300,
    )
    raw = response.content[0].text.strip()
    data = json.loads(raw)

    mf = data.get("metadata_filter", {})
    return ExtractedIntent(
        query=data["query"],
        duration_seconds=int(data.get("duration_seconds", 600)),
        ending=data.get("ending", "neutral"),
        num_tracks=int(data.get("num_tracks", 5)),
        metadata_filter=MetadataFilter(
            min_energy=mf.get("min_energy"),
            max_energy=mf.get("max_energy"),
            tempo_tag=mf.get("tempo_tag"),
            genres=mf.get("genres"),
        ),
    )


def explain_shap(track_title: str, shap_values: dict[str, float], position: int, total: int) -> tuple[str, str]:
    """
    Generate human-readable why_song and why_position explanations from SHAP values.

    Args:
        track_title:  Name of the track.
        shap_values:  Feature → contribution mapping from SHAP.
        position:     1-indexed position in the playlist.
        total:        Total number of tracks.

    Returns:
        Tuple of (why_song, why_position) natural-language strings.
    """
    shap_summary = ", ".join(f"{k}: {v:+.2f}" for k, v in sorted(shap_values.items(), key=lambda x: -abs(x[1])))
    user_msg = (
        f"Track: '{track_title}' at position {position}/{total}.\n"
        f"SHAP feature contributions: {shap_summary}.\n"
        "Write two short sentences:\n"
        "1. why_song: why this track was selected (focus on top positive contributors).\n"
        "2. why_position: why it appears at this position in the journey.\n"
        "Return JSON: {\"why_song\": \"...\", \"why_position\": \"...\"}"
    )
    response = _client.messages.create(
        model=_MODEL,
        messages=[{"role": "user", "content": user_msg}],
        temperature=0.3,
        max_tokens=150,
    )
    raw = response.content[0].text.strip()
    data = json.loads(raw)
    return data["why_song"], data["why_position"]


def explain_counterfactual(original_ending: str, alt_ending: str, changed_positions: list[int]) -> str:
    """
    Generate a plain-English explanation of why the alternative playlist differs.

    Args:
        original_ending:   e.g. "bang"
        alt_ending:        e.g. "calm"
        changed_positions: List of 1-indexed positions that changed.

    Returns:
        One or two sentence explanation string.
    """
    user_msg = (
        f"Original playlist ended with a '{original_ending}'. "
        f"Alternative playlist ends with '{alt_ending}'. "
        f"Tracks at positions {changed_positions} changed as a result. "
        "Explain in 1-2 sentences why those specific tracks changed and what the listener would experience differently. "
        "Be concrete. Return only the explanation text, no JSON."
    )
    response = _client.messages.create(
        model=_MODEL,
        messages=[{"role": "user", "content": user_msg}],
        temperature=0.4,
        max_tokens=120,
    )
    return response.content[0].text.strip()


def explain_transition(from_title: str, to_title: str, score: float, features: dict[str, float]) -> str:
    """
    Generate a one-sentence transition explanation between two tracks.

    Args:
        from_title:  Title of the outgoing track.
        to_title:    Title of the incoming track.
        score:       Transition smoothness score (0-1).
        features:    Feature deltas used to compute the score.

    Returns:
        One-sentence explanation string.
    """
    feat_str = ", ".join(f"{k}: {v:+.2f}" for k, v in features.items())
    user_msg = (
        f"Transition from '{from_title}' to '{to_title}' (score {score:.2f}). "
        f"Feature deltas: {feat_str}. "
        "Describe this transition in one sentence from a DJ perspective. Return only the sentence."
    )
    response = _client.messages.create(
        model=_MODEL,
        messages=[{"role": "user", "content": user_msg}],
        temperature=0.4,
        max_tokens=80,
    )
    return response.content[0].text.strip()
