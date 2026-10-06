export interface SourceItem {
  file: string;
  section: string;
  /** The `[n]` the answer uses to cite this source (RAG). */
  cite?: number;
  /** PDF page where the cited passage starts. */
  page?: number | null;
  category?: string;
  url?: string;
  title?: string;
  domain?: string;
  snippet?: string;
  /** A verbatim quote of the source that the backend checked against it (RAG_QUOTE_MODE). */
  quote?: string;
  content?: string;
  [key: string]: any;
}

export interface PEVStepData {
  step: 'planner' | 'executor' | 'verifier' | 'completed';
  /** `verified` / `warning` close the loop; `retry` is the Verifier asking for a correction. */
  status: 'active' | 'completed' | 'verified' | 'warning' | 'retry';
  target?: string;
  logs?: string;
  feedback?: string;
}

export interface PEVStepDetail {
  status: 'idle' | 'active' | 'completed' | 'failed' | 'retry';
  timestamp?: string;
  title: string;
  description?: string;
  data?: any;
}

export interface PEVTraceState {
  currentStep: 'planner' | 'executor' | 'verifier' | 'idle' | 'completed';
  planner: PEVStepDetail & {
    plan?: string;
    targetAgent?: string;
    reasoning?: string;
  };
  executor: PEVStepDetail & {
    agentName?: string;
    subTasks?: string[];
    logs?: string[];
    outputSummary?: string;
  };
  verifier: PEVStepDetail & {
    isVerified?: boolean;
    feedback?: string;
    retryCount?: number;
    auditPassed?: boolean;
  };
}

export interface PEVEventData {
  step?: 'planner' | 'executor' | 'verifier' | 'completed';
  status?: 'active' | 'completed' | 'verified' | string;
  target?: string;
  target_agent?: string;
  logs?: string;
  message?: string;
  feedback?: string;
  plan?: string;
  execution_result?: string;
  is_verified?: boolean;
  verifier_feedback?: string;
  retry_count?: number;
  response?: string;
  text?: string; // answer_delta: the next piece of the answer being written
  error?: string;
  pev_trace?: PEVTrace;
}

// ---------------------------------------------------------------------------
// Dashboard spec v2 (produced by the data agent; every number in it is verified against the dataset)
// ---------------------------------------------------------------------------

export type DashboardLanguage = 'en' | 'vi';

export type ChartType =
  | 'line'
  | 'area'
  | 'bar'
  | 'horizontal_bar'
  | 'donut'
  | 'scatter'
  | 'histogram'
  | 'heatmap'
  | 'treemap'
  | 'waterfall';

export type ValueFormat = 'currency' | 'percent' | 'plain';

export interface KPIDelta {
  pct: number | null;
  direction: 'up' | 'down' | 'flat';
  label: string;
  period: string;
}

export interface KPIItem {
  id: string;
  title: string;
  value: string;
  raw_value: number | null;
  type: 'count' | 'currency' | 'percent' | 'number' | 'text';
  unit?: string;
  subtitle?: string;
  icon?: string;
  delta?: KPIDelta | null;
  measure?: string | null;
  aggregation?: string | null;
}

export interface ChartPoint {
  x?: string | number | null;
  y?: string | number | null;
  name?: string | null;
  value?: number | null;
  share?: number | null;
  count?: number;
  from?: number;
  to?: number;
  kind?: 'total' | 'delta';
}

export interface ChartHighlight {
  type: 'max' | 'min' | 'anomaly';
  x: string;
  y: number;
}

export interface ChartSpecDef {
  id: string;
  type: ChartType;
  dimension?: string;
  measure?: string;
  aggregation?: string;
  [key: string]: unknown;
}

export interface ChartItem {
  id: string;
  type: ChartType;
  title: string;
  subtitle: string;
  insight: string;
  dimension?: string | null;
  measure: string;
  aggregation: string;
  grain?: string | null;
  col_span: number;
  fact_ids: string[];
  highlights: ChartHighlight[];
  data: ChartPoint[];
  x_data?: string[];
  y_data?: string[];
  format: ValueFormat;
  isMonetary: boolean;
  unit: string;
  meta?: {
    x_label?: string;
    y_label?: string;
    rho?: number | null;
    n?: number;
    median?: number | null;
    mean?: number | null;
    kind?: 'correlation' | 'crosstab';
    min?: number;
    max?: number;
    trend_line?: { slope: number | null; intercept: number | null };
  };
  spec: ChartSpecDef;
}

