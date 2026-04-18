"""
ir_schema の smoke test。
- init_ir_schema が冪等に動くこと
- FTS5 (trigram) が日本語部分一致でヒットすること
"""

from __future__ import annotations

import os
import sqlite3
import tempfile

from src.db.ir_schema import init_ir_schema


def test_init_idempotent_and_fts_japanese_hit():
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "t.db")
        init_ir_schema(db)
        init_ir_schema(db)  # 再実行で壊れない

        conn = sqlite3.connect(db)
        conn.execute("INSERT INTO ir_documents (doc_id, edinet_code) VALUES ('S100X', 'E1')")
        conn.execute(
            """INSERT INTO ir_sections
               (doc_id, section_code, section_name_ja, content_text, content_text_en,
                keywords_ja, keywords_en, char_count)
               VALUES ('S100X', 'business_risks', 'リスク',
                       'サプライチェーン依存のリスクがあります',
                       'Risks due to supply chain dependency',
                       'サプライチェーン, リスク, 依存', 'supply chain, risk, dependency', 20)"""
        )
        conn.commit()

        # JP FTS ヒット
        rows = conn.execute(
            "SELECT section_code FROM ir_sections_fts WHERE ir_sections_fts MATCH ?",
            ("サプライチェーン",),
        ).fetchall()
        assert rows and rows[0][0] == "business_risks"

        # EN FTS ヒット (英語だけのクエリでも引ける)
        rows_en = conn.execute(
            "SELECT section_code FROM ir_sections_fts WHERE ir_sections_fts MATCH ?",
            ("supply chain",),
        ).fetchall()
        assert rows_en and rows_en[0][0] == "business_risks"
        conn.close()


if __name__ == "__main__":
    test_init_idempotent_and_fts_japanese_hit()
    print("OK")
