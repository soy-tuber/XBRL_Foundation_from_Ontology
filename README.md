# XBRL Analysis Pipeline Documentation

EDINET API v2を利用した有価証券報告書（XBRL）の自動収集・解析・データベース構築パイプラインツール。
取得データはSQLite形式で保存され、財務分析や機械学習の計算資源として利用可能。

## システム要件と環境構築 (Linux/Local)

本システムはLinux環境下でのローカル実行を前提としている。Python仮想環境の使用を標準とする。

### 前提条件
*   OS: Linux (Ubuntu 22.04 LTS等 推奨)
*   Python: 3.12以上推奨 (最低3.10)
*   Network: EDINET APIへのHTTPSアクセスが可能であること

### セットアップ手順

**1. リポジトリのクローンと移動**
```bash
git clone https://github.com/soy-tuber/XBRL_Foundation_from_Ontology.git
cd XBRL_Foundation_from_Ontology
```

**2. Python仮想環境の構築**
システム環境への干渉を防ぐため、`venv` モジュールを使用する。
```bash
# 仮想環境(.venv)の作成
python3 -m venv .venv

# 仮想環境のアクティベート
source .venv/bin/activate
```
※以降のコマンドは全て仮想環境下 (`(.venv)` 表記あり) で実行する。

**3. 依存ライブラリのインストール**
```bash
pip install -r requirements.txt
```

**4. 環境変数の設定 (.env)**
プロジェクトルートに `.env` ファイルを作成し、APIキーと保存先パスを設定する。

```bash
# .envファイルの作成例
touch .env
```

`.env` 記述内容:
```ini
# EDINET APIキー (EDINET公式サイトで取得)
EDINET_API_KEY=your_api_key_xxxxxxxx

# ダウンロードしたZIPファイルの保存先絶対パス (書込権限必須)
# 例: /home/user/data/edinet_store
EDINET_DRIVE_PATH=/path/to/your/storage_directory

# (任意) データベース保存パス (デフォルト: data/xbrl_financial.db)
# DB_PATH=data/xbrl_financial.db
```

## 実行コマンド一覧 (Terminal)

仮想環境 (`source .venv/bin/activate`) にて実行すること。

### データ収集・ETL実行

**単月処理 (Default: 年次有報のみ)**
指定した年月のデータを収集し、DBへ格納する。
```bash
# フォーマット: YYYY-MM
python3 -m src.pipeline.monthly_collector 2024-05
```

**単月処理 (All Types)**
四半期報告書などを含む全書類を取得する場合。
```bash
python3 -m src.pipeline.monthly_collector 2024-05 --all
```

**年間バッチ処理 (1年分)**
指定した年の1月〜12月を連続処理する。エラー発生時は該当月をスキップし継続する。
```bash
# フォーマット: YYYY
python3 src/pipeline/run_year_batch.py 2025
```

**長期間バッチ処理 (ループ実行)**
複数年（例: 5年、10年）を処理する場合はシェルスクリプトまたはループで対応する。
```bash
# 例: 2015年から2024年まで順次実行
for year in {2015..2024}; do python3 src/pipeline/run_year_batch.py $year; done
```

### データベース管理・確認

**DB状態確認**
レコード数、最新ドキュメントID、サンプルデータを表示する。
```bash
python3 src/tools/inspect_db.py
```

**テスト実行 (E2E Test)**
ごく少量のデータを用いて、ダウンロードからDB登録までの疎通を確認する。
```bash
python3 tests/test_e2e_flow.py
```

### トラブルシューティング

**依存関係の更新**
```bash
git pull origin main
pip install -r requirements.txt
```

**途中再開 (Resume)**
本システムは `processing_history.db` (または `_history.db`) により処理済みファイルを管理している。
処理が中断した場合でも、同じコマンドを再度実行することで未処理分のみが処理される。

## データベース仕様と活用案

### 格納先
デフォルトパス: `data/xbrl_financial.db`
ファイル形式: SQLite 3

### テーブル構造: `financial_raw`
EAV (Entity-Attribute-Value) モデルを採用。

| カラム名 | 説明 | 例 |
| :--- | :--- | :--- |
| `doc_id` | 書類管理ID | `S100xxxx` |
| `security_code` | 証券コード | `7203` |
| `period` | 期間/時点 | `Duration`, `Instant` |
| `tag_name` | XBRLタグ名 | `NetSales`, `OperatingIncome` |
| `raw_value` | 値 | `1000000`, `当社は...` |
| `context_id` | コンテキストID | `CurrentYearConsolidated` |
| `unit` | 単位 | `JPY`, `Shares` |

### データ活用案 (Use Cases)

生成された `xbrl_financial.db` を活用した分析・開発の例。

1.  **特定勘定科目のクロスセクション分析**
    *   `tag_name='NetSales'` でフィルタリングし、特定年度の全上場企業の売上ランキングを作成。
2.  **時系列トレンド分析**
    *   特定企業 (`security_code`) の `OperatingIncome` を過去10年分抽出し、成長率を算出。
3.  **財務指標 (KPI) の計算**
    *   `CurrentAssets` / `CurrentLiabilities` から流動比率を計算し、安全性スコアリングを行う。
4.  **テキストマイニングによるリスク検知**
    *   「事業等のリスク」に関連するテキストタグを抽出し、ネガティブワードの出現頻度を解析。
5.  **業界平均との乖離検知**
    *   同業種の財務平均値を算出し、異常値を即座に特定するスクリーニングツール。
6.  **会計方針変更の追跡**
    *   会計基準 (`AccountingStandards`) タグの経年変化を追い、基準変更の影響を可視化。
7.  **機械学習用データセット作成**
    *   財務数値を特徴量、翌年の株価変動をラベルとした予測モデルの学習データ生成。
8.  **LLM (RAG) のナレッジベース**
    *   テキストデータをベクトル化し、企業の経営方針に関する質問応答システムの構築。
9.  **監査・ガバナンスチェック**
    *   `AuditOpinion` 等のタグを確認し、適正意見以外の報告書を自動抽出。
10. **ダッシュボード構築**
    *   Streamlit等を用い、証券コードを入力すると財務サマリーを即座に可視化するWebアプリのバックエンドとして利用。