export interface TableColumn {
  field: string;
  headerName: string;
  type: 'number' | 'date' | 'text';
  role?: string;
  agg?: string | null;
  unit?: string | null;
}

export interface TableSpec {
  title: string;
  columns: TableColumn[];
  rows: Record<string, unknown>[];
  totalRows: number;
  truncated: boolean;
}

export interface Slicer {
  field: string;
  label: string;
  values: string[];
}

export interface StoryItem {
  id: string;
  text: string;
  fact_ids: string[];
  kind?: string;
  section?: string;
}

export interface Story {
  language: DashboardLanguage;
  headline: string;
  sections: { key: string; title: string; items: StoryItem[] }[];
  findings: StoryItem[];
  actions: { text: string; [key: string]: unknown }[];
  hypothesis_note: string;
  caveats: { code?: string; text: string }[];
  next_questions: string[];
  source: 'deterministic' | 'llm';
  grounded: boolean;
}

export interface DashboardSpec {
  version: 2;
  language: DashboardLanguage;
  mode: 'dashboard' | 'single_chart';
  title: string;
  fileName: string;
  summaryText: string;
  story: Story;
  kpis: KPIItem[];
  charts: ChartItem[];
  slicers: Slicer[];
  table: TableSpec;
  analysis: {
    rows_total: number;
    rows_used: number;
    sampled: boolean;
    format: string;
    notes: Record<string, unknown>[];
    warnings: Record<string, unknown>[];
  };
  /** False when the agent's own verification failed (the UI then says so instead of claiming verification). */
  verified?: boolean;
  /** Added by the client: the chat session the dataset belongs to (needed for server-side filtering). */
  sessionId?: string;
}

/** Response of POST /api/analyze/filter. */
export interface FilteredDashboard {
  rows_used: number;
  rows_total: number;
  charts: (ChartItem | null)[];
  kpis: KPIItem[];
  verified: boolean;
}

export interface PEVTrace {
  status?: string;
  is_verified?: boolean;
  retry_count?: number;
  error_feedback?: string[];
  planner?: {
    node?: string;
    target_agent?: string;
    plan_summary?: string;
    status?: string;
  };
  executor?: {
    node?: string;
    agent_used?: string;
    execution_summary?: string;
    status?: string;
  };
  verifier?: {
    node?: string;
    is_verified?: boolean;
    verifier_feedback?: string;
    status?: string;
  };
}

export interface HumanApprovalRequest {
  action_id: string;
  agent: string;
  action_type: 'api_mutation' | 'sensitive_db_query' | string;
  description: string;
  payload: {
    url?: string;
    method?: string;
    payload?: any;
    sql?: string;
    query?: string;
    [key: string]: any;
  };
  risk_level: 'low' | 'medium' | 'high' | 'critical';
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  agentMode?: string;
  sources?: SourceItem[];
  pevStep?: PEVStepData;
  pevEvents?: {
    plan?: { plan: string; target_agent: string };
    executing?: { target_agent: string; execution_result: string };
    verifying?: { is_verified: boolean; verifier_feedback: string; retry_count: number };
    final_response?: { response: string; target_agent: string; is_verified: boolean; pev_trace?: PEVTrace };
    error?: string;
  };
  pevTrace?: PEVTrace;
  pevTraceState?: PEVTraceState;
  approvalRequest?: HumanApprovalRequest;
  approvalDecision?: 'approved' | 'rejected';
  csvFilename?: string;
  generatedCode?: string;
  dashboardSpec?: DashboardSpec;
  metadata?: any;
  status?: 'loading' | 'complete' | 'error';
  /** The text is a live preview of the answer still being written: the Verifier has not seen it, the final answer replaces it. */
  isPreview?: boolean;
  /** The message is a live card, not text: `knowledge-docs` = the documents in the knowledge base (`/docs`). */
  kind?: 'knowledge-docs';
}

export interface CSVMetadata {
  filename: string;
  totalRows: number;
  rowCount?: number;
  totalCols: number;
  columns: { name: string; type: string; role?: string }[];
  categoricalCols: string[];
  numericCols: string[];
  sampleData: Record<string, any>[];
  summary: Record<string, { min?: number; max?: number; avg?: number; sum?: number }>;
}
