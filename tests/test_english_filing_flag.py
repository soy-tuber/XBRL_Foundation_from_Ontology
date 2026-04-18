"""
英文有報フラグ (has_english_doc / has_english_filing) と
list_companies のフィルタ挙動を検証。
"""

from __future__ import annotations

import os
import sqlite3
import tempfile

from src.db.ir_schema import init_ir_schema
from src.ir import queries as Q


def test_english_filer_flag_and_filter():
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "ef.db")
        init_ir_schema(db)

        conn = sqlite3.connect(db)
        # 2社: 片方は英文有報あり、もう片方は無し
        conn.execute("INSERT INTO ir_companies (edinet_code, sec_code, company_name, has_english_filing) "
                     "VALUES ('E1', '1111', '参考企業', 1)")
        conn.execute("INSERT INTO ir_companies (edinet_code, sec_code, company_name, has_english_filing) "
                     "VALUES ('E2', '2222', '一般企業', 0)")
        conn.commit()
        conn.close()

        all_co = Q.list_companies(db)
        assert len(all_co) == 2
        # has_english_filing DESC ソートで参考企業が先頭
        assert all_co[0]["sec_code"] == "1111"

        only = Q.list_companies(db, english_filers_only=True)
        assert len(only) == 1
        assert only[0]["sec_code"] == "1111"
        assert only[0]["has_english_filing"] == 1


if __name__ == "__main__":
    test_english_filer_flag_and_filter()
    print("OK")
