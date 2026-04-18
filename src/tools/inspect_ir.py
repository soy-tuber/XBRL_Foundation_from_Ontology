"""
IR DB の状態確認ツール。既存の inspect_db.py が financial_raw を見るのに対し、
こちらは ir_* / Phase2 / Phase3 テーブル全体の健診を出す。

使い方:
  python -m src.tools.inspect_ir
  python -m src.tools.inspect_ir --db /abs/path/to.db
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from typing import Any, Dict, List

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.config import load_config  # noqa: E402


def _row_count(conn: sqlite3.Connection, tbl: str) -> int:
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
    except sqlite3.OperationalError:
        return -1


def _print_section(title: str):
    bar = "=" * 60
    print(f"\n{bar}\n {title}\n{bar}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db")
    args = ap.parse_args()
    db = args.db or load_config()["db_path"]
    if not os.path.exists(db):
        print(f"DB not found: {db}")
        sys.exit(1)

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row

    _print_section(f"DB: {db}")
    tables = [
        "financial_raw",
        "ir_companies", "ir_documents", "ir_sections", "ir_financial_figures",
        "ir_presentations", "ir_presentation_slides",
        "ir_extracted_tables", "ir_generated_artifacts",
    ]
    for t in tables:
        n = _row_count(conn, t)
        print(f"  {t:30s} : {n:>10,}" if n >= 0 else f"  {t:30s} : (missing)")

    _print_section("ir_documents 内訳")
    rows = conn.execute("""
        SELECT doc_type_code, COUNT(*) AS n,
               SUM(CASE WHEN is_amended THEN 1 ELSE 0 END) AS amended,
               SUM(CASE WHEN is_latest THEN 1 ELSE 0 END) AS latest
        FROM ir_documents GROUP BY doc_type_code ORDER BY n DESC
    """).fetchall()
    for r in rows:
        print(f"  type={r['doc_type_code'] or '?':5s}  n={r['n']:>5}  amended={r['amended']}  latest={r['latest']}")

    _print_section("ir_sections: section_code 別件数 Top 20")
    rows = conn.execute("""
        SELECT section_code, COUNT(*) AS n, AVG(char_count) AS avg_len
        FROM ir_sections GROUP BY section_code ORDER BY n DESC LIMIT 20
    """).fetchall()
    for r in rows:
        avg = int(r["avg_len"] or 0)
        print(f"  {r['section_code']:30s}  n={r['n']:>5}  avg_chars={avg:>6}")

    _print_section("ir_sections: バイリンガル付与率")
    n_total = _row_count(conn, "ir_sections")
    n_enriched = conn.execute(
        "SELECT COUNT(*) FROM ir_sections WHERE enriched_at IS NOT NULL AND enriched_at != ''"
    ).fetchone()[0]
    pct = (100.0 * n_enriched / n_total) if n_total else 0
    print(f"  enriched: {n_enriched}/{n_total} ({pct:.1f}%)")

    _print_section("ir_companies (Top 10 by sections)")
    rows = conn.execute("""
        SELECT c.sec_code, c.company_name, COUNT(s.section_id) AS n_sections
        FROM ir_companies c
        JOIN ir_documents d ON d.edinet_code = c.edinet_code
        JOIN ir_sections s ON s.doc_id = d.doc_id
        GROUP BY c.edinet_code ORDER BY n_sections DESC LIMIT 10
    """).fetchall()
    for r in rows:
        print(f"  {r['sec_code'] or '?':5s}  {r['company_name']:30s}  sections={r['n_sections']}")

    _print_section("ir_presentations / slides")
    pres = _row_count(conn, "ir_presentations")
    slides = _row_count(conn, "ir_presentation_slides")
    print(f"  presentations: {pres}, slides: {slides}")
    if slides > 0:
        en = conn.execute(
            "SELECT COUNT(*) FROM ir_presentation_slides WHERE enriched_at IS NOT NULL AND enriched_at != ''"
        ).fetchone()[0]
        print(f"  enriched: {en}/{slides} ({100.0 * en / slides:.1f}%)")
        tbl = conn.execute("SELECT COUNT(*) FROM ir_presentation_slides WHERE has_table=1").fetchone()[0]
        ch = conn.execute("SELECT COUNT(*) FROM ir_presentation_slides WHERE has_chart=1").fetchone()[0]
        print(f"  has_table: {tbl}, has_chart: {ch}")

    conn.close()


if __name__ == "__main__":
    main()
