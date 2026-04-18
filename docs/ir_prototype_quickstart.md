# IR/法務支援 DB プロト クイックスタート

要件書: [requirements_ir_support_db.md](./requirements_ir_support_db.md)

既存の XBRL 基盤 (financial_raw EAV) に、IR 支援用の拡張テーブル群を追加し、Streamlit で 4 機能を触れる状態までを最小構成で実装した下書き。

## 構成 (差分)

```
config/
  restaurant_companies.json     # 対象企業リスト (sec_code ホワイトリスト)
  section_taxonomy.json         # XBRL要素名 → section_code 正規化辞書
src/
  db/ir_schema.py               # ir_companies / ir_documents / ir_sections / ir_financial_figures + FTS5
  parser/section_extractor.py   # TextBlock → クリーンテキスト抽出
  ir/
    ir_etl_runner.py            # ZIP → IR テーブル ETL
    restaurant_collector.py     # EDINET DL + ETL オーケストレータ
    queries.py                  # Streamlit 用読取クエリ (sqlite3 直叩き)
    llm_client.py               # Gemini API / ローカル OpenAI 互換 の共通 IF
app/
  streamlit_app.py              # 4 機能タブ UI
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

飲食業ホワイトリスト企業の直近 N 年分を取得して IR テーブルに流し込む:

```bash
# 直近1年で疎通確認
python -m src.ir.restaurant_collector --years 1

# 本番 (直近5年)
python -m src.ir.restaurant_collector --years 5

# ZIP は既にある場合 (既存 DL 資産を再利用)
python -m src.ir.restaurant_collector --years 5 --skip-download
```

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

## 既知の制約 (下書きにつき)

- `restaurant_companies.json` の `edinet_code` は一部スタブ。実運用前に EDINET コード表で上書き必要。
- 数値テーブル `ir_financial_figures` は「連結・当期」のみ。単体・前期を使うユースケースが出たらフィルタを緩める。
- `ir_sections.content_text` のクリーニングは初回版。LLM クリーニングを通した「clean2」カラムを別に持たせる設計もあり (未実装)。
- FTS5 は `unicode61` トークナイザ。日本語形態素での適合精度が不足なら ICU か分かち書き前処理を検討。
- Streamlit UI はエラー握りつぶし多め (プロト優先)。
