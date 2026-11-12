"""Tests for normalization, matching, import, edge rebuilding and ranking."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import graph as graph_mod
from backend.app.db import connect, init_db
from backend.app.importer import import_papers_csv, import_references_jsonl
from backend.app.matching import PaperLite, title_candidates
from backend.app.normalize import normalize_doi, normalize_title

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


@pytest.fixture()
def db(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setenv("CITATION_DB", str(path))
    init_db(path)
    return path


@pytest.fixture()
def seeded(db):
    with connect(db) as conn:
        import_papers_csv(conn, (SAMPLES / "papers.csv").read_text(encoding="utf-8"), "papers.csv")
        import_references_jsonl(
            conn, (SAMPLES / "references.jsonl").read_text(encoding="utf-8"), "references.jsonl"
        )
        graph_mod.rebuild_edges(conn)
    return db


@pytest.fixture()
def client(db):
    from backend.app.main import app

    return TestClient(app)


# --- normalization -------------------------------------------------------

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("https://doi.org/10.1000/ABC", "10.1000/abc"),
        ("http://dx.doi.org/10.1000/ABC", "10.1000/abc"),
        ("doi: 10.1000/ABC ", "10.1000/abc"),
        ("DOI:10.1000/ABC", "10.1000/abc"),
        ("  10.1000/ABC  ", "10.1000/abc"),
        ("HTTPS://DOI.ORG/10.1000/ABC", "10.1000/abc"),
        (None, None),
        ("   ", None),
    ],
)
def test_normalize_doi(raw, expected):
    assert normalize_doi(raw) == expected


def test_normalize_title_collapses_punctuation():
    assert normalize_title("Graph Neural Networks: A Survey!") == "graph neural networks a survey"
    assert normalize_title("  Graph   Neural  Networks ") == "graph neural networks"


def test_normalize_title_handles_cjk_spacing():
    assert normalize_title("图 神经 网络：综述") == "图神经网络综述"
    assert normalize_title("引文图谱") == "引文图谱"


def test_split_list_trims_items():
    from backend.app.normalize import split_list

    assert split_list("Alice Chen; Bob Liu") == ["Alice Chen", "Bob Liu"]
    assert split_list(" Alice Chen ;  Bob Liu ;Alice Chen ") == ["Alice Chen", "Bob Liu"]
    assert split_list([" Alice Chen ", "Bob Liu"]) == ["Alice Chen", "Bob Liu"]


# --- matching ------------------------------------------------------------

def test_title_candidates_offer_duplicate_titles():
    papers = [
        PaperLite("P1", "Graph Neural Networks for Citation Analysis", 2018, ["Alice Chen"], "10.1/a", []),
        PaperLite("P2", "Graph Neural Networks for Citation Analysis", 2021, ["Bob Liu"], "10.1/b", []),
        PaperLite("P3", "Unrelated Paper", 2019, [], "10.1/c", []),
    ]
    cands = title_candidates(papers, "Graph Neural Networks for Citation Analysis", 2018, ["Alice Chen"])
    assert [c.paper_id for c in cands] == ["P1", "P2"]
    assert cands[0].score > cands[1].score
    assert any("年份一致" in r for r in cands[0].reasons)


def test_title_candidates_never_auto_link_low_similarity():
    papers = [PaperLite("P1", "Quantum Mechanics", 1990, [], None, [])]
    assert title_candidates(papers, "Totally different title", 2020) == []


# --- import --------------------------------------------------------------

def test_doi_only_unique_match_resolves(db):
    csv_text = (
        "id,title,year,authors,doi,topics\n"
        "P1,Paper One,2018,A,https://doi.org/10.1000/ONE,graphs\n"
        "P2,Paper Two,2019,B,10.1000/two,graphs\n"
    )
    jsonl = "\n".join(
        [
            json.dumps({"source_paper_id": "P1", "title": "Paper Two", "doi": " DOI:10.1000/TWO ", "year": 2019}),
            json.dumps({"source_paper_id": "P2", "title": "Paper One", "doi": "10.1000/one", "year": 2018}),
            json.dumps({"source_paper_id": "P2", "title": "Paper Zeta", "doi": None, "year": 2000}),
        ]
    )
    with connect(db) as conn:
        stats = import_papers_csv(conn, csv_text, "p.csv")
        refs = import_references_jsonl(conn, jsonl, "r.jsonl")
        rebuilt = graph_mod.rebuild_edges(conn)
    assert stats.papers_added == 2
    assert refs.doi_matched == 2
    assert refs.pending == 1
    assert rebuilt["edges"] == 2


def test_doi_ambiguity_is_never_auto_resolved(db):
    csv_text = (
        "id,title,year,authors,doi,topics\n"
        "P1,Same Title,2018,A,10.1000/dup,graphs\n"
        "P2,Same Title,2021,B,10.1000/DUP,graphs\n"
    )
    jsonl = json.dumps({"source_paper_id": "P2", "title": "Same Title", "doi": "https://doi.org/10.1000/dup"})
    with connect(db) as conn:
        import_papers_csv(conn, csv_text, "p.csv")
        stats = import_references_jsonl(conn, jsonl + "\n", "r.jsonl")
        rebuilt = graph_mod.rebuild_edges(conn)
        row = conn.execute("SELECT status, match_type FROM reference_records").fetchone()
    assert stats.doi_ambiguous == 1
    assert row["status"] == "pending" and row["match_type"] == "none"
    assert rebuilt["edges"] == 0


def test_reimport_is_idempotent(seeded):
    papers_csv = (SAMPLES / "papers.csv").read_text(encoding="utf-8")
    refs = (SAMPLES / "references.jsonl").read_text(encoding="utf-8")
    with connect(seeded) as conn:
        before = conn.execute("SELECT COUNT(*) FROM reference_records").fetchone()[0]
        stats = import_papers_csv(conn, papers_csv, "papers.csv")
        refs_stats = import_references_jsonl(conn, refs, "references.jsonl")
        after = conn.execute("SELECT COUNT(*) FROM reference_records").fetchone()[0]
    assert stats.papers_updated == 10
    assert refs_stats.references_added == 0
    assert refs_stats.references_duplicate == 34
    assert after == before


def test_repeated_citation_is_one_edge_with_occurrences(seeded):
    with connect(seeded) as conn:
        row = conn.execute(
            "SELECT occurrence_count FROM edges WHERE source_paper_id='P001' AND target_paper_id='P002'"
        ).fetchone()
        refs = conn.execute(
            """
            SELECT line_no, occurrence_index FROM reference_records
            WHERE source_paper_id='P001' AND matched_paper_id='P002'
            ORDER BY line_no
            """
        ).fetchall()
    assert row["occurrence_count"] == 2
    assert [r["occurrence_index"] for r in refs] == [1, 2]
    assert [r["line_no"] for r in refs] == [6, 7]


def test_doi_variants_collapse_to_same_target(seeded):
    """Same work cited with `DOI:` prefix, uppercase, and URL forms -> one edge."""
    with connect(seeded) as conn:
        edges = conn.execute(
            """
            SELECT source_paper_id, target_paper_id, occurrence_count FROM edges
            WHERE target_paper_id = 'P003' ORDER BY source_paper_id
            """
        ).fetchall()
    assert [e["source_paper_id"] for e in edges] == ["P002", "P005", "P007", "P009"]
    assert all(e["occurrence_count"] == 1 for e in edges)


# --- edge rebuild --------------------------------------------------------

def test_manual_link_unlink_recomputes_edges(seeded):
    with connect(seeded) as conn:
        before = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        pending = conn.execute(
            "SELECT id FROM reference_records WHERE status='pending' ORDER BY id LIMIT 1"
        ).fetchone()
        raw_before = conn.execute(
            "SELECT raw_json FROM reference_records WHERE id=?", (pending["id"],)
        ).fetchone()["raw_json"]
        conn.execute(
            """
            UPDATE reference_records SET status='resolved', match_type='manual',
            matched_paper_id='P003', updated_at='x' WHERE id=?
            """,
            (pending["id"],),
        )
        after_link = graph_mod.rebuild_edges(conn)["edges"]
        assert after_link == before + 1
        assert conn.execute("SELECT COUNT(*) FROM edges WHERE target_paper_id='P003'").fetchone()[0] >= 2

        # revocation: record returns to pending, edge disappears again
        conn.execute(
            """
            UPDATE reference_records SET status='pending', match_type='none',
            matched_paper_id=NULL, edge_id=NULL WHERE id=?
            """,
            (pending["id"],),
        )
        after_unlink = graph_mod.rebuild_edges(conn)["edges"]
        assert after_unlink == before
        # original reference payload is preserved
        assert conn.execute(
            "SELECT raw_json FROM reference_records WHERE id=?", (pending["id"],)
        ).fetchone()["raw_json"] == raw_before


def test_wiping_all_links_leaves_reference_records(seeded):
    with connect(seeded) as conn:
        conn.execute(
            "UPDATE reference_records SET status='pending', matched_paper_id=NULL, match_type='none', edge_id=NULL"
        )
        result = graph_mod.rebuild_edges(conn)
        refs = conn.execute("SELECT COUNT(*) FROM reference_records").fetchone()[0]
    assert result["edges"] == 0
    assert refs == 34


# --- anomalies -----------------------------------------------------------

def test_future_year_flagged(seeded):
    with connect(seeded) as conn:
        rows = conn.execute("SELECT source_paper_id, target_paper_id, anomalies FROM edges").fetchall()
        papers = {r["id"]: r["year"] for r in conn.execute("SELECT id, year FROM papers")}
    future = [r for r in rows if json.loads(r["anomalies"]) and "future_year" in json.loads(r["anomalies"])]
    assert future, "sample must contain at least one future-year citation"
    for row in future:
        assert papers[row["target_paper_id"]] > papers[row["source_paper_id"]]


def test_anomalies_excluded_by_default_and_opt_in(seeded):
    with connect(seeded) as conn:
        filters = graph_mod.normalize_filters({})
        graph, meta = graph_mod.build_graph(conn, filters)
        assert meta["anomaly_excluded"] == 9
        assert not any(graph.edges[u, v]["anomalies"] for u, v in graph.edges)

        filters2 = graph_mod.normalize_filters({"include_anomalies": ["future_year", "self_citation"]})
        graph2, meta2 = graph_mod.build_graph(conn, filters2)
        assert meta2["anomaly_excluded"] == 0
        assert any(graph2.edges[u, v]["anomalies"] for u, v in graph2.edges)

        filters3 = graph_mod.normalize_filters({"exclude_anomalies": ["self_citation"]})
        graph3, _ = graph_mod.build_graph(conn, filters3)
        assert not any(graph3.edges[u, v]["anomalies"] for u, v in graph3.edges)


# --- ranking -------------------------------------------------------------

def test_pagerank_converges_and_sums_to_one(seeded):
    with connect(seeded) as conn:
        filters = graph_mod.normalize_filters({})
        graph, _ = graph_mod.build_graph(conn, filters)
        ranking = graph_mod.compute_ranking(graph, filters)
    assert ranking["converged"] is True
    assert ranking["threshold"] == filters.tol
    total = sum(node["pagerank"] for node in ranking["nodes"])
    assert abs(total - 1.0) < 1e-9
    # edges are pointing from citer to cited
    assert ranking["edges"]


def test_pagerank_reports_nonconvergence(db):
    import networkx as nx

    graph = nx.DiGraph()
    graph.add_nodes_from(["a", "b", "c"])
    graph.add_edge("a", "b")
    graph.add_edge("b", "c")
    filters = graph_mod.normalize_filters({"alpha": 0.999999, "tol": 1e-14, "max_iter": 10})
    result = graph_mod.compute_ranking(graph, filters)
    assert result["converged"] is False
    assert result["iterations"] == 10
    assert result["threshold"] == 1e-14


def test_dangling_probability_is_shared_uniformly(db):
    """A dangling node's mass is spread over every node, not only its neighbours.

    Checked against NetworkX's `google_matrix` stationary vector, which applies
    uniform dangling redistribution plus a uniform teleport.
    """
    import networkx as nx
    import numpy as np

    graph = nx.DiGraph()
    graph.add_edges_from([("a", "b"), ("b", "a")])
    graph.add_node("c")  # dangling, no out-edge
    graph.add_node("d")  # dangling
    filters = graph_mod.normalize_filters({"alpha": 0.85, "tol": 1e-14, "max_iter": 1000})
    result = graph_mod.compute_ranking(graph, filters)

    # Stationary distribution of the Google matrix: pi = pi * M
    matrix = np.asarray(nx.google_matrix(graph, alpha=0.85))
    eigvals, eigvecs = np.linalg.eig(matrix.T)
    stationary = np.real(eigvecs[:, np.argmax(eigvals)])
    stationary = stationary / stationary.sum()
    nodes = list(graph.nodes)
    ref = dict(zip(nodes, stationary))
    for node in nodes:
        got = next(n["pagerank"] for n in result["nodes"] if n["id"] == node)
        assert abs(got - ref[node]) < 1e-9
    # both dangling nodes receive positive, equal mass (uniform redistribution)
    pr_c = next(n["pagerank"] for n in result["nodes"] if n["id"] == "c")
    pr_d = next(n["pagerank"] for n in result["nodes"] if n["id"] == "d")
    assert pr_c > 0
    assert abs(pr_c - pr_d) < 1e-12


def test_isolated_nodes_included(db):
    with connect(db) as conn:
        conn.execute(
            "INSERT INTO papers (id,title,year,authors,venue,doi_raw,doi_norm,topics,created_at) "
            "VALUES ('S1','Lonely Paper',2020,'[]',NULL,NULL,NULL,'[]','x')"
        )
        filters = graph_mod.normalize_filters({})
        graph, _ = graph_mod.build_graph(conn, filters)
        ranking = graph_mod.compute_ranking(graph, filters)
    node = next(n for n in ranking["nodes"] if n["id"] == "S1")
    assert node["isolated"] is True
    assert node["in_degree"] == node["out_degree"] == 0
    assert node["pagerank"] > 0


def test_empty_graph(db):
    with connect(db) as conn:
        filters = graph_mod.normalize_filters({})
        graph, meta = graph_mod.build_graph(conn, filters)
        ranking = graph_mod.compute_ranking(graph, filters)
    assert graph.number_of_nodes() == 0
    assert ranking["empty"] is True
    assert ranking["nodes"] == [] and ranking["edges"] == []
    assert ranking["converged"] is True


def test_alpha_bounds_rejected():
    for alpha in (0, 1, -0.5, 1.5):
        with pytest.raises(ValueError):
            graph_mod.normalize_filters({"alpha": alpha})
    assert graph_mod.normalize_filters({"alpha": 0.99}).alpha == 0.99


def test_year_filter_keeps_both_endpoints(seeded):
    with connect(seeded) as conn:
        filters = graph_mod.normalize_filters({"year_min": 2015, "year_max": 2018})
        graph, meta = graph_mod.build_graph(conn, filters)
    years = {graph.nodes[n]["year"] for n in graph.nodes}
    assert years <= {2015, 2016, 2017, 2018}
    for u, v in graph.edges:
        assert graph.nodes[u]["year"] is not None and graph.nodes[v]["year"] is not None
        assert graph.nodes[u]["year"] in years and graph.nodes[v]["year"] in years


# --- HTTP surface --------------------------------------------------------

def test_http_import_pending_link_unlink(client, db):
    r = client.post("/api/import/sample")
    assert r.status_code == 200, r.text
    assert client.get("/api/health").json()["edges"] == 25
    pending = client.get("/api/references/pending").json()
    assert pending["count"] == 8
    item = next(p for p in pending["pending"] if p["title"] == "Temporal Citation Networks")
    assert item["candidates"][0]["paper_id"] == "P003"

    assert client.post(f"/api/references/{item['id']}/link", json={"target_paper_id": "P003"}).status_code == 200
    assert client.get("/api/health").json()["edges"] == 26
    assert client.post(f"/api/references/{item['id']}/unlink").status_code == 200
    assert client.get("/api/health").json()["edges"] == 25
    assert client.get("/api/references/pending").json()["count"] == 8


def test_http_double_link_conflict(client, db):
    client.post("/api/import/sample")
    item = client.get("/api/references/pending").json()["pending"][0]
    assert client.post(f"/api/references/{item['id']}/link", json={"target_paper_id": "P001"}).status_code == 200
    assert client.post(f"/api/references/{item['id']}/link", json={"target_paper_id": "P001"}).status_code == 409


def test_http_cannot_unlink_doi_match(client, db):
    client.post("/api/import/sample")
    with connect(db) as conn:
        row = conn.execute("SELECT id FROM reference_records WHERE match_type='doi' LIMIT 1").fetchone()
    assert client.post(f"/api/references/{row['id']}/unlink").status_code == 409


def test_http_edge_detail_lists_occurrences(client, db):
    client.post("/api/import/sample")
    detail = client.get("/api/edges/P001/P002").json()
    assert detail["reference_count"] == 2
    assert {r["line_no"] for r in detail["references"]} == {6, 7}
    assert detail["references"][0]["raw"]["context"].startswith("PageRank baseline, main text")


def test_http_validation_errors(client, db):
    assert client.post("/api/graph", json={"alpha": 1}).status_code == 400
    assert client.post("/api/graph", json={"include_anomalies": ["nope"]}).status_code == 400
    assert client.post(
        "/api/graph", json={"include_anomalies": ["future_year"], "exclude_anomalies": ["future_year"]}
    ).status_code == 400


def test_http_snapshot_stores_filters_with_ranking(client, db):
    client.post("/api/import/sample")
    r = client.post(
        "/api/snapshots",
        json={"name": "2015-2018 graphs", "filters": {"year_min": 2015, "year_max": 2018, "topics": ["graphs"]}},
    )
    assert r.status_code == 200
    got = client.get(f"/api/snapshots/{r.json()['id']}").json()
    assert got["filters"]["year_min"] == 2015
    assert got["result"]["ranking"]["nodes"]
    assert got["result"]["filters"]["year_min"] == 2015
    listed = client.get("/api/snapshots").json()["snapshots"]
    assert listed[0]["name"] == "2015-2018 graphs"


def test_http_empty_and_isolated(client, db):
    client.post("/api/import/sample")
    empty = client.post("/api/graph", json={"year_min": 2030, "year_max": 2031}).json()
    assert empty["ranking"]["empty"] is True
    assert empty["ranking"]["converged"] is True
    assert empty["matrix"]["cells"] == []
