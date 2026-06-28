"""
LLM utilities — intent extraction and natural-language explanation generation.

Uses the Anthropic SDK pointed at claude-haiku-4-5 (cheap, fast).
Total LLM calls per request: 4
  1. extract_intent
  2. explain_shap_batch  (all main + alt tracks in one call)
  3. explain_transitions_batch  (all transitions in one call)
  4. explain_counterfactual

The LLM NEVER invents songs — it only explains deterministic scores.
"""

import json
import os
import re
import anthropic
from schemas import ExtractedIntent, MetadataFilter

_client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
_MODEL = "claude-haiku-4-5-20251001"
_MOCK = os.getenv("LLM_MOCK", "").lower() in ("1", "true", "yes")


# ── JSON helpers ──────────────────────────────────────────────────────────────

def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _parse_json(text: str):
    return json.loads(_strip_fences(text))


# ── Intent extraction ─────────────────────────────────────────────────────────

_INTENT_SYSTEM = """
You are a music search assistant. Extract structured intent from a DJ setlist request.
Return ONLY valid JSON with these exact keys:

{
  "query": "<2-5 vivid keywords describing the sonic vibe for semantic catalog search>",
  "duration_seconds": <integer, total playlist duration>,
  "ending": "<bang | calm | neutral>",
  "num_tracks": <integer, estimated number of tracks>,
  "metadata_filter": {
    "min_energy": <float 0-1 or null>,
    "max_energy": <float 0-1 or null>,
    "tempo_tag": "<slow | medium | fast | null>",
    "genres": [<genre strings>] or null
  },
  "mood_tags": [<1-3 tags from EXACTLY: aggressive, calm, chill, dark, energetic, epic, happy, romantic, sad, scary, sexy, ethereal, uplifting>],
  "genre_tags": [<1-2 tags from EXACTLY: african, ambient, asian, blues, classical, electronic, folkCountry, funkSoul, jazz, latin, metal, pop, rapHipHop, reggae, rnb, rock, singerSongwriter, soundtrack>],
  "min_bpm": <integer or null>,
  "max_bpm": <integer or null>
}

Rules:
- duration_seconds: if not specified assume 300 (5 min).
- num_tracks: derive from duration assuming ~3 min/track if not stated.
- ending: "bang" = high-energy finale; "calm" = gentle close; "neutral" = no constraint.
- query: concrete sonic keywords, not genre labels.
- mood_tags/genre_tags: ONLY exact strings from the lists above.
- BPM: slow < 90, medium 90-120, fast > 120.
- Return ONLY JSON, no markdown, no explanation.
""".strip()


async def extract_intent(prompt: str) -> ExtractedIntent:
    if _MOCK:
        return ExtractedIntent(
            query="mock vibe keywords",
            duration_seconds=600,
            ending="bang",
            num_tracks=5,
            metadata_filter=MetadataFilter(),
            mood_tags=["energetic", "happy"],
            genre_tags=["pop"],
        )
    response = await _client.messages.create(
        model=_MODEL,
        system=_INTENT_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=400,
    )
    data = _parse_json(response.content[0].text)
    mf = data.get("metadata_filter", {})
    return ExtractedIntent(
        query=data["query"],
        duration_seconds=int(data.get("duration_seconds", 300)),
        ending=data.get("ending", "neutral"),
        num_tracks=int(data.get("num_tracks", 5)),
        metadata_filter=MetadataFilter(
            min_energy=mf.get("min_energy"),
            max_energy=mf.get("max_energy"),
            tempo_tag=mf.get("tempo_tag"),
            genres=mf.get("genres"),
        ),
        mood_tags=data.get("mood_tags") or [],
        genre_tags=data.get("genre_tags") or [],
        min_bpm=data.get("min_bpm"),
        max_bpm=data.get("max_bpm"),
    )


# ── Batch SHAP explanations (ONE call for all tracks) ─────────────────────────

