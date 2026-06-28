# Tuneyloons — Explainable AI DJ Setlist Generator

> *Why this song? Why here? What would change if you wanted something different?*

Tuneyloons answers those questions. It is an AI DJ that not only builds a setlist from a natural-language prompt but **explains every decision** — and then shows you an alternative setlist to prove it.

---

## The Idea

Most music recommendation systems are black boxes. They return a playlist but cannot tell you *why* Track 3 is Track 3, or what would have happened if you had asked for something more energetic. Tuneyloons is built around the opposite philosophy: **every recommendation comes with a reason, and every reason is falsifiable**.

You type a prompt like `"girly pop for a 10 min drive"` and get back:

- A scored, ordered setlist with per-track explanations
- A knowledge graph showing how tracks relate to each other
- A counterfactual alternative setlist — what would have been different if the energy arc were reversed
- A plain-English explanation of *why* the two setlists diverge

---

## Explainability Stack

Tuneyloons uses three complementary explainability techniques layered on top of a deterministic scoring function.

### 1. SHAP — Feature Attribution per Track

Every track is scored using a weighted formula across six features:

| Feature | Weight | What it measures |
|---|---|---|
| Prompt similarity | 35% | TF-IDF cosine match between your query and the track's description/genre/moods |
| Mood match | 20% | Alignment between track moods and the intended energy arc (`bang` / `calm`) |
| Energy match | 20% | How close the track's energy is to the target at its position in the arc |
| Tempo match | 10% | Compatibility with the requested tempo |
| Transition score | 10% | Smoothness of the handoff from the previous track |
| Cyanite score | 5% | Semantic similarity score from the Cyanite music AI catalog |

Because the scoring function is deterministic (not a trained model), we fit a **GradientBoosting surrogate** on all 50 candidate tracks per request and run SHAP on it. This gives us a truthful, per-track decomposition of *why this track beat the others* — surfaced in the UI as `why_song` and `why_position` strings.

### 2. Transition Explanations — DJ Perspective

Between every consecutive track pair, a transition score is computed from six audio feature deltas (energy, tempo, mood overlap, character overlap, genre match, movement match). An LLM then converts these numeric deltas into a one-sentence DJ-style explanation:

> *"The drop in energy from Track 2 to Track 3 gives the listener a breather before the final push."*

### 3. Counterfactual Explanation — The Core Differentiator

This is where Tuneyloons goes beyond standard recommendation explainability.

**The idea:** if you change one thing about the objective — say, flip the energy arc from *high-energy finale* (`bang`) to *gentle close* (`calm`) — which tracks swap out, and why?

The pipeline:
1. Build the main setlist with the original intent
2. Perturb the intent: flip the ending style, shift the query toward opposite-energy keywords
3. Re-run the same deterministic scoring algorithm on a pool that excludes the main tracks
4. Compare the two playlists position-by-position
5. Feed the actual track-level diffs (energy, moods) to an LLM to produce a concrete explanation

The result is a side-by-side view — *Recommended* vs *Alternative* — with a banner explaining the causal difference:

> *"Positions 2, 4, and 5 swapped because the calm arc targets energy ≤ 0.4 at the close, selecting tracks with mellow, dreamy moods over the energetic, uplifting ones chosen for the bang ending."*

This is **LIME-style counterfactual reasoning**: perturb the input, observe what changes, explain the delta.

---

## Architecture

```
User prompt
    │
    ▼
┌─────────────────────────────────────────────────────────────────────┐
│ FastAPI backend                                                     │
│                                                                     │
│  1. Intent extraction (LLM)          → structured query + filters   │
│  2. Cyanite catalog search           → 50 candidate tracks          │
│  3. Greedy playlist selection        → scored, ordered setlist      │
│  4. SHAP attribution (GBR surrogate) → per-track feature scores     │
│  5. Counterfactual generation        → alternative setlist          │
│  6. Combined LLM explanation call    → all text in one request      │
│  7. Knowledge graph construction     → nodes + edges for 3D graph   │
└─────────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────────┐
│ React + Vite frontend                                               │
│                                                                     │
│  • Prompt page with mood/genre/tempo filter chips                   │
│  • 3D knowledge graph (react-force-graph-3d) with orbital focus     │
│  • Node hover: BPM · Key · Genre · Moods                           │
│  • Recommendation panel: Primary / Alternative tabs                 │
│  • Counterfactual banner explaining the diff                        │
└─────────────────────────────────────────────────────────────────────┘
```

### Key design decisions

- **LLM never picks tracks.** Claude is used only to extract intent and generate natural-language explanations. All track selection is deterministic and inspectable.
- **Surrogate model for SHAP.** Because the scoring function is not a neural network, a GBR is trained per request on the candidate pool so SHAP has a differentiable model to explain.
- **Single LLM call for all explanations.** SHAP explanations, transition explanations, and the counterfactual explanation are combined into one structured prompt, reducing API calls from 5 → 2 per request.
- **Counterfactual uses excluded tracks.** The alternative setlist is built from the tracks *not* selected for the main playlist, ensuring the comparison is always meaningful.

---

## Running Locally

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Create `backend/.env`:
```
ANTHROPIC_API_KEY=sk-ant-...
cyaniteApiKey=...
```

```bash
uvicorn app:app --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. The frontend proxies `/api/*` → `http://localhost:8000`.

### Tests

```bash
cd backend
pytest test_backend.py -v                          # all unit tests (mock APIs)
pytest test_backend.py::TestCyaniteRealAPI -v      # live Cyanite integration tests
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python · FastAPI · Anthropic SDK · scikit-learn · SHAP |
| Music catalog | Cyanite AI (semantic music search + audio feature models) |
| Frontend | React · Vite · react-force-graph-3d · three.js |
| Explainability | SHAP (GBR surrogate) · LIME-style counterfactuals · LLM narration |
