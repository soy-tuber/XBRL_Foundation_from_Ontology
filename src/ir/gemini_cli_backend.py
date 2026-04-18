"""
Gemini CLI をサブプロセスで叩く薄いバックエンド。

狙い:
  - LLM 生成を CLI 経由に寄せて、OAuth 無料枠 (60req/min, 1000req/day) で回す
  - API キー課金を避けつつ Gemini 2.5 Pro の 1M コンテキストが使える
  - Streamlit の既存 4 機能タブは LlmClient IF のまま動く

前提:
  - `npm install -g @google/gemini-cli` 済み
  - 初回のみ `gemini` を手動で 1 回起動 → ブラウザで Google OAuth を完了
    (トークンは ~/.gemini/ に保存され以降サイレント)

設計:
  - 1 呼び出し = 1 サブプロセス (セッション無し)
  - system + user を単純結合して -p で投げる
  - context_files が指定されれば prompt 先頭に @<path> で埋め込む
    (Gemini CLI は @file 構文でファイルを in-context 取り込み)
  - 埋め込みは CLI でサポートされないので LlmClient.embed は別 backend に回す
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from typing import List, Optional

logger = logging.getLogger(__name__)


class GeminiCliNotFound(RuntimeError):
    pass


class GeminiCliError(RuntimeError):
    pass


def _find_cli() -> str:
    path = os.environ.get("GEMINI_CLI_PATH", "gemini")
    full = shutil.which(path)
    if not full:
        raise GeminiCliNotFound(
            f"gemini CLI が見つかりません (探索: {path})。"
            " `npm install -g @google/gemini-cli` → 一度 `gemini` を起動して OAuth を完了してください。"
        )
    return full


def run_gemini_cli(
    prompt: str,
    context_files: Optional[List[str]] = None,
    model: Optional[str] = None,
    timeout: int = 300,
) -> str:
    """
    Gemini CLI を非対話モード (-p) で一回呼び出して stdout を返す。

    Args:
        prompt: 投入するプロンプト本文。
        context_files: prompt 先頭に @file 参照で埋め込む追加ファイル。
        model: 省略時は環境変数 GEMINI_CLI_MODEL か gemini-2.5-pro。
        timeout: サブプロセス上限秒。
    """
    cli = _find_cli()
    model = model or os.environ.get("GEMINI_CLI_MODEL", "gemini-2.5-pro")

    final_prompt = prompt
    if context_files:
        refs = "\n".join(f"@{p}" for p in context_files)
        final_prompt = f"{refs}\n\n{prompt}"

    cmd = [cli, "-p", final_prompt, "--model", model]
    logger.debug(f"gemini cli cmd (prompt len={len(final_prompt)}): {cmd[:3]}...")

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        raise GeminiCliError(f"Gemini CLI timed out after {timeout}s")
    except FileNotFoundError as e:
        raise GeminiCliNotFound(str(e))

    if result.returncode != 0:
        msg = (result.stderr or result.stdout or "").strip()[:800]
        raise GeminiCliError(f"Gemini CLI exit {result.returncode}: {msg}")

    return (result.stdout or "").strip()
