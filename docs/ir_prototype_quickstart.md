# IR/法務支援 DB プロト クイックスタート

要件書: [requirements_ir_support_db.md](./requirements_ir_support_db.md)

既存の XBRL 基盤 (financial_raw EAV) に、IR 支援用の拡張テーブル群を追加し、Streamlit で 4 機能を触れる状態までを最小構成で実装した下書き。

## 構成 (全フェーズ)

```
.env.example                       # 環境変数テンプレ
config/
  restaurant_companies.json        # [P1] 対象企業ホワイトリスト
  section_taxonomy.json            # [P1] XBRL要素名 → section_code 辞書
  compliance_rules.json            # [P1] コンプラルール (外出し)
  disclosure_events.json           # [P1] 適時開示事由 (外出し)
  presentation_sources.json        # [P2] 決算説明資料の取得元
src/
  db/
    schema.py                      # 既存: financial_raw (EAV)
    ir_schema.py                   # [P1] ir_companies/documents/sections/figures + FTS5
    phase2_schema.py               # [P2] ir_presentations/slides + FTS5
    phase3_schema.py               # [P3] ir_generated_artifacts/extracted_tables
  parser/
    section_extractor.py           # [P1] TextBlock → セクション本文
  ir/
    ir_etl_runner.py               # [P1] ZIP → IR テーブル
    restaurant_collector.py        # [P1] EDINET DL + ETL
    llm_client.py                  # 共通: Gemini / ローカル OpenAI 互換
    rule_loader.py                 # [P1] config/*.json ローダー
    queries.py                     # [P1] Streamlit 読取クエリ
  presentation/                    # [P2]
    pdf_extractor.py
    pptx_extractor.py
    gdrive_source.py
    presentation_etl.py
    queries.py
  generation/                      # [P3] (NotImplementedError で雛形のみ)
    table_extractor.py
    formula_inferrer.py
    spreadsheet_builder.py
    gas_code_generator.py
app/
  streamlit_app.py                 # 4 機能タブ UI (P1:3機能 + P2:検索)
scripts/
  init_db.py                       # 全スキーマ一括作成 (冪等)
  ingest_presentations.py          # [P2] ローカル資料の投入
tests/
  test_ir_schema.py
  test_section_extractor.py
  test_rule_loader.py
  phase2/test_phase2_schema.py
  phase3/test_phase3_schema.py
docs/
  requirements_ir_support_db.md    # 要件書
  ir_prototype_quickstart.md       # このファイル
  phase2_presentation_design.md    # P2 設計メモ
  phase3_generation_design.md      # P3 設計メモ
```

## セットアップ

既存 README のセットアップに加え:

```bash
pip install -r requirements.txt   # streamlit 追加
```

`.env` に以下を追記:

```ini
# 既存
EDINET_API_KEY=...
EDINET_DRIVE_PATH=/abs/path
DB_PATH=data/xbrl_financial.db

# LLM バックエンド (どちらか)
LLM_BACKEND=gemini               # or local
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-1.5-pro

# ローカル LLM (Nemotron 等) を使う場合
# LLM_BACKEND=local
# LOCAL_LLM_ENDPOINT=http://127.0.0.1:8000/v1
# LOCAL_LLM_MODEL=nemotron
# LOCAL_LLM_API_KEY=             # 任意
```

## データ投入

### Phase 1 (有報)

```bash
# 直近1年で疎通確認
python -m src.ir.restaurant_collector --years 1

# 本番 (直近5年)
python -m src.ir.restaurant_collector --years 5

# ZIP は既にある場合 (既存 DL 資産を再利用)
python -m src.ir.restaurant_collector --years 5 --skip-download
```

### Phase 2 (決算説明資料)

```bash
# ローカル投入
python scripts/ingest_presentations.py --root /path/to/pdfs_pptx

# sources.json の local を走査
python scripts/ingest_presentations.py
```

### Google Drive 同期 (Phase 2)

```bash
# config/presentation_sources.json の gdrive エントリすべて同期
python scripts/sync_gdrive.py

# 特定フォルダだけ
python scripts/sync_gdrive.py --folder-id 1xxxxxxxxxxxx
```

