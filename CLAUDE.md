# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Tuneyloons** is an explainable AI DJ setlist generator. Given a natural-language prompt (e.g., "girly pop playlist for a 10 min drive"), it returns an ordered playlist with per-track explanations, a counterfactual alternative playlist, and a knowledge graph — all via a single FastAPI endpoint.

## Setup & Running

### Backend
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create `backend/.env` with:
```
ANTHROPIC_API_KEY=sk-ant-...
```

Start the server:
```bash
cd backend
uvicorn app:app --reload
```

The API is available at `http://localhost:8000`. Interactive docs at `/docs`.

### Frontend
```bash
cd frontend
npm install
npm run dev
```

The dev server runs at `http://localhost:5173`. It proxies `/api/*` → `http://localhost:8000/*`, so both services must be running for full functionality.

## Architecture

The repo has two top-level directories: `backend/` (FastAPI) and `frontend/` (React/Vite).

### Request Pipeline (`app.py`)

`POST /generate_playlist` runs a sequential 9-step pipeline:

1. **Intent extraction** (`llm.extract_intent`) — `claude-haiku-4-5` converts the prompt into a structured `ExtractedIntent` (query string, duration, num_tracks, ending style, metadata filters).
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
| `llm.py` | Anthropic Claude calls. Intent extraction + 3 explanation generators. LLM never picks tracks — only explains. |
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

## Frontend Architecture (`frontend/`)

React + Vite SPA with two routes (`/` and `/graph`).

### Data flow
1. User types a prompt on `/` and optionally selects filter chips (mood/genre/tempo/vocals)
2. On submit, chips are concatenated into the prompt string (e.g. `"...prompt [Mood: dreamy; Genre: electronic]"`) and stored in `sessionStorage`
3. `/graph` calls `src/api/setlistApi.js → generateSetList()` which POSTs to `/api/generate_playlist` (proxied to `:8000`)
4. The raw backend response is mapped in `setlistApi.js` into the frontend shape before being stored in state

### Backend → Frontend response mapping (in `src/api/setlistApi.js`)

| Backend field | Frontend field | Notes |
|---|---|---|
| `playlist[].track.{id,title,artist,moods,genre}` + `score` | `recommendations[]` | `score` → `confidence` |
| `alternative_playlist` | `alternativeRecommendations[]` | same shape as above |
| `graph.nodes[].label` | `graph.nodes[].title` | strips position prefix ("1. Song") |
| `graph.edges[].transition_score` | `graph.edges[].strength` | |
| `graph.edges[].transition_explanation` | `graph.edges[].label` | |
| `counterfactual_explanation` | `counterfactualExplanation` | shown in Alternative tab banner |

### Key frontend files

| File | Role |
|---|---|
| `src/api/setlistApi.js` | Only place that knows about the backend API shape. Swap real URL in here. |
| `src/pages/PromptPage.jsx` | Page 1 — prompt textarea + filter chips |
| `src/pages/GraphPage.jsx` | Page 2 — 3D graph + tab state (primary/alternative) |
| `src/components/ThreeDKnowledgeGraph.jsx` | Lazy-loads `react-force-graph-3d`; expects `{ nodes, edges }` (converts to `links` internally) |
| `src/components/RecommendationPanel.jsx` | Right-side panel with Recommended/Alternative tabs |
| `src/styles/aquarium.css` | All visual styles — no complex inline styles in JSX |

### CSS constraint
All gradients, box-shadows, font stacks, and animations live in `aquarium.css` only. JSX `style` props may only carry simple single-value properties (e.g. `style={{ width: '80%' }}`).

## Going to Production

The three functions in `cyanite.py` have real Cyanite API signatures documented in their docstrings. Replace their bodies with HTTP calls using `requests` and the keys from `.env` to connect to the real Cyanite catalog.
