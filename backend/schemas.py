"""
Pydantic schemas for request/response and internal data models.
All models are simple dataclasses-style with no business logic.
"""

from typing import Any
from pydantic import BaseModel


# ── Request ──────────────────────────────────────────────────────────────────

class PlaylistRequest(BaseModel):
    prompt: str


# ── Cyanite internals ─────────────────────────────────────────────────────────

class TrackModels(BaseModel):
    """Feature vector extracted from Cyanite model outputs for one track."""
    id: str
    title: str
    artist: str
    duration_seconds: int

    # Cyanite model outputs
    genre: str
    moods: list[str]
    energy: float          # 0-1, derived from MoodSimpleV2 / CharacterV2
    valence: float         # 0-1, from ValenceArousalV2
    arousal: float         # 0-1, from ValenceArousalV2
    tempo_tag: str         # "slow" | "medium" | "fast"
    bpm: float
    movement: str          # e.g. "driving", "floating"
    character: list[str]   # e.g. ["aggressive", "dark"]
    description: str       # AutoDescriptionV2 free text
    cyanite_score: float   # similarity score from search (0-1)


# ── Intent extraction ─────────────────────────────────────────────────────────

class MetadataFilter(BaseModel):
    min_energy: float | None = None
    max_energy: float | None = None
    tempo_tag: str | None = None         # "slow" | "medium" | "fast"
    genres: list[str] | None = None


class ExtractedIntent(BaseModel):
    query: str
    duration_seconds: int
    ending: str                           # "bang" | "calm" | "neutral"
    num_tracks: int
    metadata_filter: MetadataFilter
    # Cyanite tag fields — used to build the metadataFilter for the search API
    mood_tags: list[str] = []             # MoodSimpleV2 tags e.g. ["calm", "energetic"]
    genre_tags: list[str] = []            # MainGenreV2 tags e.g. ["electronic", "pop"]
    min_bpm: int | None = None
    max_bpm: int | None = None


# ── Scoring internals ─────────────────────────────────────────────────────────

class TrackScore(BaseModel):
    track: TrackModels
    prompt_similarity: float
    mood_match: float
    energy_match: float
    tempo_match: float
    transition_score: float
    cyanite_score: float
    final_score: float
    shap_values: dict[str, float]
    why_song: str
    why_position: str


# ── Graph ─────────────────────────────────────────────────────────────────────

class GraphNode(BaseModel):
    id: str
    label: str
    artist: str
    type: str        # "playlist" | "related"
    energy: float
    genre: str


class GraphEdge(BaseModel):
    source: str
    target: str
    type: str        # "playlist_order" | "related"
    transition_score: float | None = None
    transition_explanation: str | None = None


class KnowledgeGraph(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


# ── API Response ──────────────────────────────────────────────────────────────

class PlaylistTrack(BaseModel):
    track: dict[str, Any]
    score: float
    why_song: str
    why_position: str
    shap_values: dict[str, float]


class PlaylistResponse(BaseModel):
    playlist: list[PlaylistTrack]
    alternative_playlist: list[PlaylistTrack]
    graph: KnowledgeGraph
    intent: ExtractedIntent
    counterfactual_explanation: str
