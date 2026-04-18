"""
Streamlit UI から叩く読み取り系クエリ。

生の SQL にしているのは FTS5 の MATCH を素直に書くため。
SQLAlchemy のセッションは使わず、sqlite3 直叩き。
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


def list_companies(db_path: str, english_filers_only: bool = False) -> List[Dict[str, Any]]:
    q = ("SELECT edinet_code, sec_code, company_name, has_english_filing "
         "FROM ir_companies")
    if english_filers_only:
        q += " WHERE has_english_filing = 1"
    q += " ORDER BY has_english_filing DESC, sec_code"
    with _conn(db_path) as c:
        rows = c.execute(q).fetchall()
    return [dict(r) for r in rows]


def list_section_codes(db_path: str) -> List[str]:
    with _conn(db_path) as c:
        rows = c.execute(
            "SELECT DISTINCT section_code FROM ir_sections ORDER BY section_code"
        ).fetchall()
    return [r["section_code"] for r in rows]


def peer_sections(
    db_path: str,
    section_code: str,
    latest_only: bool = True,
    limit: int = 30,
) -> List[Dict[str, Any]]:
    """同業他社の最新セクションを横並び取得。"""
    q = """
    SELECT
        c.sec_code, c.company_name, d.doc_id, d.period_end, d.submit_date,
        s.section_code, s.section_name_ja, s.content_text, s.char_count
    FROM ir_sections s
    JOIN ir_documents d ON s.doc_id = d.doc_id
    LEFT JOIN ir_companies c ON d.edinet_code = c.edinet_code
    WHERE s.section_code = ?
    """
    params: List[Any] = [section_code]
    if latest_only:
        q += " AND d.is_latest = 1"
    q += " ORDER BY d.period_end DESC, c.sec_code LIMIT ?"
    params.append(limit)
    with _conn(db_path) as c:
        rows = c.execute(q, params).fetchall()
    return [dict(r) for r in rows]


def self_history(
    db_path: str,
    sec_code: str,
    section_code: str,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """自社の同一セクションの時系列。"""
    q = """
    SELECT d.doc_id, d.period_end, d.submit_date, d.is_amended, d.is_latest,
           s.content_text, s.char_count
    FROM ir_sections s
    JOIN ir_documents d ON s.doc_id = d.doc_id
    WHERE s.section_code = ? AND d.sec_code = ?
    ORDER BY d.period_end DESC, d.submit_date DESC
    LIMIT ?
    """
    with _conn(db_path) as c:
        rows = c.execute(q, (section_code, sec_code, limit)).fetchall()
    return [dict(r) for r in rows]


def fts_search(
    db_path: str,
    query: str,
    section_code: Optional[str] = None,
    limit: int = 30,
    lang: str = "auto",  # "ja" | "en" | "auto" (両言語の OR)
) -> List[Dict[str, Any]]:
    """
    ir_sections_fts 経由の全文検索。BM25 順。
    lang によってカラム指定を変えることで、言語を絞ったスコアリングが可能。
    """
    match_expr = _build_match(query, lang, ["content_text", "content_text_en", "keywords_ja", "keywords_en"])
    q = """
    SELECT s.section_id, s.section_code, s.section_name_ja, s.section_name_en,
           s.content_source,
           d.doc_id, d.period_end, c.sec_code, c.company_name,
           s.keywords_ja, s.keywords_en,
           snippet(ir_sections_fts, 0, '<<', '>>', ' … ', 30) AS snippet_ja,
           snippet(ir_sections_fts, 1, '<<', '>>', ' … ', 30) AS snippet_en,
           bm25(ir_sections_fts) AS score
    FROM ir_sections_fts
    JOIN ir_sections s ON s.section_id = ir_sections_fts.rowid
    JOIN ir_documents d ON s.doc_id = d.doc_id
    LEFT JOIN ir_companies c ON d.edinet_code = c.edinet_code
    WHERE ir_sections_fts MATCH ?
    """
    params: List[Any] = [match_expr]
    if section_code:
        q += " AND s.section_code = ?"
        params.append(section_code)
    q += " AND d.is_latest = 1 ORDER BY score LIMIT ?"
    params.append(limit)
    with _conn(db_path) as c:
        rows = c.execute(q, params).fetchall()
    return [dict(r) for r in rows]


def _build_match(query: str, lang: str, all_cols: List[str]) -> str:
    """
    FTS5 MATCH 式を組み立てる。lang で検索カラムを絞る。

    - "ja": content_text / keywords_ja のみ
    - "en": content_text_en / keywords_en のみ
    - "auto": 全カラム
    ユーザー入力は FTS5 の演算子 (-, ", OR 等) を安全に扱えるようトークンごとに double-quote する。
    ただし "OR" "AND" "NOT" は演算子として温存する。
    """
    q = _safe_fts_expression(query)
    if lang == "ja":
        cols = [c for c in all_cols if c in ("content_text", "keywords_ja", "title")]
    elif lang == "en":
        cols = [c for c in all_cols if c in ("content_text_en", "keywords_en", "title_en")]
    else:
        cols = all_cols
    if not cols:
        return q
    col_expr = "{" + " ".join(cols) + "}"
    return f'{col_expr} : ({q})'


_FTS_OPERATORS = {"OR", "AND", "NOT", "NEAR"}


def _safe_fts_expression(query: str) -> str:
    tokens = query.strip().split()
    out = []
    for t in tokens:
        if t in _FTS_OPERATORS:
            out.append(t)
        else:
            t = t.replace('"', "")
            if t:
                out.append(f'"{t}"')
    return " ".join(out) or '""'


def db_stats(db_path: str) -> Dict[str, Any]:
    with _conn(db_path) as c:
        def count(tbl: str) -> int:
            try:
                return c.execute(f"SELECT COUNT(*) AS n FROM {tbl}").fetchone()["n"]
            except sqlite3.OperationalError:
                return 0
        return {
            "companies": count("ir_companies"),
            "documents": count("ir_documents"),
            "sections": count("ir_sections"),
            "figures": count("ir_financial_figures"),
            "financial_raw": count("financial_raw"),
        }
