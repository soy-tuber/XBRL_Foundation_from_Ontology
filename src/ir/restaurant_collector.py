"""
飲食業上場企業向けのエンドツーエンド収集スクリプト。

動作:
  1. config/restaurant_companies.json から対象企業を読み込む
  2. 直近 N 年分の EDINET 書類一覧を取得 (docTypeCode=120/130)
  3. 対象企業 (sec_code 一致) のみ ZIP ダウンロード
  4. IrEtlRunner で ir_documents / ir_sections / ir_financial_figures を更新

既存の monthly_collector との違い:
  - 業種フィルタ (sec_code ホワイトリスト)
  - 訂正報告書 (130) も取得
  - 本文 TextBlock を sections に展開

CLI:
  python -m src.ir.restaurant_collector --years 5
  python -m src.ir.restaurant_collector --years 1 --skip-download  # DLスキップ、ETLのみ
"""

from __future__ import annotations

import argparse
import calendar
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Set

# repo root を import パスに追加
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.config import load_config  # noqa: E402
from src.downloader.edinet_api_client import EdinetApiClient  # noqa: E402
from src.downloader.gdrive_manager import GDriveManager  # noqa: E402
from src.ir.ir_etl_runner import IrEtlRunner  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

TARGET_DOC_TYPE_CODES = {"120", "130"}  # 有報 + 訂正有報

_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "config",
    "restaurant_companies.json",
)


def _load_target_sec_codes(path: str = _CONFIG_PATH) -> Set[str]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {c["sec_code"] for c in data["companies"] if c.get("sec_code")}


def _month_range(years: int) -> List[str]:
    today = datetime.today().replace(day=1)
    months: List[str] = []
    cur = today
    for _ in range(years * 12):
        months.append(cur.strftime("%Y-%m"))
        # 前月へ
        prev_last = (cur - timedelta(days=1))
        cur = prev_last.replace(day=1)
    return list(reversed(months))


class RestaurantCollector:
    def __init__(self):
        cfg = load_config()
        self.api = EdinetApiClient(cfg["api_key"])
        self.drive = GDriveManager(base_path=cfg["drive_path"])
        self.etl = IrEtlRunner(db_path=cfg["db_path"])
        self.targets = _load_target_sec_codes()
        logger.info(f"target companies: {len(self.targets)} sec_codes")

    def run(self, years: int, skip_download: bool = False) -> None:
        months = _month_range(years)
        logger.info(f"processing months: {months[0]} .. {months[-1]} ({len(months)} months)")

        for ym in months:
            month_dir = self.drive.get_context_directory(ym)
            if not skip_download:
                self._download_month(ym)
            logger.info(f"[IR-ETL] month={ym}")
            self.etl.run(str(month_dir), doc_type_filter=list(TARGET_DOC_TYPE_CODES))

    def _download_month(self, ym: str) -> None:
        year, month = map(int, ym.split("-"))
        _, last_day = calendar.monthrange(year, month)
        start = datetime(year, month, 1)
        end = datetime(year, month, last_day)

        cur = start
        while cur <= end:
            date_str = cur.strftime("%Y-%m-%d")
            try:
                resp = self.api.get_document_list(date_str)
                docs = resp.get("results", []) or []
                matched = [
                    d for d in docs
                    if isinstance(d, dict)
                    and d.get("secCode")
                    and d.get("docTypeCode") in TARGET_DOC_TYPE_CODES
                    and d.get("secCode")[:4] in self.targets
                ]
                if matched:
                    logger.info(f"[DL] {date_str}: {len(matched)} matched")
                for d in matched:
                    self._download_one(d, date_str)
            except Exception as e:
                logger.error(f"[DL] {date_str} failed: {e}")
            cur += timedelta(days=1)
            time.sleep(1.5)

    def _download_one(self, doc: Dict, date_str: str) -> None:
        doc_id = doc.get("docID")
        sec_code = doc.get("secCode")
        filer = doc.get("filerName")
        if not doc_id:
            return
        ym = date_str[:7]
        save_path = self.drive.get_save_path_if_not_exists(
            year_month=ym,
            sec_code=sec_code,
            company_name=filer,
            filing_date=date_str,
            doc_id=doc_id,
        )
        if save_path is not None:
            try:
                content = self.api.download_document(doc_id)
                if content:
                    self.drive.save_file(content, ym, save_path.name)
                    time.sleep(1.0)
            except Exception as e:
                logger.error(f"[DL] {doc_id}: {e}")

        # 英文ZIP (type=4) を追加取得。filename は "*_en.zip" で区別
        if str(doc.get("englishDocFlag")) in ("1", "True", "true"):
            en_name = save_path.name.replace(".zip", "_en.zip") if save_path else f"{doc_id}_en.zip"
            en_dir = self.drive.get_context_directory(ym)
            if (en_dir / en_name).exists():
                return
            try:
                en_content = self.api.download_english_document(doc_id)
                if en_content:
                    self.drive.save_file(en_content, ym, en_name)
                    logger.info(f"[DL-EN] {doc_id}: saved {en_name}")
                    time.sleep(1.0)
            except Exception as e:
                logger.error(f"[DL-EN] {doc_id}: {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=5)
    ap.add_argument("--skip-download", action="store_true")
    args = ap.parse_args()
    RestaurantCollector().run(years=args.years, skip_download=args.skip_download)


if __name__ == "__main__":
    main()
