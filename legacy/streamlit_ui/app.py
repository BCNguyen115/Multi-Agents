"""Streamlit Chat UI — Frontend testing interface.

Provides a multi-agent chat interface with two modes:
  1. **RAG Agent**: Text-based Q&A grounded in internal documents.
  2. **Data Agent**: Upload a CSV file and ask analysis questions
     to generate interactive dashboards (Plotly + AgGrid).

Usage:
    streamlit run src/ui/app.py
"""

import io
import os
import uuid
from typing import Any

import httpx
import pandas as pd
import plotly.express as px
import streamlit as st
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_API_BASE_URL: str = os.getenv("API_URL", "http://localhost:8000/api/chat").rsplit("/api/chat", 1)[0]
_CHAT_ENDPOINT: str = os.getenv("API_URL", "http://localhost:8000/api/chat")
_ANALYZE_ENDPOINT: str = f"{_API_BASE_URL}/api/analyze"
_REQUEST_TIMEOUT: float = 60.0  # seconds (longer for LLM code generation)

# ---------------------------------------------------------------------------
# Page configuration
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Multi-Agent Enterprise Chat",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Session state initialisation
# ---------------------------------------------------------------------------

if "session_id" not in st.session_state:
    st.session_state["session_id"] = str(uuid.uuid4())

if "messages" not in st.session_state:
    st.session_state["messages"] = []

if "current_agent_mode" not in st.session_state:
    st.session_state["current_agent_mode"] = "RAG Agent"

session_id: str = st.session_state["session_id"]

# ---------------------------------------------------------------------------
# Sidebar — Settings & History Reset
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("Cài Đặt")
    st.caption(f"Session: `{session_id}`")
    st.divider()

    if st.button("Xóa lịch sử chat", use_container_width=True):
        st.session_state["messages"] = []
        st.rerun()

# ---------------------------------------------------------------------------
# Main Header & Agent Selector Menu
# ---------------------------------------------------------------------------

st.title("Multi-Agent Enterprise System")

# Agent selection menu buttons
col1, col2, col3 = st.columns(3)
with col1:
    rag_active: bool = st.session_state["current_agent_mode"] == "RAG Agent"
    if st.button(
        "RAG Agent (Tra cứu tài liệu)",
        use_container_width=True,
        type="primary" if rag_active else "secondary",
    ):
        st.session_state["current_agent_mode"] = "RAG Agent"
        st.rerun()

with col2:
    data_active: bool = st.session_state["current_agent_mode"] == "Data Agent"
    if st.button(
        "Data Agent (Phân tích dữ liệu)",
        use_container_width=True,
        type="primary" if data_active else "secondary",
    ):
        st.session_state["current_agent_mode"] = "Data Agent"
        st.rerun()

with col3:
    search_active: bool = st.session_state["current_agent_mode"] == "Search Agent"
    if st.button(
        "Search Agent (Tìm kiếm Web)",
        use_container_width=True,
        type="primary" if search_active else "secondary",
    ):
        st.session_state["current_agent_mode"] = "Search Agent"
        st.rerun()

st.divider()

# ---------------------------------------------------------------------------
# Main Area — Drag-and-drop CSV (for Data Agent)
# ---------------------------------------------------------------------------

uploaded_file: Any = None
if st.session_state["current_agent_mode"] == "Data Agent":
    uploaded_file = st.file_uploader(
        "Kéo thả file CSV vào đây để phân tích",
        type=["csv"],
        help="Upload file CSV để phân tích dữ liệu và tạo Dashboard tự động.",
    )

    if uploaded_file is not None:
        st.success(f"Đã tải: **{uploaded_file.name}**")
        try:
            preview_df: pd.DataFrame = pd.read_csv(uploaded_file)
            uploaded_file.seek(0)  # Reset file pointer
            st.caption(f"{len(preview_df)} dòng × {len(preview_df.columns)} cột")
            with st.expander("Xem dữ liệu mẫu"):
                st.dataframe(preview_df.head(5), use_container_width=True)
        except Exception:
            st.warning("Không thể hiển thị preview của file CSV.")
    st.divider()

