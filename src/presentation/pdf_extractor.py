"""
PDF → スライド単位テキスト抽出。pdfminer.six を使用。
表・図のメタ (has_table/has_chart) は OCR なしでは精度が出ないので、
ヒューリスティクス (罫線/数字密度) で初期判定し、本格判定は後工程の LLM に回す。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Slide:
    slide_no: int
    title: Optional[str] = None
    content_text: str = ""
    has_table: bool = False
    has_chart: bool = False

    @property
    def char_count(self) -> int:
        return len(self.content_text)


_RE_NUM_DENSITY = re.compile(r"[\d,\.]{3,}")
_RE_TABLE_HINT = re.compile(r"[│┃┆┇┊┋]|[-=]{3,}")


def extract_pdf(path: str) -> List[Slide]:
    try:
        from pdfminer.high_level import extract_pages
        from pdfminer.layout import LTTextContainer
    except ImportError as e:
        raise RuntimeError("pdfminer.six が必要です: pip install pdfminer.six") from e

    slides: List[Slide] = []
    for i, page in enumerate(extract_pages(path), start=1):
        texts = []
        for el in page:
            if isinstance(el, LTTextContainer):
                texts.append(el.get_text())
        body = "\n".join(texts).strip()
        if not body:
            continue
        first_line = body.split("\n", 1)[0].strip()[:120]
        slides.append(Slide(
            slide_no=i,
            title=first_line if len(first_line) <= 80 else None,
            content_text=body,
            has_table=bool(_RE_TABLE_HINT.search(body)) or len(_RE_NUM_DENSITY.findall(body)) >= 5,
            has_chart=False,  # PDF からチャート検出は困難。後工程で LLM マルチモーダル
        ))
    return slides
