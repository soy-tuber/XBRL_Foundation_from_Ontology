# Phase 3 設計メモ: スプレッドシート/GAS 生成

## 目的
決算説明資料の表・グラフから、来期以降も自動更新できる Google Sheets + Apps Script をアウトプットする。会社ごとのデザインは追わず、構造 (数値関係・更新ロジック) に集中。

## パイプライン
```
[ir_presentation_slides] (has_table=1)
    → スライド画像レンダリング (pdf2image / pymupdf)
    → table_extractor (マルチモーダル LLM)
    → ir_extracted_tables.json_table
    → formula_inferrer (数値関係 → 数式候補)
    → spreadsheet_builder (xlsx or Sheets)
    → gas_code_generator (更新 GAS)
    → ir_generated_artifacts
```

## 主要モジュール (すべて Phase1 時点では NotImplementedError)
- `src/generation/table_extractor.py`
- `src/generation/formula_inferrer.py`
- `src/generation/spreadsheet_builder.py`
- `src/generation/gas_code_generator.py`

## 検証ポイント (着手時)
1. **マルチモーダル精度**: Gemini 1.5 Pro / 2.0 Flash で日本語表をどこまで再現できるか。
   - 罫線ありテーブル、罫線なしテーブル、棒グラフ+数値ラベル、円グラフ の 4 ケースで Eval
   - レンダリング解像度を 150 / 300 / 600 DPI で振る
2. **数式推論のカバレッジ**: 実サンプルでの PL 構造再現率
3. **GAS 生成の実用性**: 手直しなしで動く比率

## 非スコープ
- デザイン自動生成 (罫線色・ブランドカラー) は会社依存のため扱わない
- ダッシュボード UI は作らない

## UI 統合 (後回し)
- Streamlit にタブ追加は可能だが、プロト段階では CLI で回す
- `scripts/generate_sheet.py --presentation-id N --slide N` のような形
