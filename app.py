"""Streamlit frontend for the adaptive Socratic tutor - High-Utility UX Edition."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import streamlit as st
import streamlit.components.v1 as components
from google import genai
from dotenv import load_dotenv


ROOT = Path(__file__).parent
load_dotenv(ROOT / "secrets" / ".env", override=True)

# ── Safe Local Storage (Outside of OneDrive to prevent DB corruption) ────────
LOCAL_APP_DATA = os.getenv("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
DATA_DIR = Path(LOCAL_APP_DATA) / "AITeacher"
DATA_DIR.mkdir(parents=True, exist_ok=True)
CHROMA_DB_PATH = DATA_DIR / "chroma_db"
CHROMA_DB_PATH.mkdir(parents=True, exist_ok=True)

STATE_PATH = ROOT / "learner_state.json"
SESSIONS_DIR = ROOT / "sessions"
FLASHCARDS_PATH = ROOT / "flashcards.csv"
MODEL_NAME = "gemini-3.5-flash-lite"
SUPPORTED_DOCUMENTS = ["pdf", "txt", "md"]
SUMMARY_INTERVAL = 8


def get_api_key() -> str:
    """Read and normalize the local Gemini key without exposing its value."""
    return os.getenv("GEMINI_API_KEY", "").strip().strip('"').strip("'")


def clean_level_num(level: Any) -> int:
    """Safely extract integer mastery level between 1 and 5."""
    match = re.search(r"[1-5]", str(level))
    return int(match.group()) if match else 1


def level_metadata(level_val: Any) -> tuple[str, str, str]:
    """Return (label, text_color, bg_color) for a given mastery level."""
    lvl = clean_level_num(level_val)
    meta = {
        5: ("Maestro", "#34d399", "rgba(52, 211, 153, 0.12)"),
        4: ("Avanzado", "#38bdf8", "rgba(56, 189, 248, 0.12)"),
        3: ("Competente", "#818cf8", "rgba(129, 140, 248, 0.12)"),
        2: ("Inicial", "#fbbf24", "rgba(251, 191, 36, 0.12)"),
        1: ("Por repasar", "#f87171", "rgba(248, 113, 113, 0.12)"),
    }
    return meta.get(lvl, ("Inicial", "#94a3b8", "rgba(148, 163, 184, 0.12)"))


def calculate_learner_stats(concepts: dict[str, Any]) -> dict[str, Any]:
    """Compute high-level retention and mastery metrics."""
    if not concepts:
        return {
            "total": 0,
            "mastered": 0,
            "due": 0,
            "average_level": 0.0,
            "mastery_percent": 0,
        }
    total = len(concepts)
    levels = []
    due_count = 0
    mastered_count = 0
    now_date = utc_now().date().isoformat()
    for details in concepts.values():
        det = details if isinstance(details, dict) else {"level": details}
        lvl = clean_level_num(det.get("level", 1))
        levels.append(lvl)
        if lvl >= 4:
            mastered_count += 1
        next_rev = det.get("next_review", "")
        if next_rev and next_rev <= now_date:
            due_count += 1
        elif lvl == 1:
            due_count += 1
    avg = sum(levels) / total if total > 0 else 0.0
    percent = int((avg / 5.0) * 100)
    return {
        "total": total,
        "mastered": mastered_count,
        "due": due_count,
        "average_level": round(avg, 1),
        "mastery_percent": percent,
    }


def get_due_concepts(concepts: dict[str, Any]) -> list[str]:
    """Return names of all concepts currently due for active recall."""
    now_date = utc_now().date().isoformat()
    due_list = []
    for name, details in concepts.items():
        det = details if isinstance(details, dict) else {"level": details}
        lvl = clean_level_num(det.get("level", 1))
        next_rev = det.get("next_review", "")
        if (next_rev and next_rev <= now_date) or lvl == 1:
            due_list.append(name)
    return due_list


def format_relative_time(iso_str: str) -> str:
    """Format an ISO timestamp into a concise, human-friendly relative label."""
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str)
        now = datetime.now(timezone.utc)
        diff = now - dt
        if diff.days == 0:
            hours = diff.seconds // 3600
            if hours == 0:
                minutes = max(1, diff.seconds // 60)
                return f"hace {minutes}m"
            return f"hace {hours}h"
        elif diff.days == 1:
            return "ayer"
        elif diff.days < 7:
            return f"hace {diff.days}d"
        else:
            return dt.strftime("%d %b")
    except Exception:
        return ""


def apply_styles() -> None:
    """Inject Antigravity aesthetic: clean, minimal, dark theme, fixed elements."""
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

        /* Global typography & base background */
        html, body, [class*="css"], .stApp {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
            color: #EAEAEA !important;
            background-color: #0A0A0A !important;
        }

        /* Clean Streamlit Default Chrome */
        #MainMenu { visibility: hidden !important; }
        footer { visibility: hidden !important; }
        [data-testid="stDecoration"] { display: none !important; }
        header[data-testid="stHeader"] {
            background: transparent !important;
            height: 0 !important;
            min-height: 0 !important;
            padding: 0 !important;
        }

        /* Content Container Constraint */
        .block-container {
            max-width: 1200px !important;
            padding-top: 2rem !important;
            padding-bottom: 6rem !important;
        }

        /* Clean Chat Messages */
        [data-testid="stChatMessage"] {
            background: #161616 !important;
            border: 1px solid #222 !important;
            border-radius: 8px !important;
            margin: 0.85rem 0 !important;
            padding: 1rem 1.25rem !important;
            box-shadow: none !important;
        }
        [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {
            background: #121212 !important;
            border-left: 3px solid #00E5FF !important; /* Antigravity Cyan */
        }
        [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"]) {
            background: #161616 !important;
            border-left: 3px solid #2ea043 !important; /* Green for teacher */
        }

        /* Chat Input Capsule */
        [data-testid="stChatInput"] {
            background: #161616 !important;
            border: 1px solid #222 !important;
            border-radius: 8px !important;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4) !important;
        }
        [data-testid="stChatInput"]:focus-within {
            border-color: #00E5FF !important;
        }
        [data-testid="stChatInput"] textarea {
            color: #EAEAEA !important;
            font-size: 0.95rem !important;
        }

        /* Buttons */
        .stButton button {
            border-radius: 6px !important;
            font-weight: 500 !important;
            font-size: 0.85rem !important;
            padding: 0.45rem 0.9rem !important;
            border: 1px solid #222 !important;
            background: #161616 !important;
            color: #c9d1d9 !important;
            transition: all 0.2s ease !important;
        }
        .stButton button:hover {
            border-color: #444 !important;
            background: #222 !important;
            color: #ffffff !important;
            transform: translateY(-1px);
        }
        .stButton button[kind="primary"] {
            background: #00E5FF !important;
            border: 1px solid transparent !important;
            color: #0A0A0A !important;
            font-weight: 600 !important;
        }
        .stButton button[kind="primary"]:hover {
            background: #33EEFF !important;
        }

        /* Metrics */
        [data-testid="stMetric"] {
            background: #161616 !important;
            border: 1px solid #222 !important;
            border-radius: 12px !important;
            padding: 1rem 1.25rem !important;
            box-shadow: 0 4px 12px rgba(0,0,0,0.2) !important;
        }
        [data-testid="stMetricLabel"] {
            font-size: 0.75rem !important;
            font-weight: 600 !important;
            text-transform: uppercase !important;
            color: #888 !important;
        }
        [data-testid="stMetricValue"] {
            font-size: 1.8rem !important;
            font-weight: 700 !important;
            color: #EAEAEA !important;
        }

        /* Sidebar Styling */
        [data-testid="stSidebar"] {
            background-color: #0A0A0A !important;
            border-right: 1px solid #222 !important;
        }
        [data-testid="stSidebar"] .block-container {
            padding-top: 1.5rem !important;
            padding-left: 1.25rem !important;
            padding-right: 1.25rem !important;
        }
        
        /* Radio buttons in sidebar (Navigation) */
        .stRadio div[role="radiogroup"] {
            gap: 0.5rem;
        }
        .stRadio label {
            background: #161616 !important;
            border: 1px solid #222 !important;
            border-radius: 8px !important;
            padding: 0.75rem 1rem !important;
            cursor: pointer;
            transition: all 0.2s;
        }
        .stRadio label:hover {
            border-color: #444 !important;
            background: #222 !important;
        }
        .stRadio label[data-checked="true"] {
            border-color: #00E5FF !important;
            background: rgba(0, 229, 255, 0.1) !important;
        }

        /* Inputs & Selectboxes */
        .stSelectbox div[data-baseweb="select"] {
            background-color: #161616 !important;
            border: 1px solid #222 !important;
            border-radius: 6px !important;
        }
        .stTextInput input {
            background-color: #161616 !important;
            border: 1px solid #222 !important;
            border-radius: 6px !important;
            color: #EAEAEA !important;
        }

        /* Expanders */
        [data-testid="stExpander"] {
            background: #161616 !important;
            border: 1px solid #222 !important;
            border-radius: 8px !important;
            margin-bottom: 0.75rem !important;
        }
        [data-testid="stExpander"] summary {
            font-weight: 500 !important;
            color: #EAEAEA !important;
            padding: 0.75rem 1rem !important;
        }

        /* Scrollbars */
        ::-webkit-scrollbar {
            width: 6px;
            height: 6px;
        }
        ::-webkit-scrollbar-track {
            background: transparent;
        }
        ::-webkit-scrollbar-thumb {
            background: #333;
            border-radius: 9999px;
        }
        ::-webkit-scrollbar-thumb:hover {
            background: #555;
        }

        code {
            font-family: 'JetBrains Mono', monospace !important;
            background: #1F1F1F !important;
            padding: 2px 6px !important;
            border-radius: 4px !important;
            color: #00E5FF !important;
            font-size: 0.86em !important;
        }
        
        /* Antigravity Panel / Dashboard Cards */
        .ag-card {
            background-color: #161616;
            border: 1px solid #222;
            border-radius: 12px;
            padding: 1.5rem;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
            transition: transform 0.2s ease, box-shadow 0.2s ease;
            margin-bottom: 1rem;
        }
        .ag-card:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 16px rgba(0, 229, 255, 0.05);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat(timespec="seconds")


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", normalized.lower()).strip("-")
    return slug[:48] or "sesion"


def next_review_date(level: str, reviewed_at: datetime | None = None) -> str:
    mastery = clean_level_num(level)
    intervals = {1: 1, 2: 2, 3: 4, 4: 7, 5: 14}
    base = reviewed_at or utc_now()
    return (base + timedelta(days=intervals[mastery])).date().isoformat()


def normalize_state(data: dict[str, Any]) -> dict[str, Any]:
    """Migrate older learner JSON into the memory schema."""
    concepts = data.get("concepts", {})
    normalized: dict[str, Any] = {"concepts": {}, "graph": data.get("graph", {"nodes": {}, "edges": []})}
    if not isinstance(concepts, dict):
        concepts = {}
    for name, raw_details in concepts.items():
        details = raw_details if isinstance(raw_details, dict) else {"level": raw_details}
        level = str(clean_level_num(details.get("level", "1")))
        reviewed = details.get("last_review", utc_now().date().isoformat())
        normalized["concepts"][name] = {
            "level": level,
            "last_review": reviewed,
            "next_review": details.get("next_review", next_review_date(level)),
            "times_reviewed": int(details.get("times_reviewed", 1)),
            "mistakes": list(details.get("mistakes", [])),
        }
    return normalized


def load_state(path: Path = STATE_PATH) -> dict[str, Any]:
    """Load learner state, recovering gracefully from a missing or invalid file."""
    if not path.exists():
        return normalize_state({"concepts": {}})
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return normalize_state({"concepts": {}})
    return normalize_state(data) if isinstance(data, dict) else normalize_state({"concepts": {}})


def save_state(state: dict[str, Any], path: Path = STATE_PATH) -> None:
    """Persist learner state as readable JSON."""
    path.write_text(json.dumps(normalize_state(state), ensure_ascii=True, indent=2), encoding="utf-8")


def session_path(session_id: str) -> Path:
    SESSIONS_DIR.mkdir(exist_ok=True)
    return SESSIONS_DIR / f"{session_id}.json"


def save_session(session_id: str, messages: list[dict[str, Any]], summary: str = "") -> None:
    if not messages:
        return
    first_user = next((item["content"] for item in messages if item["role"] == "user"), "Sesión")
    payload = {
        "id": session_id,
        "title": first_user[:80],
        "updated_at": iso_now(),
        "summary": summary,
        "messages": messages,
    }
    session_path(session_id).write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def list_sessions() -> list[dict[str, Any]]:
    records = []
    if not SESSIONS_DIR.exists():
        return records
    for path in SESSIONS_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("messages"):
                records.append(data)
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(records, key=lambda item: item.get("updated_at", ""), reverse=True)


def load_session(session_id: str) -> dict[str, Any] | None:
    path = session_path(session_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def create_session_id(topic: str) -> str:
    stamp = utc_now().strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{slugify(topic)}"


def concept_node_id(name: str) -> str:
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
    return f"concept_{slugify(name)[:24]}_{digest}"


def concept_status(details: dict[str, Any]) -> str:
    next_review = details.get("next_review", "")
    if next_review and next_review <= utc_now().date().isoformat():
        return "due"
    level = clean_level_num(details.get("level", "1"))
    return "mastered" if level >= 4 else "review" if level >= 2 else "new"


def skill_graph_data(state: dict[str, Any]) -> dict[str, Any]:
    """Return a serializable graph model derived locally from learner state."""
    concepts = state.get("concepts", {})
    nodes = []
    edges = []
    for concept, details in concepts.items():
        details = details if isinstance(details, dict) else {"level": details}
        node_id = concept_node_id(concept)
        nodes.append(
            {
                "id": node_id,
                "label": concept,
                "level": str(clean_level_num(details.get("level", "1"))),
                "status": concept_status(details),
                "last_review": details.get("last_review", "sin datos"),
                "next_review": details.get("next_review", "sin datos"),
            }
        )
        edges.append({"from": "root", "to": node_id})
    return {"nodes": nodes, "edges": edges}


def parse_response(text: str) -> tuple[
    str,
    list[dict[str, str]],
    list[dict[str, str]],
    list[dict[str, str]],
    list[dict[str, str]],
]:
    """Extract tutor control tags and return clean chat text plus structured data."""
    updates: list[dict[str, str]] = []
    flashcards: list[dict[str, str]] = []
    quizzes: list[dict[str, str]] = []
    memory_notes: list[dict[str, str]] = []

    def collect_update(match: re.Match[str]) -> str:
        parts = [part.strip() for part in match.group(1).split("|", 1)]
        if len(parts) == 2 and parts[0] and parts[1]:
            updates.append({"concept": parts[0], "level": parts[1]})
        return ""

    def collect_flashcards(match: re.Match[str]) -> str:
        for line in match.group(1).splitlines():
            parts = [part.strip() for part in line.split(";", 1)]
            if len(parts) == 2 and parts[0] and parts[1]:
                flashcards.append({"concept": parts[0], "definition": parts[1]})
        return ""

    def collect_quiz(match: re.Match[str]) -> str:
        parts = [part.strip() for part in match.group(1).split("|")]
        if len(parts) >= 2 and all(parts):
            quizzes.append({"question": parts[0], "options": "|".join(parts[1:])})
        return ""

    def collect_memory_note(match: re.Match[str]) -> str:
        parts = [part.strip() for part in match.group(1).split("|", 1)]
        if len(parts) == 2 and all(parts):
            memory_notes.append({"concept": parts[0], "note": parts[1]})
        return ""

    clean_text = re.sub(r"<update_memory>(.*?)</update_memory>", collect_update, text, flags=re.DOTALL)
    clean_text = re.sub(r"<flashcards>(.*?)</flashcards>", collect_flashcards, clean_text, flags=re.DOTALL)
    clean_text = re.sub(r"<quiz>(.*?)</quiz>", collect_quiz, clean_text, flags=re.DOTALL)
    clean_text = re.sub(r"<memory_note>(.*?)</memory_note>", collect_memory_note, clean_text, flags=re.DOTALL)
    return clean_text.strip(), updates, flashcards, quizzes, memory_notes


def update_memory(
    state: dict[str, Any],
    updates: list[dict[str, str]],
    memory_notes: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Apply mastery updates with programmatic anti-inflation guardrails."""
    state = normalize_state(state)
    concepts = state.setdefault("concepts", {})
    graph = state.setdefault("graph", {"nodes": {}, "edges": []})
    for update in updates:
        concept = update["concept"]
        previous = concepts.get(concept, {})
        prev_level = clean_level_num(previous.get("level", 0)) if previous else 0
        target_level = clean_level_num(update["level"])

        # Anti-inflation guard: cap jump at previous + 1 (or max 2 on first entry)
        if prev_level == 0:
            effective_level = min(target_level, 2)
        else:
            effective_level = min(target_level, prev_level + 1)

        lvl = str(effective_level)
        reviewed_at = utc_now()
        concepts[concept] = {
            "level": lvl,
            "last_review": reviewed_at.date().isoformat(),
            "next_review": next_review_date(lvl, reviewed_at),
            "times_reviewed": int(previous.get("times_reviewed", 0)) + 1,
            "mistakes": list(previous.get("mistakes", [])),
        }
        node_id = concept_node_id(concept)
        graph.setdefault("nodes", {})[node_id] = {
            "label": concept,
            "level": lvl,
            "last_review": concepts[concept]["last_review"],
        }
    for note in memory_notes or []:
        concept = note["concept"]
        details = concepts.setdefault(
            concept,
            {
                "level": "1",
                "last_review": utc_now().date().isoformat(),
                "next_review": next_review_date("1"),
                "times_reviewed": 0,
                "mistakes": [],
            },
        )
        if note["note"] not in details["mistakes"]:
            details["mistakes"].append(note["note"])
    return state


