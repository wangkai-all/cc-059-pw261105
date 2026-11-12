"""FastAPI application for the citation graph workbench."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .db import connect, init_db, now_iso, reset_data
from .graph import (
    Filters,
    normalize_filters,
    rebuild_edges,
    snapshot_payload,
)
from .importer import ImportProblem, import_papers_csv, import_references_jsonl
from .matching import title_candidates

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "samples"
FRONTEND_DIST = ROOT / "frontend" / "dist"

@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="Citation Graph Workbench", version="1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _conn():
    return connect()


if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    def spa_index() -> FileResponse:
        return FileResponse(FRONTEND_DIST / "index.html")


@app.get("/api/health")
def health() -> dict[str, Any]:
    with _conn() as conn:
        papers = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
        refs = conn.execute("SELECT COUNT(*) FROM reference_records").fetchone()[0]
        pending = conn.execute(
            "SELECT COUNT(*) FROM reference_records WHERE status = 'pending'"
        ).fetchone()[0]
        edges = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    return {"ok": True, "papers": papers, "references": refs, "pending": pending, "edges": edges}


def _read_upload(upload: UploadFile) -> tuple[str, str]:
    raw = upload.file.read()
    try:
        return raw.decode("utf-8-sig"), upload.filename or "upload"
    except UnicodeDecodeError as exc:
        raise HTTPException(400, f"文件需为 UTF-8 编码：{exc}") from exc


@app.post("/api/import/papers")
def import_papers(file: UploadFile = File(...)) -> dict[str, Any]:
    text, name = _read_upload(file)
    with _conn() as conn:
        try:
            stats = import_papers_csv(conn, text, name)
        except ImportProblem as exc:
            raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "stats": stats.as_dict()}


@app.post("/api/import/references")
def import_references(file: UploadFile = File(...)) -> dict[str, Any]:
    text, name = _read_upload(file)
    with _conn() as conn:
        try:
            stats = import_references_jsonl(conn, text, name)
            rebuilt = rebuild_edges(conn)
        except ImportProblem as exc:
            raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "stats": stats.as_dict(), "rebuild": rebuilt}


@app.post("/api/import/sample")
def import_sample() -> dict[str, Any]:
    papers_path = SAMPLES / "papers.csv"
    refs_path = SAMPLES / "references.jsonl"
    if not papers_path.exists() or not refs_path.exists():
        raise HTTPException(404, "样例文件不存在")
    with _conn() as conn:
        reset_data(conn)
        pstats = import_papers_csv(conn, papers_path.read_text(encoding="utf-8"), "samples/papers.csv")
        rstats = import_references_jsonl(conn, refs_path.read_text(encoding="utf-8"), "samples/references.jsonl")
        rebuilt = rebuild_edges(conn)
    return {
        "ok": True,
        "papers": pstats.as_dict(),
        "references": rstats.as_dict(),
        "rebuild": rebuilt,
    }


@app.post("/api/reset")
def reset() -> dict[str, Any]:
    with _conn() as conn:
        reset_data(conn)
    return {"ok": True}


@app.post("/api/edges/rebuild")
def rebuild() -> dict[str, Any]:
    with _conn() as conn:
        result = rebuild_edges(conn)
    return {"ok": True, "rebuild": result}


@app.get("/api/papers")
def list_papers(q: str | None = None) -> dict[str, Any]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, title, year, authors, topics, venue, doi_raw, doi_norm FROM papers ORDER BY id"
        ).fetchall()
    papers = []
    for row in rows:
        item = dict(row)
        item["authors"] = json.loads(item["authors"] or "[]")
        item["topics"] = json.loads(item["topics"] or "[]")
        if q and q.lower() not in json.dumps(item, ensure_ascii=False).lower():
            continue
        papers.append(item)
    return {"papers": papers, "count": len(papers)}


@app.get("/api/taxonomy")
def taxonomy() -> dict[str, Any]:
    with _conn() as conn:
        rows = conn.execute("SELECT year, authors, topics, venue FROM papers").fetchall()
    years: set[int] = set()
    authors: set[str] = set()
    topics: set[str] = set()
    venues: set[str] = set()
    for row in rows:
        if row["year"] is not None:
            years.add(row["year"])
        authors.update(json.loads(row["authors"] or "[]"))
        topics.update(json.loads(row["topics"] or "[]"))
        if row["venue"]:
            venues.add(row["venue"])
    return {
        "years": sorted(years),
        "authors": sorted(authors),
        "topics": sorted(topics),
        "venues": sorted(venues),
    }


def _decode_ref(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["raw"] = json.loads(item.pop("raw_json") or "{}")
    item["authors"] = json.loads(item.pop("authors") or "[]")
    item["candidates"] = json.loads(item.pop("candidates") or "[]")
    return item


@app.get("/api/references/pending")
def pending_references() -> dict[str, Any]:
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT r.*, p.title AS source_title, p.year AS source_year
            FROM reference_records r
            JOIN papers p ON p.id = r.source_paper_id
            WHERE r.status = 'pending'
            ORDER BY r.source_paper_id, r.line_no
            """
        ).fetchall()
        items = []
        for row in rows:
            item = _decode_ref(row)
            source = {"id": row["source_paper_id"], "title": row["source_title"], "year": row["source_year"]}
            item["source"] = source
            items.append(item)
    return {"pending": items, "count": len(items)}