async def explain_shap_batch(
    tracks: list[tuple[str, dict[str, float], int, int]]
) -> list[tuple[str, str]]:
    """
    Explain all tracks in a single LLM call.

    Args:
        tracks: list of (title, shap_values, position, total)

    Returns:
        list of (why_song, why_position) — same order as input.
    """
    if _MOCK:
        return [
            (
                f'"{title}" was selected for its strong energy and mood alignment.',
                f"At position {pos} of {total} it supports the overall arc.",
            )
            for title, _, pos, total in tracks
        ]
    lines = []
    for i, (title, shap_vals, pos, total) in enumerate(tracks):
        top = sorted(shap_vals.items(), key=lambda x: -abs(x[1]))[:4]
        shap_str = ", ".join(f"{k}: {v:+.2f}" for k, v in top)
        lines.append(f'{i + 1}. "{title}" at position {pos}/{total}. SHAP: {shap_str}')

    user_msg = (
        "You are a music curator. For each track below, write:\n"
        "- why_song: one sentence why it was selected (top positive SHAP contributors).\n"
        "- why_position: one sentence why it sits at this position in the journey.\n\n"
        "Tracks:\n" + "\n".join(lines) + "\n\n"
        "Return a JSON array — one object per track, same order:\n"
        '[{"why_song": "...", "why_position": "..."}, ...]\n'
        "Return ONLY the JSON array, no markdown."
    )

    response = await _client.messages.create(
        model=_MODEL,
        messages=[{"role": "user", "content": user_msg}],
        temperature=0.3,
        max_tokens=150 * len(tracks),
    )

    results = _parse_json(response.content[0].text)

    # Normalise — ensure we always return the right number of items
    out: list[tuple[str, str]] = []
    for i in range(len(tracks)):
        item = results[i] if i < len(results) else {}
        out.append((
            item.get("why_song", "Selected for its strong match with the prompt."),
            item.get("why_position", "Placed here to support the energy arc."),
        ))
    return out


# ── Batch transition explanations (ONE call for all transitions) ──────────────

async def explain_transitions_batch(
    transitions: list[tuple[str, str, float, dict[str, float]]]
) -> list[str]:
    """
    Explain all transitions in a single LLM call.

    Args:
        transitions: list of (from_title, to_title, score, feature_deltas)

    Returns:
        list of one-sentence explanation strings — same order as input.
    """
    if not transitions:
        return []

    if _MOCK:
        return [
            f'The move from "{frm}" to "{to}" keeps the energy flowing with a smooth blend.'
            for frm, to, *_ in transitions
        ]

    lines = []
    for i, (frm, to, score, feats) in enumerate(transitions):
        feat_str = ", ".join(f"{k}: {v:+.2f}" for k, v in feats.items())
        lines.append(f'{i + 1}. "{frm}" → "{to}" (score {score:.2f}). Deltas: {feat_str}')

    user_msg = (
        "You are a DJ. For each transition below, write exactly one sentence "
        "describing it from a DJ perspective.\n\n"
        "Transitions:\n" + "\n".join(lines) + "\n\n"
        "Return a JSON array of strings, one per transition, same order:\n"
        '["sentence 1", "sentence 2", ...]\n'
        "Return ONLY the JSON array, no markdown."
    )

    response = await _client.messages.create(
        model=_MODEL,
        messages=[{"role": "user", "content": user_msg}],
        temperature=0.4,
        max_tokens=80 * len(transitions),
    )

    results = _parse_json(response.content[0].text)

    out: list[str] = []
    for i in range(len(transitions)):
        sentence = results[i] if i < len(results) else "Smooth energy flow between tracks."
        out.append(str(sentence))
    return out


# ── Counterfactual explanation ────────────────────────────────────────────────

async def explain_counterfactual(
    original_ending: str, alt_ending: str, changed_positions: list[int]
) -> str:
    if _MOCK:
        return (
            f"Switching the ending from '{original_ending}' to '{alt_ending}' reshaped "
            f"positions {changed_positions}, giving the set a different emotional trajectory."
        )
    user_msg = (
        f"Original playlist ended with '{original_ending}'. "
        f"Alternative ends with '{alt_ending}'. "
        f"Tracks at positions {changed_positions} changed. "
        "Explain in 1-2 sentences why those tracks changed and what the listener experiences differently. "
        "Be concrete. Return only the explanation text, no JSON."
    )
    response = await _client.messages.create(
        model=_MODEL,
        messages=[{"role": "user", "content": user_msg}],
        temperature=0.4,
        max_tokens=150,
    )
    return response.content[0].text.strip()
