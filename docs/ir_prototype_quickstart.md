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

デフォルトは直近 1 年 × 120 (年次有報) のみ。プロトとしてはこれで十分。

```bash
# デフォルト (1年 × 120)
python -m src.ir.restaurant_collector

# 年数指定
python -m src.ir.restaurant_collector --years 3

# 訂正有報 (130) も含める
python -m src.ir.restaurant_collector --include-amendments

# ZIP は既にある場合 (既存 DL 資産を再利用)
python -m src.ir.restaurant_collector --skip-download
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

### 英文有報を出している企業の特定 (参考銘柄)

EDINET に英文有報を提出している企業 = IR 記載品質が高い参考銘柄。
`englishDocFlag=1` を走査して洗い出す:

```bash
# 飲食業ホワイトリストの範囲で直近3年をスキャン
python scripts/find_english_filers.py --years 3

# 出力: data/english_filers_restaurants.json
# {"filers": [{"sec_code": "...", "count": N, "last_filing_date": "..."}], ...}
```

`restaurant_collector` は `englishDocFlag=1` の書類を検知すると自動で type=4
(英文ZIP) も取得し、`*_en.zip` として保存。IR ETL 時に中の PDF を自動展開して
`ir_presentations` (source_type='edinet_english') に投入。対応する
`ir_documents.has_english_doc=True` と `ir_companies.has_english_filing=True`
を自動設定。

Streamlit タブ1 の「参考銘柄のみ (英文有報提出企業)」トグルで絞り込み可能。

### 各社 IR サイトの英文アニュアルレポート

EDINET に英文有報を出していなくても、IR サイトに英文 Annual Report PDF を置いている会社は多い。
`config/english_reports.json` に URL を登録 → 取得 & ETL:

```bash
python -m src.presentation.english_report_fetcher           # 全社
python -m src.presentation.english_report_fetcher --sec-code 3197
```

`ir_presentations` に `source_type='annual_en'` で入り、Phase 2 FTS で横断検索可能。

### RAG (埋め込み) 構築 — SQLite で完結

FTS5 (キーワード/BM25) に加え、LLM 埋め込みによるセマンティック検索を `ir_section_embeddings` に格納。

```bash
# 全セクション分の埋め込みを計算・保存
python scripts/build_embeddings.py

# モデル変更 / 先頭だけ試す
python scripts/build_embeddings.py --model gemini/text-embedding-004 --limit 50

# 本文が変わっていなければスキップ (source_hash 判定)。強制再計算は --force
```

- 格納は numpy float32 BLOB で SQLite 内に。外部ベクトル DB 不要
- クエリ時は全埋め込みを一括ロード → numpy 内積でコサイン (1万件程度なら十分)
- ハイブリッド検索は Reciprocal Rank Fusion (RRF) で FTS と semantic を結合
- Streamlit タブ⓪ "RAG 検索" で `fts / semantic / hybrid` 切替可能

### バイリンガル付与 (LLM フォールバック)

上記 1 (公式ラベル) と 2 (英文アニュアル) で埋まらない部分だけ LLM で補う。

```bash
python scripts/enrich_bilingual.py --target sections --limit 200
python scripts/enrich_bilingual.py --target slides
python scripts/enrich_bilingual.py --target all --force   # 再付与
```

`content_source='official_english'` の行はスキップされる (公式を LLM で上書きしない)。

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

### 英語データの出自 (3層フォールバック)

`ir_sections.content_source` で出自を明示する。

| 優先度 | content_source | 取得元 | 埋まる内容 |
| --- | --- | --- | --- |
| 1 | `native_xbrl_label` | EDINET 公式タクソノミ (jpcrp_cor の label-en linkbase) | `section_name_en` のみ (本文はなし) |
| 2 | `official_english` | 各社 IR サイトの英文アニュアル PDF / 英文有報 | 本文 (別 PDF のため `ir_presentations` 側に投入) |
| 3 | `llm_translated` | LLM フォールバック | `content_text_en` + `keywords_en` |

Phase 1 ETL は自動で 1 を埋める。2 は `config/english_reports.json` に URL を登録して
`python -m src.presentation.english_report_fetcher` で取得。
3 は `scripts/enrich_bilingual.py` で後付け (1/2 が埋まっている行はスキップ)。

### スキーマ・インデックス

- `ir_sections` / `ir_presentation_slides` それぞれに:
  - `content_text` (原文) / `content_text_en` (上記 2 or 3)
  - `keywords_ja` / `keywords_en` (カンマ区切り)
- FTS5 は単一テーブルに 4 カラム (+title) を indexing し、`bm25()` でスコアリング
- トークナイザは `trigram` (日本語・英語どちらにも効く)
- クエリ側で `{col1 col2}:(...)` のカラムフィルタを使い、`lang="ja"/"en"/"auto"` を切替
- 検索 UI: 英語で単語検索した方が trigram が素直に効くのは英語の空白分割のおかげ。
  JA クエリで取りこぼしが出る場合は `lang="en"` に切替 + 英語キーワードを投げるのが早い

## 既知の制約 (下書きにつき)

- `restaurant_companies.json` の `edinet_code` は一部スタブ。実運用前に EDINET コード表で上書き必要。
- 数値テーブル `ir_financial_figures` は「連結・当期」のみ。単体・前期を使うユースケースが出たらフィルタを緩める。
- `ir_sections.content_text` のクリーニングは初回版。LLM クリーニングを通した「clean2」カラムを別に持たせる設計もあり (未実装)。
- FTS5 は `trigram` トークナイザ。日本語形態素での精度が不足なら ICU か分かち書き前処理を検討。
- スキーマ変更 (新カラム追加) をした場合、既存 DB は一度削除するか、ALTER で追加してから `scripts/init_db.py` を再実行 (FTS 再構築は `INSERT INTO ir_sections_fts(ir_sections_fts) VALUES('rebuild');`)。
- Streamlit UI はエラー握りつぶし多め (プロト優先)。
