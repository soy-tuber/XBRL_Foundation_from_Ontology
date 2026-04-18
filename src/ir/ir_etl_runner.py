"""
IR 拡張スキーマへの ETL ランナー。

既存の EtlRunner が financial_raw を埋めているのに対し、こちらは:
- ir_companies (ヘッダー情報)
- ir_documents (提出書類メタ)
- ir_sections  (TextBlock 本文)
を埋める。

入力はダウンロード済みの ZIP ディレクトリ (既存 GDriveManager の構造を前提)。
ZIP 展開と XBRL パスの特定は既存 etl_runner.process_zip_file と同じ手順。
"""

from __future__ import annotations

import glob
import logging
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

from bs4 import BeautifulSoup
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.db.ir_schema import (
    Company, Document, FinancialFigure, Section, init_ir_schema,
)
from src.parser.context_handler import ContextHandler
from src.parser.metadata_extractor import MetadataExtractor
from src.parser.section_extractor import SectionExtractor, TaxonomyMapper

logger = logging.getLogger(__name__)


@dataclass
class DocHeader:
    doc_id: str
    sec_code: Optional[str]
    edinet_code: Optional[str]
    company_name: Optional[str]
    doc_type_code: Optional[str]
    period_start: Optional[date]
    period_end: Optional[date]
    submit_date: Optional[date]
    taxonomy_version: Optional[str]


_RE_TAXONOMY_VER = re.compile(r"jpcrp(\d{6})")


