"""Generate the 4 documentation diagrams into ./temp_diagrams/ (matplotlib only, no graphviz binary needed)."""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

OUT = Path("temp_diagrams")
OUT.mkdir(exist_ok=True)
NAVY, SLATE, TEAL, GREY = "#1B365D", "#336699", "#008080", "#F4F6F9"


def canvas(w=13, h=8):
    fig, ax = plt.subplots(figsize=(w, h))
    ax.set_xlim(0, w)
    ax.set_ylim(0, h)
    ax.axis("off")
    return fig, ax


def box(ax, x, y, w, h, text, fc=SLATE, tc="white", fs=10):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.12", fc=fc, ec=fc, lw=1.5))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", color=tc, fontsize=fs, fontweight="bold")


def arrow(ax, p, q, label="", color="#444"):
    ax.annotate("", xy=q, xytext=p, arrowprops=dict(arrowstyle="->", color=color, lw=1.6))
    if label:
        ax.text((p[0] + q[0]) / 2, (p[1] + q[1]) / 2 + 0.12, label, ha="center", fontsize=8, color=color, style="italic")


def layer(ax, x, y, w, h, title):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.1", fc=GREY, ec="#B8C2D0", lw=1))
    ax.text(x + 0.15, y + h - 0.25, title, fontsize=9, color=NAVY, fontweight="bold")


