"""
Gradio frontend for the Adan Retail assistant API.

Run the API first:
  uvicorn app.main:app --reload --port 8000

Then:
  python ui/gradio_app.py
"""

from __future__ import annotations

import html
import json
import os
from pathlib import Path
from typing import Any

import gradio as gr
import httpx

API_URL = os.getenv("ASSISTANT_API_URL", "http://127.0.0.1:8000").rstrip("/")
ASSETS = Path(__file__).resolve().parent / "assets"
# NOTE: gr.Blocks(css=...) expects the CSS *text*, not a file path.
CSS = (ASSETS / "style.css").read_text(encoding="utf-8")

HEAD = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=Vazirmatn:wght@400;500;600;700&display=swap" rel="stylesheet">
"""

KNOWN_ROUTES = {"rag", "sql", "hybrid", "auto"}
ROUTE_ICONS = {"rag": "📄", "sql": "🗄️", "hybrid": "🔀", "auto": "🤖"}

COMPONENT_ICONS = {
    "coordinator": "🧭",
    "rag_agent": "📄",
    "sql_agent": "🗄️",
    "hybrid_agent": "🔀",
    "query_database": "🗄️",
    "retriever": "🔍",
    "nl2sql": "🔤",
    "calculator": "🧮",
    "llm": "🧠",
    "db": "🗄️",
}

EMPTY_THINKING = '<div class="panel panel-empty">Adana Agent is Ready :)</div>'
EMPTY_TRACE = '<div class="panel-empty">مراحل اجرای ایجنت پس از اولین پرسش نمایش داده می‌شود.</div>'
EMPTY_SOURCES = '<div class="panel-empty">منابع سند پس از اولین پرسش نمایش داده می‌شود.</div>'
LOADING_HTML = (
    '<div class="answer-card loading"><div class="typing">'
    "<span></span><span></span><span></span></div>"
    '<div class="loading-text">در حال پردازش…</div></div>'
)

MAX_TABLE_ROWS = 50


def esc(value: Any) -> str:
    """Escape anything that goes into HTML (LLM output, PDF text, SQL, ...)."""
    return html.escape(str(value), quote=True)


def _icon_for(component: str) -> str:
    for key, icon in COMPONENT_ICONS.items():
        if key in component.lower():
            return icon
    return "⚙️"


def _pretty_json(data: Any) -> str:
    return esc(json.dumps(data, ensure_ascii=False, indent=2, default=str))


# ── renderers ───────────────────────────────────────────────────────────────

def _render_trace_html(trace: list[dict]) -> str:
    if not trace:
        return '<div class="panel-empty">هیچ trace‌ای دریافت نشد.</div>'

    steps = []
    for i, step in enumerate(trace):
        component = step.get("component", "unknown")
        detail = step.get("detail", "")
        data = step.get("data")
        data_html = (
            f'<details class="trace-data-wrap"><summary>داده</summary>'
            f'<pre class="code">{_pretty_json(data)}</pre></details>'
            if data
            else ""
        )
        steps.append(
            f"""
            <div class="trace-step" style="--step-delay:{i * 70}ms">
              <div class="trace-step-header">
                <span class="trace-icon">{_icon_for(component)}</span>
                <span class="trace-component">{esc(component)}</span>
                <span class="trace-index">#{i + 1}</span>
              </div>
              <div class="trace-detail" dir="auto">{esc(detail)}</div>
              {data_html}
            </div>"""
        )
    return f'<div class="trace-container">{"".join(steps)}</div>'


def _render_sources_html(sources: list[dict]) -> str:
    if not sources:
        return '<div class="panel-empty">این پاسخ منبع سندی نداشت.</div>'

    cards = []
    for s in sources:
        page = s.get("page")
        score = s.get("score")
        excerpt = s.get("excerpt") or ""

        badges = ""
        if page:
            badges += f'<span class="src-badge">صفحه {esc(page)}</span>'
        if isinstance(score, (int, float)):
            badges += f'<span class="src-badge src-score">{score:.2f}</span>'

        short = excerpt[:260] + ("…" if len(excerpt) > 260 else "")
        excerpt_html = f'<p class="src-excerpt" dir="auto">{esc(short)}</p>' if excerpt else ""

        cards.append(
            f"""
            <div class="src-card">
              <div class="src-card-header">
                <span>📄</span>
                <span class="src-doc">{esc(s.get("document", "—"))}</span>
                <div class="src-badges">{badges}</div>
              </div>
              {excerpt_html}
            </div>"""
        )
    return f'<div class="sources-grid">{"".join(cards)}</div>'


def _render_table(rows: Any) -> str | None:
    """Render a list[dict] (SQL result) as a real table; None if not tabular."""
    if not (isinstance(rows, list) and rows and all(isinstance(r, dict) for r in rows)):
        return None
    cols = list(rows[0].keys())
    head = "".join(f"<th>{esc(c)}</th>" for c in cols)
    body = "".join(
        "<tr>" + "".join(f"<td>{esc(r.get(c, ''))}</td>" for c in cols) + "</tr>"
        for r in rows[:MAX_TABLE_ROWS]
    )
    more = (
        f'<div class="table-note">{len(rows) - MAX_TABLE_ROWS} ردیف دیگر نمایش داده نشد.</div>'
        if len(rows) > MAX_TABLE_ROWS
        else ""
    )
    return f'<div class="table-wrap"><table class="result-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>{more}'


def _render_answer_html(data: dict) -> str:
    route = str(data.get("route") or "auto").lower()
    route_cls = route if route in KNOWN_ROUTES else "auto"
    route_icon = ROUTE_ICONS.get(route_cls, "⚙️")
    insufficient = bool(data.get("insufficient_context"))

    ctx_badge = (
        '<span class="badge badge-warn">⚠ زمینه ناکافی</span>'
        if insufficient
        else '<span class="badge badge-ok">✓ زمینه کافی</span>'
    )

    answer = esc(data.get("answer") or "").replace("\n", "<br>")

    blocks = ""
    if data.get("sql"):
        result = data.get("sql_result")
        table = _render_table(result)
        if table is None and result is not None:
            table = f'<pre class="code">{_pretty_json(result)}</pre>'
        blocks += f"""
        <div class="detail-block">
          <div class="detail-label">🗄️ SQL</div>
          <pre class="code">{esc(data["sql"])}</pre>
          {table or ""}
        </div>"""

    if data.get("calculator"):
        blocks += f"""
        <div class="detail-block">
          <div class="detail-label">🧮 فراخوانی ابزار Calculator</div>
          <pre class="code">{_pretty_json(data["calculator"])}</pre>
        </div>"""

    tool_calls = data.get("tool_calls") or []
    if tool_calls:
        chips = "".join(
            f'<span class="chip {"chip-ok" if t.get("ok", True) else "chip-err"}">'
            f'{"✓" if t.get("ok", True) else "✗"} {esc(t.get("tool", "tool"))}</span>'
            for t in tool_calls
        )
        blocks += f'<div class="detail-block"><div class="detail-label">🔧 ابزارها</div><div class="chips">{chips}</div></div>'

    return f"""
    <div class="answer-card">
      <div class="answer-meta-row">
        <span class="route-badge route-{route_cls}">{route_icon} {esc(route.upper())}</span>
        {ctx_badge}
      </div>
      <div class="answer-body" dir="auto">{answer}</div>
      {blocks}
    </div>"""


def _render_error_html(message: str) -> str:
    return f'<div class="answer-card error"><div class="answer-body" dir="auto">⚠ {esc(message)}</div></div>'


def _render_thinking_html(data: dict, n_trace: int, n_sources: int) -> str:
    route = str(data.get("route") or "auto").upper()
    insufficient = bool(data.get("insufficient_context"))
    return f"""
    <div class="panel">
      <div class="panel-title">Adan Agent Summary</div>
      <div class="kv"><span>مسیر</span><strong>{esc(route)}</strong></div>
      <div class="kv"><span>مراحل trace</span><strong>{n_trace}</strong></div>
      <div class="kv"><span>منابع</span><strong>{n_sources}</strong></div>
      <div class="kv"><span>زمینه</span><strong>{"ناکافی ⚠" if insufficient else "کافی ✓"}</strong></div>
    </div>"""


# ── API calls ───────────────────────────────────────────────────────────────

def _call_api(base: str, question: str, route: str) -> tuple[dict | None, str | None]:
    payload = {"question": question, "force_route": route or "auto"}
    try:
        with httpx.Client(timeout=120.0) as client:
            response = client.post(f"{base}/ask", json=payload)
            response.raise_for_status()
            return response.json(), None
    except httpx.ConnectError:
        return None, f"اتصال به API برقرار نشد. مطمئن شوید سرور روی {base} در حال اجراست."
    except httpx.TimeoutException:
        return None, "پاسخ‌دهی سرور بیش از حد طول کشید (timeout)."
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text
        try:
            detail = exc.response.json().get("detail", detail)
        except Exception:
            pass
        return None, f"خطای API ({exc.response.status_code}): {detail}"
    except Exception as exc:  # noqa: BLE001
        return None, f"خطای غیرمنتظره: {exc}"


def check_health(api_url: str) -> str:
    base = (api_url or API_URL).rstrip("/")
    try:
        r = httpx.get(f"{base}/health", timeout=5.0)
        r.raise_for_status()
        h = r.json()
    except Exception:
        return (
            '<div class="status status-off"><span class="dot"></span>'
            "<span>قطع — API در دسترس نیست</span></div>"
        )

    def flag(ok: bool) -> str:
        return "✓" if ok else "✗"

    all_ok = h.get("status") == "ok" and h.get("rag_ready") and h.get("llm_configured")
    cls = "status-on" if all_ok else "status-warn"
    label = "آنلاین" if all_ok else "آنلاین (ناقص)"
    return f"""
    <div class="status {cls}"><span class="dot"></span><span>{label}</span></div>
    <div class="status-details">
      <span>DB {flag(bool(h.get("db_ready")))}</span>
      <span>RAG {flag(bool(h.get("rag_ready")))}</span>
      <span>LLM {flag(bool(h.get("llm_configured")))}</span>
    </div>"""


# ── events ──────────────────────────────────────────────────────────────────

def submit(question: str, route: str, api_url: str, history: list[dict] | None):
    """Generator: shows the user message + loading state first, then the answer."""
    question = (question or "").strip()
    history = list(history or [])
    if not question:
        yield history, gr.update(), gr.update(), gr.update(), ""
        return

    base = (api_url or API_URL).rstrip("/")
    history.append({"role": "user", "content": question})
    history.append({"role": "assistant", "content": LOADING_HTML})
    yield history, gr.update(), gr.update(), gr.update(), ""

    data, error = _call_api(base, question, route)
    if error or data is None:
        history[-1] = {"role": "assistant", "content": _render_error_html(error or "پاسخی دریافت نشد.")}
        yield history, EMPTY_TRACE, EMPTY_SOURCES, EMPTY_THINKING, ""
        return

    trace = [t if isinstance(t, dict) else dict(t) for t in (data.get("trace") or [])]
    sources = data.get("sources") or []

    history[-1] = {"role": "assistant", "content": _render_answer_html(data)}
    yield (
        history,
        _render_trace_html(trace),
        _render_sources_html(sources),
        _render_thinking_html(data, len(trace), len(sources)),
        "",
    )


def clear_chat():
    return [], EMPTY_TRACE, EMPTY_SOURCES, EMPTY_THINKING


# Example buttons: (button label, question sent to the API, route)
# The indexed documents are English, so the questions are English.
EXAMPLES = [
    ("How many days do customers have to return unused products?", "How many days do customers have to return unused products?", "rag"),
    ("How many paid annual leave days do full-time employees get?", "How many paid annual leave days do full-time employees get?", "rag"),
    ("What is the total revenue from all sales?", "What is the total revenue from all sales?", "sql"),
    ("What is the total sales revenue and calculate 15 percent of that amount?", "What is the total sales revenue and calculate 15 percent of that amount?", "hybrid"),
]


# ── UI ──────────────────────────────────────────────────────────────────────

def build_ui() -> gr.Blocks:
    with gr.Blocks(
        title="Adan Retail — Agent",
        css=CSS,
        head=HEAD,
        theme=gr.themes.Base(
            primary_hue="teal",
            secondary_hue="slate",
            neutral_hue="zinc",
            font=["Vazirmatn", "Tahoma", "ui-sans-serif", "system-ui", "sans-serif"],
            font_mono=["IBM Plex Mono", "ui-monospace", "monospace"],
        ),
    ) as demo:

        gr.HTML(
            """
            <header class="ag-header">
              <div class="ag-logo">
                <span class="ag-logo-icon">◈</span>
                <span dir="ltr">Adan <em>Agent</em></span>
              </div>
              <div class="ag-tagline"> ایجنت آدان · RAG + SQL + Calculator</div>
            </header>
            """
        )

        with gr.Row(elem_id="ag-main", equal_height=False):

            # Sidebar (right side in RTL)
            with gr.Column(scale=1, min_width=240, elem_id="ag-sidebar"):
                status = gr.HTML(value='<div class="status"><span class="dot"></span><span>در حال بررسی…</span></div>', elem_id="ag-status")
                api_url = gr.Textbox(label="آدرس API", value=API_URL, elem_id="ag-api-url")
                check_btn = gr.Button("بررسی اتصال", size="sm", elem_classes="ghost-btn")
                force_route = gr.Radio(
                    label="مسیر پردازش",
                    choices=["auto", "rag", "sql", "hybrid"],
                    value="auto",
                    elem_id="ag-route-radio",
                )
                thinking = gr.HTML(value=EMPTY_THINKING, elem_id="ag-thinking")
                gr.HTML('<div class="sidebar-title">Some Questions</div>')
                example_btns = [
                    gr.Button(label, size="sm", elem_classes="eg-btn") for label, _, _ in EXAMPLES
                ]

            # Chat
            with gr.Column(scale=3, min_width=360, elem_id="ag-chat-col"):
                chatbot = gr.Chatbot(
                    label="گفتگو",
                    show_label=False,
                    elem_id="ag-chatbot",
                    height=560,
                    type="messages",
                    render_markdown=False,
                    sanitize_html=False,
                    placeholder="Ask Your Question...",
                )
                with gr.Row(elem_id="ag-input-row"):
                    question = gr.Textbox(
                        show_label=False,
                        placeholder="Ask anything...",
                        lines=1,
                        max_lines=4,
                        elem_id="ag-question",
                        scale=6,
                        container=False,
                    )
                    send_btn = gr.Button("ارسال", variant="primary", scale=1, min_width=90, elem_id="ag-send-btn")
                    clear_btn = gr.Button("پاک‌کردن", scale=1, min_width=90, elem_id="ag-clear-btn")

            # Trace + sources
            with gr.Column(scale=2, min_width=300, elem_id="ag-trace-col"):
                with gr.Tabs(elem_id="ag-right-tabs"):
                    with gr.TabItem("Agent Trace"):
                        trace_out = gr.HTML(value=EMPTY_TRACE, elem_id="ag-trace")
                    with gr.TabItem("RAG Source"):
                        sources_out = gr.HTML(value=EMPTY_SOURCES, elem_id="ag-sources")

        # ── wiring ──
        io_in = [question, force_route, api_url, chatbot]
        io_out = [chatbot, trace_out, sources_out, thinking, question]
        send_btn.click(submit, io_in, io_out, trigger_mode="once")
        question.submit(submit, io_in, io_out, trigger_mode="once")

        clear_btn.click(clear_chat, None, [chatbot, trace_out, sources_out, thinking])

        check_btn.click(check_health, [api_url], [status])
        api_url.submit(check_health, [api_url], [status])
        demo.load(check_health, [api_url], [status])

        for btn, (_, q, r) in zip(example_btns, EXAMPLES):
            btn.click(lambda q=q, r=r: (q, r), None, [question, force_route])

    return demo


if __name__ == "__main__":
    build_ui().launch(
        server_name=os.getenv("GRADIO_SERVER_NAME", "127.0.0.1"),
        server_port=int(os.getenv("GRADIO_SERVER_PORT", "7860")),
    )
