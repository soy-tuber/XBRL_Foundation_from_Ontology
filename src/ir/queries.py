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


def list_companies(db_path: str) -> List[Dict[str, Any]]:
    with _conn(db_path) as c:
        rows = c.execute(
            "SELECT edinet_code, sec_code, company_name FROM ir_companies ORDER BY sec_code"
        ).fetchall()
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
) -> List[Dict[str, Any]]:
    """ir_sections_fts 経由の全文検索。"""
    q = """
    SELECT s.section_id, s.section_code, s.section_name_ja,
           d.doc_id, d.period_end, c.sec_code, c.company_name,
           snippet(ir_sections_fts, 0, '<<', '>>', ' … ', 30) AS snippet
    FROM ir_sections_fts
    JOIN ir_sections s ON s.section_id = ir_sections_fts.rowid
    JOIN ir_documents d ON s.doc_id = d.doc_id
    LEFT JOIN ir_companies c ON d.edinet_code = c.edinet_code
    WHERE ir_sections_fts MATCH ?
    """
    params: List[Any] = [query]
    if section_code:
        q += " AND s.section_code = ?"
        params.append(section_code)
    q += " AND d.is_latest = 1 ORDER BY bm25(ir_sections_fts) LIMIT ?"
    params.append(limit)
    with _conn(db_path) as c:
        rows = c.execute(q, params).fetchall()
    return [dict(r) for r in rows]


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
