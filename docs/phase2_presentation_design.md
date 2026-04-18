# Phase 2 設計メモ: 決算説明資料検索

## 目的
Google Drive / ローカルに蓄積した決算説明資料 (PDF/PPTX) を、IR/CFO が検索・参照できる基盤を作る。有報とクロスで引ける状態にする。

## スキーマ (同一 SQLite 内)
- `ir_presentations`: 資料単位
- `ir_presentation_slides`: スライド単位 (content_text, has_table, has_chart)
- `ir_slides_fts`: 日本語 trigram FTS5

## データフロー
```
[GDrive or local dir]
    → GDriveSource.list_files / rglob
    → pdf_extractor / pptx_extractor (Slide[])
    → PresentationEtl._ingest_one
    → ir_presentations + ir_presentation_slides + FTS同期
```

## 抽出の限界 (Phase3 への橋渡し)
- `has_table` / `has_chart` はヒューリスティクス。精度が必要な行は Phase3 のマルチモーダル抽出へ回す。
- PPTX 内のチャートは数値系列を python-pptx で拾えるが、PDF は画像化されたグラフが多く、OCR + LLM が必要。

## 差分同期 (未実装)
- Drive の `modifiedTime` と `ir_presentations.source_uri` のレコードをキーに upsert
- 現状 `ingest_local_dir` は重複挿入を防がない (プロト優先)。キー `(source_type, source_uri)` で unique 制約を後で入れる。

## UI (Streamlit タブ2)
- キーワード検索 (FTS5 MATCH)
- sec_code フィルタ
- 表/図フラグでアイコン表示
- スニペットでヒット箇所をハイライト

## TODO
- [ ] `ingest_local_dir` に upsert
- [ ] GDrive 同期の CLI (`scripts/sync_gdrive.py`)
- [ ] スライド → PNG レンダリングキャッシュ (Phase3 入力)
- [ ] 会社名の正規化 (資料ファイル名ゆらぎ対策)
