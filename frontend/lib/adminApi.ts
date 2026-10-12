import { isUnauthorized } from './authClient';
import { getLang, t } from './i18n';
import { apiFetch } from './apiFetch';

/** One account as the administration page shows it; `source: 'env'` accounts live in the server configuration and are read-only. */
export interface AdminUser {
  username: string;
  display_name: string;
  roles: string[];
  tenant_id: string;
  department_id: string;
  disabled: boolean;
  created_at: string | null;
  source: 'registered' | 'env';
  pending: boolean;
}

export interface AdminDirectory {
  users: AdminUser[];
  tenants: string[];
  departments: string[];
  roles: string[];
}

export interface UserChanges {
  tenant_id?: string;
  department_id?: string;
  roles?: string[];
  disabled?: boolean;
}

/** A failed call: `status` tells "not an administrator" (403) from the rest. */
export class AdminError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

async function callPath<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(url, init);
  if (isUnauthorized(response)) throw new AdminError(t(getLang(), 'session.expired'), 401);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new AdminError(typeof body.detail === 'string' ? body.detail : `HTTP ${response.status}`, response.status);
  return body as T;
}

const call = <T>(path: string, init?: RequestInit): Promise<T> => callPath<T>(`/api/admin${path}`, init);

export interface UsageRow {
  calls: number;
  tokens: number;
  cost: number;
}

/** What the LLM calls of the last `days` days cost (`cost` is LiteLLM's estimate in USD; `today` since midnight, server time). */
export interface UsageReport {
  days: number;
  budget_usd_per_user_day: number | null;
  /** The budget refuses a user who has spent it today (`USAGE_BUDGET_HARD`), it does not only mark them. */
  budget_hard: boolean;
  totals: UsageRow;
  users: (UsageRow & { tenant_id: string; user_id: string; today: number; over_budget: boolean })[];
  tenants: (UsageRow & { tenant_id: string })[];
  models: (UsageRow & { model: string })[];
  /** Cost per agent; `retry_cost` = what its re-runs (attempt 2 and later) cost. Calls made outside an agent (the planner) are not in here. */
  agents: (UsageRow & { agent: string; retry_cost: number })[];
  /** Cost per PEV step: planner, executor, verifier, and helper calls such as the follow-up rewriter or the quality grader. */
  nodes: (UsageRow & { node: string })[];
  per_day: (UsageRow & { day: string })[];
}

export const formatUsd = (amount: number): string => `$${amount.toFixed(amount >= 1 ? 2 : 4)}`;

export interface OrgDepartment {
  id: string;
  name: string;
  users: number;
  /** Created in the registry; false = it only exists because an account uses it. */
  registered: boolean;
}

export interface OrgTenant {
  id: string;
  name: string;
  users: number;
  registered: boolean;
  /** The pending tenant every new sign-up starts in: it cannot be created or given departments. */
  pending: boolean;
  departments: OrgDepartment[];
}

/** Ids of tenants and departments: letters, digits and `_ . : -`, 1 to 64 characters (the backend checks the same). */
export const ORG_ID = /^[A-Za-z0-9_.:-]{1,64}$/;

const post = (body: unknown): RequestInit => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

export const getOrg = () => call<OrgTenant[]>('/org');
export const createTenant = (id: string, name: string) => call<OrgTenant>('/tenants', post({ id, name }));
export const createDepartment = (tenantId: string, id: string, name: string) =>
  call<OrgTenant>(`/tenants/${encodeURIComponent(tenantId)}/departments`, post({ id, name }));

export interface CostDay {
  day: string;
  calls: number;
  tokens: number;
  cost: number;
}

export interface ActivityRow {
  at: string;
  actor: string;
  action: string;
  target: string;
  outcome: string;
}

/** What the console's front page shows, in one call (`GET /api/admin/overview`). */
export interface AdminOverviewData {
  accounts: { total: number; pending: number; locked: number; env: number };
  organization: { tenants: number; departments: number };
  /** `null` when Redis could not be asked. */
  approvals_pending: number | null;
  jobs: { queued: number; running: number; done_24h: number; failed_24h: number };
  cost: { today: number; week_total: number; week_calls: number; per_day: CostDay[] };
  content: { conversations: number; dashboards: number; documents: number; feedback_up: number; feedback_down: number };
  activity: ActivityRow[];
}

export interface ServiceStatus {
  /** `ok`, `off` (not configured), or the class name of what went wrong. */
  status: string;
  ms: number;
}

export interface HttpSnapshot {
  uptime_seconds: number;
  total: number;
  by_class: Record<string, number>;
  rate_limited: number;
  error_rate: number;
  routes: { method: string; route: string; count: number; errors: number; avg_ms: number }[];
  /** The verification loop per agent since this replica started. */
  pev: { agent: string; runs: number; verified: number; unverified: number; retries: number }[];
}

