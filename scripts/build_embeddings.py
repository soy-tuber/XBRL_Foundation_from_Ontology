"""
ir_sections 全行の埋め込みを作成し ir_section_embeddings に格納する。

使い方:
  python scripts/build_embeddings.py                 # 全セクション
  python scripts/build_embeddings.py --limit 50      # 先頭50件だけ
  python scripts/build_embeddings.py --force         # source_hash が同じでも再計算
  python scripts/build_embeddings.py --model gemini/text-embedding-004
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.config import load_config  # noqa: E402
from src.ir.rag import DEFAULT_MODEL, build_embeddings  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    db = load_config()["db_path"]
    ok, ng = build_embeddings(
        db,
        model=args.model,
        limit=args.limit,
        batch_size=args.batch_size,
        force=args.force,
    )
    print(f"[OK] embeddings built: ok={ok}, ng={ng}")


if __name__ == "__main__":
    main()