@app.get("/api/references/search")
def search_manual_candidates(
    ref_id: int = Query(...),
    q: str | None = None,
) -> dict[str, Any]:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM reference_records WHERE id = ?", (ref_id,)).fetchone()
        if not row:
            raise HTTPException(404, "引用记录不存在")
        from .importer import load_papers

        papers = load_papers(conn)
        if q:
            qlower = q.lower()
            matches = [
                p for p in papers if qlower in p.title.lower() or qlower in p.id.lower()
            ][:25]
            return {
                "candidates": [
                    {"paper_id": p.id, "title": p.title, "year": p.year, "doi": p.doi_norm, "score": None}
                    for p in matches
                ]
            }
        title = row["title"]
        year = row["year"]
        authors = json.loads(row["authors"] or "[]")
        if not title:
            return {"candidates": []}
        cands = title_candidates(papers, title, year, authors)
        return {
            "candidates": [
                {
                    "paper_id": c.paper_id,
                    "title": next(p.title for p in papers if p.id == c.paper_id),
                    "year": next(p.year for p in papers if p.id == c.paper_id),
                    "doi": next(p.doi_norm for p in papers if p.id == c.paper_id),
                    "score": c.score,
                    "reasons": c.reasons,
                }
                for c in cands
            ]
        }


class ManualLink(BaseModel):
    target_paper_id: str = Field(min_length=1)


@app.post("/api/references/{ref_id}/link")
def link_reference(ref_id: int, body: ManualLink) -> dict[str, Any]:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM reference_records WHERE id = ?", (ref_id,)).fetchone()
        if not row:
            raise HTTPException(404, "引用记录不存在")
        target = conn.execute("SELECT id, title FROM papers WHERE id = ?", (body.target_paper_id,)).fetchone()
        if not target:
            raise HTTPException(404, "目标论文不存在")
        if row["status"] == "resolved":
            raise HTTPException(409, "该引用记录已关联；请先撤销再重新关联")
        conn.execute(
            """
            UPDATE reference_records
            SET status='resolved', match_type='manual', matched_paper_id=?, updated_at=?
            WHERE id=?
            """,
            (body.target_paper_id, now_iso(), ref_id),
        )
        rebuilt = rebuild_edges(conn)
    return {"ok": True, "rebuild": rebuilt}


@app.post("/api/references/{ref_id}/unlink")
def unlink_reference(ref_id: int) -> dict[str, Any]:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM reference_records WHERE id = ?", (ref_id,)).fetchone()
        if not row:
            raise HTTPException(404, "引用记录不存在")
        if row["match_type"] != "manual":
            raise HTTPException(409, "只有人工关联可以撤销；DOI 精确匹配由数据决定")
        conn.execute(
            """
            UPDATE reference_records
            SET status='pending', match_type='none', matched_paper_id=NULL, edge_id=NULL, updated_at=?
            WHERE id=?
            """,
            (now_iso(), ref_id),
        )
        rebuilt = rebuild_edges(conn)
        # Refresh suggestions after unlink so the record returns to a useful state.
        from .importer import load_papers

        papers = load_papers(conn)
        candidates = title_candidates(
            papers,
            row["title"],
            row["year"],
            json.loads(row["authors"] or "[]"),
        )
        conn.execute(
            "UPDATE reference_records SET candidates=? WHERE id=?",
            (
                json.dumps(
                    [
                        {
                            **c.as_dict(),
                            "title": next(p.title for p in papers if p.id == c.paper_id),
                            "year": next(p.year for p in papers if p.id == c.paper_id),
                        }
                        for c in candidates
                    ],
                    ensure_ascii=False,
                ),
                ref_id,
            ),
        )
    return {"ok": True, "rebuild": rebuilt}


