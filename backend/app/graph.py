"""Edge rebuild, anomaly detection, filtering and ranking.

Graph direction is fixed: an edge runs from the citing paper to the cited paper.
Edges are derived from resolved reference records, never written by hand:
one edge per (citing paper, cited paper) pair, with `occurrence_count` counting
how many reference records contributed to it.
"""
from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Iterable

import networkx as nx

from .db import now_iso


def _decode(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def rebuild_edges(conn: sqlite3.Connection) -> dict[str, Any]:
    """Recompute all edges from resolved reference records.

    Every resolved reference record is a citation occurrence. Records that share
    the same (source, target) pair collapse to one edge, and repeated citations
    increment `occurrence_count` while every record keeps its own row and its
    own original position (file + line + occurrence_index + raw JSON).
    Pending records contribute nothing; their source references stay untouched.
    """
    conn.execute("UPDATE reference_records SET edge_id = NULL")
    conn.execute("DELETE FROM edges")
    now = now_iso()

    groups = conn.execute(
        """
        SELECT source_paper_id, matched_paper_id, COUNT(*) AS n
        FROM reference_records
        WHERE status = 'resolved' AND matched_paper_id IS NOT NULL
        GROUP BY source_paper_id, matched_paper_id
        ORDER BY source_paper_id, matched_paper_id
        """
    ).fetchall()

    papers = {
        row["id"]: row
        for row in conn.execute("SELECT id, year FROM papers").fetchall()
    }
    edge_count = 0
    for group in groups:
        source = group["source_paper_id"]
        target = group["matched_paper_id"]
        anomalies: list[str] = []
        if source == target:
            anomalies.append("self_citation")
        source_year = papers.get(source, {})["year"] if papers.get(source) else None
        target_year = papers.get(target, {})["year"] if papers.get(target) else None
        if source_year is not None and target_year is not None and target_year > source_year:
            anomalies.append("future_year")
        cur = conn.execute(
            """
            INSERT INTO edges (source_paper_id, target_paper_id, occurrence_count, anomalies)
            VALUES (?, ?, ?, ?)
            """,
            (source, target, group["n"], json.dumps(anomalies)),
        )
        edge_id = int(cur.lastrowid)
        # Re-number occurrence positions in file/line order so the displayed
        # "第 N 次出现" stays consistent after links are added or revoked.
        positions = conn.execute(
            """
            SELECT id FROM reference_records
            WHERE status = 'resolved' AND source_paper_id = ? AND matched_paper_id = ?
            ORDER BY file_name, line_no
            """,
            (source, target),
        ).fetchall()
        for position, record in enumerate(positions, start=1):
            conn.execute(
                """
                UPDATE reference_records SET edge_id = ?, occurrence_index = ?, updated_at = ?
                WHERE id = ?
                """,
                (edge_id, position, now, record["id"]),
            )
        edge_count += 1
    return {
        "edges": edge_count,
        "resolved_references": sum(g["n"] for g in groups),
        "pending_references": conn.execute(
            "SELECT COUNT(*) FROM reference_records WHERE status = 'pending'"
        ).fetchone()[0],
        "rebuilt_at": now,
    }


ANOMALY_CHOICES = {"self_citation", "future_year"}


def parse_anomaly_filter(values: Iterable[str]) -> set[str]:
    allowed = {v.strip() for v in values if v and v.strip()}
    unknown = allowed - ANOMALY_CHOICES
    if unknown:
        raise ValueError("未知异常类型：" + "、".join(sorted(unknown)))
    return allowed


@dataclass
class Filters:
    year_min: int | None = None
    year_max: int | None = None
    topics: list[str] = field(default_factory=list)
    authors: list[str] = field(default_factory=list)
    include_anomalies: list[str] = field(default_factory=list)
    exclude_anomalies: list[str] = field(default_factory=list)
    alpha: float = 0.85
    tol: float = 1e-8
    max_iter: int = 200

    def as_dict(self) -> dict[str, Any]:
        return {
            "year_min": self.year_min,
            "year_max": self.year_max,
            "topics": self.topics,
            "authors": self.authors,
            "include_anomalies": self.include_anomalies,
            "exclude_anomalies": self.exclude_anomalies,
            "alpha": self.alpha,
            "tol": self.tol,
            "max_iter": self.max_iter,
        }


def normalize_filters(raw: dict[str, Any] | None) -> Filters:
    raw = raw or {}
    year_min = raw.get("year_min")
    year_max = raw.get("year_max")
    year_min = int(year_min) if year_min not in (None, "") else None
    year_max = int(year_max) if year_max not in (None, "") else None
    if year_min is not None and year_max is not None and year_min > year_max:
        year_min, year_max = year_max, year_min
    alpha = float(raw.get("alpha", 0.85))
    if not (0.0 < alpha < 1.0):
        raise ValueError("阻尼系数 delta 必须满足 0 < delta < 1")
    tol = float(raw.get("tol", 1e-8))
    if not (1e-14 <= tol <= 0.1):
        raise ValueError("收敛阈值需在 1e-14 与 0.1 之间")
    max_iter = int(raw.get("max_iter", 200))
    if not (10 <= max_iter <= 2000):
        raise ValueError("最大迭代次数需在 10 与 2000 之间")
    include = sorted(parse_anomaly_filter(raw.get("include_anomalies") or []))
    exclude = sorted(parse_anomaly_filter(raw.get("exclude_anomalies") or []))
    if set(include) & set(exclude):
        raise ValueError("同一异常类型不能同时纳入与排除")
    return Filters(
        year_min=year_min,
        year_max=year_max,
        topics=[str(t).strip() for t in (raw.get("topics") or []) if str(t).strip()],
        authors=[str(a).strip() for a in (raw.get("authors") or []) if str(a).strip()],
        include_anomalies=include,
        exclude_anomalies=exclude,
        alpha=alpha,
        tol=tol,
        max_iter=max_iter,
    )


def build_graph(conn: sqlite3.Connection, filters: Filters) -> tuple[nx.DiGraph, dict[str, Any]]:
    """Build the filtered graph and carry per-node display data.

    Year filtering keeps papers whose year is inside the range, and only edges
    whose two endpoints are both kept. Papers without a year are excluded when a
    year range is set (they cannot be placed inside the range).
    """
    paper_rows = conn.execute(
        "SELECT id, title, year, authors, topics, venue, doi_norm FROM papers ORDER BY id"
    ).fetchall()
    papers_by_id: dict[str, dict[str, Any]] = {}
    for row in paper_rows:
        papers_by_id[row["id"]] = {
            "id": row["id"],
            "title": row["title"],
            "year": row["year"],
            "authors": _decode(row["authors"], []),
            "topics": _decode(row["topics"], []),
            "venue": row["venue"],
            "doi": row["doi_norm"],
        }

    def in_year_range(year: int | None) -> bool:
        if filters.year_min is None and filters.year_max is None:
            return True
        if year is None:
            return False
        if filters.year_min is not None and year < filters.year_min:
            return False
        if filters.year_max is not None and year > filters.year_max:
            return False
        return True

    def matches_topic(paper: dict[str, Any]) -> bool:
        if not filters.topics:
            return True
        return bool({t.lower() for t in filters.topics} & {t.lower() for t in paper["topics"]})

    def matches_author(paper: dict[str, Any]) -> bool:
        if not filters.authors:
            return True
        return bool({a.lower() for a in filters.authors} & {a.lower() for a in paper["authors"]})

    kept = {
        pid for pid, paper in papers_by_id.items()
        if in_year_range(paper["year"]) and matches_topic(paper) and matches_author(paper)
    }

    edge_rows = conn.execute(
        "SELECT id, source_paper_id, target_paper_id, occurrence_count, anomalies FROM edges"
    ).fetchall()
    graph = nx.DiGraph()
    for pid in sorted(kept):
        paper = papers_by_id[pid]
        graph.add_node(pid, **paper)

    included_edges: list[dict[str, Any]] = []
    excluded_edges: list[dict[str, Any]] = []
    for row in edge_rows:
        source = row["source_paper_id"]
        target = row["target_paper_id"]
        if source not in kept or target not in kept:
            continue
        anomalies = _decode(row["anomalies"], [])
        if anomalies and not set(anomalies) <= set(filters.include_anomalies):
            excluded_edges.append(
                {
                    **dict(row),
                    "anomalies": anomalies,
                    "reason": "异常边未纳入",
                }
            )
            continue
        graph.add_edge(source, target, occurrence_count=row["occurrence_count"], anomalies=anomalies)
        included_edges.append(
            {
                **dict(row),
                "anomalies": anomalies,
                "occurrence_count": row["occurrence_count"],
                "source_paper_id": source,
                "target_paper_id": target,
            }
        )

    meta = {
        "papers_total": len(papers_by_id),
        "papers_in_scope": len(kept),
        "edges_in_scope": len(included_edges) + len(excluded_edges),
        "anomaly_excluded": len(excluded_edges),
        "excluded_edges": excluded_edges,
    }
    return graph, meta


def compute_ranking(graph: nx.DiGraph, filters: Filters) -> dict[str, Any]:
    """PageRank + degree metrics, with explicit convergence reporting.

    Dangling-node probability is redistributed evenly across *all* nodes.
    PageRank is computed on the directed graph as-is (in-edge = cited by).
    """
    n = graph.number_of_nodes()
    if n == 0:
        return {
            "nodes": [],
            "edges": [],
            "converged": True,
            "iterations": 0,
            "error": 0.0,
            "threshold": filters.tol,
            "alpha": filters.alpha,
            "max_iter": filters.max_iter,
            "empty": True,
        }
    if filters.alpha <= 0 or filters.alpha >= 1:
        raise ValueError("阻尼系数 delta 必须严格位于 0 与 1 之间")

    pagerank = _pagerank_with_dangling(graph, filters.alpha, filters.tol, filters.max_iter)
    values = pagerank["values"]
    nodes: list[dict[str, Any]] = []
    for node_id in graph.nodes:
        data = graph.nodes[node_id]
        incoming = graph.in_degree(node_id)
        outgoing = graph.out_degree(node_id)
        nodes.append(
            {
                "id": node_id,
                "title": data.get("title"),
                "year": data.get("year"),
                "authors": data.get("authors", []),
                "topics": data.get("topics", []),
                "venue": data.get("venue"),
                "doi": data.get("doi"),
                "in_degree": incoming,
                "out_degree": outgoing,
                "pagerank": values.get(node_id, 0.0),
                "isolated": incoming == 0 and outgoing == 0,
            }
        )
    nodes.sort(key=lambda item: (-item["pagerank"], item["id"]))
    for rank, node in enumerate(nodes, start=1):
        node["rank"] = rank

    edges = [
        {
            "source": u,
            "target": v,
            "occurrence_count": data.get("occurrence_count", 1),
            "anomalies": data.get("anomalies", []),
        }
        for u, v, data in graph.edges(data=True)
    ]
    edges.sort(key=lambda e: (e["source"], e["target"]))
    return {
        "nodes": nodes,
        "edges": edges,
        "converged": pagerank["converged"],
        "iterations": pagerank["iterations"],
        "error": pagerank["error"],
        "threshold": filters.tol,
        "alpha": filters.alpha,
        "max_iter": filters.max_iter,
        "empty": False,
    }


def _pagerank_with_dangling(
    graph: nx.DiGraph, alpha: float, tol: float, max_iter: int
) -> dict[str, Any]:
    """Power iteration with uniform dangling redistribution.

    NetworkX's default pagerank also redistributes dangling mass, but it does
    not expose iteration/error. Implementing the loop here makes the recorded
    threshold, iterations and convergence status explicit and reproducible.
    """
    nodes = list(graph.nodes)
    n = len(nodes)
    if n == 0:
        return {"values": {}, "converged": True, "iterations": 0, "error": 0.0}
    out_targets: dict[str, list[str]] = {}
    dangling: list[str] = []
    for node in nodes:
        successors = list(graph.successors(node))
        if successors:
            out_targets[node] = successors
        else:
            dangling.append(node)

    x = {node: 1.0 / n for node in nodes}
    teleport = 1.0 / n
    error = math.inf
    iterations = 0
    converged = False
    for iterations in range(1, max_iter + 1):
        dangling_mass = sum(x[node] for node in dangling)
        base = teleport * (1.0 - alpha) + alpha * dangling_mass / n
        new = {node: base for node in nodes}
        for node, successors in out_targets.items():
            share = alpha * x[node] / len(successors)
            for target in successors:
                new[target] += share
        error = sum(abs(new[node] - x[node]) for node in nodes)
        x = new
        if error <= tol:
            converged = True
            break
    total = sum(x.values()) or 1.0
    values = {node: value / total for node, value in x.items()}
    return {"values": values, "converged": converged, "iterations": iterations, "error": error}


def build_matrix(
    graph: nx.DiGraph, included_edges: list[dict[str, Any]]
) -> dict[str, Any]:
    """Year/topic matrix of *citing* edges.

    A citation is attributed to the cited paper's year and topic — the row says
    "works of this year were cited this many times in this topic". Because an
    edge lands in every topic of its target, the per-topic totals sum over
    topics; the edge count itself is reported separately as `edges`.
    """
    years = sorted({graph.nodes[n].get("year") for n in graph.nodes if graph.nodes[n].get("year") is not None})
    topic_set = sorted({t for n in graph.nodes for t in graph.nodes[n].get("topics", [])})
    counts: dict[tuple[int, str], int] = {}
    for edge in included_edges:
        target = graph.nodes.get(edge["target_paper_id"], {})
        year = target.get("year")
        if year is None:
            continue
        for topic in target.get("topics", []):
            counts[(year, topic)] = counts.get((year, topic), 0) + 1
    cells = [
        {"year": year, "topic": topic, "citations": count}
        for (year, topic), count in sorted(counts.items())
    ]
    return {
        "years": years,
        "topics": topic_set,
        "cells": cells,
        "total": sum(c["citations"] for c in cells),
        "edges": len(included_edges),
    }


def snapshot_payload(conn: sqlite3.Connection, filters: Filters) -> dict[str, Any]:
    graph, meta = build_graph(conn, filters)
    ranking = compute_ranking(graph, filters)
    matrix = build_matrix(
        graph,
        [
            {
                "source_paper_id": u,
                "target_paper_id": v,
            }
            for u, v in graph.edges
        ],
    )
    return {
        "filters": filters.as_dict(),
        "meta": meta,
        "ranking": ranking,
        "matrix": matrix,
    }
