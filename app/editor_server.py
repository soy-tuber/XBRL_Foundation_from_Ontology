"""
有価証券報告書エディタ — FastAPI サーバー。

セクションごとに「記載例 / 入力 / AI出力」の 3 カラムエディタを提供。
既存の src.ir.queries / src.ir.llm_client を再利用。

起動: uvicorn app.editor_server:app --host 0.0.0.0 --port 8503
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.requests import Request
from fastapi.responses import HTMLResponse, JSONResponse
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel

# repo root を import パスに追加
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.config import load_config  # noqa: E402
from src.ir import queries as Q  # noqa: E402
from src.ir.llm_client import LlmClient, LlmConfig  # noqa: E402

app = FastAPI(title="有報エディタ")

_cfg = load_config()
_db_path = _cfg["db_path"]
_llm = LlmClient(LlmConfig.from_env())

_templates = Environment(
    loader=FileSystemLoader(str(Path(__file__).parent / "templates")),
    autoescape=True,
)

# ナラティブセクション (財務諸表は除外)
NARRATIVE_CODES = {
    "company_history", "business_overview", "business_risks", "mdna",
    "r_and_d", "management_policy", "sustainability", "climate",
    "human_capital", "corporate_governance", "directors",
    "director_compensation", "dividend_policy", "policy_shareholdings",
    "critical_contracts",
}


def _load_taxonomy():
    path = REPO_ROOT / "config" / "section_taxonomy.json"
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [
        m for m in data["mappings"]
        if m["section_code"] in NARRATIVE_CODES
    ]


@app.get("/", response_class=HTMLResponse)
async def editor_page():
    tpl = _templates.get_template("editor.html")
    return HTMLResponse(tpl.render())


@app.get("/api/taxonomy")
async def taxonomy():
    sections = _load_taxonomy()
    sections.sort(key=lambda m: m.get("order", 999))
    return JSONResponse([
        {
            "section_code": m["section_code"],
            "section_name_ja": m["section_name_ja"],
            "section_name_en": m.get("section_name_en", ""),
            "order": m.get("order", 999),
        }
        for m in sections
    ])


@app.get("/api/peers/{section_code}")
async def peers(section_code: str, limit: int = 5):
    rows = Q.peer_sections(_db_path, section_code=section_code, latest_only=True, limit=limit)
    return JSONResponse([
        {
            "sec_code": r.get("sec_code"),
            "company_name": r.get("company_name"),
            "period_end": str(r.get("period_end") or ""),
            "content_text": (r.get("content_text") or "")[:3000],
        }
        for r in rows
    ])


class GenerateRequest(BaseModel):
    section_code: str
    section_name_ja: str = ""
    draft_text: str = ""
    peer_texts: list[str] = []


@app.post("/api/generate")
async def generate(req: GenerateRequest):
    peer_ctx = "\n\n---\n\n".join(
        f"【記載例 {i+1}】\n{t[:2000]}" for i, t in enumerate(req.peer_texts[:5])
    )
    system = (
        "あなたは日本の有価証券報告書作成を支援する編集者です。\n"
        f"セクション: {req.section_name_ja or req.section_code}\n\n"
        "ユーザのドラフトと同業他社の記載例を踏まえ、改善されたドラフトを日本語で出力してください。\n"
        "構成・トーン・網羅性を同業他社水準に合わせてください。\n"
        "ドラフトが空の場合は、記載例を参考に新規のドラフトを作成してください。"
    )
    user = f"## ドラフト\n{req.draft_text or '（未入力）'}\n\n## 記載例\n{peer_ctx or '（なし）'}"

    try:
        output = _llm.generate(system, user, temperature=0.3)
    except Exception as e:
        output = f"[LLM エラー] {e}"

    return JSONResponse({"output_text": output})