class FilterPayload(BaseModel):
    year_min: int | None = None
    year_max: int | None = None
    topics: list[str] = Field(default_factory=list)
    authors: list[str] = Field(default_factory=list)
    include_anomalies: list[str] = Field(default_factory=list)
    exclude_anomalies: list[str] = Field(default_factory=list)
    alpha: float = 0.85
    tol: float = 1.0e-8
    max_iter: int = 200


def _run_filters(payload: FilterPayload) -> tuple[Filters, dict[str, Any]]:
    try:
        filters = normalize_filters(payload.model_dump())
        with _conn() as conn:
            return filters, snapshot_payload(conn, filters)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/graph")
def graph_view(payload: FilterPayload = Body(...)) -> dict[str, Any]:
    return _run_filters(payload)[1]


@app.post("/api/graph/edges")
def graph_edges(payload: FilterPayload = Body(...)) -> dict[str, Any]:
    _, snapshot = _run_filters(payload)
    return {
        "edges": snapshot["ranking"]["edges"],
        "excluded_edges": snapshot["meta"]["excluded_edges"],
    }


@app.get("/api/edges/{source}/{target}")
def edge_detail(source: str, target: str) -> dict[str, Any]:
    with _conn() as conn:
        edge = conn.execute(
            "SELECT * FROM edges WHERE source_paper_id = ? AND target_paper_id = ?",
            (source, target),
        ).fetchone()
        if not edge:
            raise HTTPException(404, "边不存在")
        refs = conn.execute(
            """
            SELECT * FROM reference_records
            WHERE source_paper_id = ? AND matched_paper_id = ? AND status = 'resolved'
            ORDER BY file_name, line_no
            """,
            (source, target),
        ).fetchall()
        papers = conn.execute(
            "SELECT id, title, year, authors, topics, venue, doi_raw FROM papers WHERE id IN (?, ?)",
            (source, target),
        ).fetchall()
    paper_map = {row["id"]: dict(row) for row in papers}
    for paper in paper_map.values():
        paper["authors"] = json.loads(paper["authors"] or "[]")
        paper["topics"] = json.loads(paper["topics"] or "[]")
    return {
        "edge": {
            **dict(edge),
            "anomalies": json.loads(edge["anomalies"] or "[]"),
            "source_paper": paper_map.get(source),
            "target_paper": paper_map.get(target),
        },
        "references": [_decode_ref(row) for row in refs],
        "reference_count": len(refs),
    }


class SnapshotPayload(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    filters: FilterPayload


@app.post("/api/snapshots")
def save_snapshot(body: SnapshotPayload) -> dict[str, Any]:
    filters, snapshot = _run_filters(body.filters)
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO snapshots (name, filters, result, created_at) VALUES (?, ?, ?, ?)",
            (
                body.name.strip(),
                json.dumps(filters.as_dict(), ensure_ascii=False),
                json.dumps(snapshot, ensure_ascii=False),
                now_iso(),
            ),
        )
        snapshot_id = int(cur.lastrowid)
    return {"ok": True, "id": snapshot_id}


@app.get("/api/snapshots")
def list_snapshots() -> dict[str, Any]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, name, filters, created_at, length(result) AS size FROM snapshots ORDER BY id DESC"
        ).fetchall()
    return {
        "snapshots": [
            {
                "id": row["id"],
                "name": row["name"],
                "filters": json.loads(row["filters"]),
                "created_at": row["created_at"],
                "size": row["size"],
            }
            for row in rows
        ]
    }


@app.get("/api/snapshots/{snapshot_id}")
def get_snapshot(snapshot_id: int) -> dict[str, Any]:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM snapshots WHERE id = ?", (snapshot_id,)).fetchone()
    if not row:
        raise HTTPException(404, "快照不存在")
    return {
        "id": row["id"],
        "name": row["name"],
        "filters": json.loads(row["filters"]),
        "result": json.loads(row["result"]),
        "created_at": row["created_at"],
    }


@app.delete("/api/snapshots/{snapshot_id}")
def delete_snapshot(snapshot_id: int) -> dict[str, Any]:
    with _conn() as conn:
        cur = conn.execute("DELETE FROM snapshots WHERE id = ?", (snapshot_id,))
        if cur.rowcount == 0:
            raise HTTPException(404, "快照不存在")
    return {"ok": True}
