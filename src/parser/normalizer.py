from typing import Union, Optional

class ValueNormalizer:
    """
    XBRLから抽出した数値データの型変換を行うクラス。
    
    方針:
    「一次DB（Raw Layer）」としての正確性を保つため、
    単位変換やスケーリング（100万倍など）は一切行わない。
    XBRLに記載されている数値をそのまま float として返すことを責務とする。
    解釈や単位の調整は、分析・利用段階（Data Mart層）で行う。
    """

    @staticmethod
    def normalize(value: Union[str, float, int], decimals: Optional[str] = None, unit_ref: Optional[str] = None) -> float:
        """
        値を数値型(float)に変換する。
        スケーリングは行わない。

        Args:
            value: 元の数値（文字列含む）
            decimals: (未使用) 互換性のために残しているが無視する
            unit_ref: (未使用) 互換性のために残しているが無視する

        Returns:
            float: 数値変換された値。変換不可の場合は 0.0 を返す。
        """
        if value is None:
            return 0.0
            
        try:
            return float(value)
        except (ValueError, TypeError):
            # ハイフンだけのデータや空文字など、数値化できないものは0.0とする
            return 0.0