def save(fig, name):
    fig.savefig(OUT / name, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def system_architecture():
    fig, ax = canvas(13, 9)
    layer(ax, 0.2, 7.6, 12.6, 1.25, "CLIENT")
    box(ax, 0.6, 7.75, 5.4, 0.7, "Next.js UI (Chat, PEV Stepper, Dashboard, DuckDB-WASM)", NAVY, fs=9)
    box(ax, 6.6, 7.75, 5.8, 0.7, "Route handlers /app/api/** (JWT cookie -> Bearer)", NAVY, fs=9)
    layer(ax, 0.2, 5.9, 12.6, 1.5, "GATEWAY (FastAPI)")
    box(ax, 0.6, 6.05, 2.8, 0.75, "Auth + Rate limit\n(JWT, Redis)", SLATE, fs=9)
    box(ax, 3.7, 6.05, 3.0, 0.75, "Guardrails: injection scan\n+ canary leak check", SLATE, fs=9)
    box(ax, 7.0, 6.05, 2.7, 0.75, "REST + SSE\n/api/chat, /analyze", SLATE, fs=9)
    box(ax, 10.0, 6.05, 2.5, 0.75, "Conversations /\nKnowledge routers", SLATE, fs=9)
    layer(ax, 0.2, 3.5, 12.6, 2.2, "ORCHESTRATOR (LangGraph PEV: Planner -> Executor -> Verifier, retry <= 2)")
    box(ax, 0.6, 3.7, 1.9, 0.8, "RAG\nagent", TEAL, fs=9)
    box(ax, 2.7, 3.7, 1.9, 0.8, "Data\nanalyst", TEAL, fs=9)
    box(ax, 4.8, 3.7, 1.9, 0.8, "Search\nagent", TEAL, fs=9)
    box(ax, 6.9, 3.7, 1.9, 0.8, "DB agent\n(SELECT only)", TEAL, fs=9)
    box(ax, 9.0, 3.7, 1.9, 0.8, "Integration\nagent (MCP)", TEAL, fs=9)
    box(ax, 11.0, 3.7, 1.6, 0.8, "HITL\napproval", "#B26B00", fs=9)
    layer(ax, 0.2, 0.2, 12.6, 3.0, "DATA & INFRASTRUCTURE")
    box(ax, 0.6, 1.9, 2.8, 0.8, "PostgreSQL + pgvector\n(rag_chunks, conversations)", NAVY, fs=8)
    box(ax, 3.7, 1.9, 2.2, 0.8, "Redis\n(history, HITL, limits)", NAVY, fs=8)
    box(ax, 6.2, 1.9, 2.3, 0.8, "TEI Reranker\n(cross-encoder)", NAVY, fs=8)
    box(ax, 8.8, 1.9, 2.0, 0.8, "Python Sandbox\n(HMAC, isolated)", NAVY, fs=8)
    box(ax, 11.0, 1.9, 1.6, 0.8, "Langfuse\ntracing", NAVY, fs=8)
    box(ax, 0.6, 0.4, 3.8, 0.8, "OpenRouter / LiteLLM (fast + heavy LLM)", "#6B4C9A", fs=8)
    box(ax, 4.7, 0.4, 3.0, 0.8, "Tavily / Crawl4AI (web)", "#6B4C9A", fs=8)
    box(ax, 8.0, 0.4, 4.6, 0.8, "mem0 long-term memory (pgvector)", "#6B4C9A", fs=8)
    for x in (3, 9):
        arrow(ax, (x, 7.75), (x, 6.85))
        arrow(ax, (x, 6.05), (x, 5.75))
    arrow(ax, (6.5, 3.7), (6.5, 2.75))
    save(fig, "system_architecture.png")


def erd():
    fig, ax = canvas(13, 7)

    def table(x, y, title, rows, w):
        h = 0.38 * (len(rows) + 1)
        ax.add_patch(FancyBboxPatch((x, y - h), w, h, boxstyle="square,pad=0", fc="white", ec=NAVY, lw=1.5))
        ax.add_patch(FancyBboxPatch((x, y - 0.38), w, 0.38, boxstyle="square,pad=0", fc=NAVY, ec=NAVY))
        ax.text(x + w / 2, y - 0.19, title, color="white", ha="center", va="center", fontsize=10, fontweight="bold")
        for i, r in enumerate(rows):
            ax.text(x + 0.12, y - 0.38 * (i + 1) - 0.19, r, va="center", fontsize=8, family="monospace")

    table(0.4, 6.7, "rag_chunks", ["PK id (generated)", "content TEXT", "raw_content TEXT", "embedding VECTOR(dim)", "tsv tsvector (generated)",
          "doc_key TEXT (category/filename)", "doc_hash TEXT", "chunk_index INT", "page INT", "filename, category, section_title",
          "detected_pattern TEXT", "tenant_id TEXT = 'public'", "created_at TIMESTAMPTZ"], 4.6)
    table(6.4, 6.7, "conversations", ["PK tenant_id TEXT", "PK user_id TEXT", "PK id TEXT", "title TEXT", "pinned BOOLEAN",
          "messages JSONB", "created_at TIMESTAMPTZ", "updated_at TIMESTAMPTZ (optimistic lock)"], 5.2)
    table(6.4, 3.3, "mem0_memories (mem0, pgvector)", ["id, vector, payload JSONB", "user_id = '<tenant>:<user>'"], 5.2)
    table(0.4, 1.4, "alembic_version", ["version_num TEXT (0001, 0002)"], 4.6)
    ax.text(6.4, 0.8, "Logical relations (no FK): conversations.(tenant_id,user_id) = Principal; rag_chunks.tenant_id scopes RLS;\n"
            "rag_chunks.doc_key groups chunks of one document. Indexes: HNSW(embedding), GIN(tsv), doc_key, category,\n"
            "conversations(tenant_id,user_id,updated_at DESC).", fontsize=8, color="#444")
    save(fig, "erd_diagram.png")


def data_flow():
    fig, ax = canvas(13, 8)
    lanes = ["User / UI", "Gateway", "Planner", "Executor+Agent", "Verifier", "Redis / PG"]
    xs = [1.1, 3.3, 5.5, 7.7, 9.9, 12.0]
    for n, x in zip(lanes, xs):
        box(ax, x - 0.95, 7.2, 1.9, 0.5, n, NAVY, fs=8)
        ax.plot([x, x], [0.8, 7.2], ls="--", color="#B8C2D0", lw=1)
    steps = [(0, 1, "1 POST /api/chat/stream"), (1, 1, "2 auth, rate limit, injection scan"), (1, 2, "3 build state"),
             (2, 2, "4 route: mode / CSV / DAG / LLM"), (2, 3, "5 plan"), (3, 5, "6 history, memory, RAG/SQL"),
             (3, 4, "7 result"), (4, 4, "8 audit / judge (retry <= 2)"), (4, 1, "9 final_response"), (1, 0, "10 SSE events")]
    y = 6.6
    for a, b, t in steps:
        if a == b:
            ax.text(xs[a] + 0.1, y, t, fontsize=7.5, color=TEAL, va="center", fontweight="bold")
        else:
            arrow(ax, (xs[a], y), (xs[b], y), t, SLATE)
        y -= 0.58
    ax.text(6.5, 0.4, "HITL: sensitive SQL / mutating integration -> human_approval_required -> POST /api/chat/approve -> resume",
            ha="center", fontsize=8, color="#B26B00", fontweight="bold")
    save(fig, "data_flow.png")


def components():
    fig, ax = canvas(13, 8)
    mods = {
        "gateway": (0.5, 6.4, "src/gateway\nmain, conversations,\nknowledge, schemas"),
        "orch": (5.0, 6.4, "src/orchestrator\ncore, approvals,\nstreaming, verifier"),
        "reg": (9.5, 6.4, "src/registry\nAgentRegistry"),
        "rag": (0.5, 3.9, "agents/rag_agent\nplanner, knowledge"),
        "data": (3.6, 3.9, "agents/data_agent\ningest>profiler>charts\n>story>verifier"),
        "db": (6.7, 3.9, "agents/db_agent\nvalidator, rls"),
        "oth": (9.8, 3.9, "search_agent\nintegration_agent"),
        "ing": (0.5, 1.3, "src/ingestion\nloader, chunker,\nembedder, ocr"),
        "shared": (4.2, 1.3, "src/shared\nauth, security, llm_client,\nredis, postgres, rerank"),
        "fe": (9.0, 1.3, "frontend/\nChatInterface, PEVStepper,\ndashboard, i18n"),
    }
    for k, (x, y, t) in mods.items():
        box(ax, x, y, 3.0, 1.4, t, TEAL if k in ("rag", "data", "db", "oth") else SLATE, fs=8)
    arrow(ax, (3.5, 7.1), (5.0, 7.1))
    arrow(ax, (8.0, 7.1), (9.5, 7.1))
    for k in ("rag", "data", "db", "oth"):
        x, y, _ = mods[k]
        arrow(ax, (6.5, 6.4), (x + 1.5, y + 1.4), color="#777")
    for k in ("rag", "data", "db"):
        x, y, _ = mods[k]
        arrow(ax, (x + 1.5, y), (5.7, 2.7), color="#999")
    arrow(ax, (3.5, 2.0), (4.2, 2.0), color="#999")
    arrow(ax, (9.0, 2.0), (7.2, 2.0), "HTTP/SSE", "#999")
    save(fig, "component_diagram.png")


if __name__ == "__main__":
    for f in (system_architecture, erd, data_flow, components):
        f()
    print(sorted(p.name for p in OUT.iterdir()))