# ---------------------------------------------------------------------------
# Render Chat History
# ---------------------------------------------------------------------------

message_item: dict[str, Any]
for message_item in st.session_state["messages"]:
    with st.chat_message(message_item["role"]):
        st.markdown(message_item["content"])

        # Show RAG sources if present
        msg_sources: list[dict[str, Any]] = message_item.get("sources", [])
        if msg_sources:
            with st.expander("Xem nguồn trích dẫn"):
                for src in msg_sources:
                    file_name: str = src.get("file", "N/A")
                    section: str = src.get("section", "N/A")
                    category: str = src.get("category", "")
                    cat_badge: str = f" ({category})" if category else ""
                    st.markdown(f"- **{file_name}**{cat_badge} | Section: *{section}*")

        # Show generated code if present
        msg_code: str = message_item.get("generated_code", "")
        if msg_code:
            with st.expander("Xem mã nguồn (Live Code)"):
                st.code(msg_code, language="python")

            # Re-render the dashboard
            msg_csv: str | None = message_item.get("csv_content")
            if msg_csv:
                try:
                    df: pd.DataFrame = pd.read_csv(io.StringIO(msg_csv))
                    exec_globals: dict[str, Any] = {
                        "st": st,
                        "pd": pd,
                        "px": px,
                        "AgGrid": AgGrid,
                        "GridOptionsBuilder": GridOptionsBuilder,
                        "GridUpdateMode": GridUpdateMode,
                        "df": df,
                    }
                    exec(msg_code, exec_globals)  # noqa: S102
                except Exception as render_err:
                    st.error(f"Lỗi khi render lại dashboard: {render_err}")

# ---------------------------------------------------------------------------
# Chat Input Handling & API Routing
# ---------------------------------------------------------------------------

placeholder_text: str = (
    "Nhập câu hỏi để tìm kiếm thông tin trên Internet..."
    if st.session_state["current_agent_mode"] == "Search Agent"
    else "Nhập câu hỏi của bạn…"
)
user_input: str | None = st.chat_input(placeholder_text)

