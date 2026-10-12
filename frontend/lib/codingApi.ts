import { apiFetch } from './apiFetch';
import { isUnauthorized } from './authClient';
import { getLang, t } from './i18n';

export interface CodingCheck {
  ok: boolean;
  exit_code: number | null;
  output: string;
}
export interface CodingFinding {
  severity: 'high' | 'medium' | 'low';
  rule?: string;
  state?: string;
  file: string;
  line: number | null;
  text?: string;
  summary?: string;
}
export interface CodingResult {
  summary: string;
  stopped: string;
  steps: number;
  cost_usd: number;
  files_changed: string[];
  patch: string;
  checks: Record<string, CodingCheck>;
  tests_passed: boolean;
  ruff_clean: boolean;
  ready_for_review: boolean;
  risk_findings: CodingFinding[];
  review: { reviewed: boolean; findings: CodingFinding[] };
  plan: { content: string; status: 'pending' | 'in_progress' | 'done' }[];
  protected_touched: string[];
  secrets_found: string[];
  /** The terminal: every shell command the agent ran (or was refused), in order. Empty when the shell was off. */
  commands?: { command: string; exit_code: number | null; seconds: number | null; timed_out: boolean | null; modified: boolean | null; blocked: boolean | null }[];
  shell?: boolean;
  repo?: { id: string; name: string; kind: 'github' | 'local' };
  revisions?: number;
  branch?: string;
  pr_url?: string;
}
export interface CodingReview {
  id: string;
  status: 'queued' | 'running' | 'done' | 'failed';
  requester: string;
  error: string;
  result: CodingResult | null;
  can_publish: boolean;
  /** Where approval leads: a pull request on GitHub, or a branch in the local repository (no pull request). */
  target: 'github' | 'local';
  /** The finished work is still open in the sandbox, so a reviewer can edit it and have the checks run again. */
  editable?: boolean;
}
export interface CodingFile {
  path: string;
  status: 'added' | 'modified' | 'deleted';
  before: string;
  after: string;
  binary?: boolean;
  too_large?: boolean;
  protected: boolean;
}
export interface CodingRepo {
  id: string;
  name: string;
  kind: 'github' | 'local';
  location: string;
  branch: string;
  mine: boolean;
  builtin: boolean;
}
export interface CodingRevision {
  ready_for_review: boolean;
  checks: Record<string, CodingCheck>;
  risk_findings: CodingFinding[];
  files_changed: string[];
  revisions: number;
}

/** The task id inside the chat reply that queued the task (32 hex characters). */
export function jobIdOf(text: string): string | null {
  return /\b[0-9a-f]{32}\b/.exec(text)?.[0] ?? null;
}

/** Running and queued tasks are polled; a finished one is not. */
export const isFinished = (status: CodingReview['status']): boolean => status === 'done' || status === 'failed';

/** The server answers with a sentence, or with {message, errors: {path: reason}} when an edit was refused. */
export function describeDetail(detail: unknown): string {
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object') {
    const { message, errors } = detail as { message?: string; errors?: Record<string, string> };
    const lines = Object.entries(errors ?? {}).map(([path, why]) => `${path}: ${why}`);
    return [message, ...lines].filter(Boolean).join('\n');
  }
  return '';
}

/** github.dev opens the pull request's repository in VS Code for the web; the pull request URL is the only input. */
export function githubDevUrl(prUrl: string): string | null {
  try {
    const url = new URL(prUrl);
    return url.hostname === 'github.com' ? `https://github.dev${url.pathname}` : null;
  } catch {
    return null;
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(`/api/coding${path}`, init);
  if (isUnauthorized(response)) throw new Error(t(getLang(), 'session.expired'));
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(describeDetail(body.detail) || `HTTP ${response.status}`);
  if (response.status === 204) return undefined as T;
  return body as T;
}

export const getReview = (id: string) => call<CodingReview>(`/${encodeURIComponent(id)}/review`);
export const publishTask = (id: string) => call<{ branch: string; pr_url: string; local?: boolean }>(`/${encodeURIComponent(id)}/publish`, { method: 'POST' });
export const getFiles = (id: string) => call<{ files: CodingFile[]; truncated: boolean }>(`/${encodeURIComponent(id)}/files`);
export const reviseTask = (id: string, files: Record<string, string>) =>
  call<CodingRevision>(`/${encodeURIComponent(id)}/revise`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ files }) });
export const listRepos = () => call<{ repos: CodingRepo[]; can_add_local: boolean; has_roots: boolean }>('/repos');
export const discoverFolders = () => call<{ folders: { path: string; name: string; branch: string }[]; roots: string[] }>('/repos/discover');
export const addRepo = (body: { kind: 'github' | 'local'; location: string; name: string; branch?: string }) =>
  call<CodingRepo>('/repos', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
export const removeRepo = (id: string) => call<void>(`/repos/${encodeURIComponent(id)}`, { method: 'DELETE' });

const REPO_KEY = 'coding.repo';
/** The repository chosen for the next Coding task (a per-browser convenience: the server re-checks it for every task). */
export function selectedRepoId(): string {
  try {
    return window.localStorage.getItem(REPO_KEY) ?? '';
  } catch {
    return '';
  }
}
export function selectRepo(id: string): void {
  try {
    window.localStorage.setItem(REPO_KEY, id);
  } catch {
    /* private window: the choice lasts until reload */
  }
}
