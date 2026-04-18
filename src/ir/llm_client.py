"""
LLM 呼び出しの共通IF。Gemini API (リモート) とローカルOpenAI互換エンドポイントを同一IFで扱う。

用途:
- Streamlit 4機能の生成系バックエンド
- セクション本文のクリーニング/正規化の対話的実行 (Claude Code から curl 的に叩く前提)

設計方針:
- 追加依存は requests のみ (既存で入っている)
- 環境変数で切替: LLM_BACKEND=gemini | local
- ストリーミングはサポートしない (プロト用途)
- エラーは素直に上げ、UI 側で握る
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import List, Optional

import requests

logger = logging.getLogger(__name__)


@dataclass
class LlmConfig:
    backend: str           # "gemini" | "local"
    model: str
    api_key: Optional[str]
    endpoint: Optional[str]  # local 用
    timeout: int = 120

    @classmethod
    def from_env(cls) -> "LlmConfig":
        backend = os.getenv("LLM_BACKEND", "gemini").lower()
        if backend == "gemini":
            return cls(
                backend="gemini",
                model=os.getenv("GEMINI_MODEL", "gemini-1.5-pro"),
                api_key=os.getenv("GEMINI_API_KEY"),
                endpoint=None,
            )
        return cls(
            backend="local",
            model=os.getenv("LOCAL_LLM_MODEL", "nemotron"),
            api_key=os.getenv("LOCAL_LLM_API_KEY"),
            endpoint=os.getenv("LOCAL_LLM_ENDPOINT", "http://127.0.0.1:8000/v1"),
        )


class LlmClient:
    """Gemini API と OpenAI 互換 (/chat/completions) の2本立てを吸収するシンプルクライアント。"""

    def __init__(self, config: Optional[LlmConfig] = None):
        self.config = config or LlmConfig.from_env()

    def generate(self, system: str, user: str, temperature: float = 0.2) -> str:
        if self.config.backend == "gemini":
            return self._call_gemini(system, user, temperature)
        return self._call_openai_compat(system, user, temperature)

    # ---------- 埋め込み (RAG 用) ----------

    def embed(self, texts, model: Optional[str] = None):
        """
        テキストのリストを埋め込みベクトルのリストに変換する。
        返り値: List[List[float]]
        """
        if isinstance(texts, str):
            texts = [texts]
        if self.config.backend == "gemini":
            return self._embed_gemini(texts, model or "text-embedding-004")
        return self._embed_openai_compat(texts, model or "text-embedding-3-small")

    def _embed_gemini(self, texts, model: str):
        if not self.config.api_key:
            raise RuntimeError("GEMINI_API_KEY is not set")
        # batchEmbedContents エンドポイントで一括
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:batchEmbedContents?key={self.config.api_key}"
        )
        payload = {
            "requests": [
                {"model": f"models/{model}", "content": {"parts": [{"text": t}]}}
                for t in texts
            ]
        }
        resp = requests.post(url, json=payload, timeout=self.config.timeout)
        resp.raise_for_status()
        data = resp.json()
        try:
            return [r["values"] for r in data["embeddings"]]
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"Gemini embed parse failed: {e}; body={json.dumps(data)[:500]}")

    def _embed_openai_compat(self, texts, model: str):
        if not self.config.endpoint:
            raise RuntimeError("LOCAL_LLM_ENDPOINT is not set")
        url = f"{self.config.endpoint.rstrip('/')}/embeddings"
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        resp = requests.post(
            url, headers=headers,
            json={"model": model, "input": texts},
            timeout=self.config.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        try:
            return [d["embedding"] for d in data["data"]]
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"OpenAI-compat embed parse failed: {e}; body={json.dumps(data)[:500]}")

    # ---------- Gemini ----------

    def _call_gemini(self, system: str, user: str, temperature: float) -> str:
        if not self.config.api_key:
            raise RuntimeError("GEMINI_API_KEY is not set")
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.config.model}:generateContent?key={self.config.api_key}"
        )
        payload = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": temperature},
        }
        resp = requests.post(url, json=payload, timeout=self.config.timeout)
        resp.raise_for_status()
        data = resp.json()
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as e:
            logger.error(f"Gemini unexpected response: {data}")
            raise RuntimeError(f"Gemini response parse failed: {e}")

    # ---------- OpenAI 互換 (ローカルNemotron等) ----------

    def _call_openai_compat(self, system: str, user: str, temperature: float) -> str:
        if not self.config.endpoint:
            raise RuntimeError("LOCAL_LLM_ENDPOINT is not set")
        url = f"{self.config.endpoint.rstrip('/')}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=self.config.timeout)
        resp.raise_for_status()
        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"Local LLM response parse failed: {e}; body={json.dumps(data)[:500]}")


# ---------- クリーニング用のプリセットプロンプト ----------

CLEAN_SECTION_SYSTEM = (
    "あなたは日本の有価証券報告書の編集者です。"
    "入力テキストは XBRL TextBlock を HTML 除去した後のものです。"
    "以下を行ってください:\n"
    "- 目次・ページ番号・見出しの重複を削除\n"
    "- 表は可能な限り Markdown 表として再構成\n"
    "- 誤認識と思われる改行・半角記号を修正\n"
    "- 内容の要約や言い換えは行わない (原文忠実)\n"
    "- 出力はクリーニング済みテキストのみ。説明文は付けない。"
)


def clean_section_with_llm(text: str, client: Optional[LlmClient] = None) -> str:
    client = client or LlmClient()
    return client.generate(CLEAN_SECTION_SYSTEM, text, temperature=0.0)
