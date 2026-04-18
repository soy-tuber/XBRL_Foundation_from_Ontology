"""
EDINET を走査して「英文有報を提出している企業」を洗い出す調査スクリプト。

用途:
  飲食業 60 社の中で englishDocFlag=1 の書類を出したことがある企業を特定する。
  これらは IR 記載・開示品質の高い参考銘柄候補。

出力:
  ./data/english_filers_{scope}.json
  {
    "scanned_from": "YYYY-MM-DD",
    "scanned_to":   "YYYY-MM-DD",
    "filers": [
      {"sec_code": "7550", "filer_name": "...", "doc_ids": ["..."], "last_filing_date": "..."}
    ],
    "non_filers": [...]
  }

使い方:
  # 飲食業ホワイトリストの範囲で直近3年をスキャン
  python scripts/find_english_filers.py --years 3

  # 全上場企業をスキャン (APIレートに注意 / 半日かかるレベル)
  python scripts/find_english_filers.py --years 3 --all
"""

from __future__ import annotations

import argparse
import calendar
import json
import logging
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Set

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.config import load_config  # noqa: E402
from src.downloader.edinet_api_client import EdinetApiClient  # noqa: E402
from src.ir.restaurant_collector import _load_target_sec_codes  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

TARGET_DOC_TYPE_CODES = {"120", "130"}  # 有報 + 訂正有報


def _iter_days(years: int):
    today = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
    start = today - timedelta(days=years * 365)
    cur = start
    while cur <= today:
        yield cur.strftime("%Y-%m-%d")
        cur += timedelta(days=1)


def scan(years: int, scope: str = "restaurants") -> Dict:
    cfg = load_config()
    api = EdinetApiClient(cfg["api_key"])

    whitelist: Set[str] = set()
    if scope == "restaurants":
        whitelist = _load_target_sec_codes()
        logger.info(f"scope=restaurants, {len(whitelist)} sec_codes")

    english_docs: Dict[str, List[dict]] = defaultdict(list)
    all_seen: Dict[str, str] = {}

    days = list(_iter_days(years))
    logger.info(f"scanning {len(days)} days ({years} years)")

    start = days[0]
    end = days[-1]

    for i, d in enumerate(days):
        if i % 30 == 0:
            logger.info(f"day {i}/{len(days)} ({d})")
        try:
            resp = api.get_document_list(d)
            docs = resp.get("results", []) or []
            for doc in docs:
                if not isinstance(doc, dict):
                    continue
                if doc.get("docTypeCode") not in TARGET_DOC_TYPE_CODES:
                    continue
                sec = (doc.get("secCode") or "")[:4]
                if not sec:
                    continue
                if whitelist and sec not in whitelist:
                    continue
                all_seen[sec] = doc.get("filerName") or all_seen.get(sec, "")
                if str(doc.get("englishDocFlag")) in ("1", "True", "true"):
                    english_docs[sec].append({
                        "doc_id": doc.get("docID"),
                        "filer_name": doc.get("filerName"),
                        "submit_date": d,
                        "doc_type_code": doc.get("docTypeCode"),
                        "period_end": doc.get("periodEnd"),
                    })
        except Exception as e:
            logger.warning(f"skip {d}: {e}")
        time.sleep(1.0)

    filers = []
    for sec, entries in sorted(english_docs.items()):
        entries_sorted = sorted(entries, key=lambda x: x["submit_date"], reverse=True)
        filers.append({
            "sec_code": sec,
            "filer_name": entries_sorted[0].get("filer_name") or all_seen.get(sec, ""),
            "count": len(entries_sorted),
            "last_filing_date": entries_sorted[0]["submit_date"],
            "doc_ids": [e["doc_id"] for e in entries_sorted],
        })

    non_filers = [
        {"sec_code": sec, "filer_name": name}
        for sec, name in sorted(all_seen.items())
        if sec not in english_docs
    ]

    return {
        "scope": scope,
        "scanned_from": start,
        "scanned_to": end,
        "filers": filers,
        "non_filers": non_filers,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=3)
    ap.add_argument("--all", action="store_true", help="飲食業ホワイトリストを無視して全上場企業")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    scope = "all" if args.all else "restaurants"
    result = scan(args.years, scope=scope)
    out = args.out or f"data/english_filers_{scope}.json"
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[OK] {out}: filers={len(result['filers'])}, non_filers={len(result['non_filers'])}")
    for f in result["filers"]:
        print(f"  {f['sec_code']}  {f['filer_name']}  (count={f['count']}, last={f['last_filing_date']})")


if __name__ == "__main__":
    main()
