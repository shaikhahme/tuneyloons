"""
Knowledge graph construction.

Returns a graph JSON compatible with React Flow and Cytoscape.js.

Structure:
  Nodes: playlist tracks (type="playlist") + related tracks (type="related")
  Edges:
    - playlist_order: sequential edges between playlist tracks (with transition data)
    - related: edges from each playlist track to 1-5 similar tracks
"""

from schemas import TrackModels, GraphNode, GraphEdge, KnowledgeGraph
from playlist import score_transition


def _make_playlist_node(track: TrackModels, position: int) -> GraphNode:
    return GraphNode(
        id=track.id,
        label=f"{position}. {track.title}",
        artist=track.artist,
        type="playlist",
        energy=track.energy,
        genre=track.genre,
    )


def _make_related_node(track: TrackModels) -> GraphNode:
    return GraphNode(
        id=track.id,
        label=track.title,
        artist=track.artist,
        type="related",
        energy=track.energy,
        genre=track.genre,
    )


def _make_transition_edge(
    a: TrackModels,
    b: TrackModels,
    transition_score: float,
    transition_explanation: str,
) -> GraphEdge:
    return GraphEdge(
        source=a.id,
        target=b.id,
        type="playlist_order",
        transition_score=transition_score,
        transition_explanation=transition_explanation,
    )


def _make_related_edge(playlist_track_id: str, related_id: str) -> GraphEdge:
    return GraphEdge(
        source=playlist_track_id,
        target=related_id,
        type="related",
        transition_score=None,
        transition_explanation=None,
    )


def build_graph(
    playlist_items: list[tuple[TrackModels, float, dict, float]],
    transition_explanations: list[str],
    similar_fetch_fn,  # callable: (track_id: str) -> list[TrackModels]
) -> KnowledgeGraph:
    """
    Build the knowledge graph from a finalized playlist.

    Args:
        playlist_items:           Output of build_playlist() — list of
                                  (track, score, contribs, transition_score).
        transition_explanations:  LLM-generated explanation per inter-track edge
                                  (len = num_tracks - 1).
        similar_fetch_fn:         Function to fetch similar tracks for a given
                                  track ID (wraps cyanite.fetch_similar_tracks).

    Returns:
        KnowledgeGraph with nodes and edges ready for React Flow / Cytoscape.
    """
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    seen_ids: set[str] = set()

    tracks = [t for t, *_ in playlist_items]
    transition_scores = [ts for _, _, _, ts in playlist_items]

    # ── Playlist nodes ────────────────────────────────────────────────────────
    for i, track in enumerate(tracks):
        nodes.append(_make_playlist_node(track, i + 1))
        seen_ids.add(track.id)

    # ── Playlist order edges (with transition data) ───────────────────────────
    for i in range(len(tracks) - 1):
        a, b = tracks[i], tracks[i + 1]
        ts = transition_scores[i + 1]
        explanation = transition_explanations[i] if i < len(transition_explanations) else ""
        edges.append(_make_transition_edge(a, b, ts, explanation))

    # ── Related nodes and edges ───────────────────────────────────────────────
    for track in tracks:
        similar = similar_fetch_fn(track.id)
        for rel in similar:
            if rel.id not in seen_ids:
                nodes.append(_make_related_node(rel))
                seen_ids.add(rel.id)
            edges.append(_make_related_edge(track.id, rel.id))

    return KnowledgeGraph(nodes=nodes, edges=edges)
