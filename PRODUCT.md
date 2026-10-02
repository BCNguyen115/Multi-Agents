# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
Primary (confirmed): **data specialists** who upload a CSV/Excel/Parquet/JSON file and need a dashboard they can trust, then keep asking questions of the same data (cross-filtering, natural-language follow-ups, SQL in the browser).

Other audiences named in the repository's technical documentation, not confirmed in the init interview: business staff asking questions of internal documents (need cited sources), approvers/admins who release sensitive operations and manage the knowledge base, and IT/DevOps who run the system.

## Product Purpose
An internal enterprise multi-agent system behind one chat window. Five specialised agents (RAG over documents, data analysis, web search, database, external integrations) answer under a Plan, Execute, Verify loop, so a person gets answers they can rely on instead of a chatbot's guesses. Success means hallucination close to zero: every number shown can be traced to the data or to a cited source, and nothing sensitive happens without a human decision.

## Positioning
The answer is checked before it is shown. Dashboards are recomputed from the uploaded file (charts, KPIs and every number in the story are re-verified), RAG answers must cite `[n]` sources and use only numbers found in them, SQL is read-only with row-level security, and sensitive queries and any write to an external system stop at a human approval step.

## Operating Context
Real internal product used at work (confirmed), in Vietnamese and English (`lib/locales/vi.ts` is the key contract). Users attach files to the chat; the planner/executor/verifier progress streams live (SSE) and is shown as a stepper; a PREVIEW of the answer streams in and is replaced by the verified `final_response`. Signed-in users' conversations are stored per tenant and user. Data stays in the browser for ad-hoc SQL (DuckDB-WASM).

## Capabilities and Constraints
- Chat with agent selection, CSV and document attachment; documents go to the knowledge base, not the chat.
- Dashboard `dashboard_spec` v2: 12-column layout, story, facts, KPIs, charts, slicers, table. The frontend only draws numbers computed by the server; no client-side re-aggregation.
- Cited sources with "view page" opening the PDF page with the passage highlighted.
- Human-in-the-loop approval card for sensitive queries and mutating integration calls.
- Knowledge-base management (`/docs`), conversation sidebar, command palette, login (JWT in an httpOnly cookie).
- All interface text lives in the locale dictionaries; no inline Vietnamese or English strings.
- Next.js 14 App Router, Tailwind CSS, ECharts, AG Grid, DuckDB-WASM.

## Brand Commitments
The FPT logo (`public/FPT.VN-df6a5b44.png`, `components/ui/FptLogo.tsx`) is a binding identity requirement (confirmed): the interface keeps it and must stay compatible with FPT's brand. No other palette, typeface or voice rule has been set.

## Evidence on Hand
Technical documentation: `docs/Enterprise_Multi_Agent_System_Technical_Documentation.docx`. Sample corpus under `dataset/`. The repository has no screenshots (`docs/screenshots` is empty) and no customer testimonials, benchmarks or usage numbers; none may be invented.

## Product Principles
1. **Trust is the product.** Anything that shows a number shows where it came from; a preview is visibly a preview until it is verified.
2. **Show the process, not the plumbing.** Planner, executor and verifier states are legible at a glance, in the user's language.
3. **Humans decide what matters.** Approval is unmissable and states exactly what will run, before anyone can click.
4. **Data work first.** The data specialist's loop (upload, trust, filter, ask again) gets the shortest path; other agents do not crowd it.
5. **Two languages, one interface.** Vietnamese and English are equals; layout survives either.

## Accessibility & Inclusion
No product-specific standard has been established yet. Open decision.
