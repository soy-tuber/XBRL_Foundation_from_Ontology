"""
ir_sections / ir_presentation_slides にバイリンガル列 (英訳 + キーワード) を
LLM で付与するスクリプト。

使い方:
  python scripts/enrich_bilingual.py --target sections --limit 50
  python scripts/enrich_bilingual.py --target slides --limit 100
  python scripts/enrich_bilingual.py --target all --force     # 再付与
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.config import load_config  # noqa: E402
from src.ir.bilingual_enricher import enrich_sections, enrich_slides  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", choices=["sections", "slides", "all"], default="sections")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    db = load_config()["db_path"]

    if args.target in ("sections", "all"):
        ok, ng = enrich_sections(db, limit=args.limit, force=args.force)
        print(f"[sections] ok={ok} ng={ng}")
    if args.target in ("slides", "all"):
        ok, ng = enrich_slides(db, limit=args.limit, force=args.force)
        print(f"[slides] ok={ok} ng={ng}")


if __name__ == "__main__":
    main()