def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(s.strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _detect_taxonomy_version(xbrl_path: str) -> Optional[str]:
    """ファイル名・ヘッダに含まれる jpcrpYYYYMMDD から世代を推定。"""
    m = _RE_TAXONOMY_VER.search(os.path.basename(xbrl_path))
    if m:
        return m.group(1)[:4]
    return None


def _extract_doc_header(xbrl_path: str, doc_id: str) -> DocHeader:
    meta = MetadataExtractor.extract(xbrl_path)

    # 追加: 期間情報と EDINET コードを DEI タグから拾う
    with open(xbrl_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, "lxml-xml")

    def _first(pattern: str) -> Optional[str]:
        tag = soup.find(re.compile(pattern))
        return tag.text.strip() if tag and tag.text else None

    edinet_code = _first(r".*:EDINETCodeDEI$")
    doc_type_code = _first(r".*:DocumentTypeDEI$")
    period_start = _parse_date(_first(r".*:CurrentPeriodStartDateDEI$"))
    period_end = _parse_date(
        _first(r".*:CurrentPeriodEndDateDEI$")
        or _first(r".*:CurrentFiscalYearEndDateDEI$")
        or meta.get("fiscal_year_end")
    )

    return DocHeader(
        doc_id=doc_id,
        sec_code=meta.get("security_code"),
        edinet_code=edinet_code,
        company_name=meta.get("company_name"),
        doc_type_code=doc_type_code,
        period_start=period_start,
        period_end=period_end,
        submit_date=_parse_date(meta.get("filing_date")),
        taxonomy_version=_detect_taxonomy_version(xbrl_path),
    )


def _extract_figures(xbrl_path: str, doc_id: str) -> List[Dict]:
    """
    連結・当期/前期の主要数値だけを ir_financial_figures に投影する薄い抽出。
    重い全件 EAV は既存 financial_raw に任せる。
    """
    with open(xbrl_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, "lxml-xml")

    rows: List[Dict] = []
    for tag in soup.find_all(True):
        ctx = tag.get("contextRef")
        if not ctx:
            continue
        unit = tag.get("unitRef")
        if not unit:
            continue  # 数値のみ対象
        raw = (tag.text or "").strip()
        if not raw:
            continue
        # 文字列値はスキップ
        try:
            float(raw)
        except ValueError:
            continue

        is_consolidated = bool(re.search(r"(?<!Non)Consolidated", ctx)) and not re.search(r"NonConsolidated", ctx)
        is_current = bool(re.search(r"CurrentYear", ctx))
        if not (is_consolidated and is_current):
            continue

        rows.append({
            "doc_id": doc_id,
            "element_name": tag.name.split(":")[-1],
            "context_ref": ctx,
            "is_current": is_current,
            "is_consolidated": is_consolidated,
            "value": raw,
            "unit": unit,
            "decimals": tag.get("decimals"),
        })
    return rows


def _find_xbrl_in_zip(zip_path: str, temp_dir: str) -> Optional[str]:
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(temp_dir)
    xbrls = glob.glob(os.path.join(temp_dir, "**", "*.xbrl"), recursive=True)
    for xf in xbrls:
        if "PublicDoc" in xf:
            return xf
    return xbrls[0] if xbrls else None


def _doc_id_from_zip(zip_path: str) -> str:
    name = os.path.basename(zip_path)
    return name.split("_")[0] if "_" in name else os.path.splitext(name)[0]


class IrEtlRunner:
    def __init__(self, db_path: str):
        self.db_path = db_path
        init_ir_schema(db_path)
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        self._SessionFactory = sessionmaker(bind=engine)
        self._extractor = SectionExtractor(TaxonomyMapper())

    def run(self, source_dir: str, doc_type_filter: Optional[List[str]] = None) -> Dict[str, int]:
        """
        source_dir 配下の ZIP を走査し、IR テーブルへ書き込む。
        doc_type_filter を渡すと該当 docTypeCode のみ対象。
        """
        zips = glob.glob(os.path.join(source_dir, "**", "*.zip"), recursive=True)
        logger.info(f"[IR-ETL] target zips: {len(zips)}")
        stats = {"processed": 0, "sections": 0, "figures": 0, "errors": 0, "skipped": 0}

        for zip_path in zips:
            try:
                self._process_one(zip_path, stats, doc_type_filter)
            except Exception as e:
                stats["errors"] += 1
                logger.exception(f"[IR-ETL] failed: {zip_path}: {e}")

        self._mark_latest_versions()
        logger.info(f"[IR-ETL] done: {stats}")
        return stats

    def _process_one(
        self, zip_path: str, stats: Dict[str, int], doc_type_filter: Optional[List[str]]
    ) -> None:
        doc_id = _doc_id_from_zip(zip_path)
        tmp = tempfile.mkdtemp()
        try:
            xbrl_path = _find_xbrl_in_zip(zip_path, tmp)
            if not xbrl_path:
                stats["skipped"] += 1
                return

            header = _extract_doc_header(xbrl_path, doc_id)
            if doc_type_filter and header.doc_type_code not in doc_type_filter:
                stats["skipped"] += 1
                return

            sections = self._extractor.extract(xbrl_path, doc_id)
            figures = _extract_figures(xbrl_path, doc_id)

            with self._SessionFactory() as session:  # type: Session
                self._upsert_company(session, header)
                self._upsert_document(session, header, zip_path)
                # 再投入時の重複を避けるため、同 doc_id の既存 sections/figures を削除
                session.query(Section).filter(Section.doc_id == doc_id).delete()
                session.query(FinancialFigure).filter(FinancialFigure.doc_id == doc_id).delete()
                for s in sections:
                    # 初期状態: セクション名 (JA/EN) は公式タクソノミ由来で埋まっているが、
                    # 本文の英訳はまだ無い。content_source はラベルまでしか無いことを示す。
                    s.setdefault("content_source", "native_xbrl_label")
                    session.add(Section(**s))
                for f in figures:
                    session.add(FinancialFigure(**f))
                session.commit()

            stats["processed"] += 1
            stats["sections"] += len(sections)
            stats["figures"] += len(figures)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _upsert_company(self, session: Session, h: DocHeader) -> None:
        if not h.edinet_code:
            return
        existing = session.get(Company, h.edinet_code)
        if existing:
            if h.company_name and not existing.company_name:
                existing.company_name = h.company_name
            if h.sec_code and not existing.sec_code:
                existing.sec_code = h.sec_code
            return
        session.add(Company(
            edinet_code=h.edinet_code,
            sec_code=h.sec_code,
            company_name=h.company_name or "(unknown)",
        ))

    def _upsert_document(self, session: Session, h: DocHeader, zip_path: str) -> None:
        existing = session.get(Document, h.doc_id)
        is_amended = (h.doc_type_code == "130")
        if existing:
            existing.edinet_code = h.edinet_code or existing.edinet_code
            existing.sec_code = h.sec_code or existing.sec_code
            existing.doc_type_code = h.doc_type_code or existing.doc_type_code
            existing.period_start = h.period_start or existing.period_start
            existing.period_end = h.period_end or existing.period_end
            existing.submit_date = h.submit_date or existing.submit_date
            existing.is_amended = is_amended
            existing.taxonomy_version = h.taxonomy_version or existing.taxonomy_version
            existing.source_zip_path = zip_path
            return
        session.add(Document(
            doc_id=h.doc_id,
            edinet_code=h.edinet_code,
            sec_code=h.sec_code,
            doc_type_code=h.doc_type_code,
            period_start=h.period_start,
            period_end=h.period_end,
            submit_date=h.submit_date,
            is_amended=is_amended,
            is_latest=True,
            taxonomy_version=h.taxonomy_version,
            source_zip_path=zip_path,
        ))

    def _mark_latest_versions(self) -> None:
        """
        訂正報告書 (130) を考慮した is_latest/superseded_by の整合化。
        同一 (edinet_code, period_end) で submit_date が最大のものを is_latest=True にする。
        """
        with self._SessionFactory() as session:  # type: Session
            rows = session.query(Document).all()
            by_key: Dict[Tuple[Optional[str], Optional[date]], List[Document]] = {}
            for r in rows:
                by_key.setdefault((r.edinet_code, r.period_end), []).append(r)

            for group in by_key.values():
                if len(group) <= 1:
                    for g in group:
                        g.is_latest = True
                        g.superseded_by = None
                    continue
                group_sorted = sorted(
                    group,
                    key=lambda d: (d.submit_date or date.min),
                    reverse=True,
                )
                latest = group_sorted[0]
                latest.is_latest = True
                latest.superseded_by = None
                for older in group_sorted[1:]:
                    older.is_latest = False
                    older.superseded_by = latest.doc_id
            session.commit()
