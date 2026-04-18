"""
Phase 3 (スタブ): スライド画像からマルチモーダル LLM で表を復元する。

現状の設計:
- 入力: PDF の該当ページ画像 or PPTX をレンダリングした画像
- 出力: ir_extracted_tables.json_table に格納する正規化 JSON
  { "columns": [...], "rows": [[...]], "meta": {"unit": "百万円", "period": "FY2024"} }

実装方針 (フェーズ1時点では未実装):
- Gemini 1.5 Pro / 2.0 Flash のマルチモーダルで画像 + プロンプトを投げる
- レンダリングは pdf2image か pymupdf
- 精度はプロンプトより「画像解像度」が支配的なので、300 DPI 以上を推奨
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class ExtractedTable:
    columns: list
    rows: list
    meta: Dict[str, Any]


def extract_table_from_image(
    image_path: str,
    caption: Optional[str] = None,
    *,
    llm_client=None,  # src.ir.llm_client.LlmClient
) -> ExtractedTable:
    """
    画像から表を復元する。未実装 (Phase 3 着手時に実装)。

    予定する I/F:
        table = extract_table_from_image("slide_42.png", caption="セグメント別売上")
        table.columns  # ["セグメント", "FY23", "FY24"]
        table.rows     # [["国内", 1000, 1200], ["海外", 500, 700]]
    """
    raise NotImplementedError(
        "Phase 3: マルチモーダル LLM による表抽出は未実装。"
        "Gemini multimodal + 300DPI レンダリング で実装予定。"
    )
