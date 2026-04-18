"""
Phase 2: 決算説明資料 → ir_presentations / ir_presentation_slides への ETL。

入力:
- config/presentation_sources.json で定義されたソース
  - source_type=local: ローカルパスを再帰走査
  - source_type=gdrive: Drive フォルダを再帰走査 (GDriveSource)

ファイル名からの自動タグ付け:
- sec_code (4桁)
- 年度 (YYYY, FYYYYY, YYYYQn)
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.phase2_schema import Presentation, PresentationSlide, init_phase2_schema
from src.presentation.pdf_extractor import Slide, extract_pdf
from src.presentation.pptx_extractor import extract_pptx

logger = logging.getLogger(__name__)

_RE_SEC = re.compile(r"(?<!\d)(\d{4})(?!\d)")
_RE_FY = re.compile(r"FY?\s*(\d{4})(?:Q([1-4]))?", re.I)


@dataclass
class ParsedName:
    sec_code: Optional[str]
    fiscal_period: Optional[str]
    title: str


def _parse_filename(name: str) -> ParsedName:
    stem = Path(name).stem
    sec = _RE_SEC.search(stem)
    fy = _RE_FY.search(stem)
    fiscal_period = None
    if fy:
        fiscal_period = f"FY{fy.group(1)}" + (f"Q{fy.group(2)}" if fy.group(2) else "")
    return ParsedName(
        sec_code=sec.group(1) if sec else None,
        fiscal_period=fiscal_period,
        title=stem,
    )


def _extract(path: str) -> List[Slide]:
    ext = Path(path).suffix.lower()
    if ext == ".pdf":
        return extract_pdf(path)
    if ext == ".pptx":
        return extract_pptx(path)
    logger.warning(f"unsupported ext: {path}")
    return []


class PresentationEtl:
    def __init__(self, db_path: str):
        self.db_path = db_path
        init_phase2_schema(db_path)
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        self._SessionFactory = sessionmaker(bind=engine)

    def ingest_local_dir(self, root: str) -> int:
        paths: List[str] = []
        for ext in ("*.pdf", "*.pptx"):
            paths.extend(str(p) for p in Path(root).rglob(ext))
        count = 0
        for p in paths:
            try:
                self.ingest_file(
                    path=p,
                    source_type="local",
                    source_uri=p,
                    source_url=f"file://{os.path.abspath(p)}",
                    source_modified_at=datetime.utcfromtimestamp(os.path.getmtime(p)),
                )
                count += 1
            except Exception as e:
                logger.exception(f"failed: {p}: {e}")
        return count

    def ingest_file(
        self,
        path: str,
        source_type: str,
        source_uri: str,
        source_url: str,
        source_modified_at: Optional[datetime] = None,
    ) -> None:
        """
        単一ファイルをアップサート投入する。
        (source_type, source_uri) が一致する既存 Presentation があれば、
        modified_at を比較して未更新ならスキップ、更新済みならスライドを差し替え。
        """
        slides = _extract(path)
        if not slides:
            logger.info(f"no slides: {path}")
            return

        meta = _parse_filename(os.path.basename(path))
        ext = Path(path).suffix.lower().lstrip(".")

        with self._SessionFactory() as session:
            existing = (
                session.query(Presentation)
                .filter_by(source_type=source_type, source_uri=source_uri)
                .one_or_none()
            )

            if existing is not None:
                if (
                    source_modified_at is not None
                    and existing.source_modified_at is not None
                    and existing.source_modified_at >= source_modified_at
                ):
                    logger.info(f"skip (up-to-date): {path}")
                    return
                # スライドを丸ごと入れ替え
                session.query(PresentationSlide).filter_by(
                    presentation_id=existing.presentation_id
                ).delete()
                pres = existing
                pres.sec_code = meta.sec_code or pres.sec_code
                pres.fiscal_period = meta.fiscal_period or pres.fiscal_period
                pres.source_url = source_url or pres.source_url
                pres.source_modified_at = source_modified_at or pres.source_modified_at
                pres.file_type = ext
                pres.title = meta.title
            else:
                pres = Presentation(
                    sec_code=meta.sec_code,
                    fiscal_period=meta.fiscal_period,
                    source_type=source_type,
                    source_uri=source_uri,
                    source_url=source_url,
                    source_modified_at=source_modified_at,
                    file_type=ext,
                    title=meta.title,
                )
                session.add(pres)
                session.flush()

            for s in slides:
                session.add(PresentationSlide(
                    presentation_id=pres.presentation_id,
                    slide_no=s.slide_no,
                    slide_url=_slide_url(source_type, source_url, s.slide_no, ext),
                    title=s.title,
                    content_text=s.content_text,
                    has_table=1 if s.has_table else 0,
                    has_chart=1 if s.has_chart else 0,
                    char_count=s.char_count,
                ))
            session.commit()
            logger.info(f"ingested/updated {len(slides)} slides from {path}")


def _slide_url(source_type: str, source_url: str, slide_no: int, ext: str) -> str:
    """
    スライド個別 URL を組み立てる。
    - Drive + PDF: https://drive.google.com/file/d/<id>/view#page=<N>
    - Drive + PPTX: (個別アンカー無し) → 資料URLをそのまま
    - ローカル PDF: file://.../x.pdf#page=N
    - ローカル PPTX: file://.../x.pptx (アンカー無し)
    """
    if not source_url:
        return ""
    if ext == "pdf":
        return f"{source_url}#page={slide_no}"
    return source_url
