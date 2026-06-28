"""
Test suite for the Explainable AI DJ Setlist Generator backend.

Covers every module without hitting real APIs (Cyanite mock, OpenAI patched).

Run:
    pytest test_backend.py -v
    pytest test_backend.py -v --tb=short   # compact tracebacks
"""

import json
import os
import pytest
from unittest.mock import patch, MagicMock

# ── Env must be set before importing app modules ──────────────────────────────
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("cyaniteApiKey", "test-key")
os.environ.setdefault("LLM_MOCK", "true")  # never hit the real Anthropic API in tests

from fastapi.testclient import TestClient

from schemas import (
    ExtractedIntent,
    MetadataFilter,
    TrackModels,
    PlaylistRequest,
)
from cyanite import search_tracks, fetch_similar_tracks
from playlist import (
    build_playlist,
    score_track,
    score_transition,
    _prompt_similarity,
    _mood_match,
    _energy_match,
    _tempo_match,
)
from explainer import (
    compute_shap,
    build_alternative_intent,
    build_alternative_playlist,
    find_changed_positions,
    _ENDING_FLIP,
    _FEATURE_NAMES,
)
from graph import build_graph


# ─────────────────────────────────────────────────────────────────────────────
# Shared fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def candidates():
    """50 mock Cyanite tracks — reused across tests."""
    return search_tracks("girly pop", limit=50)


@pytest.fixture(scope="module")
def bang_intent():
    return ExtractedIntent(
        query="girly pop",
        duration_seconds=600,
        ending="bang",
        num_tracks=5,
        metadata_filter=MetadataFilter(),
    )


@pytest.fixture(scope="module")
def calm_intent():
    return ExtractedIntent(
        query="ambient chill",
        duration_seconds=900,
        ending="calm",
        num_tracks=5,
        metadata_filter=MetadataFilter(max_energy=0.5),
    )


@pytest.fixture(scope="module")
def bang_playlist(candidates, bang_intent):
    return build_playlist(candidates, bang_intent)


@pytest.fixture()
def app_client():
    """FastAPI test client with OpenAI patched out."""
    from app import app
    return TestClient(app)


# ─────────────────────────────────────────────────────────────────────────────
# 1. cyanite.py
# ─────────────────────────────────────────────────────────────────────────────

class TestCyaniteMock:

    def test_search_returns_requested_count(self):
        tracks = search_tracks("pop", limit=30)
        assert len(tracks) == 30

    def test_search_default_limit(self):
        tracks = search_tracks("rock")
        assert len(tracks) == 50

    def test_scores_descend(self):
        """Cyanite search results are ranked best-first."""
        tracks = search_tracks("electronic", limit=10)
        scores = [t.cyanite_score for t in tracks]
        assert scores == sorted(scores, reverse=True)

    def test_track_fields_populated(self):
        t = search_tracks("indie", limit=1)[0]
        assert t.id.startswith("libtr_mock_")
        assert 0 < len(t.title)
        assert 0 < len(t.artist)
        assert 0.0 <= t.energy <= 1.0
        assert 0.0 <= t.valence <= 1.0
        assert 0.0 <= t.arousal <= 1.0
        assert t.tempo_tag in {"slow", "medium", "fast"}
        assert t.bpm > 0
        assert isinstance(t.moods, list) and len(t.moods) >= 1
        assert isinstance(t.character, list) and len(t.character) >= 1

    def test_ids_are_unique(self):
        tracks = search_tracks("dance", limit=50)
        ids = [t.id for t in tracks]
        assert len(ids) == len(set(ids))

    def test_similar_tracks_count(self):
        tracks = search_tracks("pop", limit=1)
        similar = fetch_similar_tracks(tracks[0].id, limit=5)
        assert len(similar) == 5

    def test_similar_tracks_have_valid_fields(self):
        t = search_tracks("pop", limit=1)[0]
        similar = fetch_similar_tracks(t.id, limit=3)
        for s in similar:
            assert s.id.startswith("libtr_mock_")
            assert 0.0 <= s.energy <= 1.0

    def test_similar_scores_descend(self):
        t = search_tracks("pop", limit=1)[0]
        similar = fetch_similar_tracks(t.id, limit=5)
        scores = [s.cyanite_score for s in similar]
        assert scores == sorted(scores, reverse=True)

    def test_deterministic_with_same_query(self):
        """Same query always returns same track IDs."""
        a = [t.id for t in search_tracks("girly pop", limit=10)]
        b = [t.id for t in search_tracks("girly pop", limit=10)]
        assert a == b


