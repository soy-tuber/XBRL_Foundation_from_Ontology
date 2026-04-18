"""
Phase 3 (スタブ): 抽出済みの表データから計算式を推論する。

例:
  入力: [["売上", 1000, 1200], ["売上原価", 600, 700], ["売上総利益", 400, 500]]
  推論: 売上総利益行 = 売上 - 売上原価 (行3 = 行1 - 行2)

方針:
- 加減算・比率・成長率 の 3 パターンを数値検証で候補化
- LLM は列/行ヘッダの意味解釈と命名に使う
- 確信度スコアを付けて出力する

ここではインタフェースのみ定義。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class InferredFormula:
    target_cell: str      # 例: "C5"
    formula: str          # 例: "=C2-C3"
    description: str      # 例: "売上総利益 = 売上 - 売上原価"
    confidence: float     # 0.0 - 1.0


def infer_formulas(table_json: dict) -> List[InferredFormula]:
    raise NotImplementedError(
        "Phase 3: 数式推論は未実装。"
        "加減算マッチング → LLM 命名 → 確信度スコアリング の3段構成で実装予定。"
    )
