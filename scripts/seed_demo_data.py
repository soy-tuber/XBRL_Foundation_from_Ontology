"""
EDINET / Drive 無しでも Streamlit を動作確認できるよう、
ir_* / phase2 テーブルにダミーデータを投入する。

使い方:
  python scripts/seed_demo_data.py
  python scripts/seed_demo_data.py --reset   # 既存デモ行を削除してから入れ直す

DEMO_ プレフィックスの doc_id / source_uri を使い、本物データと混ざらない。
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.config import load_config  # noqa: E402
from src.db.ir_schema import init_ir_schema  # noqa: E402
from src.db.phase2_schema import init_phase2_schema  # noqa: E402

COMPANIES = [
    ("E_DEMO_3197", "3197", "デモすかいらーくHD"),
    ("E_DEMO_8153", "8153", "デモモスフードサービス"),
    ("E_DEMO_3543", "3543", "デモコメダHD"),
]

SECTIONS = [
    ("business_risks", "事業等のリスク",
     "当社グループは原材料 (主に食肉・小麦・乳製品) の市況変動および為替の影響を強く受ける。"
     "サプライチェーン依存度が高く、特定産地での疾病発生・物流停止が業績に重大な影響を及ぼす。",
     "Our group is materially affected by raw material price fluctuations (meat, wheat, dairy) and FX. "
     "High supply chain dependency means disease outbreaks or logistics disruptions in specific regions "
     "may have a material impact on results.",
     "サプライチェーン, 原材料, 為替, 食肉, 物流",
     "supply chain, raw materials, FX, meat, logistics"),
    ("mdna", "経営者による分析",
     "既存店売上は前年同期比 +5.3% で推移し、客単価上昇が寄与した。原材料費高騰の影響は値上げで部分的に吸収。",
     "Same-store sales grew +5.3% YoY, driven by higher average ticket. "
     "Cost inflation was partially absorbed via price hikes.",
     "既存店売上, 客単価, 値上げ, インフレ",
     "same-store sales, average ticket, price hike, inflation"),
    ("corporate_governance", "コーポレート・ガバナンス",
     "取締役11名のうち5名が社外取締役。指名委員会・報酬委員会を任意で設置している。",
     "5 of 11 directors are independent outside directors. "
     "Voluntary nomination and compensation committees are in place.",
     "社外取締役, 指名委員会, 報酬委員会, ガバナンス",
     "independent directors, nomination committee, compensation committee, governance"),
]


def _seed(db: str, reset: bool) -> None:
    init_ir_schema(db)
    init_phase2_schema(db)

    conn = sqlite3.connect(db)
    cur = conn.cursor()

    if reset:
        cur.execute("DELETE FROM ir_sections WHERE doc_id LIKE 'DEMO_%'")
        cur.execute("DELETE FROM ir_documents WHERE doc_id LIKE 'DEMO_%'")
        cur.execute("DELETE FROM ir_companies WHERE edinet_code LIKE 'E_DEMO_%'")
        cur.execute("DELETE FROM ir_presentation_slides WHERE presentation_id IN "
                    "(SELECT presentation_id FROM ir_presentations WHERE source_uri LIKE 'DEMO_%')")
        cur.execute("DELETE FROM ir_presentations WHERE source_uri LIKE 'DEMO_%'")

    today = date.today()

    for edi, sec, name in COMPANIES:
        cur.execute(
            "INSERT OR IGNORE INTO ir_companies (edinet_code, sec_code, company_name) VALUES (?, ?, ?)",
            (edi, sec, name),
        )
        # 直近2期 (当期・前期) の有報をデモ生成
        for years_ago in (0, 1):
            period_end = date(today.year - years_ago, 3, 31)
            doc_id = f"DEMO_{sec}_{period_end.year}"
            cur.execute(
                """INSERT OR REPLACE INTO ir_documents
                   (doc_id, edinet_code, sec_code, doc_type_code, period_end, submit_date,
                    is_amended, is_latest, taxonomy_version)
                   VALUES (?, ?, ?, '120', ?, ?, 0, ?, '2023')""",
                (doc_id, edi, sec, period_end, period_end + timedelta(days=90), 1 if years_ago == 0 else 0),
            )
            for code, name_ja, ja, en, kja, ken in SECTIONS:
                cur.execute(
                    """INSERT INTO ir_sections
                       (doc_id, section_code, section_name_ja, section_order,
                        content_text, content_text_en, keywords_ja, keywords_en,
                        char_count, enriched_at)
                       VALUES (?, ?, ?, 10, ?, ?, ?, ?, ?, ?)""",
                    (doc_id, code, name_ja, ja, en, kja, ken, len(ja),
                     datetime.utcnow().isoformat(timespec="seconds")),
                )

    # Phase 2 デモ資料
    cur.execute(
        """INSERT OR REPLACE INTO ir_presentations
           (presentation_id, sec_code, company_name, fiscal_period, source_type,
            source_uri, source_url, file_type, title)
           VALUES (1001, '3197', 'デモすかいらーくHD', 'FY2024Q4',
                   'local', 'DEMO_PRES_1', 'file:///demo/skylark_fy24q4.pdf',
                   'pdf', 'デモ_スカイラーク_FY2024Q4_決算説明資料')"""
    )
    slides = [
        (1, "業績ハイライト", "Performance Highlights",
         "売上収益 4,200 億円 (前期比 +6.1%)、営業利益 280 億円 (+12.4%)。",
         "Revenue JPY 420.0bn (+6.1% YoY), operating income JPY 28.0bn (+12.4%).",
         "売上収益, 営業利益, 業績", "revenue, operating income, performance"),
        (2, "既存店売上推移", "Same-store sales trend",
         "既存店売上は4Qで +5.3%。客数 +2.1%、客単価 +3.1%。",
         "Same-store sales +5.3% in 4Q. Traffic +2.1%, ticket +3.1%.",
         "既存店, 客数, 客単価", "same-store sales, traffic, average ticket"),
        (3, "原材料コスト見通し", "Raw material cost outlook",
         "牛肉・小麦・乳製品の市況高止まり。次期は値上げで吸収する方針。",
         "Beef, wheat, dairy prices remain elevated. Plan to absorb via price hikes next FY.",
         "原材料, 牛肉, 小麦, 値上げ", "raw materials, beef, wheat, price hike"),
    ]
    cur.execute(
        "DELETE FROM ir_presentation_slides WHERE presentation_id=1001"
    )
    for no, t_ja, t_en, body_ja, body_en, kja, ken in slides:
        cur.execute(
            """INSERT INTO ir_presentation_slides
               (presentation_id, slide_no, slide_url, title, title_en,
                content_text, content_text_en, keywords_ja, keywords_en,
                has_table, has_chart, char_count, enriched_at)
               VALUES (1001, ?, ?, ?, ?, ?, ?, ?, ?, 0, 1, ?, ?)""",
            (no, f"file:///demo/skylark_fy24q4.pdf#page={no}",
             t_ja, t_en, body_ja, body_en, kja, ken, len(body_ja),
             datetime.utcnow().isoformat(timespec="seconds")),
        )

    conn.commit()
    conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()
    db = load_config()["db_path"]
    os.makedirs(os.path.dirname(db) or ".", exist_ok=True)
    _seed(db, args.reset)
    print(f"[OK] demo data seeded into {db}")


if __name__ == "__main__":
    main()