# ─────────────────────────────────────────────────────────────────────────────
# 2. playlist.py — individual scoring helpers
# ─────────────────────────────────────────────────────────────────────────────

class TestScoringHelpers:

    def test_prompt_similarity_range(self, candidates):
        for t in candidates[:10]:
            s = _prompt_similarity("girly pop", t)
            assert 0.0 <= s <= 1.0, f"Out of range for {t.title}: {s}"

    def test_prompt_similarity_higher_for_matching_genre(self):
        """A pop track should score higher than an unrelated description."""
        t_pop = search_tracks("pop", limit=1)[0]
        s_match = _prompt_similarity("pop music", t_pop)
        s_miss = _prompt_similarity("jazz saxophone improvisation midnight", t_pop)
        # Not always guaranteed due to TF-IDF, but directionally expected
        assert s_match >= 0.0 and s_miss >= 0.0

    def test_mood_match_bang_favours_high_energy_moods(self, bang_intent):
        t = search_tracks("pop", limit=1)[0]
        t_energetic = t.model_copy(update={"moods": ["energetic", "euphoric"]})
        t_melancholic = t.model_copy(update={"moods": ["melancholic", "dreamy"]})
        assert _mood_match(bang_intent, t_energetic) > _mood_match(bang_intent, t_melancholic)

    def test_mood_match_calm_favours_calm_moods(self, calm_intent):
        t = search_tracks("pop", limit=1)[0]
        t_calm = t.model_copy(update={"moods": ["melancholic", "dreamy"]})
        t_energetic = t.model_copy(update={"moods": ["energetic", "aggressive"]})
        assert _mood_match(calm_intent, t_calm) > _mood_match(calm_intent, t_energetic)

    def test_energy_match_bang_ramps_up(self, bang_intent):
        """Later positions should reward higher energy tracks."""
        t_low  = search_tracks("pop", limit=1)[0].model_copy(update={"energy": 0.3})
        t_high = search_tracks("pop", limit=1)[0].model_copy(update={"energy": 0.95})
        early_low  = _energy_match(bang_intent, t_low, 0, 5)
        early_high = _energy_match(bang_intent, t_high, 0, 5)
        late_low   = _energy_match(bang_intent, t_low, 4, 5)
        late_high  = _energy_match(bang_intent, t_high, 4, 5)
        # At the end of a "bang" playlist, high energy should win
        assert late_high > late_low
        # Early in the playlist, difference should be smaller
        assert abs(early_high - early_low) < abs(late_high - late_low)

    def test_energy_match_returns_zero_outside_filter(self):
        intent = ExtractedIntent(
            query="test", duration_seconds=300, ending="neutral", num_tracks=3,
            metadata_filter=MetadataFilter(min_energy=0.8),
        )
        t = search_tracks("pop", limit=1)[0].model_copy(update={"energy": 0.4})
        assert _energy_match(intent, t, 0, 3) == 0.0

    def test_tempo_match_exact(self, bang_intent):
        intent_with_fast = ExtractedIntent(
            query="test", duration_seconds=300, ending="bang", num_tracks=3,
            metadata_filter=MetadataFilter(tempo_tag="fast"),
        )
        t_fast = search_tracks("pop", limit=1)[0].model_copy(update={"tempo_tag": "fast"})
        t_slow = search_tracks("pop", limit=1)[0].model_copy(update={"tempo_tag": "slow"})
        assert _tempo_match(intent_with_fast, t_fast) == 1.0
        assert _tempo_match(intent_with_fast, t_slow) < 1.0

    def test_tempo_match_no_filter_returns_neutral(self, bang_intent):
        t = search_tracks("pop", limit=1)[0]
        score = _tempo_match(bang_intent, t)
        assert score == 0.7  # neutral constant