if user_input:
    # Validate Data Agent mode requirement (CSV upload required)
    if st.session_state["current_agent_mode"] == "Data Agent" and uploaded_file is None:
        st.warning("Vui lòng kéo thả file CSV vào trước khi bắt đầu chat phân tích dữ liệu!")
    else:
        # Display user message immediately
        st.session_state["messages"].append(
            {"role": "user", "content": user_input}
        )
        with st.chat_message("user"):
            st.markdown(user_input)

        sources_to_store: list[dict[str, Any]] = []
        code_to_store: str = ""
        csv_to_store: str | None = None
        assistant_reply: str = ""

        with st.chat_message("assistant"):
            with st.spinner("Đang xử lý…"):
                if st.session_state["current_agent_mode"] == "Data Agent" and uploaded_file is not None:
                    # =============================================
                    # MODE: DATA AGENT (CSV Analysis)
                    # =============================================
                    try:
                        uploaded_file.seek(0)
                        csv_bytes: bytes = uploaded_file.read()
                        csv_string: str = csv_bytes.decode("utf-8")
                        uploaded_file.seek(0)

                        response: httpx.Response = httpx.post(
                            _ANALYZE_ENDPOINT,
                            data={
                                "query": user_input,
                                "session_id": session_id,
                            },
                            files={
                                "file": (
                                    uploaded_file.name,
                                    csv_bytes,
                                    "text/csv",
                                ),
                            },
                            timeout=_REQUEST_TIMEOUT,
                        )
                        response.raise_for_status()

                        data: dict[str, Any] = response.json()
                        explanation: str = data.get("explanation", "Không có phản hồi.")
                        generated_code: str = data.get("generated_code", "")

                        assistant_reply = explanation
                        st.markdown(explanation)

                        if generated_code:
                            code_to_store = generated_code
                            csv_to_store = csv_string

                            with st.expander("Xem mã nguồn (Live Code)"):
                                st.code(generated_code, language="python")

                            st.divider()
                            st.subheader("Dashboard")
                            try:
                                df = pd.read_csv(io.StringIO(csv_string))
                                exec_globals = {
                                    "st": st,
                                    "pd": pd,
                                    "px": px,
                                    "AgGrid": AgGrid,
                                    "GridOptionsBuilder": GridOptionsBuilder,
                                    "GridUpdateMode": GridUpdateMode,
                                    "df": df,
                                }
                                exec(generated_code, exec_globals)  # noqa: S102
                            except Exception as exec_err:
                                st.error(
                                    f"Lỗi khi thực thi code: {exec_err}\n\n"
                                    "Vui lòng thử lại với câu hỏi khác hoặc mô tả cụ thể hơn."
                                )

                    except httpx.ConnectError:
                        assistant_reply = (
                            f"Không thể kết nối tới server. Hãy đảm bảo FastAPI đang chạy tại `{_API_BASE_URL}`."
                        )
                        st.markdown(assistant_reply)
                    except httpx.TimeoutException:
                        assistant_reply = "Yêu cầu đã hết thời gian chờ. Vui lòng thử lại."
                        st.markdown(assistant_reply)
                    except httpx.HTTPStatusError as exc:
                        assistant_reply = (
                            f"Lỗi từ server (HTTP {exc.response.status_code}): {exc.response.text[:200]}"
                        )
                        st.markdown(assistant_reply)
                    except Exception as exc:
                        assistant_reply = f"Lỗi không xác định: {exc}"
                        st.markdown(assistant_reply)

                else:
                    # =============================================
                    # MODE: RAG AGENT / SEARCH AGENT
                    # =============================================
                    chat_payload: dict[str, Any] = {
                        "query": user_input,
                        "session_id": session_id,
                    }
                    if st.session_state["current_agent_mode"] == "Search Agent":
                        chat_payload["agent_mode"] = "search_agent"

                    try:
                        response = httpx.post(
                            _CHAT_ENDPOINT,
                            json=chat_payload,
                            timeout=_REQUEST_TIMEOUT,
                        )
                        response.raise_for_status()

                        data = response.json()
                        assistant_reply = data.get("response", "Không có phản hồi.")
                        sources_to_store = data.get("sources", [])

                    except httpx.ConnectError:
                        assistant_reply = (
                            f"Không thể kết nối tới server. Hãy đảm bảo FastAPI đang chạy tại `{_API_BASE_URL}`."
                        )
                    except httpx.TimeoutException:
                        assistant_reply = "Yêu cầu đã hết thời gian chờ. Vui lòng thử lại."
                    except httpx.HTTPStatusError as exc:
                        assistant_reply = (
                            f"Lỗi từ server (HTTP {exc.response.status_code}): {exc.response.text[:200]}"
                        )
                    except Exception as exc:
                        assistant_reply = f"Lỗi không xác định: {exc}"

                    st.markdown(assistant_reply)

                    if sources_to_store:
                        with st.expander("Xem nguồn trích dẫn"):
                            for src in sources_to_store:
                                file_name = src.get("file", "N/A")
                                section = src.get("section", "N/A")
                                category = src.get("category", "")
                                cat_badge = f" ({category})" if category else ""
                                st.markdown(
                                    f"- **{file_name}**{cat_badge} | Section: *{section}*"
                                )

        # Persist assistant reply
        st.session_state["messages"].append(
            {
                "role": "assistant",
                "content": assistant_reply,
                "sources": sources_to_store,
                "generated_code": code_to_store,
                "csv_content": csv_to_store,
            }
        )
