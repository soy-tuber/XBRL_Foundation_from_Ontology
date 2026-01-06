# XBRL Analysis Pipeline

EDINETから有価証券報告書（XBRL）をダウンロードし、SQLiteデータベースへ格納するためのパイプラインツールです。
「まるっとわかるXBRL入門」シリーズのコードをベースに、大量データのバッチ処理向けにリファクタリングされています。

## 主な機能

- **自動ダウンロード**: EDINET API v2を利用して指定期間のレポートを取得
- **ローカル保存**: Google Drive（または任意のローカルパス）にZIPファイルを整理して保存
- **パース処理**: XBRLファイルから財務数値と主要なテキスト情報を抽出（テキストブロックは除外）
- **データベース格納**: SQLiteを使用したEAV（Entity-Attribute-Value）モデルでの柔軟なデータ蓄積
- **並列処理**: マルチプロセスによる高速なパース処理
- **レジューム機能**: 処理済みファイルをスキップし、中断箇所から再開可能

## クイックスタート（実行コマンド例）

Linux環境での典型的な実行手順です。

```bash
# 1. プロジェクトフォルダに移動
cd XBRL_Foundation_from_Ontology

# 2. 最新のコードを取得
git pull origin main

# 3. 仮想環境をアクティベート（環境に合わせてパス調整）
# まだ作成していない場合: python3 -m venv .venv
source .venv/bin/activate

# 4. 依存ライブラリ更新（更新があった場合）
pip install -r requirements.txt

# 5. 月次データの収集とDB登録（例: 2024年5月分）
# ※デフォルトで「有価証券報告書(年次)」のみを収集します
python3 -m src.pipeline.monthly_collector 2024-05
```

## ディレクトリ構成

```
.
├── src/
│   ├── downloader/  # EDINET API & ファイル保存機能
│   ├── parser/      # XBRLパース & 正規化ロジック
│   ├── db/          # データベース定義 & バルクインサート
│   ├── pipeline/    # 実行スクリプト (monthly_collector.py)
│   └── executor.py  # 並列処理エグゼキュータ
├── data/            # SQLiteデータベース保存先 (デフォルト)
├── tests/           # テストコード
└── requirements.txt # 依存ライブラリ
```

## セットアップ手順

### 1. リポジトリのクローン
```bash
git clone https://github.com/soy-tuber/XBRL_Foundation_from_Ontology.git
cd XBRL_Foundation_from_Ontology
```

### 2. 依存ライブラリのインストール
Python 3.12以上推奨。
```bash
pip install -r requirements.txt
```

### 3. 環境変数の設定
プロジェクトルートに `.env` ファイルを作成し、以下の情報を記述してください。

```env
# EDINET APIのエンドツーエンド利用に必要（アカウント登録が必要）
EDINET_API_KEY=your_api_key_here

# ダウンロードしたZIPファイルの保存先（絶対パス推奨）
# Windows Example: D:\GoogleDrive\XBRL_Data
# Linux/Mac Example: /Users/username/my_drive_mount/xbrl_data
EDINET_DRIVE_PATH=/absolute/path/to/save/files

# (任意) SQLiteデータベースのパス
# DB_PATH=data/xbrl_financial.db
```

## 実行方法

### 月次データ収集（推奨）
指定した年月のデータを一括でダウンロードし、DBへ格納します。

```bash
# 例: 2024年6月のデータを処理
python src/pipeline/monthly_collector.py 2024-06
```

### 動作確認（E2Eテスト）
API接続、保存、パース、DB格納の一連の流れを少量のデータでテストします。
```bash
python tests/test_e2e_flow.py
```

## データベース仕様
データは `financial_raw` テーブルに格納されます。

- **doc_id**: 書類管理ID
- **element_id**: XBRLタグ名（例: `NetSales`, `OperatingIncome`）
- **value**: 数値（Rawデータ）または短いテキスト
- **context_ref**: コンテキスト（連結/単体、期間などの属性）
- **unit_ref**: 単位（JPY, Sharesなど）
- **decimals**: 精度