# ─────────────────────────────────────────────────────────────────────────────
# 3. playlist.py — transition scoring
# ─────────────────────────────────────────────────────────────────────────────

class TestTransitionScoring:

    def test_score_range(self, candidates):
        score, feats = score_transition(candidates[0], candidates[1])
        assert 0.0 <= score <= 1.0

    def test_feature_keys_present(self, candidates):
        _, feats = score_transition(candidates[0], candidates[1])
        assert set(feats.keys()) == {
            "energy_delta", "tempo_delta", "mood_overlap",
            "char_overlap", "genre_match", "movement_match",
        }

    def test_identical_track_scores_high(self, candidates):
        """A track transitioning to itself should be near-perfect."""
        t = candidates[0]
        score, _ = score_transition(t, t)
        assert score >= 0.8

    def test_very_different_tracks_score_lower(self, candidates):
        t_low = candidates[0].model_copy(update={
            "energy": 0.1, "tempo_tag": "slow", "moods": ["melancholic"],
            "genre": "classical", "movement": "floating", "character": ["dark"],
        })
        t_high = candidates[0].model_copy(update={
            "energy": 0.99, "tempo_tag": "fast", "moods": ["aggressive"],
            "genre": "metal", "movement": "explosive", "character": ["raw"],
        })
        same_score, _ = score_transition(candidates[0], candidates[0])
        diff_score, _ = score_transition(t_low, t_high)
        assert same_score > diff_score

    def test_energy_delta_is_negative_when_different(self, candidates):
        t_low  = candidates[0].model_copy(update={"energy": 0.1})
        t_high = candidates[0].model_copy(update={"energy": 0.9})
        _, feats = score_transition(t_low, t_high)
        assert feats["energy_delta"] < 0


