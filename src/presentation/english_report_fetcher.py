"""
公式英文アニュアルレポート / 英文有報 の取得と投入。

方針:
- 会社ごとの公式 PDF URL を config/english_reports.json に手動登録する運用
  (各社 IR サイトの URL 規則がバラバラなのでスクレイパー一元化は割に合わない)
- ダウンロード後は Phase2 の ir_presentations に source_type='annual_en' で投入
  → 既存の FTS5 インデックスと Streamlit 検索がそのまま使える

使い方:
  python -m src.presentation.english_report_fetcher
  python -m src.presentation.english_report_fetcher --sec-code 3197
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.config import load_config  # noqa: E402
from src.presentation.presentation_etl import PresentationEtl  # noqa: E402

logger = logging.getLogger(__name__)

_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "config",
    "english_reports.json",
)

_CACHE_DIR_DEFAULT = "data/english_reports_cache"


def _load_reports(path: str = _CONFIG_PATH) -> List[dict]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)["reports"]


def _safe_filename(url: str, sec_code: str, fiscal_period: str) -> str:
    h = hashlib.md5(url.encode("utf-8")).hexdigest()[:8]
    return f"{sec_code}_{fiscal_period}_{h}.pdf"


def _download(url: str, dest: str) -> None:
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as f:
        f.write(resp.content)


def fetch_and_ingest(
    db_path: str,
    cache_dir: str = _CACHE_DIR_DEFAULT,
    sec_code_filter: Optional[str] = None,
) -> int:
    etl = PresentationEtl(db_path=db_path)
    reports = _load_reports()
    n = 0
    for r in reports:
        if sec_code_filter and r["sec_code"] != sec_code_filter:
            continue
        url = r.get("url")
        if not url or url.startswith("REPLACE_"):
            logger.info(f"skip (no URL): {r['sec_code']} {r.get('fiscal_period')}")
            continue

        fname = _safe_filename(url, r["sec_code"], r.get("fiscal_period", "unknown"))
        local = os.path.join(cache_dir, fname)
        try:
            if not os.path.exists(local):
                logger.info(f"downloading {url} -> {local}")
                _download(url, local)
            etl.ingest_file(
                path=local,
                source_type=r.get("source_type", "annual_en"),
                source_uri=url,
                source_url=url,
                source_modified_at=datetime.utcfromtimestamp(os.path.getmtime(local)),
            )
            n += 1
        except Exception as e:
            logger.exception(f"failed: {r['sec_code']}: {e}")
    return n


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--sec-code")
    ap.add_argument("--cache-dir", default=_CACHE_DIR_DEFAULT)
    args = ap.parse_args()
    db = load_config()["db_path"]
    n = fetch_and_ingest(db, cache_dir=args.cache_dir, sec_code_filter=args.sec_code)
    print(f"[english_reports] ingested {n} reports")


if __name__ == "__main__":
    main()
