"""
IR/法務支援 DB プロト UI (Streamlit)。

タブ構成:
  1. 有報作成支援 (同業他社 + 自社時系列)
  2. 決算説明資料作成支援 (フェーズ2: プレースホルダ)
  3. コンプラ/リスクチェッカー
  4. 適時開示ヒットチェッカー

LLM 呼び出しは src.ir.llm_client.LlmClient を使用。
LLM_BACKEND=gemini or local を .env で切替。

起動:
  streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# repo root を import パスに追加
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import streamlit as st  # noqa: E402

from src.config import load_config  # noqa: E402
from src.ir import queries as Q  # noqa: E402
from src.ir.llm_client import LlmClient, LlmConfig  # noqa: E402
from src.ir.rule_loader import compliance_rules_text, disclosure_events_text  # noqa: E402
from src.ir import rag as RAG  # noqa: E402
from src.ir.answer_gen import format_sources_for_context, build_answer_prompt  # noqa: E402
from src.presentation import queries as PQ  # noqa: E402


st.set_page_config(page_title="IR/法務支援 DB", layout="wide")

# ---------- 共通 ----------

@st.cache_resource
def _cfg():
    return load_config()


@st.cache_resource
def _llm():
    return LlmClient(LlmConfig.from_env())


def _db_path() -> str:
    return _cfg()["db_path"]


def _sidebar_stats():
    st.sidebar.subheader("LLM backend")
    cfg = _llm().config
    backend_label = {
        "gemini_cli": f"🆓 Gemini CLI ({cfg.model})",
        "gemini": f"💳 Gemini API ({cfg.model})",
        "local": f"🖥️ Local ({cfg.model})",
    }.get(cfg.backend, cfg.backend)
    st.sidebar.caption(backend_label)

    st.sidebar.subheader("DB 状態")
    try:
        stats = Q.db_stats(_db_path())
        for k, v in stats.items():
            st.sidebar.metric(k, f"{v:,}")
    except Exception as e:
        st.sidebar.error(f"DB 接続失敗: {e}")


def _llm_call_safe(system: str, user: str, temperature: float = 0.2) -> str:
    try:
        return _llm().generate(system, user, temperature=temperature)
    except Exception as e:
        return f"[LLM 呼び出し失敗] {e}\n\n入力を確認するか、.env の LLM_BACKEND / GEMINI_API_KEY / LOCAL_LLM_ENDPOINT を確認してください。"


# ---------- タブ1: 有報作成支援 ----------

def tab_rag_search():
    st.header("0. RAG 検索 (FTS / Semantic / Hybrid)")
    st.caption("質問を入力すると、有報を横断検索し典拠付きで回答します。")

    q = st.text_input("質問 (日本語 / 英語可)", value="", placeholder="例: 飲食業各社のサプライチェーンにおける価格高騰リスクは？")

    col1, col2, col3, col4 = st.columns([1, 1, 1, 1])
    with col1:
        mode = st.selectbox("モード", ["hybrid", "fts", "semantic"], index=0)
    with col2:
        section_code = st.text_input("section_code (任意)", value="")
    with col3:
        k = st.number_input("検索件数", min_value=5, max_value=50, value=15)
    with col4:
        n_sources = st.number_input("引用ソース数", min_value=3, max_value=10, value=5)

    if st.button("検索して回答", type="primary", key="rag_btn"):
        if not q.strip():
            st.warning("質問を入力してください。")
            return
        sc = section_code or None

        # 1. 検索
        try:
            with st.spinner("検索中..."):
                if mode == "fts":
                    rows = Q.fts_search(_db_path(), q, section_code=sc, limit=int(k), lang="auto")
                elif mode == "semantic":
                    rows = RAG.semantic_search(_db_path(), q, k=int(k), section_code=sc)
                else:
                    rows = RAG.hybrid_search(_db_path(), q, k=int(k), section_code=sc, lang="auto")
        except Exception as e:
            st.error(f"検索失敗: {e}")
            st.caption("埋め込みを未構築かもしれません: `python scripts/build_embeddings.py`")
            return
        if not rows:
            st.info("ヒットなし。")
            return

        # 2. 回答生成
        top_rows = rows[:int(n_sources)]
        context_str, source_meta = format_sources_for_context(top_rows, _db_path())
        system, user = build_answer_prompt(q, context_str)
        with st.spinner("LLM 回答生成中..."):
            answer = _llm_call_safe(system, user, temperature=0.3)

        # 3. session_state に保存
        st.session_state["rag_results"] = rows
        st.session_state["rag_answer"] = answer
        st.session_state["rag_source_meta"] = source_meta

    # ---------- 回答表示 ----------
    if st.session_state.get("rag_answer"):
        st.markdown(st.session_state["rag_answer"])

        with st.expander("出典", expanded=False):
            for meta in st.session_state.get("rag_source_meta", []):
                label = (
                    f"**[{meta['index']}]** {meta['company_name']} ({meta['sec_code']}) "
                    f"/ {meta['section_code']} / {meta['period_end']}"
                )
                st.markdown(label)
                st.text((meta.get("content_text") or "")[:2000])
                st.divider()

    # ---------- 検索結果一覧 (折りたたみ) ----------
    rows = st.session_state.get("rag_results")
    if rows:
        with st.expander(f"検索結果 ({len(rows)} 件)", expanded=False):
            for r in rows:
                header = (
                    f"**{r.get('sec_code') or '?'}** {r.get('company_name') or ''} "
                    f"`{r.get('section_code') or ''}` ({r.get('period_end') or ''})"
                )
                if "score" in r:
                    header += f"  — score: {r['score']:.4f}"
                if r.get("fts_rank") is not None or r.get("sem_rank") is not None:
                    header += f"  (fts#{r.get('fts_rank')} / sem#{r.get('sem_rank')})"
                st.markdown(header)
                if r.get("snippet_ja"):
                    st.caption("JA: " + r["snippet_ja"])
                if r.get("snippet_en"):
                    st.caption("EN: " + r["snippet_en"])
                if not r.get("snippet_ja") and not r.get("snippet_en"):
                    body = (r.get("content_text") or "")[:240]
                    if body:
                        st.caption(body + " …")
                st.divider()


def tab_annual_report_support():
    st.header("1. 有報作成支援")
    st.caption("ドラフト対象セクションを選ぶと、同業他社の最新記載と自社の前年度が並びます。")

    english_only = st.toggle(
        "参考銘柄のみ (英文有報提出企業)",
        value=False,
        help="EDINET に英文有報 (englishDocFlag=1) を一度でも出している企業のみ。IR 記載の品質が高い傾向。",
    )
    companies = Q.list_companies(_db_path(), english_filers_only=english_only)
    codes = Q.list_section_codes(_db_path())
    if not companies or not codes:
        st.warning("DB にデータがありません。`python -m src.ir.restaurant_collector --years 1` を先に実行してください。")
        return

    col1, col2 = st.columns([1, 1])
    with col1:
        def _fmt(c):
            badge = " 🇬🇧" if c.get("has_english_filing") else ""
            return f"{c['sec_code']} {c['company_name']}{badge}"
        target = st.selectbox("自社 (証券コード)", companies, format_func=_fmt)
    with col2:
        section = st.selectbox("セクション", codes, index=codes.index("business_risks") if "business_risks" in codes else 0)

    draft = st.text_area("ドラフト中のテキスト (任意)", height=180,
                         placeholder="ここに作成中の記載を貼り付け → 下のボタンで類似表現・差分を生成")

    colA, colB = st.columns(2)
    with colA:
        st.subheader("同業他社の最新記載")
        peers = Q.peer_sections(_db_path(), section_code=section, latest_only=True, limit=15)
        for p in peers:
            with st.expander(f"{p['sec_code']} {p['company_name']} ({p['period_end']})"):
                st.text(p["content_text"][:3000])

    with colB:
        st.subheader("自社の時系列")
        hist = Q.self_history(_db_path(), sec_code=target["sec_code"], section_code=section, limit=6)
        for h in hist:
            label = f"{h['period_end']} {'[訂正]' if h['is_amended'] else ''} {'(latest)' if h['is_latest'] else ''}"
            with st.expander(label):
                st.text(h["content_text"][:3000])

    st.divider()
    if st.button("類似表現サジェスト / 前年度との差分を生成", type="primary"):
        if not draft.strip():
            st.warning("ドラフトを入力してください。")
            return
        peer_ctx = "\n\n".join(f"# {p['company_name']} ({p['period_end']})\n{p['content_text'][:1500]}" for p in peers[:5])
        self_ctx = "\n\n".join(f"# 自社 {h['period_end']}\n{h['content_text'][:1500]}" for h in hist[:2])
        sys_msg = (
            "あなたは日本の有価証券報告書作成を支援する編集者です。"
            "ドラフト、同業他社の最新記載、自社の前年度を踏まえ、"
            "(1) 差分・追記すべき観点、(2) 言い換え候補、(3) 注意すべき表現 を日本語で端的に提示してください。"
        )
        user_msg = f"## ドラフト\n{draft}\n\n## 同業他社\n{peer_ctx}\n\n## 自社過去\n{self_ctx}"
        with st.spinner("LLM 呼び出し中..."):
            out = _llm_call_safe(sys_msg, user_msg)
        st.markdown(out)


# ---------- タブ2: 決算説明資料 ----------

def tab_presentation_support():
    st.header("2. 決算説明資料作成支援")
    st.caption("スライド単位で全文検索 (JP/EN 両方)。URL をクリックすると該当ページが開きます。")

    stats = PQ.phase2_stats(_db_path())
    st.caption(f"資料数: {stats['presentations']:,} / スライド数: {stats['slides']:,}")

    col1, col2, col3 = st.columns([3, 1, 1])
    with col1:
        q = st.text_input("検索キーワード (FTS5 MATCH 構文可)", value="same-store sales OR 既存店")
    with col2:
        sec_code = st.text_input("sec_code 絞込 (任意)", value="")
    with col3:
        lang = st.selectbox("言語", ["auto", "ja", "en"], index=0,
                            help="auto: JP+EN 両方からヒット。en: 英語のみ。")

    if st.button("検索", type="primary"):
        if not q.strip():
            st.warning("キーワードを入力してください。")
            return
        try:
            rows = PQ.search_slides(_db_path(), q, sec_code=sec_code or None, limit=30, lang=lang)
        except Exception as e:
            st.error(f"検索失敗: {e}")
            return
        if not rows:
            st.info("ヒットなし。資料投入 → `scripts/ingest_presentations.py` → `scripts/enrich_bilingual.py --target slides` の順で実行してください。")
            return
        for r in rows:
            flags = []
            if r["has_table"]:
                flags.append("📊表")
            if r["has_chart"]:
                flags.append("📈図")
            label = f"**{r['sec_code'] or '?'}** {r['pres_title']} / slide {r['slide_no']} {' '.join(flags)}"
            if r.get("slide_url"):
                label += f"  [🔗]({r['slide_url']})"
            st.markdown(label)
            if r.get("snippet_ja"):
                st.caption("JA: " + r["snippet_ja"])
            if r.get("snippet_en"):
                st.caption("EN: " + r["snippet_en"])
            kw = ", ".join(filter(None, [r.get("keywords_ja"), r.get("keywords_en")]))
            if kw:
                st.caption("keywords: " + kw)
            st.divider()


# ---------- タブ3: コンプラ/リスクチェッカー ----------

# ルールは config/compliance_rules.json から読む (rule_loader 経由)


def tab_compliance_checker():
    st.header("3. コンプラ/リスクチェッカー")
    st.caption("テキストを貼り付けると、関連法令・開示規則と照合して指摘を返します。")

    target_text = st.text_area("チェック対象テキスト", height=220,
                               placeholder="事業等のリスク、内部統制、ガバナンス記載など")
    severity = st.radio("検知感度", ["標準", "過剰検知 (見逃し最小)"], horizontal=True)

    if st.button("チェック実行", type="primary"):
        if not target_text.strip():
            st.warning("対象テキストを入力してください。")
            return
        sys_msg = (
            "あなたは日本の開示実務に精通した法務担当です。"
            "以下のルール群を前提に、入力テキストを監査してください。"
            "指摘は (1) 条項・規則名 (2) 該当箇所 (3) 推奨対応 の3点を JSON 風の箇条書きで返してください。"
            "確信度が低い指摘もすべて挙げてください (過剰検知寄り)。" if "過剰" in severity else ""
        )
        user_msg = f"## ルール群\n{compliance_rules_text()}\n\n## 対象\n{target_text}"
        with st.spinner("LLM 呼び出し中..."):
            out = _llm_call_safe(sys_msg, user_msg, temperature=0.0)
        st.markdown(out)


# ---------- タブ4: 適時開示ヒットチェッカー ----------

# 事由は config/disclosure_events.json から読む (rule_loader 経由)


def tab_disclosure_hit_checker():
    st.header("4. 適時開示ヒットチェッカー / アラート")
    st.caption("社内イベントを自然文で入力 → 該当する開示義務を提示します。過去臨報の参考事例も表示。")

    event_text = st.text_area("イベント内容", height=160,
                              placeholder="例: 来月、主要仕入先A社との基本契約を解消予定。年間取引額は XX 億円。")

    if st.button("開示義務を判定", type="primary"):
        if not event_text.strip():
            st.warning("イベントを入力してください。")
            return

        # 過去臨報 (docTypeCode=160) の参考事例を FTS で引く
        try:
            keywords = [w for w in event_text.replace("、", " ").replace("。", " ").split() if len(w) >= 2][:4]
            fts_query = " OR ".join(keywords) if keywords else event_text[:20]
            refs = Q.fts_search(_db_path(), fts_query, section_code=None, limit=5, lang="auto")
        except Exception as e:
            refs = []
            st.warning(f"参考事例検索スキップ: {e}")

        ref_ctx = "\n\n".join(
            f"- {r['company_name']} ({r['period_end']}) [{r['section_code']}] … {r.get('snippet_ja') or r.get('snippet_en') or ''}"
            for r in refs
        )

        sys_msg = (
            "あなたは日本の上場会社の適時開示実務に詳しい担当者です。"
            "入力イベントが以下のどの開示事由に該当しうるか、過剰検知寄り (見逃しゼロ優先) で判定してください。"
            "出力: (1) 該当しうる事由 (複数可) (2) 根拠規則 (3) 即時 or 次回定期のどちらで開示か (4) 判断の前提として確認すべき事項。"
        )
        user_msg = (
            f"## 開示事由リスト\n{disclosure_events_text()}\n\n"
            f"## イベント\n{event_text}\n\n"
            f"## 参考 (過去の類似記述)\n{ref_ctx or 'なし'}"
        )
        with st.spinner("LLM 呼び出し中..."):
            out = _llm_call_safe(sys_msg, user_msg, temperature=0.0)
        st.markdown(out)

        if refs:
            st.subheader("参考事例 (FTS ヒット)")
            for r in refs:
                st.markdown(f"**{r['company_name']}** ({r['period_end']}) — `{r['section_code']}`")
                if r.get("snippet_ja"):
                    st.caption("JA: " + r["snippet_ja"])
                if r.get("snippet_en"):
                    st.caption("EN: " + r["snippet_en"])


# ---------- main ----------

def main():
    st.title("IR/法務支援 DB (飲食業プロト)")
    _sidebar_stats()

    tabs = st.tabs(["⓪ RAG検索", "① 有報作成支援", "② 決算説明資料", "③ コンプラ/リスク", "④ 適時開示ヒット"])
    with tabs[0]:
        tab_rag_search()
    with tabs[1]:
        tab_annual_report_support()
    with tabs[2]:
        tab_presentation_support()
    with tabs[3]:
        tab_compliance_checker()
    with tabs[4]:
        tab_disclosure_hit_checker()


if __name__ == "__main__":
    main()