差分同期: `ir_presentations.source_modified_at` と Drive の `modifiedTime` を比較し、未更新ならスキップ。
更新済みのファイルはスライドを置換。

### デモデータ投入 (EDINET / Drive 不要)

```bash
python scripts/seed_demo_data.py            # ダミー3社×2期+資料1本を入れる
python scripts/seed_demo_data.py --reset    # 既存デモを消してから入れ直し
```

Streamlit を最短で触りたいときに使う。本物データと混ざらないよう `DEMO_*` プレフィックス。

### DB 状態確認

```bash
python -m src.tools.inspect_db    # 既存: financial_raw 系
python -m src.tools.inspect_ir    # 新: ir_* / phase2 / phase3 全体
```

### バイリンガル付与 (Phase 1 / 2 共通)

英訳とキーワード (JA/EN) を LLM で付与すると、FTS5+BM25 の精度が上がる。

```bash
python scripts/enrich_bilingual.py --target sections --limit 200
python scripts/enrich_bilingual.py --target slides
python scripts/enrich_bilingual.py --target all --force   # 再付与
```

enrich_at が埋まっている行はデフォルトでスキップされる。

注意:

- 対象企業は `config/restaurant_companies.json` の `sec_code` で絞る。現状 10 社のスタブ。
  上場企業コード表と業種フィルタで 60 社まで拡充する。
- `section_taxonomy.json` は 2014/2019/2023 世代の要素名揺れを吸収する前提の辞書。
  カバレッジは `ir_sections` の `section_code='other'` を定期的にチェックして追加していく。

## UI 起動

```bash
streamlit run app/streamlit_app.py
```

## データクリーニングの泥臭い部分について

`section_extractor.clean_textblock_html` は BeautifulSoup + 正規表現の一次クリーニング。
OCR 崩れ・表の潰れ・目次残骸など残るので、仕上げは Claude Code から以下のように curl で LLM を叩いて対話的に掃除する想定:

```bash
# Gemini
curl -s "https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}:generateContent?key=${GEMINI_API_KEY}" \
  -H 'Content-Type: application/json' \
  -d @payload.json

# ローカル (OpenAI 互換)
curl -s "${LOCAL_LLM_ENDPOINT}/chat/completions" \
  -H 'Content-Type: application/json' \
  -d @payload.json
```

同じ処理を Python から呼びたい場合は `src.ir.llm_client.LlmClient.generate(system, user)` を使う。`clean_section_with_llm(text)` が `CLEAN_SECTION_SYSTEM` プロンプトのプリセット。

## バイリンガル検索の設計

- `ir_sections` / `ir_presentation_slides` それぞれに:
  - `content_text` (原文) / `content_text_en` (LLM 翻訳)
  - `keywords_ja` / `keywords_en` (LLM 抽出、カンマ区切り)
- FTS5 は単一テーブルに 4 カラム (+title) を indexing し、`bm25()` でスコアリング
- トークナイザは `trigram` (日本語・英語どちらにも一応効く)
- クエリ側で `{col1 col2}:(...)` のカラムフィルタを使い、`lang="ja"/"en"/"auto"` を切替
- 検索 UI: 英語で単語検索した方が trigram が素直に効くのは英語の空白分割のおかげ。
  JA クエリで取りこぼしが出る場合は `lang="en"` に切替 + LLM で英訳してから投げるのが早い

## 既知の制約 (下書きにつき)

- `restaurant_companies.json` の `edinet_code` は一部スタブ。実運用前に EDINET コード表で上書き必要。
- 数値テーブル `ir_financial_figures` は「連結・当期」のみ。単体・前期を使うユースケースが出たらフィルタを緩める。
- `ir_sections.content_text` のクリーニングは初回版。LLM クリーニングを通した「clean2」カラムを別に持たせる設計もあり (未実装)。
- FTS5 は `trigram` トークナイザ。日本語形態素での精度が不足なら ICU か分かち書き前処理を検討。
- スキーマ変更 (新カラム追加) をした場合、既存 DB は一度削除するか、ALTER で追加してから `scripts/init_db.py` を再実行 (FTS 再構築は `INSERT INTO ir_sections_fts(ir_sections_fts) VALUES('rebuild');`)。
- Streamlit UI はエラー握りつぶし多め (プロト優先)。
