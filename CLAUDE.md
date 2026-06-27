# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Tuneyloons** is an explainable AI DJ setlist generator. Given a natural-language prompt (e.g., "girly pop playlist for a 10 min drive"), it returns an ordered playlist with per-track explanations, a counterfactual alternative playlist, and a knowledge graph — all via a single FastAPI endpoint.

## Setup & Running

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create `backend/.env` with:
```
OPENAI_API_KEY=sk-...
```

Start the server:
```bash
cd backend
uvicorn app:main --reload
```

The API is available at `http://localhost:8000`. Interactive docs at `/docs`.

## Architecture

Everything lives in `backend/`. There is no frontend in this repo yet (the graph output is designed for React Flow / Cytoscape.js).

### Request Pipeline (`app.py`)

`POST /generate_playlist` runs a sequential 9-step pipeline:

1. **Intent extraction** (`llm.extract_intent`) — GPT-4o-mini converts the prompt into a structured `ExtractedIntent` (query string, duration, num_tracks, ending style, metadata filters).
2. **Cyanite candidate search** (`cyanite.search_tracks`) — Fetches 50 candidate tracks. **Currently fully mocked** — replace function bodies in `cyanite.py` with real HTTP calls to go live.
3. **Greedy playlist selection** (`playlist.build_playlist`) — Picks tracks position by position using a weighted scoring formula. No ML training involved.
4. **SHAP attribution** (`explainer.compute_shap`) — Trains a GBR surrogate on all candidates, then computes SHAP values for each selected track to explain feature contributions.
5. **Per-track LLM explanations** (`llm.explain_shap`) — Converts SHAP values into `why_song` and `why_position` strings.
6. **Transition explanations** (`llm.explain_transition`) — One sentence per consecutive track pair, from a DJ perspective.
7. **LIME counterfactual** (`explainer.build_alternative_playlist`) — Flips the ending style (bang↔calm) and inverts energy constraints, then rebuilds a second playlist to show what would have changed.
8. **Counterfactual LLM explanation** (`llm.explain_counterfactual`) — Explains the diff between original and alternative.
9. **Knowledge graph** (`graph.build_graph`) — Nodes are playlist tracks + related tracks (via `cyanite.fetch_similar_tracks`); edges are `playlist_order` (with transition data) and `related`.

### Module Responsibilities

| File | Role |
|------|------|
| `schemas.py` | All Pydantic models. Pure data — no logic. |
| `cyanite.py` | Cyanite API client. **Mocked.** Real signatures in place; swap function bodies to go live. |
| `llm.py` | OpenAI calls. Intent extraction + 3 explanation generators. LLM never picks tracks — only explains. |
| `playlist.py` | Deterministic scoring. Weights at top of file (must sum to 1.0). Scoring features: prompt_similarity (TF-IDF cosine), mood_match, energy_match (position-aware arc), tempo_match, transition_score, cyanite_score. |
| `explainer.py` | SHAP (GBR surrogate per request) + LIME counterfactual via intent perturbation. |
| `graph.py` | Assembles `KnowledgeGraph` (nodes + edges) compatible with React Flow / Cytoscape.js. |

### Key Design Decisions

- **Scoring is position-aware**: `energy_match` in `playlist.py` targets a different energy level depending on position in the arc and the `ending` style (`bang` ramps up, `calm` ramps down).
- **SHAP uses a surrogate**: Since the scoring function is deterministic (not an ML model), a GBR is trained on all 50 candidates per request to give SHAP something to explain.
- **Cyanite mock is query-deterministic**: `search_tracks()` seeds randomness from the query string, so the same query always returns the same tracks across calls.
- **LLM model**: `claude-haiku-4-5-20251001` throughout (cheap and fast; set in `llm.py:_MODEL`).

## Environment Variables

| Variable | Required | Source |
|----------|----------|--------|
| `ANTHROPIC_API_KEY` | Yes | Anthropic console |
| `cyaniteApiKey` | No (mocked) | Cyanite dashboard — for production use |
| `cyaniteClientId` | No (mocked) | Cyanite dashboard — for production use |

## Going to Production

The three functions in `cyanite.py` have real Cyanite API signatures documented in their docstrings. Replace their bodies with HTTP calls using `requests` and the keys from `.env` to connect to the real Cyanite catalog.
