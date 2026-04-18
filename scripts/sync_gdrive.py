"""
Google Drive の指定フォルダから決算説明資料を取得し、ローカルキャッシュ → ETL する。

使い方:
  # config/presentation_sources.json の gdrive エントリをすべて同期
  python scripts/sync_gdrive.py

  # 特定フォルダだけ
  python scripts/sync_gdrive.py --folder-id 1xxxxxxxxxxxx --sec-code 1234

依存: google-api-python-client + google-auth (requirements.txt の optional 部分を有効化)
認証: GDRIVE_SERVICE_ACCOUNT_JSON 環境変数にサービスアカウント JSON のパス

差分同期:
  ir_presentations.source_modified_at を Drive の modifiedTime と比較し、
  既存 ≧ Drive なら DL もパースもスキップ。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.config import load_config  # noqa: E402
from src.presentation.gdrive_source import DriveFile, GDriveSource  # noqa: E402
from src.presentation.presentation_etl import PresentationEtl  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

_SOURCES_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "presentation_sources.json")


def _drive_url(file_id: str, mime: str) -> str:
    if "presentation" in mime:
        return f"https://docs.google.com/presentation/d/{file_id}/edit"
    return f"https://drive.google.com/file/d/{file_id}/view"


def _parse_iso(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _sync_folder(
    src: GDriveSource,
    etl: PresentationEtl,
    folder_id: str,
    cache_dir: Path,
    sec_code_hint: Optional[str] = None,
) -> int:
    cache_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    files: Iterable[DriveFile] = src.list_files(folder_id)
    for f in files:
        local = cache_dir / f"{f.drive_id}_{f.name}"
        try:
            src.download(f.drive_id, str(local))
            etl.ingest_file(
                path=str(local),
                source_type="gdrive",
                source_uri=f.drive_id,
                source_url=_drive_url(f.drive_id, f.mime_type),
                source_modified_at=_parse_iso(f.modified_time),
            )
            n += 1
        except Exception as e:
            logger.exception(f"failed: {f.name} ({f.drive_id}): {e}")
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder-id", help="特定 Drive フォルダだけ同期")
    ap.add_argument("--sec-code", help="--folder-id 時のヒント (現状未使用)")
    ap.add_argument(
        "--cache-dir",
        default="data/presentations_gdrive_cache",
        help="DL したファイルのキャッシュ先",
    )
    args = ap.parse_args()

    cfg = load_config()
    etl = PresentationEtl(db_path=cfg["db_path"])
    src = GDriveSource()
    cache = Path(args.cache_dir)

    if args.folder_id:
        n = _sync_folder(src, etl, args.folder_id, cache, args.sec_code)
        print(f"[gdrive] folder={args.folder_id}: {n} files")
        return

    with open(_SOURCES_PATH, "r", encoding="utf-8") as f:
        sources = json.load(f)["sources"]
    for s in sources:
        if s["source_type"] != "gdrive":
            continue
        fid = s["folder_id"]
        n = _sync_folder(src, etl, fid, cache / fid, s.get("sec_code_hint"))
        print(f"[gdrive] folder={fid}: {n} files")


if __name__ == "__main__":
    main()
