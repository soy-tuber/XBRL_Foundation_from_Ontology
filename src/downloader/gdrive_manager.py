import os
import logging
from datetime import datetime
from pathlib import Path
import re
from typing import Optional, Union

logger = logging.getLogger(__name__)

class GDriveManager:
    """
    Google Drive（マウントされたローカルパス）上でのファイル保存、
    フォルダ管理、重複チェックを行うマネージャクラス。
    """

    def __init__(self, base_path: Optional[str] = None):
        """
        Args:
            base_path (str, optional): Google Driveのデータ保存ルートパス。
                                       指定がない場合、環境変数 `EDINET_DRIVE_PATH` を参照する。
        """
        self.base_path = base_path or os.getenv("EDINET_DRIVE_PATH")
        
        if not self.base_path:
            raise ValueError(
                "Base path is not set. Provide `base_path` argument or set `EDINET_DRIVE_PATH` environment variable."
            )
        
        # パスをPathオブジェクト化
        self.base_path = Path(self.base_path)
        self._check_mount()

    def _check_mount(self):
        """
        保存先のルートパスがアクセス可能（マウントされている）か確認する。
        """
        if not self.base_path.exists():
            error_msg = f"Mount check failed: Base path does not exist: {self.base_path}"
            logger.critical(error_msg)
            raise FileNotFoundError(error_msg)
        
        if not os.access(self.base_path, os.W_OK):
            error_msg = f"Mount check failed: Base path is not writable: {self.base_path}"
            logger.critical(error_msg)
            raise PermissionError(error_msg)

        logger.info(f"Google Drive mount confirmed at: {self.base_path}")

    def get_context_directory(self, target_date: Union[str, datetime]) -> Path:
        """
        対象年月（YYYY-MM）に対応するフォルダパスを取得し、存在しない場合は作成する。

        Args:
            target_date (str or datetime): 'YYYY-MM-DD' 文字列 または datetimeオブジェクト

        Returns:
            Path: 作成された（または既存の）月別ディレクトリパス
        """
        if isinstance(target_date, str):
            # 文字列から年月を抽出 (YYYY-MM)
            # YYYY-MM-DD でも YYYY-MM でも対応できるよう先頭7文字を取る簡易実装、
            # あるいはdatetimeパースする。
            try:
                dt = datetime.strptime(target_date[:7], "%Y-%m")
            except ValueError:
                # 日付形式でない場合はそのまま文字列としてフォルダ作成を試みる（柔軟性）
                logger.warning(f"Invalid date format: {target_date}, treating as folder name.")
                month_str = target_date
        elif isinstance(target_date, datetime):
            dt = target_date
            month_str = dt.strftime("%Y-%m")
        else:
            raise TypeError("target_date must be str or datetime")
        
        if 'dt' in locals():
            month_str = dt.strftime("%Y-%m")

        target_dir = self.base_path / month_str
        
        if not target_dir.exists():
            try:
                target_dir.mkdir(parents=True, exist_ok=True)
                logger.info(f"Created monthly directory: {target_dir}")
            except Exception as e:
                logger.error(f"Failed to create directory {target_dir}: {e}")
                raise
        
        return target_dir

    def sanitize_filename(self, filename: str) -> str:
        """
        ファイル名に使えない文字を置換する。
        """
        # Windows/Linuxで禁止されがちな文字をアンダースコアに
        return re.sub(r'[\\/*?:"<>|]', '_', filename)

    def generate_filename(self, doc_id: str, sec_code: str, company_name: str, filing_date: str) -> str:
        """
        命名規則に従ったファイル名を生成する。
        規則: [DocID]_[証券コード4桁]_[会社名]_[提出日].zip
        
        Args:
            doc_id (str): 書類管理番号
            sec_code (str): 証券コード
            company_name (str): 会社名
            filing_date (str): 提出日 (YYYY-MM-DD)
        
        Returns:
            str: 生成されたファイル名
        """
        if not company_name:
            company_name = "Unknown"
        
        safe_company_name = self.sanitize_filename(company_name)
        return f"{doc_id}_{sec_code}_{safe_company_name}_{filing_date}.zip"

    def is_file_exists(self, directory: Path, filename: str) -> bool:
        """
        ファイルが既に存在するかチェックする。
        """
        return (directory / filename).exists()

    def save_file(self, content: bytes, year_month: str, filename: str) -> Path:
        """
        バイナリデータをファイルとして保存する。

        Args:
            content (bytes): 保存するデータ
            year_month (str): ターゲット年月（フォルダ振り分け用）
            filename (str): 保存ファイル名

        Returns:
            Path: 保存されたファイルのフルパス
        """
        target_dir = self.get_context_directory(year_month)
        save_path = target_dir / filename
        
        # 上書きする場合でも、一応ログ出しやチェックを行う
        # is_file_exists で事前にチェックされている前提の設計だが、ここでも実行する
        if save_path.exists():
            logger.info(f"File already exists, overwriting: {save_path}")
        
        try:
            with open(save_path, 'wb') as f:
                f.write(content)
            logger.info(f"Saved file to: {save_path}")
            return save_path
        except Exception as e:
            logger.error(f"Failed to save file {save_path}: {e}")
            raise

    def get_save_path_if_not_exists(self, year_month: str, doc_id: str, sec_code: str, company_name: str, filing_date: str) -> Optional[Path]:
        """
        保存すべきパスを計算し、既にファイルが存在する場合は None を返す便利メソッド。
        APIリクエスト前の重複チェックに使用する。

        Args:
           year_month (str): 年月 (YYYY-MM)
           doc_id (str): 書類管理番号
           sec_code (str): 証券コード
           company_name (str): 会社名
           filing_date (str): 提出日 (YYYY-MM-DD)

        Returns:
            Optional[Path]: 保存予定のパス（存在しない場合）。既に存在する場合は None。
        """
        filename = self.generate_filename(doc_id, sec_code, company_name, filing_date)
        target_dir = self.get_context_directory(year_month)
        
        if self.is_file_exists(target_dir, filename):
            logger.debug(f"Skipping download, file exists: {filename}")
            return None
        
        return target_dir / filename
