---
name: Multi-Agent Enterprise System
description: Dark-first enterprise workspace where every number is shown with its proof; flat surfaces, soft shapes, four state colors.
colors:
  background: "#09090b"
  background-secondary: "#18181b"
  surface: "#18181b"
  surface-raised: "#27272a"
  surface-overlay: "#3f3f46"
  foreground: "#f4f4f5"
  foreground-secondary: "#a1a1aa"
  foreground-muted: "#71717a"
  border: "#27272a"
  border-strong: "#3f3f46"
  primary: "#3b82f6"
  primary-hover: "#2563eb"
  focus: "#3b82f6"
  planner: "#f59e0b"
  executor: "#6366f1"
  verifier: "#10b981"
  error: "#f43f5e"
  brand-fpt-blue: "#005697"
  brand-fpt-orange: "#f37021"
  light-background: "#f8fafc"
  light-surface: "#ffffff"
  light-surface-raised: "#f1f5f9"
  light-surface-overlay: "#e2e8f0"
  light-foreground: "#0f172a"
  light-foreground-secondary: "#334155"
  light-foreground-muted: "#3d4a5c"
  light-border: "#e2e8f0"
  light-primary: "#1e40af"
  light-planner: "#92400e"
  light-executor: "#4338ca"
  light-verifier: "#065f46"
  light-error: "#9f1239"
typography:
  body:
    fontFamily: "Inter, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.6
  label:
    fontFamily: "Inter, system-ui, sans-serif"
    fontSize: "12px"
    fontWeight: 600
    lineHeight: 1.5
  micro:
    fontFamily: "Inter, system-ui, sans-serif"
    fontSize: "10px"
    fontWeight: 500
    lineHeight: "14px"
  data:
    fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', ui-monospace, monospace"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.5
    fontFeature: "tabular-nums"
rounded:
  sm: "6px"
  md: "8px"
  lg: "12px"
  xl: "16px"
  2xl: "20px"
  3xl: "24px"
  full: "9999px"
spacing:
  "1": "4px"
  "2": "8px"
  "3": "12px"
  "4": "16px"
  "5": "20px"
  "6": "24px"
  "8": "32px"
  "10": "40px"
  "12": "48px"
  "16": "64px"
components:
  button-toolbar:
    backgroundColor: "{colors.surface-raised}"
    textColor: "{colors.foreground}"
    typography: "{typography.label}"
    rounded: "{rounded.lg}"
    padding: "6px 12px"
  button-toolbar-hover:
    backgroundColor: "{colors.surface-overlay}"
  chat-input-collapsed:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.full}"
    padding: "8px 16px"
    height: "56px"
  chat-input-expanded:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.2xl}"
    padding: "16px"
  card-enterprise:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.lg}"
  card-kpi:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.lg}"
    padding: "0 0 0 16px"
    height: "112px"
---

# Design System: Multi-Agent Enterprise System

## Overview

**Creative North Star: "The Clear Ledger"**

A ledger is trusted because every figure sits where it can be read and checked. The interface behaves the same way: flat surfaces separated by thin borders, numbers set in tabular figures, and the verification state of every answer visible next to the answer. The product's promise is that nothing is shown unchecked, so the design spends its contrast on the facts (numbers, sources, approval decisions) and keeps everything around them quiet.

Dark is the default (zinc 950 base, never pure black); a light theme mirrors every token and is tuned for AAA text contrast. Shapes are soft (8 to 20px radii, a fully round chat field) so a dense data tool still feels approachable. Color is functional: one interactive blue, and four state colors that mean Planner, Executor, Verifier and Error and nothing else. The FPT identity is carried by the logo, which is a binding commitment.

**Key Characteristics:**
- Flat at rest; depth comes from borders and four surface tones, not from shadow.
- Soft, friendly shapes on a dense, numeric workspace.
- Four state colors with fixed meanings; everything else is neutral.
- Numbers use tabular figures; charts only draw numbers the server computed.
- Dark-first, light theme at parity, reduced motion respected.

## Colors

A zinc-neutral palette with one interactive blue and four semantic state colors. The FPT blue and orange exist as brand tokens and are not used as interface accents.

