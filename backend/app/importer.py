"""Import papers from CSV and reference records from JSONL.

Import is idempotent: papers are upserted by id, and reference records are
deduplicated on a content fingerprint (file, line, raw payload), so re-importing
the same file does not create duplicate rows. A *second* citation of the same
work is kept as its own reference record: those records all point at one edge,
which counts the occurrences. This keeps "one edge per paper pair" while the
original reference positions remain inspectable.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from .db import now_iso
from .matching import (
    PaperLite,
    reference_authors,
    reference_doi,
    reference_title,
    reference_year,
    source_identifier,
    title_candidates,
)
from .normalize import normalize_doi, parse_year, split_list


class ImportProblem(Exception):
    """Raised for a user-facing import problem."""


@dataclass
class ImportStats:
    papers_added: int = 0
    papers_updated: int = 0
    papers_skipped: int = 0
    references_seen: int = 0
    references_added: int = 0
    references_duplicate: int = 0
    doi_matched: int = 0
    doi_ambiguous: int = 0
    pending: int = 0
    lines_skipped: int = 0
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _coerce_row(row: dict[str, Any]) -> dict[str, Any]:
    return {str(k).strip().lower(): v for k, v in row.items() if k is not None}


def _first(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _new_run(conn: sqlite3.Connection, kind: str, file_name: str) -> int:
    cur = conn.execute(
        "INSERT INTO import_runs (kind, file_name, imported_at, detail) VALUES (?, ?, ?, '{}')",
        (kind, file_name, now_iso()),
    )
    return int(cur.lastrowid)


def _finish_run(conn: sqlite3.Connection, run_id: int, detail: dict[str, Any]) -> None:
    conn.execute(
        "UPDATE import_runs SET detail = ? WHERE id = ?",
        (json.dumps(detail, ensure_ascii=False), run_id),
    )


def import_papers_csv(conn: sqlite3.Connection, text: str, file_name: str) -> ImportStats:
    stats = ImportStats()
    try:
        reader = csv.DictReader(io.StringIO(text))
        fieldnames = [name for name in (reader.fieldnames or []) if name]
        header = {name.strip().lower() for name in fieldnames}
        if not header:
            raise ImportProblem("CSV 文件没有表头")
        if not ({"id", "paper_id"} & header) or "title" not in header:
            raise ImportProblem("CSV 至少需要 id 与 title 两列")
        reader.fieldnames = fieldnames
        rows = list(reader)
    except csv.Error as exc:
        raise ImportProblem(f"无法解析 CSV：{exc}") from exc
    except UnicodeDecodeError as exc:
        raise ImportProblem(f"CSV 编码无法读取：{exc}") from exc

    run_id = _new_run(conn, "papers", file_name)
    now = now_iso()
    for line_no, raw in enumerate(rows, start=2):
        row = _coerce_row(raw)
        paper_id = str(_first(row, "id", "paper_id") or "").strip()
        title = str(_first(row, "title") or "").strip()
        if not paper_id or not title:
            stats.papers_skipped += 1
            stats.lines_skipped += 1
            stats.warnings.append(f"第 {line_no} 行缺少 id 或 title，已跳过")
            continue
        year = parse_year(_first(row, "year", "publication_year"))
        authors = split_list(_first(row, "authors", "author"))
        topics = split_list(_first(row, "topics", "keywords", "topic"))
        venue = _first(row, "venue", "journal", "container_title")
        doi_raw = _first(row, "doi")
        doi_raw_str = str(doi_raw).strip() if doi_raw is not None else None
        doi_norm = normalize_doi(doi_raw_str)
        existing = conn.execute("SELECT id FROM papers WHERE id = ?", (paper_id,)).fetchone()
        conn.execute(
            """
            INSERT INTO papers (id, title, year, authors, venue, doi_raw, doi_norm, topics, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title=excluded.title, year=excluded.year, authors=excluded.authors,
                venue=excluded.venue, doi_raw=excluded.doi_raw, doi_norm=excluded.doi_norm,
                topics=excluded.topics
            """,
            (
                paper_id,
                title,
                year,
                json.dumps(authors, ensure_ascii=False),
                str(venue) if venue is not None else None,
                doi_raw_str,
                doi_norm,
                json.dumps(topics, ensure_ascii=False),
                now,
            ),
        )
        if existing:
            stats.papers_updated += 1
        else:
            stats.papers_added += 1
    if stats.papers_added + stats.papers_updated == 0:
        _finish_run(conn, run_id, stats.as_dict())
        raise ImportProblem("CSV 中没有可导入的论文行（需要 id 与 title）")
    _finish_run(conn, run_id, stats.as_dict())
    return stats


def load_papers(conn: sqlite3.Connection) -> list[PaperLite]:
    rows = conn.execute(
        "SELECT id, title, year, authors, doi_norm, topics FROM papers ORDER BY id"
    ).fetchall()
    return [
        PaperLite(
            id=row["id"],
            title=row["title"],
            year=row["year"],
            authors=json.loads(row["authors"] or "[]"),
            doi_norm=row["doi_norm"],
            topics=json.loads(row["topics"] or "[]"),
        )
        for row in rows
    ]


def _find_source(conn: sqlite3.Connection, ident: dict[str, str | None]) -> str | None:
    if ident["paper_id"]:
        row = conn.execute("SELECT id FROM papers WHERE id = ?", (ident["paper_id"],)).fetchone()
        if row:
            return row["id"]
    if doi_norm := normalize_doi(ident["doi"]):
        row = conn.execute("SELECT id FROM papers WHERE doi_norm = ?", (doi_norm,)).fetchone()
        if row:
            return row["id"]
    if ident["title"]:
        rows = conn.execute(
            "SELECT id, title FROM papers WHERE lower(title) = lower(?)",
            (ident["title"].strip(),),
        ).fetchall()
        if len(rows) == 1:
            return rows[0]["id"]
    return None


def _fingerprint(file_name: str, line_no: int, raw: dict[str, Any]) -> str:
    payload = json.dumps(
        {"file": file_name, "line": line_no, "raw": raw},
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def import_references_jsonl(conn: sqlite3.Connection, text: str, file_name: str) -> ImportStats:
    stats = ImportStats()
    papers = load_papers(conn)
    if not papers:
        raise ImportProblem("请先导入论文 CSV，再导入参考文献 JSONL")
    doi_index: dict[str, list[PaperLite]] = {}
    for paper in papers:
        if paper.doi_norm:
            doi_index.setdefault(paper.doi_norm, []).append(paper)

    run_id = _new_run(conn, "references", file_name)
    now = now_iso()
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            stats.lines_skipped += 1
            stats.warnings.append(f"第 {line_no} 行不是合法 JSON：{exc.msg}")
            continue
        if not isinstance(raw, dict):
            stats.lines_skipped += 1
            stats.warnings.append(f"第 {line_no} 行不是 JSON 对象")
            continue
        stats.references_seen += 1
        ident = source_identifier(raw)
        source_id = _find_source(conn, ident)
        if not source_id:
            stats.references_seen -= 1
            stats.lines_skipped += 1
            label = ident["paper_id"] or ident["doi"] or ident["title"] or "未知"
            stats.warnings.append(f"第 {line_no} 行找不到引用者论文（{label}），已跳过")
            continue

        fingerprint = _fingerprint(file_name, line_no, raw)
        duplicate = conn.execute(
            "SELECT id FROM reference_records WHERE fingerprint = ?", (fingerprint,)
        ).fetchone()
        if duplicate:
            stats.references_duplicate += 1
            continue

        doi_raw = reference_doi(raw)
        doi_norm = normalize_doi(doi_raw)
        title = reference_title(raw)
        year = reference_year(raw)
        authors = reference_authors(raw)

        target_id: str | None = None
        match_type = "none"
        status = "pending"
        candidates: list[dict[str, Any]] = []
        if doi_norm:
            matches = doi_index.get(doi_norm, [])
            if len(matches) == 1:
                target_id = matches[0].id
                match_type = "doi"
                status = "resolved"
                stats.doi_matched += 1
            elif len(matches) > 1:
                stats.doi_ambiguous += 1
                candidates = [
                    {
                        "paper_id": c.id,
                        "score": 100.0,
                        "reasons": ["同一 DOI 对应多篇论文，需人工确认"],
                        "title": c.title,
                        "year": c.year,
                    }
                    for c in matches
                ]
                stats.warnings.append(f"第 {line_no} 行 DOI {doi_norm} 对应多篇论文，需人工确认")
        if status == "pending":
            stats.pending += 1
            if not candidates:
                for cand in title_candidates(papers, title, year, authors):
                    candidates.append(
                        {
                            **cand.as_dict(),
                            "title": next(p.title for p in papers if p.id == cand.paper_id),
                            "year": next(p.year for p in papers if p.id == cand.paper_id),
                        }
                    )
        occurrence_index = 1
        if target_id:
            occurrence_index = (
                conn.execute(
                    "SELECT COUNT(*) FROM reference_records WHERE source_paper_id = ? AND matched_paper_id = ?",
                    (source_id, target_id),
                ).fetchone()[0]
                + 1
            )

        records = conn.execute(
            """
            INSERT INTO reference_records (
                source_paper_id, raw_json, file_name, line_no, occurrence_index,
                fingerprint, doi_raw, doi_norm, title, year, authors, candidates,
                status, match_type, matched_paper_id, edge_id, import_run_id,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)
            """,
            (
                source_id,
                json.dumps(raw, ensure_ascii=False),
                file_name,
                line_no,
                occurrence_index,
                fingerprint,
                str(doi_raw) if doi_raw is not None else None,
                doi_norm,
                title,
                year,
                json.dumps(authors, ensure_ascii=False),
                json.dumps(candidates, ensure_ascii=False),
                status,
                match_type,
                target_id,
                run_id,
                now,
                now,
            ),
        )
        _ = records
        stats.references_added += 1

    if stats.references_added == 0 and stats.references_duplicate == 0:
        _finish_run(conn, run_id, stats.as_dict())
        raise ImportProblem(
            "JSONL 中没有可导入的引用记录（每行需为合法 JSON，且能定位引用者论文 id/DOI/标题）"
        )
    _finish_run(conn, run_id, stats.as_dict())
    return stats


__all__ = [
    "ImportProblem",
    "ImportStats",
    "import_papers_csv",
    "import_references_jsonl",
    "load_papers",
]