def flashcards_csv(flashcards: list[dict[str, str]]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["concept", "definition"])
    writer.writeheader()
    writer.writerows(flashcards)
    return output.getvalue()


def flashcards_markdown(flashcards: list[dict[str, str]]) -> str:
    lines = ["# Flashcards de Repaso", ""]
    for card in flashcards:
        lines.extend([f"## {card['concept']}", "", card["definition"], ""])
    return "\n".join(lines)


def render_flashcards(flashcards: list[dict[str, str]]) -> None:
    """Render flashcards as clean, minimal study cards."""
    if not flashcards:
        return
    st.caption(f"Tarjetas de memoria generadas ({len(flashcards)})")
    cols = st.columns(min(2, len(flashcards)))
    for index, card in enumerate(flashcards):
        with cols[index % len(cols)]:
            st.markdown(
                f"""
                <div style="background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 12px; margin-bottom: 10px;">
                    <div style="font-size: 0.72rem; font-weight: 600; color: #8b949e; text-transform: uppercase; margin-bottom: 4px;">CONCEPTO</div>
                    <div style="font-size: 0.95rem; font-weight: 600; color: #f0f6fc; margin-bottom: 6px;">{card['concept']}</div>
                    <div style="font-size: 0.85rem; color: #c9d1d9; line-height: 1.5; border-top: 1px solid #21262d; padding-top: 6px;">{card['definition']}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def render_rich_text(text: str) -> None:
    """Render Markdown and Mermaid blocks cleanly without visual glitches."""
    parts = re.split(r"```mermaid\s*\n(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    for index, part in enumerate(parts):
        if not part.strip():
            continue
        if index % 2 == 0:
            st.markdown(part)
        else:
            mermaid_content = part.strip()
            line_count = len(mermaid_content.splitlines())
            computed_height = min(550, max(240, line_count * 34))
            components.html(
                f"""
                <!DOCTYPE html>
                <html>
                <head>
                  <meta charset="utf-8">
                  <style>
                    * {{ box-sizing: border-box; }}
                    body {{
                      margin: 0;
                      padding: 10px;
                      background: transparent;
                      color: #e6edf3;
                      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                      display: flex;
                      justify-content: center;
                    }}
                    .mermaid-card {{
                      width: 100%;
                      background: #161b22;
                      border: 1px solid #30363d;
                      border-radius: 8px;
                      padding: 16px;
                      overflow-x: auto;
                      display: flex;
                      justify-content: center;
                    }}
                    .mermaid {{
                      display: flex;
                      justify-content: center;
                      width: 100%;
                    }}
                  </style>
                </head>
                <body>
                  <div class="mermaid-card">
                    <div class="mermaid">
{mermaid_content}
                    </div>
                  </div>
                  <script type="module">
                    import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';
                    mermaid.initialize({{
                      startOnLoad: true,
                      securityLevel: 'loose',
                      theme: 'dark',
                      themeVariables: {{
                        darkMode: true,
                        background: '#161b22',
                        primaryColor: '#388bfd',
                        primaryTextColor: '#f0f6fc',
                        primaryBorderColor: '#30363d',
                        lineColor: '#58a6ff',
                        secondaryColor: '#21262d',
                        tertiaryColor: '#161b22'
                      }}
                    }});
                    await mermaid.run({{ querySelector: '.mermaid' }});
                  </script>
                </body>
                </html>
                """,
                height=computed_height,
                scrolling=True,
            )


def extract_document_text(uploaded_file: Any) -> str:
    """Extract text from an uploaded PDF, Markdown, or plain-text document.

    Enforces CTO/PO limits: 15 MB max, 100 pages max for PDFs.
    Raises ValueError with user-friendly messages if any constraint is violated.
    Per CISO rules: only raw text is extracted — the PDF bytes are never persisted.
    """
    # ── Guard: file size (15 MB) ────────────────────────────────────────────
    MAX_BYTES = 15 * 1024 * 1024
    file_bytes = uploaded_file.getvalue()
    if len(file_bytes) > MAX_BYTES:
        raise ValueError(
            "Este archivo supera el límite de 15 MB. "
            "Por favor, comprimelo o sube un capítulo más corto."
        )

    suffix = Path(uploaded_file.name).suffix.lower()

    if suffix in {".txt", ".md"}:
        return file_bytes.decode("utf-8", errors="replace")

    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as error:
            raise RuntimeError(
                "Instala pypdf: .venv/Scripts/pip install pypdf"
            ) from error

        reader = PdfReader(io.BytesIO(file_bytes))

        # ── Guard: page count (100 pages) ───────────────────────────────────
        MAX_PAGES = 100
        if len(reader.pages) > MAX_PAGES:
            raise ValueError(
                f"¡Es una lectura muy extensa! ({len(reader.pages)} páginas) "
                "Para enseñarte mejor, solo proceso hasta 100 páginas a la vez. "
                "Por favor, divide el PDF y sube la sección de hoy."
            )

        # ── Extract text (page by page, skip blank pages) ───────────────────
        pages_text = []
        for page in reader.pages:
            raw = page.extract_text()
            if raw:
                # Collapse excessive whitespace to reduce token bloat
                clean = re.sub(r"\n{3,}", "\n\n", raw.strip())
                pages_text.append(clean)

        extracted = "\n\n".join(pages_text).strip()

        # ── Guard: scanned / image-only PDF ─────────────────────────────────
        if not extracted:
            raise ValueError(
                "No encontré texto legible en este archivo. "
                "Parece ser un PDF escaneado (imagen). "
                "Por favor, asegúrate de que el PDF tenga texto seleccionable."
            )

        return extracted

    raise ValueError("Formato no compatible. Usa PDF, TXT o Markdown.")


def build_prompt(
    state: dict[str, Any],
    message: str,
    reference_material: str = "",
    history: list[dict[str, Any]] | None = None,
    summary: str = "",
) -> str:
    context = json.dumps(state, ensure_ascii=True)
    summary_text = f"\n\n[RESUMEN DE LA SESION]\n{summary}" if summary.strip() else ""
    history_text = ""
    if history:
        recent_history = history[-12:]
        history_text = "\n\n[HISTORIAL RECIENTE]\n" + "\n".join(format_history_item(item) for item in recent_history)
    material = ""
    if reference_material.strip():
        material = (
            "\n\n[MATERIAL DE REFERENCIA]\n"
            f"{reference_material.strip()}\n"
            "Basa la explicación estrictamente en este material y no inventes conceptos fuera de él."
        )
    return f"[ESTADO DEL ALUMNO]\n{context}{summary_text}{history_text}{material}\n\nMensaje del alumno:\n{message}"


def format_history_item(item: dict[str, Any]) -> str:
    entry = f"{item['role'].upper()}: {item['content']}"
    if item.get("flashcards"):
        entry += "\nFLASHCARDS DISPONIBLES:\n" + "\n".join(
            f"- {card['concept']}: {card['definition']}" for card in item["flashcards"]
        )
    if item.get("memory_notes"):
        entry += "\nNOTAS DE MEMORIA:\n" + "\n".join(
            f"- {note['concept']}: {note['note']}" for note in item["memory_notes"]
        )
    return entry


def ask_tutor(
    client: genai.Client,
    state: dict[str, Any],
    message: str,
    reference_material: str = "",
    history: list[dict[str, Any]] | None = None,
    summary: str = "",
) -> str:
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=build_prompt(state, message, reference_material, history, summary),
        config={"system_instruction": (ROOT / "orchestrator_agent.md").read_text(encoding="utf-8")},
    )
    return response.text or "No recibí una respuesta del tutor. Inténtalo de nuevo."


def summarize_conversation(client: genai.Client, messages: list[dict[str, Any]]) -> str:
    """Compress a long session into durable learning context."""
    prompt = (
        "Resume esta sesión de aprendizaje en Markdown conciso. Incluye:\n"
        "- tema actual\n- conceptos comprendidos\n- confusiones detectadas\n- próximo paso\n"
        f"{session_transcript(messages)}"
    )
    response = client.models.generate_content(model=MODEL_NAME, contents=prompt)
    return response.text or ""


def skill_tree_mermaid(state: dict[str, Any]) -> str:
    """Build a Mermaid skill tree locally with high-contrast palette."""
    graph = skill_graph_data(state)
    lines = ["graph TD", '  root["Tutor Socrático"]']
    classes: list[str] = []
    for node in graph["nodes"]:
        label = node["label"].replace('"', "'").replace("\n", " ")[:48]
        level = node["level"]
        lines.append(f'  root --> {node["id"]}["{label}<br>Nivel {level}"]')
        classes.append(f"class {node['id']} {node['status']}")
    lines.extend(
        [
            "  classDef mastered fill:#1b4728,color:#d1fae5,stroke:#2ea043,stroke-width:1px",
            "  classDef review fill:#59380a,color:#fef3c7,stroke:#d97706,stroke-width:1px",
            "  classDef new fill:#21262d,color:#e6edf3,stroke:#8b949e,stroke-width:1px",
            "  classDef due fill:#5c1d24,color:#fee2e2,stroke:#f87171,stroke-width:1px",
            "  classDef default fill:#161b22,color:#f0f6fc,stroke:#58a6ff,stroke-width:1px",
            *classes,
        ]
    )
    return "\n".join(lines)


def session_transcript(messages: list[dict[str, Any]]) -> str:
    return "\n\n".join(format_history_item(m) for m in messages)


def generate_cheat_sheet(client: genai.Client, messages: list[dict[str, Any]]) -> str:
    prompt = (
        "Crea un apunte ejecutivo en Markdown a partir de esta sesión. Incluye:\n"
        "1. ## Resumen Ejecutivo de 30 Segundos (Idea central y valor del tema).\n"
        "2. ## Verdades Incondicionales Establecidas (Principios no negociables).\n"
        "3. ## Diagramas Conceptuales (Conserva bloques ```mermaid``` intactos si existen).\n"
        "4. ## Preguntas Clave para Repaso Futuro (Autoevaluación).\n"
        "Sé preciso y conciso. No inventes contenido fuera de la conversación.\n\n"
        f"{session_transcript(messages)}"
    )
    response = client.models.generate_content(model=MODEL_NAME, contents=prompt)
    return response.text or "# Apunte de Sesión\n\nNo se pudo generar contenido."


def render_quiz(quiz: dict[str, str], index: int, key_prefix: str = "") -> None:
    options = [option.strip() for option in quiz["options"].split("|") if option.strip()]
    if not options:
        return
    with st.container(border=True):
        st.caption(f"Pregunta de Verificación #{index + 1}")
        answer = st.radio(
            quiz["question"],
            options,
            key=f"quiz_{key_prefix}_{index}",
            label_visibility="visible",
        )
        if st.button("Enviar Respuesta", key=f"submit_quiz_{key_prefix}_{index}", type="primary"):
            st.session_state.quiz_submission = (
                f"Respondí el quiz '{quiz['question']}' con la opción '{answer}'. "
                "Evalúa mi respuesta, explica si es correcta y continúa con el método socrático."
            )
            st.rerun()


def main() -> None:
    st.set_page_config(
        page_title="Socrates · Tutor Socrático",
        page_icon="🎓",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    apply_styles()

    # Session State Initialization
    if "learner_state" not in st.session_state:
        st.session_state.learner_state = load_state()
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "flashcards" not in st.session_state:
        st.session_state.flashcards = []
    if "last_flashcards" not in st.session_state:
        st.session_state.last_flashcards = []
    if "reference_material" not in st.session_state:
        st.session_state.reference_material = ""
    if "reference_filename" not in st.session_state:
        st.session_state.reference_filename = ""
    if "cheat_sheet" not in st.session_state:
        st.session_state.cheat_sheet = ""
    if "quiz_submission" not in st.session_state:
        st.session_state.quiz_submission = ""
    if "pending_prompt" not in st.session_state:
        st.session_state.pending_prompt = ""
    if "conversation_summary" not in st.session_state:
        st.session_state.conversation_summary = ""
    if "current_session_id" not in st.session_state:
        st.session_state.current_session_id = ""
    if "session_notice" not in st.session_state:
        st.session_state.session_notice = ""
    if "study_card_idx" not in st.session_state:
        st.session_state.study_card_idx = 0
    if "study_card_revealed" not in st.session_state:
        st.session_state.study_card_revealed = False

    # Always initialize chat_user_input to prevent UnboundLocalError across tabs
    chat_user_input: str | None = None

    # Calculate global telemetry
    concepts = st.session_state.learner_state.get("concepts", {})
    stats = calculate_learner_stats(concepts)
    due_concepts = get_due_concepts(concepts)

    # SIDEBAR: ACTIONABLE COMMAND CENTER
    with st.sidebar:
        st.markdown(
            """
            <div style="padding-bottom: 10px; margin-bottom: 12px; border-bottom: 1px solid #222;">
                <div style="font-size: 1.25rem; font-weight: 700; color: #00E5FF; letter-spacing: -0.5px;">⚡ AI Teacher</div>
                <div style="font-size: 0.75rem; color: #888;">Powered by Antigravity</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        view_mapping = {
            "Inicio": "home",
            "Tutor (Estudio)": "tutor",
            "Árbol de Habilidades": "tree",
            "Flashcards": "flashcards",
            "Apuntes de Sesión": "notes",
        }
        selected_nav = st.radio(
            "Navegación",
            list(view_mapping.keys()),
            label_visibility="collapsed",
        )
        active_view = view_mapping.get(selected_nav, "home")
        
        st.markdown("<hr style='margin: 1rem 0; border-color: #222;'>", unsafe_allow_html=True)
        # Primary Quick Action: Start Fresh Session
        if st.button("+ Nueva Sesión", key="btn_new_session", type="primary"):
            st.session_state.current_session_id = ""
            st.session_state.messages = []
            st.session_state.flashcards = []
            st.session_state.conversation_summary = ""
            st.session_state.session_notice = "Nueva sesión lista. Elige una sugerencia o escribe tu tema."
            st.rerun()

        # 1-CLICK DAILY SPACED REPETITION DRILL
        if due_concepts:
            st.markdown(
                f"""
                <div style="background: rgba(248, 113, 113, 0.08); border: 1px solid rgba(248, 113, 113, 0.25); border-radius: 6px; padding: 10px; margin: 12px 0;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                        <span style="font-size: 0.74rem; font-weight: 700; color: #f87171; text-transform: uppercase;">⚡ Repaso Espaciado Hoy</span>
                        <span style="background: rgba(248, 113, 113, 0.2); color: #fca5a5; font-size: 0.7rem; font-weight: 700; padding: 1px 6px; border-radius: 9999px;">{len(due_concepts)}</span>
                    </div>
                    <div style="font-size: 0.78rem; color: #cbd5e1; margin-bottom: 6px;">
                        Tienes conceptos vencidos listos para consolidar en memoria.
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if st.button("▶ Iniciar Repaso Diario (3 min)", key="btn_start_due_review"):
                sample_due = due_concepts[:3]
                st.session_state.pending_prompt = (
                    f"Quiero iniciar mi sesión de repaso espaciado diario para afianzar los conceptos que tengo pendientes: {', '.join(sample_due)}. "
                    "Hazme una pregunta directa de recuperación activa sobre el primero para evaluar mi retención sin rodeos."
                )
                st.rerun()
        else:
            st.markdown(
                """
                <div style="font-size: 0.76rem; color: #34d399; background: rgba(52, 211, 153, 0.08); border: 1px solid rgba(52, 211, 153, 0.2); border-radius: 6px; padding: 6px 10px; margin: 10px 0;">
                    ✓ Repasos espaciados al día
                </div>
                """,
                unsafe_allow_html=True,
            )

        # RECENT SESSIONS WORKSPACE
        session_records = list_sessions()
        if session_records:
            st.markdown(
                """
                <div style="font-size: 0.74rem; font-weight: 600; text-transform: uppercase; color: #8b949e; margin: 14px 0 6px 0;">
                    Sesiones Recientes
                </div>
                """,
                unsafe_allow_html=True,
            )
            for rec in session_records[:4]:
                sid = rec["id"]
                is_active = (sid == st.session_state.current_session_id)
                title = rec.get("title", sid)[:26]
                rel_time = format_relative_time(rec.get("updated_at", ""))
                label = f"{'● ' if is_active else '○ '}{title} ({rel_time})"
                if st.button(label, key=f"sess_{sid}", disabled=is_active):
                    record = load_session(sid)
                    if record:
                        st.session_state.current_session_id = record["id"]
                        st.session_state.messages = record.get("messages", [])
                        st.session_state.conversation_summary = record.get("summary", "")
                        st.session_state.session_notice = f"Sesión '{title}' cargada."
                        st.rerun()

            if len(session_records) > 4:
                with st.expander("Ver sesiones anteriores..."):
                    all_by_id = {r["id"]: r for r in session_records}
                    sel_all = st.selectbox(
                        "Todas las sesiones",
                        options=[""] + list(all_by_id.keys()),
                        format_func=lambda x: "Elegir sesión..." if not x else f"{all_by_id[x].get('title', x)[:32]} ({format_relative_time(all_by_id[x].get('updated_at', ''))})",
                        key="sel_all_sessions",
                        label_visibility="collapsed",
                    )
                    if sel_all and sel_all != st.session_state.current_session_id:
                        if st.button("Cargar sesión", key="btn_load_more_sess"):
                            rec = load_session(sel_all)
                            if rec:
                                st.session_state.current_session_id = rec["id"]
                                st.session_state.messages = rec.get("messages", [])
                                st.session_state.conversation_summary = rec.get("summary", "")
                                st.session_state.session_notice = "Sesión cargada."
                                st.rerun()

        # RAG / DOCUMENT INSPECTOR & DETACH
        st.markdown(
            """
            <div style="font-size: 0.74rem; font-weight: 600; text-transform: uppercase; color: #8b949e; margin: 14px 0 6px 0;">
                Material de Referencia
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.session_state.reference_material:
            doc_label = st.session_state.reference_filename or "Documento activo"
            char_count = len(st.session_state.reference_material)
            page_estimate = max(1, char_count // 2000)
            st.markdown(
                f"""
                <div style="background: rgba(0,229,255,0.05); border: 1px solid rgba(0,229,255,0.2); border-radius: 6px; padding: 8px 10px; margin-bottom: 6px;">
                    <div style="font-size: 0.78rem; font-weight: 600; color: #00E5FF; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="{doc_label}">
                        📄 {doc_label}
                    </div>
                    <div style="font-size: 0.70rem; color: #888; margin-top: 2px;">
                        {char_count:,} caracteres · ~{page_estimate} págs indexadas
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if st.button("✕ Desvincular documento", key="btn_detach_doc"):
                st.session_state.reference_material = ""
                st.session_state.reference_filename = ""
                st.session_state.session_notice = "Documento desvinculado de la memoria."
                st.rerun()
        else:
            st.caption("Sube tu material de estudio — Formato: PDF, TXT o MD · Límite: 15 MB y 100 páginas")
            uploaded_file = st.file_uploader(
                "Cargar apunte",
                type=SUPPORTED_DOCUMENTS,
                label_visibility="collapsed",
                key="uploader_input",
            )
            if uploaded_file is not None:
                with st.spinner("Analizando tu documento para preparar la clase..."):
                    try:
                        text = extract_document_text(uploaded_file)
                        st.session_state.reference_material = text
                        st.session_state.reference_filename = uploaded_file.name
                        st.session_state.session_notice = f"✓ '{uploaded_file.name}' listo. Ya puedes preguntarme sobre él."
                        st.rerun()
                    except ValueError as err:
                        st.warning(str(err))
                    except (OSError, RuntimeError) as err:
                        st.error(f"Error al procesar el documento: {err}")


        # TELEMETRY PROGRESS & CONCEPTS LEDGER
        st.markdown(
            f"""
            <div style="background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 10px; margin: 14px 0 8px 0;">
                <div style="display: flex; justify-content: space-between; font-size: 0.76rem; color: #8b949e; margin-bottom: 4px;">
                    <span>Dominio Global</span>
                    <span style="font-weight: 600; color: #e6edf3;">{stats['mastery_percent']}%</span>
                </div>
                <div style="width: 100%; height: 4px; background: #21262d; border-radius: 2px; margin-bottom: 8px;">
                    <div style="width: {stats['mastery_percent']}%; height: 100%; background: #388bfd; border-radius: 2px;"></div>
                </div>
                <div style="display: flex; justify-content: space-between; font-size: 0.78rem; color: #c9d1d9;">
                    <span>Conceptos: <b>{stats['total']}</b></span>
                    <span>Dominados: <b>{stats['mastered']}</b></span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if concepts:
            with st.expander(f"Registro de Conceptos ({len(concepts)})", expanded=False):
                for name, det in concepts.items():
                    details = det if isinstance(det, dict) else {"level": det}
                    lvl = clean_level_num(details.get("level", 1))
                    lbl, col, bg = level_metadata(lvl)
                    st.markdown(
                        f"""
                        <div style="display: flex; justify-content: space-between; align-items: center; padding: 4px 0; border-bottom: 1px solid #21262d;">
                            <span style="font-size: 0.78rem; color: #c9d1d9; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 160px;" title="{name}">{name}</span>
                            <span style="background: {bg}; color: {col}; font-size: 0.68rem; font-weight: 600; padding: 1px 6px; border-radius: 4px;">
                                Lvl {lvl}
                            </span>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

        st.divider()

        # SESSION ACTION: FINALIZE & EXPORT CHEAT SHEET
        if st.button("Finalizar Sesión & Crear Apunte", key="btn_finalize_session"):
            api_key = get_api_key()
            if not api_key:
                st.error("Configura GEMINI_API_KEY para generar el apunte.")
            elif not st.session_state.messages:
                st.warning("No hay conversación activa para sintetizar.")
            else:
                try:
                    with st.spinner("Sintetizando apunte ejecutivo..."):
                        st.session_state.cheat_sheet = generate_cheat_sheet(
                            genai.Client(api_key=api_key), st.session_state.messages
                        )
                        if st.session_state.current_session_id:
                            save_session(
                                st.session_state.current_session_id,
                                st.session_state.messages,
                                st.session_state.conversation_summary,
                            )
                        st.session_state.last_flashcards = list(st.session_state.flashcards)
                        st.session_state.messages = []
                        st.session_state.flashcards = []
                        st.session_state.reference_material = ""
                        st.session_state.reference_filename = ""
                        st.session_state.quiz_submission = ""
                        st.session_state.conversation_summary = ""
                        st.session_state.current_session_id = ""
                        st.session_state.session_notice = "Sesión finalizada. Apunte generado con éxito."
                        st.rerun()
                except Exception as error:
                    st.error(f"Error al generar el apunte: {error}")

        if st.session_state.session_notice:
            st.success(st.session_state.session_notice)
            st.session_state.session_notice = ""


    # VIEW: INICIO (DASHBOARD)
    if active_view == "home":
        st.markdown(
            """
            <div style='text-align: left; padding: 1rem 0 2rem 0;'>
                <h1 style='font-size: 2.5rem; font-weight: 700; letter-spacing: -1px; margin-bottom: 0.5rem;'>Bienvenido de vuelta.</h1>
                <p style='color: #888; font-size: 1.1rem;'>Tu panel de control de aprendizaje.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        
        col1, col2, col3 = st.columns(3)
        col1.metric("Conceptos Totales", stats["total"])
        col2.metric("Dominio Promedio", f"{stats['mastery_percent']}%")
        col3.metric("Repasos Pendientes", stats["due"])
        
        st.markdown("<h3 style='margin-top: 2rem;'>Acciones Rápidas</h3>", unsafe_allow_html=True)
        q1, q2, q3 = st.columns(3)
        with q1:
            st.markdown("<div class='ag-card'><h4>📘 Continuar Tema</h4><p style='color:#888; font-size: 0.85rem;'>Sigue donde lo dejaste en tu última sesión activa.</p></div>", unsafe_allow_html=True)
            if st.button("Ir al Tutor", use_container_width=True):
                # Cannot change st.radio programmatically easily without session state linked to widget, but just a UI mock for now
                pass
        with q2:
            st.markdown("<div class='ag-card'><h4>⚡ Repaso Activo</h4><p style='color:#888; font-size: 0.85rem;'>Tienes flashcards programadas para repasar hoy.</p></div>", unsafe_allow_html=True)
        with q3:
            st.markdown("<div class='ag-card'><h4>📊 Ver Progreso</h4><p style='color:#888; font-size: 0.85rem;'>Analiza tus conceptos dominados y dependencias.</p></div>", unsafe_allow_html=True)
            
        st.markdown("<h3 style='margin-top: 2rem;'>Historial de Sesiones</h3>", unsafe_allow_html=True)
        sessions_list = list_sessions()
        if sessions_list:
            for sess in sessions_list[:5]:
                with st.container(border=True):
                    st.markdown(f"**{sess.get('title', 'Sesión')}**")
                    st.caption(f"Última actividad: {format_relative_time(sess.get('updated_at', ''))}")
        else:
            st.info("No hay sesiones recientes.")

    # VIEW: ÁRBOL DE HABILIDADES
    elif active_view == "tree":
        st.subheader("Árbol de Habilidades & Dependencias")
        if concepts:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Conceptos", stats["total"])
            c2.metric("Nivel Medio", f"{stats['average_level']}/5")
            c3.metric("Dominados", stats["mastered"])
            c4.metric("Por Repasar", stats["due"])

            render_rich_text(f"```mermaid\n{skill_tree_mermaid(st.session_state.learner_state)}\n```")

            st.caption("Inspección de conceptos")
            selected_concept = st.selectbox(
                "Inspeccionar concepto",
                ["Seleccionar..."] + list(concepts.keys()),
                label_visibility="collapsed",
            )
            if selected_concept and selected_concept != "Seleccionar...":
                details = concepts[selected_concept]
                details = details if isinstance(details, dict) else {"level": details}
                lvl_val = clean_level_num(details.get("level", 1))
                lbl, col, _ = level_metadata(lvl_val)

                with st.container(border=True):
                    st.markdown(f"**{selected_concept}** · {lbl} (Nivel {lvl_val}/5)")
                    ic1, ic2, ic3 = st.columns(3)
                    ic1.write(f"**Último repaso:** {details.get('last_review', 'N/A')}")
                    ic2.write(f"**Próximo repaso:** {details.get('next_review', 'N/A')}")
                    ic3.write(f"**Repasos:** {details.get('times_reviewed', 0)}")

                    mistakes = details.get("mistakes", [])
                    if mistakes:
                        st.warning("Confusiones detectadas previamente: " + "; ".join(mistakes))
        else:
            st.info("Aún no hay conceptos en memoria. Comienza una conversación en el Tutor para registrar conceptos.")

    # VIEW: APUNTE DE SESIÓN
    elif active_view == "notes":
        st.subheader("Apunte de Sesión")
        if st.session_state.cheat_sheet:
            exp_col1, exp_col2 = st.columns([1, 1])
            with exp_col1:
                st.download_button(
                    "📥 Descargar Markdown (.md)",
                    data=st.session_state.cheat_sheet,
                    file_name=f"apunte_{datetime.now():%Y%m%d_%H%M}.md",
                    mime="text/markdown",
                    use_container_width=True,
                    type="primary",
                )
            with exp_col2:
                with st.expander("📋 Ver Markdown en bruto para copiar"):
                    st.code(st.session_state.cheat_sheet, language="markdown")

            with st.container(border=True):
                render_rich_text(st.session_state.cheat_sheet)
        else:
            st.info("Aún no se ha generado un apunte. Usa 'Finalizar Sesión & Crear Apunte' en la barra lateral para sintetizar la sesión actual.")

    # VIEW: FLASHCARDS (ACTIVE RECALL & DECK MODES)
    elif active_view == "flashcards":
        visible_flashcards = st.session_state.flashcards or st.session_state.last_flashcards
        st.subheader(f"Flashcards de Repaso ({len(visible_flashcards)})")

        if visible_flashcards:
            fc_mode = st.radio(
                "Modo de Flashcards",
                ["🗂️ Modo Estudio Activo (Flipping)", "📋 Mazo Completo"],
                horizontal=True,
                label_visibility="collapsed",
            )

            # MODE 1: ACTIVE RECALL STUDY FLIPPER
            if fc_mode == "🗂️ Modo Estudio Activo (Flipping)":
                total_cards = len(visible_flashcards)
                current_idx = min(st.session_state.study_card_idx, total_cards - 1)
                card = visible_flashcards[current_idx]

                st.caption(f"Tarjeta {current_idx + 1} de {total_cards}")
                st.progress((current_idx + 1) / total_cards)

                with st.container(border=True):
                    st.markdown(
                        f"""
                        <div style="padding: 16px 8px; text-align: center;">
                            <div style="font-size: 0.72rem; font-weight: 600; color: #8b949e; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 6px;">
                                CONCEPTO A RECORDAR
                            </div>
                            <div style="font-size: 1.25rem; font-weight: 700; color: #f0f6fc; line-height: 1.4;">
                                {card['concept']}
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                    if not st.session_state.study_card_revealed:
                        if st.button("👁️ Mostrar Definición", key="btn_reveal_def", use_container_width=True, type="primary"):
                            st.session_state.study_card_revealed = True
                            st.rerun()
                    else:
                        st.markdown(
                            f"""
                            <div style="border-top: 1px solid #30363d; padding-top: 12px; margin-top: 8px;">
                                <div style="font-size: 0.72rem; font-weight: 600; color: #58a6ff; text-transform: uppercase; margin-bottom: 6px;">
                                    DEFINICIÓN / EXPLICACIÓN
                                </div>
                                <div style="font-size: 0.95rem; color: #e6edf3; line-height: 1.6;">
                                    {card['definition']}
                                </div>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

                        st.caption("Autoevaluación de recuerdo:")
                        r_col1, r_col2, r_col3 = st.columns(3)
                        with r_col1:
                            if st.button("🔴 Me costó / Olvidado", key="btn_card_hard", use_container_width=True):
                                c_name = card["concept"]
                                if c_name in st.session_state.learner_state.get("concepts", {}):
                                    st.session_state.learner_state["concepts"][c_name]["level"] = "1"
                                    st.session_state.learner_state["concepts"][c_name]["next_review"] = utc_now().date().isoformat()
                                    save_state(st.session_state.learner_state)
                                st.session_state.study_card_revealed = False
                                st.session_state.study_card_idx = (current_idx + 1) % total_cards
                                st.rerun()
                        with r_col2:
                            if st.button("🟡 Parcial", key="btn_card_medium", use_container_width=True):
                                c_name = card["concept"]
                                if c_name in st.session_state.learner_state.get("concepts", {}):
                                    st.session_state.learner_state["concepts"][c_name]["times_reviewed"] = int(st.session_state.learner_state["concepts"][c_name].get("times_reviewed", 0)) + 1
                                    save_state(st.session_state.learner_state)
                                st.session_state.study_card_revealed = False
                                st.session_state.study_card_idx = (current_idx + 1) % total_cards
                                st.rerun()
                        with r_col3:
                            if st.button("🟢 Lo sabía bien", key="btn_card_easy", use_container_width=True, type="primary"):
                                c_name = card["concept"]
                                if c_name in st.session_state.learner_state.get("concepts", {}):
                                    prev = clean_level_num(st.session_state.learner_state["concepts"][c_name].get("level", 1))
                                    new_lvl = min(5, prev + 1)
                                    st.session_state.learner_state["concepts"][c_name]["level"] = str(new_lvl)
                                    st.session_state.learner_state["concepts"][c_name]["last_review"] = utc_now().date().isoformat()
                                    st.session_state.learner_state["concepts"][c_name]["next_review"] = next_review_date(str(new_lvl))
                                    st.session_state.learner_state["concepts"][c_name]["times_reviewed"] = int(st.session_state.learner_state["concepts"][c_name].get("times_reviewed", 0)) + 1
                                    save_state(st.session_state.learner_state)
                                st.session_state.study_card_revealed = False
                                st.session_state.study_card_idx = (current_idx + 1) % total_cards
                                st.rerun()

            # MODE 2: COMPLETE DECK LIST
            else:
                fc_col1, fc_col2, search_col = st.columns([1, 1, 2])
                with fc_col1:
                    st.download_button(
                        "Exportar CSV",
                        data=flashcards_csv(visible_flashcards),
                        file_name="flashcards.csv",
                        mime="text/csv",
                        use_container_width=True,
                    )
                with fc_col2:
                    st.download_button(
                        "Exportar Markdown",
                        data=flashcards_markdown(visible_flashcards),
                        file_name="flashcards.md",
                        mime="text/markdown",
                        use_container_width=True,
                    )
                with search_col:
                    filter_q = st.text_input("Filtrar", placeholder="Buscar concepto o término...", label_visibility="collapsed").strip().lower()

                filtered = [
                    c for c in visible_flashcards
                    if not filter_q or filter_q in c["concept"].lower() or filter_q in c["definition"].lower()
                ]

                card_cols = st.columns(2)
                for idx, card in enumerate(filtered):
                    with card_cols[idx % 2]:
                        with st.container(border=True):
                            st.markdown(f"**{card['concept']}**")
                            st.caption(card["definition"])
        else:
            st.info("No hay flashcards generadas aún. El tutor las creará a medida que afiances conceptos en el diálogo.")

    # VIEW: TUTOR (CHAT)
    else:
        if st.session_state.conversation_summary:
            with st.expander("Resumen de contexto de la sesión activa", expanded=False):
                st.markdown(st.session_state.conversation_summary)

        # Starter prompts — context-aware (PO: Action Pills spec)
        if not st.session_state.messages:
            if st.session_state.reference_material:
                # ── Document loaded: show document-specific Action Pills ──────
                doc_name = st.session_state.reference_filename or "tu documento"
                st.markdown(
                    f"""
                    <div style="padding: 1rem 0 0.75rem 0;">
                        <div style="font-size: 1.1rem; font-weight: 600; color: #EAEAEA; margin-bottom: 4px;">
                            📄 <span style="color: #00E5FF;">{doc_name}</span> listo.
                        </div>
                        <div style="font-size: 0.85rem; color: #888; margin-bottom: 1rem;">
                            ¿Por dónde empezamos? Elige una acción o escribe tu pregunta directamente.
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                pill_col1, pill_col2, pill_col3 = st.columns(3)
                with pill_col1:
                    if st.button("⚡ Resumen Rápido", key="doc_p1", use_container_width=True):
                        st.session_state.pending_prompt = (
                            "Dame los 3 puntos clave y el tema principal de este documento "
                            "de forma clara y directa."
                        )
                        st.rerun()
                with pill_col2:
                    if st.button("🎯 Hazme un Quiz", key="doc_p2", use_container_width=True):
                        st.session_state.pending_prompt = (
                            "Hazme 3 preguntas de opción múltiple para evaluar mi comprensión "
                            "inicial de este texto. Usa términos y ejemplos del documento."
                        )
                        st.rerun()
                with pill_col3:
                    if st.button("🔬 Conceptos Difíciles", key="doc_p3", use_container_width=True):
                        st.session_state.pending_prompt = (
                            "Extrae los términos técnicos o conceptos más complejos de este texto "
                            "y explícalos de forma directa y sencilla, uno por uno."
                        )
                        st.rerun()
            else:
                # ── No document: show generic topic pills ────────────────────
                st.markdown(
                    """
                    <div style="padding: 1rem 0 0.75rem 0;">
                        <div style="font-size: 1.15rem; font-weight: 600; color: #EAEAEA; margin-bottom: 4px;">
                            ¿Sobre qué tema deseas profundizar hoy?
                        </div>
                        <div style="font-size: 0.85rem; color: #888; margin-bottom: 1rem;">
                            Elige una sugerencia para iniciar el diálogo socrático o escribe tu propio objetivo.
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("📐 **Cálculo:** Derivada como velocidad instantánea", key="p1", use_container_width=True):
                        st.session_state.pending_prompt = "Quiero comprender por qué la derivada representa la velocidad instantánea y cómo se supera la división por cero desde primeros principios."
                        st.rerun()
                    if st.button("🤖 **Inteligencia Artificial:** Auto-atención en Transformers", key="p2", use_container_width=True):
                        st.session_state.pending_prompt = "Explícame el mecanismo de auto-atención (Self-Attention) en modelos Transformers desde primeros principios."
                        st.rerun()
                with col2:
                    if st.button("⚖️ **Derecho:** Colisión de normas y jerarquía", key="p3", use_container_width=True):
                        st.session_state.pending_prompt = "Quiero explorar cómo resuelve la teoría general del derecho la colisión entre normas de igual jerarquía."
                        st.rerun()
                    if st.button("🎯 **Diagnóstico:** Pon a prueba mis fundamentos", key="p4", use_container_width=True):
                        st.session_state.pending_prompt = "Hazme un sondeo de 3 preguntas socráticas para diagnosticar mis fundamentos conceptuales en un tema clave."
                        st.rerun()

        # Render message history
        for message_index, message in enumerate(st.session_state.messages):
            with st.chat_message(message["role"]):
                render_rich_text(message["content"])
                render_flashcards(message.get("flashcards", []))
                for index, quiz in enumerate(message.get("quizzes", [])):
                    render_quiz(quiz, index, str(message_index))

        # PEDAGOGICAL STEERING CHIPS (Visible when conversation is active)
        if st.session_state.messages:
            st.caption("Moduladores pedagógicos rápidos:")
            chip_col1, chip_col2, chip_col3, chip_col4, chip_col5 = st.columns(5)
            with chip_col1:
                if st.button("💡 Analogía simple", key="chip_analogy", use_container_width=True):
                    st.session_state.pending_prompt = "Explícame esto con una analogía cotidiana intuitiva y sencilla para afianzar la intuición."
                    st.rerun()
            with chip_col2:
                if st.button("🔬 Caso límite", key="chip_edge_case", use_container_width=True):
                    st.session_state.pending_prompt = "Dame un caso límite o contraejemplo extremo para poner a prueba si realmente comprendo los límites de este concepto."
                    st.rerun()
            with chip_col3:
                if st.button("🎯 ¿Por qué importa?", key="chip_why_matters", use_container_width=True):
                    st.session_state.pending_prompt = "¿Qué problema práctico real motivó la invención de este concepto y por qué fallaban las soluciones previas?"
                    st.rerun()
            with chip_col4:
                if st.button("⚡ Pruébame", key="chip_quiz_me", use_container_width=True):
                    st.session_state.pending_prompt = "Hazme una pregunta socrática desafiante o un quiz para comprobar si he asimilado este concepto correctamente."
                    st.rerun()
            with chip_col5:
                if st.button("🔓 Dame la respuesta", key="chip_escape_valve", use_container_width=True):
                    st.session_state.pending_prompt = "Activa la válvula de escape: detén las preguntas socráticas por un momento, dame la respuesta directa y clara con su explicación, y luego pídeme que te la resuma con mis palabras."
                    st.rerun()

        chat_user_input = st.chat_input("Escribe tu respuesta o pregunta...")

    # Resolve Prompt Trigger safely
    prompt = None
    if chat_user_input:
        prompt = chat_user_input
    elif st.session_state.quiz_submission:
        prompt = st.session_state.quiz_submission
        st.session_state.quiz_submission = ""
    elif st.session_state.pending_prompt:
        prompt = st.session_state.pending_prompt
        st.session_state.pending_prompt = ""

    # Execute Socratic Cycle
    if prompt:
        if not st.session_state.current_session_id:
            st.session_state.current_session_id = create_session_id(prompt)
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            render_rich_text(prompt)

        api_key = get_api_key()
        if not api_key:
            st.error("Configura la variable de entorno GEMINI_API_KEY para iniciar el tutor.")
            return

        with st.chat_message("assistant"):
            try:
                with st.spinner("Razonando..."):
                    response = ask_tutor(
                        genai.Client(api_key=api_key),
                        st.session_state.learner_state,
                        prompt,
                        st.session_state.reference_material,
                        st.session_state.messages[:-1],
                        st.session_state.conversation_summary,
                    )
                clean_text, updates, flashcards, quizzes, memory_notes = parse_response(response)
                render_rich_text(clean_text)
                st.session_state.learner_state = update_memory(
                    st.session_state.learner_state, updates, memory_notes
                )
                save_state(st.session_state.learner_state)
                st.session_state.flashcards.extend(flashcards)
                FLASHCARDS_PATH.write_text(
                    flashcards_csv(st.session_state.flashcards), encoding="utf-8"
                )
                for index, quiz in enumerate(quizzes):
                    render_quiz(quiz, index, f"live_{len(st.session_state.messages)}")
                render_flashcards(flashcards)
                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": clean_text,
                        "flashcards": flashcards,
                        "memory_notes": memory_notes,
                        "quizzes": quizzes,
                    }
                )
                if len(st.session_state.messages) >= SUMMARY_INTERVAL and len(st.session_state.messages) % SUMMARY_INTERVAL == 0:
                    try:
                        st.session_state.conversation_summary = summarize_conversation(
                            genai.Client(api_key=api_key), st.session_state.messages
                        )
                    except Exception:
                        pass
                save_session(
                    st.session_state.current_session_id,
                    st.session_state.messages,
                    st.session_state.conversation_summary,
                )
            except Exception as error:
                st.error(f"Error del tutor: {error}")


if __name__ == "__main__":
    main()