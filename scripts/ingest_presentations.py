"""
決算説明資料をローカルディレクトリから投入するスクリプト。

使い方:
  python scripts/ingest_presentations.py --root data/presentations_local
  python scripts/ingest_presentations.py            # config/presentation_sources.json の local ソースを走査
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.config import load_config  # noqa: E402
from src.presentation.presentation_etl import PresentationEtl  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

_SOURCES_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "presentation_sources.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", help="走査するローカルディレクトリ (指定時は sources.json を無視)")
    args = ap.parse_args()

    cfg = load_config()
    etl = PresentationEtl(db_path=cfg["db_path"])

    if args.root:
        n = etl.ingest_local_dir(args.root)
        print(f"ingested {n} presentations from {args.root}")
        return

    with open(_SOURCES_PATH, "r", encoding="utf-8") as f:
        sources = json.load(f)["sources"]
    for s in sources:
        if s["source_type"] == "local":
            path = s["path"]
            if os.path.isdir(path):
                n = etl.ingest_local_dir(path)
                print(f"ingested {n} from {path}")
            else:
                print(f"skip (missing dir): {path}")
        elif s["source_type"] == "gdrive":
            print(f"[TODO] gdrive source: {s}")
        else:
            print(f"unknown source_type: {s['source_type']}")


if __name__ == "__main__":
    main()