/** Service status, database revision, this instance's requests and the job queue (`GET /api/admin/health`). */
export interface AdminHealthData {
  checked_at: string;
  status: 'ok' | 'degraded' | 'down';
  services: Record<string, ServiceStatus>;
  instance: { hostname: string; uptime_seconds: number; db_revision: string | null; db_head: string; db_current: boolean };
  http: HttpSnapshot;
  queue: {
    queued: number;
    running: number;
    failed_24h: number;
    oldest_queued_seconds: number;
    recent_failures: { id: string; kind: string; user_id: string; error: string; finished_at: string | null }[];
  };
}

export const getOverview = () => call<AdminOverviewData>('/overview');
export const getHealth = () => call<AdminHealthData>('/health');
export const getUsageReport = (days: number, tenant?: string) => call<UsageReport>(`/usage?days=${days}${tenant ? `&tenant=${encodeURIComponent(tenant)}` : ''}`);

const enc = encodeURIComponent;
const del = (): RequestInit => ({ method: 'DELETE' });
const patch = (body: unknown): RequestInit => ({ method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

// ---------------------------------------------------------------- accounts: create, reset, sign out, bulk

/** What a created or reset account gets: shown ONCE, the backend keeps only hashes. */
export interface IssuedCredentials {
  user: AdminUser;
  temporary_password: string;
  recovery_key: string;
}

export interface NewAccount {
  username: string;
  display_name?: string;
  tenant_id: string;
  department_id: string;
  roles: string[];
}

export type BulkActionName = 'lock' | 'unlock' | 'move' | 'sign_out';

export interface BulkResult {
  done: string[];
  /** `reason`: `env_managed`, `self`, `not_found` or `failed`. */
  skipped: { username: string; reason: string }[];
}

export const createAccount = (account: NewAccount) => call<IssuedCredentials>('/users', post(account));
export const resetCredentials = (username: string) => call<IssuedCredentials>(`/users/${enc(username)}/reset-credentials`, post({}));
export const signOutUser = (username: string) => call<{ signed_out: boolean }>(`/users/${enc(username)}/sign-out`, post({}));
export const bulkUsers = (body: { usernames: string[]; action: BulkActionName; tenant_id?: string; department_id?: string }) => call<BulkResult>('/users/bulk', post(body));

// ---------------------------------------------------------------- tenants and departments: rename, delete

export const renameTenant = (id: string, name: string) => call<OrgTenant>(`/tenants/${enc(id)}`, patch({ name }));
/** `moveTo` = where the accounts still in it go (`tenant/department`); the backend refuses to delete something accounts use without it. */
export const deleteTenant = (id: string, moveTo?: string) => call<Record<string, never>>(`/tenants/${enc(id)}${moveTo ? `?move_to=${encodeURIComponent(moveTo)}` : ''}`, del());
export const renameDepartment = (tenantId: string, id: string, name: string) => call<OrgTenant>(`/tenants/${enc(tenantId)}/departments/${enc(id)}`, patch({ name }));
/** `moveTo` = the department of the same tenant the accounts still in it go to. */
export const deleteDepartment = (tenantId: string, id: string, moveTo?: string) =>
  call<Record<string, never>>(`/tenants/${enc(tenantId)}/departments/${enc(id)}${moveTo ? `?move_to=${encodeURIComponent(moveTo)}` : ''}`, del());

// ---------------------------------------------------------------- what a department may use

/** One policy row: `department_id` `*` is the tenant's default; `null` in a field = no restriction from there. */
export interface DepartmentPolicy {
  tenant_id: string;
  department_id: string;
  allowed_agents: string[] | null;
  can_upload_knowledge: boolean | null;
  updated_at?: string;
  updated_by?: string;
}

export interface PolicyList {
  agents: string[];
  upload_roles: string[];
  policies: DepartmentPolicy[];
}

export const TENANT_DEFAULT = '*';
export const getPolicies = () => call<PolicyList>('/policies');
export const setPolicy = (tenantId: string, departmentId: string, policy: { allowed_agents: string[] | null; can_upload_knowledge: boolean | null }) =>
  call<DepartmentPolicy>(`/policies/${enc(tenantId)}/${departmentId === TENANT_DEFAULT ? '*' : enc(departmentId)}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(policy) });

// ---------------------------------------------------------------- audit trail

export interface AuditRow {
  id: number;
  at: string;
  tenant_id: string;
  actor: string;
  action: string;
  target: string;
  outcome: string;
  detail: Record<string, unknown>;
}

/** What the audit viewer filters on; `since`/`until` are the `YYYY-MM-DD` of a date input (the day itself is included in `until`). */
export interface AuditFilter {
  actor?: string;
  action?: string;
  tenant?: string;
  outcome?: string;
  q?: string;
  since?: string;
  until?: string;
}

export interface AuditPage {
  rows: AuditRow[];
  next_before: number | null;
}

export const getAudit = (query: string) => call<AuditPage>(`/audit${query}`);

// ---------------------------------------------------------------- approvals, jobs, configuration, alerts, backup, feedback

export interface PendingApproval {
  action_id: string;
  agent: string | null;
  action_type: string | null;
  description: string | null;
  risk_level: string | null;
  requested_by: string | null;
  tenant_id: string | null;
  department_id: string | null;
  expires_in: number;
}

export interface PendingApprovals {
  available: boolean;
  two_person: boolean;
  ttl_seconds: number;
  items: PendingApproval[];
}

export interface AdminJob {
  id: string;
  kind: string;
  tenant_id: string;
  user_id: string;
  status: 'queued' | 'running' | 'done' | 'failed';
  attempts: number;
  error: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface AdminJobs {
  jobs: AdminJob[];
  counts: Record<string, number>;
  retention_days: number;
}

export interface ConfigGroup {
  group: string;
  items: { key: string; value: string | number | boolean | string[] | Record<string, unknown> | null }[];
}

export interface AlertsReport {
  configured: boolean;
  error?: string;
  alerts: { name: string; severity: string; summary: string; since: string | null }[];
}

export interface BackupReport {
  configured: boolean;
  error?: string;
  count?: number;
  total_bytes?: number;
  latest?: { name: string; size: number; at: string; age_seconds: number } | null;
}

export interface FeedbackReport {
  days: number;
  up: number;
  down: number;
  satisfaction: number | null;
  per_day: { day: string; up: number; down: number }[];
  tenants: { tenant_id: string; up: number; down: number }[];
  agents: { agent: string; up: number; down: number }[];
  reasons: { reason: string; count: number }[];
  recent_down: { at: string; tenant_id: string; user_id: string; query: string; comment: string; agent: string; answer: string; run_id: string; verified: boolean | null; retries: number; reasons: string[] }[];
  /** Answers graded 1-5 by a model in the background (a sample of real traffic, no user action needed). */
  reviews: {
    graded: number;
    average: number | null;
    low: number;
    sample_rate: number;
    agents: { agent: string; graded: number; average: number | null }[];
    recent_low: { at: string; tenant_id: string; agent: string; query: string; answer: string; score: number; reason: string; verified: boolean | null; retries: number }[];
  };
}

export const getApprovals = () => call<PendingApprovals>('/approvals');
export const getJobs = (status?: string) => call<AdminJobs>(`/jobs${status ? `?status=${enc(status)}` : ''}`);
export const cancelJob = (id: string) => call<{ cancelled: boolean }>(`/jobs/${enc(id)}/cancel`, post({}));
export const getConfig = () => call<{ groups: ConfigGroup[] }>('/config');
export const getAlerts = () => call<AlertsReport>('/alerts');
export const getBackup = () => call<BackupReport>('/backup');
export const getFeedback = (days: number, tenant?: string) => call<FeedbackReport>(`/feedback?days=${days}${tenant ? `&tenant=${enc(tenant)}` : ''}`);
export const listAdminUsers = () => call<AdminDirectory>('/users');
export const updateAdminUser = (username: string, changes: UserChanges) =>
  call<AdminUser>(`/users/${encodeURIComponent(username)}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(changes) });

/** What the edited row changes compared to the account as stored: only those fields are sent (empty = nothing to save). */
export function diffUser(user: AdminUser, draft: { tenant_id: string; department_id: string; roles: string[] }): UserChanges {
  const changes: UserChanges = {};
  const tenant = draft.tenant_id.trim();
  const department = draft.department_id.trim();
  if (tenant && tenant !== user.tenant_id) changes.tenant_id = tenant;
  if (department && department !== user.department_id) changes.department_id = department;
  const wanted = [...new Set(draft.roles)].sort();
  if (wanted.join(',') !== [...user.roles].sort().join(',')) changes.roles = wanted;
  return changes;
}

// ---------------------------------------------------------------- knowledge base (the chat's endpoints, used from the console)

export interface KnowledgeDocument {
  doc_key: string;
  filename: string;
  category: string;
  chunks: number;
  pages: number | null;
  chars: number;
  updated_at: string | null;
  has_pdf: boolean;
}

export interface KnowledgeUploadResult {
  status: 'added' | 'updated' | 'unchanged';
  filename: string;
  category: string;
  chunks: number;
}

export const listKnowledge = () => callPath<KnowledgeDocument[]>('/api/knowledge/documents');
export const deleteKnowledge = (docKey: string) =>
  callPath<{ doc_key: string; deleted_chunks: number; file_removed: boolean }>(`/api/knowledge/documents?doc_key=${encodeURIComponent(docKey)}`, { method: 'DELETE' });

/** A document goes through the same endpoint as the chat's attachment; the category is inferred from the file. */
export function uploadKnowledge(file: File): Promise<KnowledgeUploadResult> {
  const form = new FormData();
  form.append('file', file);
  return callPath<KnowledgeUploadResult>('/api/knowledge/upload', { method: 'POST', body: form });
}
