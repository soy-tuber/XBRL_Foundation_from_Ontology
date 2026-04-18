from __future__ import annotations

import os
import sqlite3
import tempfile

from src.db.phase2_schema import init_phase2_schema


def test_init_phase2_and_fts_hit():
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "p2.db")
        init_phase2_schema(db)
        conn = sqlite3.connect(db)
        conn.execute("INSERT INTO ir_presentations (sec_code, title) VALUES ('1234', 'FY2024_決算説明会資料')")
        pres_id = conn.execute("SELECT presentation_id FROM ir_presentations").fetchone()[0]
        conn.execute(
            """INSERT INTO ir_presentation_slides
               (presentation_id, slide_no, slide_url, title, title_en, content_text, content_text_en,
                keywords_ja, keywords_en, char_count)
               VALUES (?, 1, 'file:///tmp/x.pdf#page=1',
                       '既存店売上', 'Same-store sales',
                       '既存店売上は前年同期比5.3%増加しました',
                       'Same-store sales increased 5.3% YoY',
                       '既存店, 売上', 'same-store, sales, YoY', 20)""",
            (pres_id,),
        )
        conn.commit()

        ja = conn.execute(
            "SELECT title FROM ir_slides_fts WHERE ir_slides_fts MATCH ?",
            ("既存店",),
        ).fetchall()
        assert ja
        # FTS5 は '-' を演算子とみなすため、英語フレーズは空白区切り or ダブルクオート必須
        en = conn.execute(
            "SELECT title FROM ir_slides_fts WHERE ir_slides_fts MATCH ?",
            ('"same-store"',),
        ).fetchall()
        assert en
        conn.close()


if __name__ == "__main__":
    test_init_phase2_and_fts_hit()
    print("OK")
