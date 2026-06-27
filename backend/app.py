"""
FastAPI entrypoint — POST /generate_playlist

Pipeline:
  1. LLM intent extraction
  2. Cyanite prompt search (50 candidates)
  3. Deterministic playlist ranking
  4. SHAP explanations per track
  5. LLM natural-language why_song / why_position per track
  6. LLM transition explanations
  7. LIME counterfactual playlist + explanation
  8. Knowledge graph construction
  9. Return unified JSON response
"""

import os
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from schemas import PlaylistRequest, PlaylistResponse, PlaylistTrack
from cyanite import search_tracks, fetch_similar_tracks
from llm import extract_intent, explain_shap, explain_counterfactual, explain_transition
from playlist import build_playlist, score_transition
from explainer import compute_shap, build_alternative_playlist
from graph import build_graph

app = FastAPI(title="Explainable AI DJ Setlist Generator", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/generate_playlist", response_model=PlaylistResponse)
async def generate_playlist(request: PlaylistRequest) -> PlaylistResponse:
    """
    Generate an explainable, ordered DJ setlist from a natural-language prompt.

    Steps mirror the spec pipeline exactly.
    """
    if not request.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty.")

    # ── Step 1: Extract structured intent ────────────────────────────────────
    intent = extract_intent(request.prompt)

    # ── Step 2: Cyanite prompt search — top 50 candidates ────────────────────
    candidates = search_tracks(query=intent.query, limit=50)
    if not candidates:
        raise HTTPException(status_code=502, detail="Cyanite returned no tracks.")

    # ── Step 3: Models already embedded in mock; in production call
    #    fetch_track_models() here per track ID. ──────────────────────────────

    # ── Step 4 + 5: Rank and select playlist ─────────────────────────────────
    playlist_items = build_playlist(candidates, intent)

    # ── Step 6: SHAP + LLM explanations per track ────────────────────────────
    playlist_out: list[PlaylistTrack] = []
    n = len(playlist_items)

    for i, (track, score, contribs, ts) in enumerate(playlist_items):
        shap_vals = compute_shap(track, contribs, candidates, intent)
        why_song, why_position = explain_shap(track.title, shap_vals, i + 1, n)
        playlist_out.append(
            PlaylistTrack(
                track={
                    "id": track.id,
                    "title": track.title,
                    "artist": track.artist,
                    "duration_seconds": track.duration_seconds,
                    "energy": track.energy,
                    "bpm": track.bpm,
                    "genre": track.genre,
                    "moods": track.moods,
                },
                score=score,
                why_song=why_song,
                why_position=why_position,
                shap_values=shap_vals,
            )
        )

    # ── Step 5: Transition explanations (for graph edges) ────────────────────
    tracks = [t for t, *_ in playlist_items]
    transition_explanations: list[str] = []
    for i in range(len(tracks) - 1):
        a, b = tracks[i], tracks[i + 1]
        _, feat_deltas = score_transition(a, b)
        ts_score = playlist_items[i + 1][3]
        expl = explain_transition(a.title, b.title, ts_score, feat_deltas)
        transition_explanations.append(expl)

    # ── Step 7: LIME counterfactual playlist ──────────────────────────────────
    alt_items, alt_intent, changed_positions = build_alternative_playlist(candidates, intent)

    alt_out: list[PlaylistTrack] = []
    for i, (track, score, contribs, ts) in enumerate(alt_items):
        shap_vals = compute_shap(track, contribs, candidates, alt_intent)
        why_song, why_position = explain_shap(track.title, shap_vals, i + 1, len(alt_items))
        alt_out.append(
            PlaylistTrack(
                track={
                    "id": track.id,
                    "title": track.title,
                    "artist": track.artist,
                    "duration_seconds": track.duration_seconds,
                    "energy": track.energy,
                    "bpm": track.bpm,
                    "genre": track.genre,
                    "moods": track.moods,
                },
                score=score,
                why_song=why_song,
                why_position=why_position,
                shap_values=shap_vals,
            )
        )

    counterfactual_explanation = explain_counterfactual(
        intent.ending, alt_intent.ending, changed_positions
    )

    # ── Step 8: Knowledge graph ───────────────────────────────────────────────
    graph = build_graph(
        playlist_items=playlist_items,
        transition_explanations=transition_explanations,
        similar_fetch_fn=fetch_similar_tracks,
    )

    return PlaylistResponse(
        playlist=playlist_out,
        alternative_playlist=alt_out,
        graph=graph,
        intent=intent,
        counterfactual_explanation=counterfactual_explanation,
    )


@app.get("/health")
async def health() -> dict:
    """Liveness check."""
    return {"status": "ok"}
