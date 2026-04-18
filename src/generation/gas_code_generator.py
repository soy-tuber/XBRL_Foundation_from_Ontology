"""
Phase 3 (スタブ): Google Apps Script (GAS) コードの自動生成。

ユースケース:
- 決算説明資料の「セグメント別売上前年対比」のような表を、
  来期以降も自動更新できる Sheets + GAS セットとして納品する。

方針:
- テンプレート (trigger + Sheets API 利用) を埋めるだけの差分生成
- LLM には「どのセルに何を書き、どのセルを編集可能にするか」の設計を書かせる
- 出力は .gs テキストファイル (Apps Script エディタに貼り付け前提)
"""

from __future__ import annotations


def generate_gas_script(spec_json: dict) -> str:
    raise NotImplementedError("Phase 3: GAS 生成は未実装。テンプレート + LLM 差分生成で実装予定。")
