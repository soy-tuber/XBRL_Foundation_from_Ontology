"""
Phase 2: Streamlit 用の読取クエリ。
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional


@contextmanager
def _conn(db_path: str) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def list_presentations(db_path: str, sec_code: Optional[str] = None) -> List[Dict[str, Any]]:
    q = "SELECT * FROM ir_presentations"
    params: List[Any] = []
    if sec_code:
        q += " WHERE sec_code = ?"
        params.append(sec_code)
    q += " ORDER BY period_end DESC, presentation_id DESC"
    with _conn(db_path) as c:
        return [dict(r) for r in c.execute(q, params).fetchall()]


def search_slides(
    db_path: str,
    query: str,
    sec_code: Optional[str] = None,
    limit: int = 30,
    lang: str = "auto",
) -> List[Dict[str, Any]]:
    match_expr = _build_match(query, lang)
    q = """
    SELECT s.slide_id, s.slide_no, s.slide_url,
           s.title AS slide_title, s.title_en AS slide_title_en,
           s.has_table, s.has_chart,
           s.keywords_ja, s.keywords_en,
           p.sec_code, p.company_name, p.fiscal_period,
           p.title AS pres_title, p.source_url,
           snippet(ir_slides_fts, 0, '<<', '>>', ' … ', 40) AS snippet_ja,
           snippet(ir_slides_fts, 1, '<<', '>>', ' … ', 40) AS snippet_en,
           bm25(ir_slides_fts) AS score
    FROM ir_slides_fts
    JOIN ir_presentation_slides s ON s.slide_id = ir_slides_fts.rowid
    JOIN ir_presentations p ON s.presentation_id = p.presentation_id
    WHERE ir_slides_fts MATCH ?
    """
    params: List[Any] = [match_expr]
    if sec_code:
        q += " AND p.sec_code = ?"
        params.append(sec_code)
    q += " ORDER BY score LIMIT ?"
    params.append(limit)
    with _conn(db_path) as c:
        return [dict(r) for r in c.execute(q, params).fetchall()]


def _build_match(query: str, lang: str) -> str:
    # 演算子安全化は src.ir.queries と同じロジックを流用
    from src.ir.queries import _safe_fts_expression
    q = _safe_fts_expression(query)
    if lang == "ja":
        cols = ["content_text", "keywords_ja", "title"]
    elif lang == "en":
        cols = ["content_text_en", "keywords_en", "title_en"]
    else:
        cols = ["content_text", "content_text_en", "keywords_ja", "keywords_en", "title", "title_en"]
    col_expr = "{" + " ".join(cols) + "}"
    return f'{col_expr} : ({q})'


def phase2_stats(db_path: str) -> Dict[str, Any]:
    with _conn(db_path) as c:
        def count(tbl: str) -> int:
            try:
                return c.execute(f"SELECT COUNT(*) AS n FROM {tbl}").fetchone()["n"]
            except sqlite3.OperationalError:
                return 0
        return {
            "presentations": count("ir_presentations"),
            "slides": count("ir_presentation_slides"),
        }
