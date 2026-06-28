"""
FastAPI entrypoint.

Endpoints:
  POST /generate_playlist         — standard JSON response (Swagger / testing)
  POST /generate_playlist/stream  — SSE stream with live progress + final result

LLM calls per request: 4 total (down from ~2N+2)
  1. extract_intent
  2. explain_shap_batch   (all main + alt tracks in one call)
  3. explain_transitions_batch
  4. explain_counterfactual
"""

import asyncio
import json
import os
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

load_dotenv()

from schemas import PlaylistRequest, PlaylistResponse, PlaylistTrack
from cyanite import search_tracks, fetch_similar_tracks, build_cyanite_filter
from llm import (
    extract_intent,
    explain_all,
    explain_shap_batch,
    explain_transitions_batch,
    explain_counterfactual,
)
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


# ── Shared CPU helpers ────────────────────────────────────────────────────────

def _build_playlists(candidates, intent):
    playlist_items = build_playlist(candidates, intent)
    original_tracks = [t for t, *_ in playlist_items]
    # Pass original_tracks to avoid a redundant second build_playlist call inside
    alt_items, alt_intent, changed_positions = build_alternative_playlist(
        candidates, intent, original_tracks=original_tracks
    )
    return playlist_items, alt_items, alt_intent, changed_positions


def _compute_all_shap(playlist_items, alt_items, candidates, intent, alt_intent):
    main_shap = [
        compute_shap(track, contribs, candidates, intent)
        for track, _, contribs, _ in playlist_items
    ]
    alt_shap = [
        compute_shap(track, contribs, candidates, alt_intent)
        for track, _, contribs, _ in alt_items
    ]
    return main_shap, alt_shap


