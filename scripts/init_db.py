"""
全フェーズのスキーマを一括作成するスクリプト。
既存の financial_raw も含め、冪等。

使い方:
  python scripts/init_db.py
  python scripts/init_db.py --db /abs/path/to.db
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.config import load_config  # noqa: E402
from src.db.ir_schema import init_ir_schema  # noqa: E402
from src.db.phase2_schema import init_phase2_schema  # noqa: E402
from src.db.phase3_schema import init_phase3_schema  # noqa: E402
from src.db.schema import init_db as init_raw_db  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", help="DB パス (省略時は .env の DB_PATH)")
    args = ap.parse_args()

    db_path = args.db or load_config()["db_path"]
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

    init_raw_db(db_path)
    print(f"[OK] financial_raw -> {db_path}")
    init_ir_schema(db_path)
    print(f"[OK] ir_* (companies/documents/sections/figures + FTS5)")
    init_phase2_schema(db_path)
    print(f"[OK] ir_presentations / ir_presentation_slides + FTS5")
    init_phase3_schema(db_path)
    print(f"[OK] ir_generated_artifacts / ir_extracted_tables")


if __name__ == "__main__":
    main()
