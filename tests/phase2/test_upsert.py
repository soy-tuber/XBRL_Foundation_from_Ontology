"""
Phase2 ETL のアップサート挙動を検証する。
PDF/PPTX 抽出ライブラリを使わずに済むよう、抽出層をモンキーパッチでスタブ化。
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from datetime import datetime

import src.presentation.presentation_etl as etl_mod
from src.presentation.pdf_extractor import Slide
from src.presentation.presentation_etl import PresentationEtl


def _stub_extract(_path: str):
    return [Slide(slide_no=1, title="タイトル", content_text="本文 v1")]


def _stub_extract_v2(_path: str):
    return [
        Slide(slide_no=1, title="タイトル", content_text="本文 v2-page1"),
        Slide(slide_no=2, title="新タイトル", content_text="本文 v2-page2"),
    ]


def test_upsert_replaces_slides_when_modified():
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "u.db")
        etl = PresentationEtl(db_path=db)

        fake = os.path.join(td, "1234_FY2024.pdf")
        with open(fake, "wb") as f:
            f.write(b"%PDF dummy")

        # v1 投入
        etl_mod._extract = _stub_extract
        etl.ingest_file(
            path=fake, source_type="local", source_uri=fake,
            source_url=f"file://{fake}",
            source_modified_at=datetime(2024, 1, 1),
        )

        conn = sqlite3.connect(db)
        n1 = conn.execute("SELECT COUNT(*) FROM ir_presentation_slides").fetchone()[0]
        assert n1 == 1

        # 同じ modified_at で再投入 → スキップされ件数変わらず
        etl.ingest_file(
            path=fake, source_type="local", source_uri=fake,
            source_url=f"file://{fake}",
            source_modified_at=datetime(2024, 1, 1),
        )
        n2 = conn.execute("SELECT COUNT(*) FROM ir_presentation_slides").fetchone()[0]
        assert n2 == 1, f"expected skip, got {n2}"

        # 新しい modified_at + v2 抽出器 → 既存スライドが置換される
        etl_mod._extract = _stub_extract_v2
        etl.ingest_file(
            path=fake, source_type="local", source_uri=fake,
            source_url=f"file://{fake}",
            source_modified_at=datetime(2024, 6, 1),
        )
        rows = conn.execute(
            "SELECT slide_no, content_text FROM ir_presentation_slides ORDER BY slide_no"
        ).fetchall()
        assert len(rows) == 2
        assert rows[0][1] == "本文 v2-page1"
        # presentation 自体は同一行 (UNIQUE 制約により 1 行のまま)
        m = conn.execute("SELECT COUNT(*) FROM ir_presentations").fetchone()[0]
        assert m == 1
        conn.close()


if __name__ == "__main__":
    test_upsert_replaces_slides_when_modified()
    print("OK")