### Primary
- **Interface Blue** (#3b82f6 dark / #1e40af light): primary actions, focus ring, selected state, file chips, KPI accent bar. Hover is #2563eb (dark) / #1e3a8a (light). The light value is a 800-level blue so white text on it passes AAA.

### Secondary (state colors)
- **Planner Amber** (#f59e0b dark / #92400e light): the Planner step and its pulse.
- **Executor Indigo** (#6366f1 dark / #4338ca light): the Executor step.
- **Verifier Emerald** (#10b981 dark / #065f46 light): the Verifier step and "verified".
- **Alert Rose** (#f43f5e dark / #9f1239 light): errors, destructive hover, critical risk.

### Tertiary (brand)
- **FPT Blue** (#005697) and **FPT Orange** (#f37021): brand tokens (`--brand-primary`, `--brand-accent`). They accompany the FPT logo; the interface's own blue is Interface Blue.

### Neutral
- **Ink Base** (#09090b): page background in dark. Light: **Paper Slate** (#f8fafc).
- **Panel Zinc** (#18181b): cards, chat field, sidebar surface. Light: **White** (#ffffff).
- **Raised Zinc** (#27272a): toolbar buttons, header cells; also the default border. Light: #f1f5f9.
- **Overlay Zinc** (#3f3f46): hover fills, strong borders, scrollbar thumb. Light: #e2e8f0.
- **Text** (#f4f4f5), **Secondary Text** (#a1a1aa), **Muted Text** (#71717a). Light: #0f172a, #334155, #3d4a5c (muted keeps at least 7:1 on every light surface).

### Named Rules
**The Four Meanings Rule.** Amber, indigo, emerald and rose mean Planner, Executor, Verifier and Error. They never decorate and never mark an unrelated category.
**The Token Rule.** Interface colors come from the CSS variables through the Tailwind token names (`bg-surface`, `text-foreground-muted`, `border-border`). A raw palette class is a drift, not a style.
**The No Pure Black Rule.** The darkest surface is #09090b.

## Typography

**Display Font:** none; the system has no display face.
**Body Font:** Inter (with system-ui, Segoe UI, Roboto), weights 300 to 900 loaded, OpenType features cv02 cv03 cv04 cv11.
**Label/Mono Font:** JetBrains Mono (with Fira Code, Cascadia Code) for file sizes, SQL and identifiers.

**Character:** Inter at small sizes does the whole job: neutral, legible in Vietnamese diacritics and in English, dense without being cramped.

### Hierarchy
- **Body** (400, 1rem, 1.6): chat answers and prose.
- **Label** (600, 12px): toolbar buttons, chips, table and chart headers.
- **Micro** (500, 10px / 14px): badges and metadata.
- **Data** (mono 400, 12px, tabular figures): file sizes, counts, KPI values (`tabular-nums` is applied to KPI values).

### Named Rules
**The Tabular Rule.** Any number a person compares (KPI, table column, file size) uses tabular figures.
**The Both Languages Rule.** Vietnamese strings run longer than English; type and containers are sized so either fits without truncating meaning.

## Layout

An app shell: sidebar of conversations, a header, and a centered chat column capped at 64rem (`max-w-5xl`) with 16px side gutters. Dashboards use a 12-column grid (`repeat(12, minmax(0, 1fr))`) with fixed minimum heights: KPI 112px, chart 380px, table 420px, dashboard 500px, card 360px. Spacing follows an 8pt rhythm (4, 8, 12, 16, 20, 24, 32, 40, 48, 64) with a few extensions (18, 52, 60, 72, 88). Horizontal overflow is clipped at the page level. A print stylesheet turns a dashboard into an A4 landscape export with the chrome removed and cards kept whole across page breaks.

## Elevation & Depth

Flat at rest. Surfaces are told apart by four tonal steps (background, surface, raised, overlay) and a 1px border; shadow is a response, not a resting state.

### Shadow Vocabulary
- **Hairline** (`0 1px 2px rgba(0,0,0,0.3)` dark / 0.05 light): toolbar buttons.
- **Lift** (`0 4px 12px rgba(0,0,0,0.4)` dark / 0.08 light): card hover and the chat field.
- **Float** (`0 8px 24px rgba(0,0,0,0.5)` dark / 0.12 light): menus and overlays.
- **State glow** (`0 0 20px` at 15% of blue, amber or emerald): only for the step currently running, with a 2s pulse (`0 0 0 6px` fading out).

Two translucent exceptions: the header (blur 12px, saturate 180%, 80% background) and the chart tooltip (blur 12px on rgba(24,24,27,0.95)).

### Named Rules
**The Flat-By-Default Rule.** No shadow at rest. Hover, focus and "running" are the only reasons for one.
**The Running Glow Rule.** A glow means that step is active right now; a finished step is still.

## Shapes

Soft but not toy-like. Radius scale 6, 8, 12, 16, 20, 24 px plus full. Buttons and cards sit at 12px, the expanded chat field at 20px, the empty chat field and avatars fully round. Borders are 1px; the KPI card has a 3px left accent bar with 2px rounding. Scrollbars are 6px with round thumbs.

## Components

Soft and friendly: generous radii and clear hover states on a dense workspace.

### Buttons
- **Shape:** 12px radius (`rounded-lg`), 6px 12px padding.
- **Toolbar (`btn-dash`):** Raised Zinc fill, text color, 1px border, hairline shadow, 12px / 600 label, icon with 6px gap.
- **Hover / Focus:** fill steps to Overlay Zinc; focus is a 2px ring at 40% Interface Blue (`focus-visible` only). Transitions 150ms ease-out.

### Chips
- **Style:** file chip uses Interface Blue at 8% fill and 15% border, 8px radius, 12px / 500 text, file size in mono tabular figures.
- **State:** removable with an X that turns Alert Rose on hover.

### Cards / Containers
- **Corner Style:** 12px.
- **Background:** Panel Zinc.
- **Shadow Strategy:** none at rest; Lift on hover with border moving from border to border-strong.
- **Border:** 1px.
- **Internal Padding:** 16px step; the KPI card reserves 16px on its left for the accent bar.

### Inputs / Fields
- **Style (chat):** Panel Zinc, 1px border, Lift shadow. Empty it is a full-round single line (56px minimum); once there is text or an attachment it grows to a 20px-radius field with 16px padding, textarea up to 200px.
- **Focus:** border becomes Interface Blue with a 2px ring at 20%.
- **Error / Disabled:** errors use Alert Rose; no other treatment is established.

### Navigation
Sidebar lists conversations (pin, sync); header uses the frosted bar. A skip link and a command palette exist. Mobile treatment is not recorded here.

### Approval card (signature)
Appears when a sensitive query or write needs a human decision. Carries a risk badge (critical: red, high: amber, otherwise blue; each as 15% fill, 30% border, lighter text), a copyable payload, Approve and Reject (reject asks for a reason first), and the result after a decision. The user must see exactly what will run before the buttons.

### PEV stepper (signature)
Three nodes in fixed order: Planner (amber), Executor (indigo), Verifier (emerald), each idle, active (state glow) or completed, expandable to the plan, execution summary and verifier feedback, with the agent's pipeline steps. Node descriptions come from the dictionaries, not from backend text.

## Do's and Don'ts

### Do:
- **Do** read every color from the tokens (`bg-surface`, `text-foreground-secondary`, `border-border`, `accent-*`) so the dark and light themes stay in sync.
- **Do** keep dark and light at parity: any new token needs both values, and light text on accent fills must be at least 7:1.
- **Do** use tabular figures for numbers people compare.
- **Do** make a preview look like a preview until the verified `final_response` replaces it.
- **Do** keep all interface text in the locale dictionaries (vi and en) and size containers for the longer Vietnamese string.
- **Do** honor `prefers-reduced-motion`: animations collapse to near-zero and the glow stops.
- **Do** keep the FPT logo on the interface.

### Don't:
- **Don't** use pure black or pure white as a page base in the dark theme (base is #09090b).
- **Don't** give a resting surface a shadow; use border and tone.
- **Don't** reuse amber, indigo, emerald or rose for anything except their state meaning.
- **Don't** introduce raw Tailwind palette colors where a token exists; the interface currently has none (checked 2026-10-02).
- **Don't** aggregate or compute chart numbers in the browser; draw what the server sent.
- **Don't** write Vietnamese or English text inside components.

## Variants

### Google Gemini Workspace (Studied DNA)
- **Source:** Image study (dark & light modes captured 2026-10-02)
- **Portable Spec:** [design.gemini.md](file:///c:/CaoNguyen_Folder/Python%20Project/Agent/multi_agent_mvp/design.gemini.md)
- **Genre:** Atmospheric
- **Macrostructure:** Marquee Hero (conversational zero-state application shell)
- **Navigation:** N3 Side-rail (collapsible icon dock ↔ drawer)
- **Footer:** Ft2 Inline single-line (profile/settings cluster)
- **Geometry:** Pill-first architecture (`border-radius: 9999px` on inputs, active indicators, segmented tabs)
- **Palette:** Dark slate-indigo base (`oklch(13% 0.015 260)`) with subtle radial illumination bloom; clean white parity in light mode (`oklch(99% 0 0)`).

