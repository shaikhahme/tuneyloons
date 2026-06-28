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

_client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"), max_retries=4)
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


# ── Single combined explanation call (2 LLM calls total per request) ──────────

async def explain_all(
    shap_batch: list[tuple[str, dict[str, float], int, int]],
    transitions: list[tuple[str, str, float, dict[str, float]]],
    original_ending: str,
    alt_ending: str,
    changed_positions: list[int],
    original_tracks: list,
    alt_tracks: list,
) -> tuple[list[tuple[str, str]], list[str], str]:
    """
    Single LLM call covering all three explanation tasks:
      - SHAP explanations for every track (main + alt combined)
      - Transition explanations
      - Counterfactual explanation

    Returns: (track_explanations, transition_explanations, counterfactual)
    """
    n_tracks = len(shap_batch)

    if _MOCK:
        track_expls = [
            (
                f'"{title}" was selected for its strong energy and mood alignment.',
                f"At position {pos} of {total} it supports the overall arc.",
            )
            for title, _, pos, total in shap_batch
        ]
        trans_expls = [
            f'The move from "{frm}" to "{to}" keeps the energy flowing with a smooth blend.'
            for frm, to, *_ in transitions
        ]
        counterfactual = (
            f"Switching the ending from '{original_ending}' to '{alt_ending}' reshaped "
            f"positions {changed_positions}, giving the set a different emotional trajectory."
        )
        return track_expls, trans_expls, counterfactual

    # ── Section 1: tracks ──
    track_lines = []
    for i, (title, shap_vals, pos, total) in enumerate(shap_batch):
        top = sorted(shap_vals.items(), key=lambda x: -abs(x[1]))[:4]
        shap_str = ", ".join(f"{k}: {v:+.2f}" for k, v in top)
        track_lines.append(f'{i + 1}. "{title}" pos {pos}/{total}. SHAP: {shap_str}')

    # ── Section 2: transitions ──
    trans_lines = []
    for i, (frm, to, score, feats) in enumerate(transitions):
        feat_str = ", ".join(f"{k}: {v:+.2f}" for k, v in feats.items())
        trans_lines.append(f'{i + 1}. "{frm}" → "{to}" (score {score:.2f}). {feat_str}')

    # ── Section 3: counterfactual ──
    cf_lines = []
    for pos in changed_positions:
        idx = pos - 1
        if idx < len(original_tracks) and idx < len(alt_tracks):
            o, a = original_tracks[idx], alt_tracks[idx]
            cf_lines.append(
                f"  pos {pos}: '{o.title}' (energy={o.energy}, moods={o.moods})"
                f" → '{a.title}' (energy={a.energy}, moods={a.moods})"
            )
    cf_diff = "\n".join(cf_lines) if cf_lines else "  (no track-level details)"

    user_msg = (
        "You are an AI music curator and DJ. Answer all three sections below in ONE JSON object.\n\n"

        "## SECTION 1 — Track explanations\n"
        "For each track write why_song (one sentence: top SHAP contributors) "
        "and why_position (one sentence: role in the energy arc).\n"
        "Tracks:\n" + "\n".join(track_lines) + "\n\n"

        "## SECTION 2 — Transition explanations\n"
        "For each transition write one sentence from a DJ perspective.\n"
        "Transitions:\n" + ("\n".join(trans_lines) if trans_lines else "  (none)") + "\n\n"

        "## SECTION 3 — Counterfactual\n"
        f"Original ending: '{original_ending}'. Alternative ending: '{alt_ending}'.\n"
        f"Track changes:\n{cf_diff}\n"
        "Write 1-2 sentences explaining why tracks changed and what the listener experiences differently.\n\n"

        "Return ONLY this JSON, no markdown:\n"
        '{\n'
        '  "tracks": [{"why_song": "...", "why_position": "..."}, ...],\n'
        '  "transitions": ["sentence 1", ...],\n'
        '  "counterfactual": "..."\n'
        '}'
    )

    response = await _client.messages.create(
        model=_MODEL,
        messages=[{"role": "user", "content": user_msg}],
        temperature=0.3,
        max_tokens=150 * n_tracks + 80 * len(transitions) + 150,
    )

    result = _parse_json(response.content[0].text)

    # ── Parse tracks ──
    raw_tracks = result.get("tracks", [])
    track_expls: list[tuple[str, str]] = []
    for i in range(n_tracks):
        item = raw_tracks[i] if i < len(raw_tracks) else {}
        track_expls.append((
            item.get("why_song", "Selected for its strong match with the prompt."),
            item.get("why_position", "Placed here to support the energy arc."),
        ))

    # ── Parse transitions ──
    raw_trans = result.get("transitions", [])
    trans_expls: list[str] = []
    for i in range(len(transitions)):
        trans_expls.append(
            str(raw_trans[i]) if i < len(raw_trans) else "Smooth energy flow between tracks."
        )

    counterfactual = str(result.get("counterfactual", "The alternative playlist explores a different emotional direction."))

    return track_expls, trans_expls, counterfactual


# ── Kept for test compatibility ────────────────────────────────────────────────

async def explain_shap_batch(
    tracks: list[tuple[str, dict[str, float], int, int]]
) -> list[tuple[str, str]]:
    expls, _, _ = await explain_all(tracks, [], "neutral", "neutral", [], [], [])
    return expls


async def explain_transitions_batch(
    transitions: list[tuple[str, str, float, dict[str, float]]]
) -> list[str]:
    _, trans, _ = await explain_all([], transitions, "neutral", "neutral", [], [], [])
    return trans


async def explain_counterfactual(
    original_ending: str,
    alt_ending: str,
    changed_positions: list[int],
    original_tracks: list,
    alt_tracks: list,
) -> str:
    _, _, cf = await explain_all([], [], original_ending, alt_ending, changed_positions, original_tracks, alt_tracks)
    return cf