def _make_track(track, score, shap_vals, why_song, why_position) -> PlaylistTrack:
    return PlaylistTrack(
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


# ── Core pipeline (shared by both endpoints) ──────────────────────────────────

async def _run(intent) -> PlaylistResponse:
    cyanite_filter = build_cyanite_filter(intent)
    candidates = await asyncio.to_thread(
        search_tracks, query=intent.query, metadata_filter=cyanite_filter, limit=50
    )
    if not candidates:
        raise ValueError("Cyanite returned no tracks.")

    playlist_items, alt_items, alt_intent, changed_positions = await asyncio.to_thread(
        _build_playlists, candidates, intent
    )

    tracks = [t for t, *_ in playlist_items]
    alt_tracks = [t for t, *_ in alt_items]
    n = len(playlist_items)

    main_shap, alt_shap = await asyncio.to_thread(
        _compute_all_shap, playlist_items, alt_items, candidates, intent, alt_intent
    )

    feat_deltas_list = [
        score_transition(tracks[i], tracks[i + 1])[1]
        for i in range(len(tracks) - 1)
    ]

    main_batch = [(t.title, sv, i + 1, n) for i, (t, sv) in enumerate(zip(tracks, main_shap))]
    alt_batch = [(t.title, sv, i + 1, len(alt_items)) for i, (t, sv) in enumerate(zip(alt_tracks, alt_shap))]
    trans_batch = [
        (tracks[i].title, tracks[i + 1].title, playlist_items[i + 1][3], feat_deltas_list[i])
        for i in range(len(tracks) - 1)
    ]

    # Single call for all explanations — 2 LLM calls total per request
    combined_expl, transition_explanations, counterfactual_explanation = await explain_all(
        main_batch + alt_batch,
        trans_batch,
        intent.ending,
        alt_intent.ending,
        changed_positions,
        tracks,
        alt_tracks,
    )
    main_expl = combined_expl[:len(main_batch)]
    alt_expl = combined_expl[len(main_batch):]

    playlist_out = [
        _make_track(track, score, main_shap[i], *main_expl[i])
        for i, (track, score, _, _) in enumerate(playlist_items)
    ]
    alt_out = [
        _make_track(track, score, alt_shap[i], *alt_expl[i])
        for i, (track, score, _, _) in enumerate(alt_items)
    ]

    graph = await asyncio.to_thread(
        build_graph,
        playlist_items=playlist_items,
        transition_explanations=list(transition_explanations),
        similar_fetch_fn=fetch_similar_tracks,
    )

    return PlaylistResponse(
        playlist=playlist_out,
        alternative_playlist=alt_out,
        graph=graph,
        intent=intent,
        counterfactual_explanation=counterfactual_explanation,
    )


# ── SSE helpers ───────────────────────────────────────────────────────────────

def _sse(event: str, data: str) -> str:
    return f"event: {event}\ndata: {data}\n\n"


def _prog(message: str) -> str:
    return _sse("progress", json.dumps({"message": message}))


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/generate_playlist/stream")
async def generate_playlist_stream(request: PlaylistRequest):
    """SSE stream — yields live progress events then a final 'result' event."""
    if not request.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty.")

    async def stream():
        try:
            # Step 1 — intent (1 LLM call)
            yield _prog("Extracting your vibe\u2026")
            intent = await extract_intent(request.prompt)

            # Step 2 — Cyanite search (I/O in thread)
            yield _prog(f'Searching the catalog for \u201c{intent.query}\u201d\u2026')
            cyanite_filter = build_cyanite_filter(intent)
            candidates = await asyncio.to_thread(
                search_tracks, query=intent.query, metadata_filter=cyanite_filter, limit=50
            )
            if not candidates:
                yield _sse("error", json.dumps({"message": "Cyanite returned no tracks."}))
                return

            # Step 3 — ranking (CPU in thread)
            yield _prog(f'Curating {intent.num_tracks} tracks for your set\u2026')
            playlist_items, alt_items, alt_intent, changed_positions = await asyncio.to_thread(
                _build_playlists, candidates, intent
            )
            tracks = [t for t, *_ in playlist_items]
            alt_tracks = [t for t, *_ in alt_items]
            n = len(playlist_items)

            # Step 4 — SHAP + 3 LLM calls in parallel
            yield _prog("Analysing features & writing explanations\u2026")
            main_shap, alt_shap = await asyncio.to_thread(
                _compute_all_shap, playlist_items, alt_items, candidates, intent, alt_intent
            )
            feat_deltas_list = [
                score_transition(tracks[i], tracks[i + 1])[1]
                for i in range(len(tracks) - 1)
            ]
            main_batch = [(t.title, sv, i + 1, n) for i, (t, sv) in enumerate(zip(tracks, main_shap))]
            alt_batch = [(t.title, sv, i + 1, len(alt_items)) for i, (t, sv) in enumerate(zip(alt_tracks, alt_shap))]
            trans_batch = [
                (tracks[i].title, tracks[i + 1].title, playlist_items[i + 1][3], feat_deltas_list[i])
                for i in range(len(tracks) - 1)
            ]
            # Single call for all explanations — 2 LLM calls total per request.
            # If rate limits are exhausted after all retries, fall back to
            # placeholder text so the user still gets their playlist.
            yield _prog("Writing explanations\u2026")
            try:
                combined_expl, transition_explanations, counterfactual_explanation = await explain_all(
                    main_batch + alt_batch,
                    trans_batch,
                    intent.ending,
                    alt_intent.ending,
                    changed_positions,
                    tracks,
                    alt_tracks,
                )
            except Exception:
                combined_expl = [
                    ("Selected for its strong match with your prompt.", "Placed here to support the energy arc.")
                    for _ in main_batch + alt_batch
                ]
                transition_explanations = ["Smooth energy flow between tracks." for _ in trans_batch]
                counterfactual_explanation = (
                    "Alternative playlist generated with a different energy arc — "
                    "explanations unavailable due to a temporary rate limit."
                )
            main_expl = combined_expl[:len(main_batch)]
            alt_expl = combined_expl[len(main_batch):]

            playlist_out = [
                _make_track(track, score, main_shap[i], *main_expl[i])
                for i, (track, score, _, _) in enumerate(playlist_items)
            ]
            alt_out = [
                _make_track(track, score, alt_shap[i], *alt_expl[i])
                for i, (track, score, _, _) in enumerate(alt_items)
            ]

            # Step 5 — knowledge graph (Cyanite I/O in thread)
            yield _prog("Mapping connections in the knowledge graph\u2026")
            graph = await asyncio.to_thread(
                build_graph,
                playlist_items=playlist_items,
                transition_explanations=list(transition_explanations),
                similar_fetch_fn=fetch_similar_tracks,
            )

            result = PlaylistResponse(
                playlist=playlist_out,
                alternative_playlist=alt_out,
                graph=graph,
                intent=intent,
                counterfactual_explanation=counterfactual_explanation,
            )
            yield _sse("result", result.model_dump_json())

        except Exception as exc:
            yield _sse("error", json.dumps({"message": str(exc)}))

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/generate_playlist", response_model=PlaylistResponse)
async def generate_playlist(request: PlaylistRequest) -> PlaylistResponse:
    """Standard JSON endpoint — for Swagger UI / direct testing."""
    if not request.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty.")
    try:
        intent = await extract_intent(request.prompt)
        return await _run(intent)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
