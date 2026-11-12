"""Reference-to-paper matching: DOI exact match plus title candidates."""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Any, Iterable

from .normalize import normalize_doi, normalize_title, title_tokens, parse_year


@dataclass
class PaperLite:
    id: str
    title: str
    year: int | None
    authors: list[str]
    doi_norm: str | None
    topics: list[str]

    @property
    def title_norm(self) -> str:
        return normalize_title(self.title)


@dataclass
class Candidate:
    paper_id: str
    score: float
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"paper_id": self.paper_id, "score": round(self.score, 4), "reasons": self.reasons}


def doi_lookup(papers: Iterable[PaperLite], doi_norm: str | None) -> list[PaperLite]:
    if not doi_norm:
        return []
    return [p for p in papers if p.doi_norm and p.doi_norm == doi_norm]


def title_candidates(
    papers: Iterable[PaperLite],
    title: str | None,
    year: int | None = None,
    authors: Iterable[str] | None = None,
    limit: int = 8,
) -> list[Candidate]:
    """Rank papers by title similarity, year closeness and author overlap.

    Only meaningful candidates are returned; the caller never auto-links them.
    """
    ref_title = normalize_title(title)
    ref_tokens = title_tokens(title)
    ref_authors = {a.strip().lower() for a in (authors or []) if a and str(a).strip()}
    if not ref_title:
        return []
    scored: list[Candidate] = []
    for paper in papers:
        p_title = paper.title_norm
        if not p_title:
            continue
        exact = p_title == ref_title
        if exact:
            ratio = 1.0
        else:
            ratio = difflib.SequenceMatcher(None, ref_title, p_title).ratio()
            p_tokens = title_tokens(paper.title)
            if ref_tokens and p_tokens:
                jaccard = len(ref_tokens & p_tokens) / len(ref_tokens | p_tokens)
                ratio = max(ratio, jaccard)
        if ratio < 0.55:
            continue
        reasons: list[str] = []
        score = ratio * 100
        if exact:
            reasons.append("标题完全一致")
        else:
            reasons.append(f"标题相似度 {int(round(ratio * 100))}%")
        if year is not None and paper.year is not None:
            delta = abs(paper.year - year)
            if delta == 0:
                score += 8
                reasons.append("年份一致")
            elif delta == 1:
                score += 4
                reasons.append("年份相差 1 年")
            elif delta <= 3:
                score += 1
        elif paper.year is not None:
            reasons.append(f"论文年份 {paper.year}")
        overlap = ref_authors & {a.lower() for a in paper.authors}
        if overlap:
            score += min(len(overlap) * 6, 12)
            reasons.append("作者重合：" + "、".join(sorted(overlap)))
        scored.append(Candidate(paper.id, score, reasons))
    scored.sort(key=lambda c: (-c.score, c.paper_id))
    return scored[:limit]


def resolve_doi(
    papers: list[PaperLite], doi_norm: str | None
) -> tuple[str | None, list[PaperLite]]:
    """Return (target_id, ambiguous matches). A unique DOI match auto-resolves."""
    matches = doi_lookup(papers, doi_norm)
    if len(matches) == 1:
        return matches[0].id, matches
    return None, matches


def title_ambiguity(papers: Iterable[PaperLite]) -> dict[str, list[str]]:
    """Map normalized title -> paper ids whenever more than one paper shares it."""
    by_title: dict[str, list[str]] = {}
    for p in papers:
        if n := p.title_norm:
            by_title.setdefault(n, []).append(p.id)
    return {n: ids for n, ids in by_title.items() if len(ids) > 1}


def reference_authors(raw: dict[str, Any]) -> list[str]:
    for key in ("authors", "author", "reference_authors", "cited_authors"):
        if key in raw and raw[key]:
            value = raw[key]
            if isinstance(value, list):
                return [str(v) for v in value]
            return [part.strip() for part in str(value).replace("|", ";").split(";") if part.strip()]
    return []


def reference_title(raw: dict[str, Any]) -> str | None:
    for key in ("title", "reference_title", "cited_title", "article_title"):
        if value := raw.get(key):
            return str(value)
    return None


def reference_doi(raw: dict[str, Any]) -> str | None:
    for key in ("doi", "reference_doi", "cited_doi", "DOI"):
        if value := raw.get(key):
            return str(value)
    return None


def reference_year(raw: dict[str, Any]) -> int | None:
    for key in ("year", "reference_year", "cited_year", "publication_year"):
        if key in raw:
            return parse_year(raw[key])
    return None


def source_identifier(raw: dict[str, Any]) -> dict[str, str | None]:
    """Extract the citing paper's identity from a reference record."""
    paper_id = None
    doi = None
    title = None
    for key in ("source_paper_id", "source_paper", "citing_paper_id", "source_id", "paper_id"):
        if raw.get(key):
            paper_id = str(raw[key]).strip()
            break
    for key in ("source_doi", "citing_doi"):
        if raw.get(key):
            doi = str(raw[key])
            break
    for key in ("source_title", "citing_title"):
        if raw.get(key):
            title = str(raw[key])
            break
    return {"paper_id": paper_id, "doi": doi, "title": title}