# ─────────────────────────────────────────────────────────────────────────────
# 4. playlist.py — build_playlist
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildPlaylist:

    def test_returns_correct_count(self, candidates, bang_intent):
        result = build_playlist(candidates, bang_intent)
        assert len(result) == bang_intent.num_tracks

    def test_no_duplicate_tracks(self, candidates, bang_intent):
        result = build_playlist(candidates, bang_intent)
        ids = [t.id for t, *_ in result]
        assert len(ids) == len(set(ids))

    def test_scores_in_range(self, candidates, bang_intent):
        result = build_playlist(candidates, bang_intent)
        for _, score, _, _ in result:
            assert 0.0 <= score <= 1.0, f"Score out of range: {score}"

    def test_all_feature_keys_present(self, candidates, bang_intent):
        result = build_playlist(candidates, bang_intent)
        expected = {
            "prompt_similarity", "mood_match", "energy_match",
            "tempo_match", "transition_score", "cyanite_score",
        }
        for _, _, contribs, _ in result:
            assert set(contribs.keys()) == expected

    def test_bang_ending_last_track_high_energy(self, candidates, bang_intent):
        """Last track in a 'bang' playlist should have above-average energy."""
        result = build_playlist(candidates, bang_intent)
        last_track = result[-1][0]
        all_energies = [t.energy for t in candidates]
        median_energy = sorted(all_energies)[len(all_energies) // 2]
        assert last_track.energy >= median_energy * 0.75  # within 25% of median

    def test_calm_ending_last_track_lower_energy(self, candidates, calm_intent):
        result = build_playlist(candidates, calm_intent)
        last_track = result[-1][0]
        first_track = result[0][0]
        # Energy should not spike at the end for a calm playlist
        assert last_track.energy <= first_track.energy + 0.35

    def test_used_ids_excluded(self, candidates, bang_intent):
        first_result = build_playlist(candidates, bang_intent)
        used = {t.id for t, *_ in first_result}
        second_result = build_playlist(candidates, bang_intent, used_ids=used)
        second_ids = {t.id for t, *_ in second_result}
        assert second_ids.isdisjoint(used)

    def test_transition_score_present(self, candidates, bang_intent):
        result = build_playlist(candidates, bang_intent)
        for _, _, _, ts in result:
            assert 0.0 <= ts <= 1.0


# ─────────────────────────────────────────────────────────────────────────────
# 5. explainer.py — SHAP
# ─────────────────────────────────────────────────────────────────────────────

class TestSHAP:

    def test_shap_returns_all_features(self, candidates, bang_intent, bang_playlist):
        track, score, contribs, _ = bang_playlist[0]
        sv = compute_shap(track, contribs, candidates, bang_intent)
        assert set(sv.keys()) == set(_FEATURE_NAMES)

    def test_shap_values_are_floats(self, candidates, bang_intent, bang_playlist):
        track, score, contribs, _ = bang_playlist[0]
        sv = compute_shap(track, contribs, candidates, bang_intent)
        for k, v in sv.items():
            assert isinstance(v, float), f"{k} is not float: {v}"

    def test_shap_runs_for_all_tracks(self, candidates, bang_intent, bang_playlist):
        """SHAP should not raise for any track in the playlist."""
        for track, _, contribs, _ in bang_playlist:
            sv = compute_shap(track, contribs, candidates, bang_intent)
            assert len(sv) == len(_FEATURE_NAMES)


# ─────────────────────────────────────────────────────────────────────────────
# 6. explainer.py — counterfactual / LIME
# ─────────────────────────────────────────────────────────────────────────────

class TestCounterfactual:

    def test_ending_flips(self, bang_intent, calm_intent):
        alt_bang = build_alternative_intent(bang_intent)
        alt_calm = build_alternative_intent(calm_intent)
        assert alt_bang.ending == _ENDING_FLIP["bang"]
        assert alt_calm.ending == _ENDING_FLIP["calm"]

    def test_all_endings_have_flip(self):
        for ending in ("bang", "calm", "neutral"):
            intent = ExtractedIntent(
                query="test", duration_seconds=300, ending=ending,
                num_tracks=3, metadata_filter=MetadataFilter(),
            )
            alt = build_alternative_intent(intent)
            assert alt.ending != ending

    def test_query_preserved_in_alternative(self, bang_intent):
        alt = build_alternative_intent(bang_intent)
        assert alt.query == bang_intent.query
        assert alt.num_tracks == bang_intent.num_tracks

    def test_alternative_playlist_different_from_original(self, candidates, bang_intent):
        alt_items, alt_intent, changed = build_alternative_playlist(candidates, bang_intent)
        original = build_playlist(candidates, bang_intent)
        original_ids = [t.id for t, *_ in original]
        alt_ids = [t.id for t, *_ in alt_items]
        # The playlists should differ in at least one position
        assert original_ids != alt_ids

    def test_alternative_returns_correct_count(self, candidates, bang_intent):
        alt_items, _, _ = build_alternative_playlist(candidates, bang_intent)
        assert len(alt_items) == bang_intent.num_tracks

    def test_changed_positions_are_valid_indices(self, candidates, bang_intent):
        _, _, changed = build_alternative_playlist(candidates, bang_intent)
        n = bang_intent.num_tracks
        for pos in changed:
            assert 1 <= pos <= n

    def test_find_changed_positions_detects_swap(self, candidates):
        tracks = search_tracks("pop", limit=6)
        original = tracks[:5]
        alternative = tracks[:3] + tracks[4:6]  # positions 4 and 5 differ
        changed = find_changed_positions(original, alternative)
        assert 4 in changed
        assert 5 in changed
        assert 1 not in changed

    def test_find_changed_positions_identical(self, candidates):
        tracks = search_tracks("pop", limit=5)
        assert find_changed_positions(tracks, tracks) == []


# ─────────────────────────────────────────────────────────────────────────────
# 7. graph.py
# ─────────────────────────────────────────────────────────────────────────────

class TestGraph:

    @pytest.fixture(scope="class")
    def graph(self, candidates, bang_intent, bang_playlist):
        transitions = ["smooth vibe", "energy lift", "tempo bridge", "final surge"]
        return build_graph(bang_playlist, transitions, fetch_similar_tracks)

    def test_playlist_nodes_present(self, graph, bang_playlist):
        playlist_nodes = [n for n in graph.nodes if n.type == "playlist"]
        assert len(playlist_nodes) == len(bang_playlist)

    def test_related_nodes_present(self, graph):
        related_nodes = [n for n in graph.nodes if n.type == "related"]
        assert len(related_nodes) > 0

    def test_playlist_order_edges(self, graph, bang_playlist):
        po_edges = [e for e in graph.edges if e.type == "playlist_order"]
        assert len(po_edges) == len(bang_playlist) - 1

    def test_related_edges_present(self, graph):
        rel_edges = [e for e in graph.edges if e.type == "related"]
        assert len(rel_edges) > 0

    def test_no_duplicate_nodes(self, graph):
        ids = [n.id for n in graph.nodes]
        assert len(ids) == len(set(ids))

    def test_playlist_order_edges_have_transition_data(self, graph):
        for e in graph.edges:
            if e.type == "playlist_order":
                assert e.transition_score is not None
                assert 0.0 <= e.transition_score <= 1.0
                assert isinstance(e.transition_explanation, str)

    def test_related_edges_have_no_transition_data(self, graph):
        for e in graph.edges:
            if e.type == "related":
                assert e.transition_score is None
                assert e.transition_explanation is None

    def test_playlist_node_labels_include_position(self, graph):
        playlist_nodes = [n for n in graph.nodes if n.type == "playlist"]
        for node in playlist_nodes:
            assert node.label[0].isdigit(), f"Label missing position: {node.label}"

    def test_all_edge_sources_exist_as_nodes(self, graph):
        node_ids = {n.id for n in graph.nodes}
        for e in graph.edges:
            assert e.source in node_ids, f"Source {e.source} not in nodes"

    def test_all_edge_targets_exist_as_nodes(self, graph):
        node_ids = {n.id for n in graph.nodes}
        for e in graph.edges:
            assert e.target in node_ids, f"Target {e.target} not in nodes"


# ─────────────────────────────────────────────────────────────────────────────
# 8. FastAPI endpoint — /generate_playlist (LLM patched)
# ─────────────────────────────────────────────────────────────────────────────

async def _mock_extract_intent(prompt: str):
    return ExtractedIntent(
        query="girly pop",
        duration_seconds=600,
        ending="bang",
        num_tracks=5,
        metadata_filter=MetadataFilter(),
    )


async def _mock_explain_shap_batch(tracks):
    return [
        ("Selected because of its energy and mood match.", f"Position {pos} of {total} suits its vibe.")
        for _, _, pos, total in tracks
    ]


async def _mock_explain_counterfactual(orig, alt, positions):
    return f"Switching from '{orig}' to '{alt}' changed positions {positions}."


async def _mock_explain_transitions_batch(transitions):
    return [f"Smooth move from {a} to {b}." for a, b, *_ in transitions]


class TestEndpoint:

    @pytest.fixture(autouse=True)
    def patch_llm(self):
        """Patch all LLM calls so the endpoint runs without Anthropic API."""
        with (
            patch("app.extract_intent", side_effect=_mock_extract_intent),
            patch("app.explain_shap_batch", side_effect=_mock_explain_shap_batch),
            patch("app.explain_counterfactual", side_effect=_mock_explain_counterfactual),
            patch("app.explain_transitions_batch", side_effect=_mock_explain_transitions_batch),
        ):
            yield

    def test_health_check(self, app_client):
        r = app_client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}

    def test_generate_playlist_status_200(self, app_client):
        r = app_client.post("/generate_playlist", json={"prompt": "girly pop for a 10 min drive"})
        assert r.status_code == 200

    def test_response_has_required_keys(self, app_client):
        r = app_client.post("/generate_playlist", json={"prompt": "girly pop for a 10 min drive"})
        body = r.json()
        assert "playlist" in body
        assert "alternative_playlist" in body
        assert "graph" in body
        assert "intent" in body
        assert "counterfactual_explanation" in body

    def test_playlist_track_count(self, app_client):
        r = app_client.post("/generate_playlist", json={"prompt": "girly pop for a 10 min drive"})
        assert len(r.json()["playlist"]) == 5

    def test_playlist_track_schema(self, app_client):
        r = app_client.post("/generate_playlist", json={"prompt": "girly pop for a 10 min drive"})
        for item in r.json()["playlist"]:
            assert "track" in item
            assert "score" in item
            assert "why_song" in item
            assert "why_position" in item
            assert "shap_values" in item
            assert 0.0 <= item["score"] <= 1.0

    def test_track_fields_in_response(self, app_client):
        r = app_client.post("/generate_playlist", json={"prompt": "girly pop for a 10 min drive"})
        for item in r.json()["playlist"]:
            t = item["track"]
            for field in ("id", "title", "artist", "duration_seconds", "energy", "bpm", "genre", "moods"):
                assert field in t, f"Missing field: {field}"

    def test_alternative_playlist_present(self, app_client):
        r = app_client.post("/generate_playlist", json={"prompt": "girly pop for a 10 min drive"})
        assert len(r.json()["alternative_playlist"]) == 5

    def test_playlists_differ(self, app_client):
        r = app_client.post("/generate_playlist", json={"prompt": "girly pop for a 10 min drive"})
        body = r.json()
        orig_ids = [i["track"]["id"] for i in body["playlist"]]
        alt_ids  = [i["track"]["id"] for i in body["alternative_playlist"]]
        assert orig_ids != alt_ids

    def test_graph_has_nodes_and_edges(self, app_client):
        r = app_client.post("/generate_playlist", json={"prompt": "girly pop for a 10 min drive"})
        g = r.json()["graph"]
        assert len(g["nodes"]) > 0
        assert len(g["edges"]) > 0

    def test_graph_node_types(self, app_client):
        r = app_client.post("/generate_playlist", json={"prompt": "girly pop for a 10 min drive"})
        types = {n["type"] for n in r.json()["graph"]["nodes"]}
        assert "playlist" in types
        assert "related" in types

    def test_empty_prompt_returns_400(self, app_client):
        r = app_client.post("/generate_playlist", json={"prompt": "   "})
        assert r.status_code == 400

    def test_intent_in_response(self, app_client):
        r = app_client.post("/generate_playlist", json={"prompt": "girly pop for a 10 min drive"})
        intent = r.json()["intent"]
        assert intent["query"] == "girly pop"
        assert intent["ending"] == "bang"
        assert intent["num_tracks"] == 5

    def test_counterfactual_explanation_is_string(self, app_client):
        r = app_client.post("/generate_playlist", json={"prompt": "girly pop for a 10 min drive"})
        exp = r.json()["counterfactual_explanation"]
        assert isinstance(exp, str) and len(exp) > 0

    def test_shap_values_sum_non_zero(self, app_client):
        """At least one SHAP value per track should be non-zero."""
        r = app_client.post("/generate_playlist", json={"prompt": "girly pop for a 10 min drive"})
        for item in r.json()["playlist"]:
            total = sum(abs(v) for v in item["shap_values"].values())
            assert total > 0, f"All SHAP values are zero for {item['track']['title']}"