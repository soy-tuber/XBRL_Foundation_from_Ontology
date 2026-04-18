"""
Google Drive 上の決算説明資料を列挙・ダウンロードするソース。

認証:
- サービスアカウント JSON を GDRIVE_SERVICE_ACCOUNT_JSON (パス) に指定
- 共有ドライブの場合は supportsAllDrives=True を指定

設計:
- 「対象企業の最上位フォルダ」を config/presentation_sources.json で定義
- そのフォルダ配下を再帰走査し、pdf/pptx を列挙
- 差分同期はファイル modifiedTime をローカル state に保持

ここでは対話的に curl で Drive API を叩く選択肢を残すため、
インタフェースのみ軽く切ってある。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Iterator, List, Optional


@dataclass
class DriveFile:
    drive_id: str
    name: str
    mime_type: str
    modified_time: str
    parent_id: Optional[str] = None


class GDriveSource:
    """
    サービスアカウントで Drive API を叩く薄いラッパ。
    google-api-python-client と google-auth が必要。
    """

    SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

    def __init__(self, service_account_json: Optional[str] = None):
        self._sa_path = service_account_json or os.getenv("GDRIVE_SERVICE_ACCOUNT_JSON")
        self._service = None

    def _get_service(self):
        if self._service is not None:
            return self._service
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
        except ImportError as e:
            raise RuntimeError(
                "google-api-python-client が必要: "
                "pip install google-api-python-client google-auth"
            ) from e
        if not self._sa_path:
            raise RuntimeError("GDRIVE_SERVICE_ACCOUNT_JSON が未設定です")
        creds = service_account.Credentials.from_service_account_file(
            self._sa_path, scopes=self.SCOPES
        )
        self._service = build("drive", "v3", credentials=creds, cache_discovery=False)
        return self._service

    def list_files(self, folder_id: str, mime_types: Optional[List[str]] = None) -> Iterator[DriveFile]:
        mime_types = mime_types or [
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ]
        svc = self._get_service()
        mime_query = " or ".join(f"mimeType='{m}'" for m in mime_types)
        q = f"'{folder_id}' in parents and trashed=false and ({mime_query})"
        page_token = None
        while True:
            resp = svc.files().list(
                q=q,
                fields="nextPageToken, files(id, name, mimeType, modifiedTime, parents)",
                pageSize=200,
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
                pageToken=page_token,
            ).execute()
            for f in resp.get("files", []):
                yield DriveFile(
                    drive_id=f["id"],
                    name=f["name"],
                    mime_type=f["mimeType"],
                    modified_time=f.get("modifiedTime", ""),
                    parent_id=(f.get("parents") or [None])[0],
                )
            page_token = resp.get("nextPageToken")
            if not page_token:
                break

    def download(self, drive_id: str, dest_path: str) -> str:
        from googleapiclient.http import MediaIoBaseDownload
        svc = self._get_service()
        req = svc.files().get_media(fileId=drive_id, supportsAllDrives=True)
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        with open(dest_path, "wb") as fh:
            downloader = MediaIoBaseDownload(fh, req)
            done = False
            while not done:
                _, done = downloader.next_chunk()
        return dest_path


def load_sources(config_path: str) -> List[dict]:
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)["sources"]
