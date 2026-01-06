import concurrent.futures
import logging
import os
import shutil
from typing import List, Callable, Any, Optional
from tqdm import tqdm

# ロガーの設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def _process_wrapper(file_path: str, process_func: Callable[[str], Any]) -> Any:
    """
    ワーカープロセス内で実行されるラッパー関数。
    
    Note: ProcessPoolExecutorでは、ここで発生した例外はメインプロセスの
    future.result() 呼び出し時に再送出されるため、ここではキャッチせずにそのまま実行する。
    ただし、デバッグ用にワーカー側でもログが出ると便利な場合があるため、
    一度キャッチしてログ出力してから再送出するパターンにする。
    
    Args:
        file_path (str): 処理対象のファイルパス
        process_func (Callable): 実行する処理関数

    Returns:
        Any: 処理結果。
    """
    try:
        return process_func(file_path)
    except Exception as e:
        # ワーカープロセス側でのログ出力（必要に応じて）
        # logger.error(f"Worker error processing {file_path}: {e}")
        raise

class BatchExecutor:
    """
    大量のファイルを並列処理するためのエグゼキュータクラス。
    ProcessPoolExecutorを使用してCPUバウンドな処理（XBRLパース等）を並列化する。
    """

    def __init__(self, max_workers: Optional[int] = None, error_dir: Optional[str] = None):
        """
        初期化

        Args:
            max_workers (int, optional): 並列実行するワーカープロセス数。
                                         Noneの場合はマシンのCPUコア数に基づいて自動設定される。
            error_dir (str, optional): エラーが発生したファイルを移動するディレクトリパス。
                                       Noneの場合は移動しない。
        """
        self.max_workers = max_workers
        self.error_dir = error_dir
        
        if self.error_dir and not os.path.exists(self.error_dir):
            os.makedirs(self.error_dir, exist_ok=True)

    def process_files(self, file_paths: List[str], process_func: Callable[[str], Any]) -> List[Any]:
        """
        ファイルリストに対して処理関数を並列適用する。
        Google Drive上の大量のZIPファイルなどを処理することを想定。

        Args:
            file_paths (List[str]): 処理対象のファイルパス（ZIPファイル等）のリスト
            process_func (Callable[[str], Any]): 各ファイルに対して実行する関数。
                                                 引数はファイルパス1つ、戻り値は抽出データなどの任意の結果。
                                                 重要: multiprocessingの制約上、この関数はトップレベルで定義されているか、
                                                 pickle化可能である必要があります（lambda式やローカル関数は不可）。

        Returns:
            List[Any]: 成功した処理結果のリスト。エラーが発生したファイルの結果（None）は除外される。
        """
        results = []
        total_files = len(file_paths)
        
        if total_files == 0:
            logger.warning("No files to process.")
            return results

        logger.info(f"Starting batch processing for {total_files} files with {self.max_workers or 'default'} workers.")

        with concurrent.futures.ProcessPoolExecutor(max_workers=self.max_workers) as executor:
            # futureオブジェクトをキーにして、元のファイルパスを値に持つ辞書を作成
            future_to_file = {
                executor.submit(_process_wrapper, path, process_func): path 
                for path in file_paths
            }
            
            # tqdmでプログレスバーを表示しつつ、成功数・エラー数をリアルタイム更新
            success_count = 0
            error_count = 0
            
            with tqdm(total=total_files, desc="Processing XBRL Files") as pbar:
                for future in concurrent.futures.as_completed(future_to_file):
                    file_path = future_to_file[future]
                    try:
                        result = future.result()
                        # Noneが返ってきた場合は明示的なスキップやデータなしとみなすこともできるが、
                        # 基本的にはprocess_funcが値を返すことを期待する。
                        if result is not None:
                            results.append(result)
                            success_count += 1
                        else:
                            # 処理は正常終了したが結果がNoneだった場合（スキップなど）
                            # エラーではないが成功カウントに入れるかは要件次第。ここではログのみ。
                            pass 
                            
                    except Exception as e:
                        # process_func内で例外が発生した場合
                        error_count += 1
                        logger.error(f"Error processing file {file_path}", exc_info=True)
                        
                        if self.error_dir:
                            try:
                                # ファイル名を取得
                                filename = os.path.basename(file_path)
                                dest_path = os.path.join(self.error_dir, filename)
                                # 移動先に同名ファイルがある場合の考慮（上書き）
                                shutil.move(file_path, dest_path)
                                logger.info(f"Moved failed file to: {dest_path}")
                            except Exception as move_error:
                                logger.error(f"Failed to move error file {file_path}: {move_error}")
                    
                    pbar.update(1)
                    pbar.set_postfix({'success': success_count, 'error': error_count})

        logger.info(f"Batch processing completed. {len(results)}/{total_files} succeeded.")
        return results
