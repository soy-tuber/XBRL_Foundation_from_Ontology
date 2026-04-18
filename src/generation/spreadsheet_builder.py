"""
Phase 3 (スタブ): 推論結果を Google Sheets / Excel に出力する。

実装方針:
- ローカル出力は openpyxl で .xlsx
- Google Sheets への直接書き込みは google-api-python-client + sheets v4
- デザイン (罫線/色) は会社依存なので、最小装飾のみデフォルト

未実装。Phase 3 着手時に埋める。
"""

from __future__ import annotations

from typing import List

from src.generation.formula_inferrer import InferredFormula


def build_xlsx(output_path: str, table_json: dict, formulas: List[InferredFormula]) -> str:
    raise NotImplementedError("Phase 3: xlsx ビルダーは未実装。openpyxl で実装予定。")


def build_gsheet(spreadsheet_id: str, table_json: dict, formulas: List[InferredFormula]) -> str:
    raise NotImplementedError("Phase 3: Google Sheets 書き込みは未実装。sheets v4 API で実装予定。")
