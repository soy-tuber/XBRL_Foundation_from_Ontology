"""
コンプラ/適時開示の外出しルールを読み込む薄いローダー。
Streamlit タブやバッチ監査の両方から呼ぶ。
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any, Dict

_CONFIG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "config",
)


@lru_cache(maxsize=None)
def load_json(name: str) -> Dict[str, Any]:
    path = os.path.join(_CONFIG_DIR, name)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def compliance_rules_text() -> str:
    data = load_json("compliance_rules.json")
    lines = []
    for r in data["rules"]:
        lines.append(f"- [{r['code']}] {r['title']}: {r['summary']}")
    return "\n".join(lines)


def disclosure_events_text() -> str:
    data = load_json("disclosure_events.json")
    blocks = []
    for cat in data["categories"]:
        block = [f"## {cat['name_ja']} ({cat['key']}) — timing: {cat['timing']}"]
        block += [f"  - {ex}" for ex in cat["examples"]]
        blocks.append("\n".join(block))
    return "\n\n".join(blocks)
