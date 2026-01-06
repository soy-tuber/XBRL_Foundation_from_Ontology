import re

class ContextHandler:
    """
    XBRLのコンテキストID (ContextRef) を解析し、
    財務諸表の属性（連結/個別、年度、期間タイプ）を判定するためのハンドラ。
    """

    @staticmethod
    def is_consolidated_current(context_id: str) -> bool:
        """
        コンテキストIDが「連結(Consolidated)」かつ「当期(CurrentYear)」であるかを判定する。
        Instant（時点）とDuration（期間）の両方に対応し、NonConsolidated（個別）は除外する。

        Args:
            context_id (str): XBRLタグのcontextRef属性値

        Returns:
            bool: ターゲット（連結・当期）であればTrue
        """
        if not context_id:
            return False

        # 1. "CurrentYear" が含まれているか（当期）
        #    Prior1Year, Prior2Year などが含まれている場合は（通常CurrentYearと共存しないが）除外されることを期待
        #    ただし、IDに "CurrentYear" が含まれれば良しとする
        if not re.search(r'CurrentYear', context_id):
            return False

        # 2. "Consolidated" が含まれ、かつ "NonConsolidated" ではないこと
        #    否定後読み (?<!Non) を使用して NonConsolidated の Consolidated にマッチしないようにする
        if not re.search(r'(?<!Non)Consolidated', context_id):
            return False
            
        # 安全のため、明示的に NonConsolidated が含まれている場合は False を返す（二重チェック）
        if re.search(r'NonConsolidated', context_id):
            return False

        return True

    @staticmethod
    def get_period_type(context_id: str) -> str:
        """
        コンテキストIDから期間タイプ（Instant/Duration）を推定する。
        
        Args:
            context_id (str): XBRLタグのcontextRef属性値
            
        Returns:
            str: 'Instant', 'Duration', または 'Unknown'
        """
        if re.search(r'Instant', context_id):
            return 'Instant'
        elif re.search(r'Duration', context_id):
            return 'Duration'
        return 'Unknown'
