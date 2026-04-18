"""
Streamlit UI から叩く読み取り系クエリ。

生の SQL にしているのは FTS5 の MATCH を素直に書くため。
SQLAlchemy のセッションは使わず、sqlite3 直叩き。

FTS5 検索は SoyLM パターンを採用:
  日本語クエリ → LLM で日英キーワード抽出 → OR 結合で FTS5 MATCH
  助詞を含む日本語フレーズの trigram 空振り問題を根本解決。
"""

from __future__ import annotations

import logging
import re
import sqlite3
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger(__name__)


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
    FTS5 MATCH 式を組み立てる。

    SoyLM パターン: LLM で日英キーワード抽出 → OR 結合。
    LLM が使えない場合は助詞分割フォールバック。
    """
    keywords = _extract_search_keywords(query)
    q = _keywords_to_fts5(keywords)
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


def _extract_search_keywords(query: str) -> str:
    """
    SoyLM 由来: LLM でクエリから日英キーワードを抽出。
    LLM 非可用時は助詞分割フォールバック。
    """
    try:
        from src.ir.llm_client import LlmClient
        client = LlmClient()
        prompt = (
            "Translate to English, then list only the nouns. "
            "Output original Japanese nouns and English nouns, comma-separated. "
            "Max 8 words. Nothing else.\n\n"
            f"Q: Chromebookのセットアップ方法\n"
            f"A: Chromebook, setup, セットアップ\n\n"
            f"Q: サプライチェーンの価格高騰\n"
            f"A: supply chain, price surge, サプライチェーン, 価格, 高騰\n\n"
            f"Q: {query}\nA:"
        )
        raw = client.generate("", prompt, temperature=0.0)
        result = raw.strip().split("\n")[0].strip()
        if result:
            logger.info(f"[FTS] LLM keywords: {query!r} -> {result!r}")
            return result
    except Exception as e:
        logger.warning(f"[FTS] LLM keyword extraction failed, using fallback: {e}")
    return _fallback_split_ja(query)


_JA_PARTICLES = re.compile(
    r"[のをがはにでとも]|から|まで|より|について|における|に関する|による|として|および|ならびに|または"
)


def _fallback_split_ja(query: str) -> str:
    """LLM が使えない場合の助詞分割フォールバック。"""
    chunks = _JA_PARTICLES.split(query)
    terms = [c.strip() for c in chunks if c.strip() and len(c.strip()) >= 2]
    if not terms:
        terms = [query]
    # スペース区切りの英語トークンも拾う
    for t in query.split():
        if t.isascii() and len(t) >= 2:
            terms.append(t)
    return ", ".join(terms)


def _keywords_to_fts5(keywords: str) -> str:
    """
    SoyLM 由来: カンマ区切りキーワード → FTS5 OR 式。
    各キーワードを引用符で囲み OR 結合。
    """
    tokens = re.split(r"[,、]+", keywords)
    terms = []
    for t in tokens:
        cleaned = t.strip()
        if cleaned and len(cleaned) >= 2:
            terms.append(f'"{cleaned}"')
    if not terms:
        return '""'
    return " OR ".join(terms)


def fetch_sections_by_ids(
    db_path: str,
    section_ids: List[int],
) -> Dict[int, Dict[str, Any]]:
    """section_id リストから content_text を含むセクション情報を返す。"""
    if not section_ids:
        return {}
    placeholders = ",".join("?" * len(section_ids))
    with _conn(db_path) as c:
        rows = c.execute(
            f"""SELECT s.section_id, s.section_code, s.section_name_ja,
                       s.content_text, d.period_end, c.sec_code, c.company_name
                FROM ir_sections s
                JOIN ir_documents d ON s.doc_id = d.doc_id
                LEFT JOIN ir_companies c ON d.edinet_code = c.edinet_code
                WHERE s.section_id IN ({placeholders})""",
            section_ids,
        ).fetchall()
    return {r["section_id"]: dict(r) for r in rows}


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
