import { test, expect, type Page, type Route } from '@playwright/test';

/**
 * The administration console (`/admin/*`) with the whole API mocked: every page opens, shows its heading, raises no console or page error and
 * does not overflow; and the actions that change something ask first and send what they should.
 */

const json = (body: unknown, status = 200) => ({ status, contentType: 'application/json', body: JSON.stringify(body) });

const me = { authenticated: true, user: 'sysadmin', name: 'sysadmin', tenant_id: 'tenant_enterprise', department_id: 'dept_general', roles: ['admin'], can_approve: true, can_manage_knowledge: true, can_admin: true };
const org = [
  { id: 'tenant_enterprise', name: '', users: 3, registered: false, pending: false, departments: [{ id: 'dept_general', name: '', users: 3, registered: false }] },
  { id: 'initech', name: 'Initech', users: 0, registered: true, pending: false, departments: [{ id: 'hr', name: 'Nhân sự', users: 0, registered: true }] },
  { id: 'emptyco', name: 'Empty Co', users: 0, registered: true, pending: false, departments: [] },
  { id: 'tenant_pending', name: '', users: 1, registered: false, pending: true, departments: [{ id: 'dept_pending', name: '', users: 1, registered: false }] },
];
const users = {
  users: [
    { username: 'sysadmin', display_name: '', roles: ['admin'], tenant_id: 'tenant_enterprise', department_id: 'dept_general', disabled: false, created_at: null, source: 'env', pending: false },
    { username: 'alice', display_name: 'Alice', roles: [], tenant_id: 'tenant_pending', department_id: 'dept_pending', disabled: false, created_at: '2026-10-06T08:00:00Z', source: 'registered', pending: true },
  ],
  tenants: ['initech', 'tenant_enterprise', 'tenant_pending'],
  departments: ['dept_general', 'hr'],
  roles: ['admin', 'approver'],
};
const days = ['2026-10-04', '2026-10-06', '2026-10-07'].map((day, i) => ({ day, calls: 5 + i, tokens: 900, cost: [0.1, 0.3, 0.2][i] }));
const usage = { days: 30, budget_usd_per_user_day: 1, budget_hard: true, totals: { calls: 18, tokens: 5000, cost: 0.6 }, users: [{ tenant_id: 'acme', user_id: 'bob', calls: 18, tokens: 5000, cost: 0.6, today: 0.2, over_budget: false }], tenants: [{ tenant_id: 'acme', calls: 18, tokens: 5000, cost: 0.6 }], models: [{ model: 'm', calls: 18, tokens: 5000, cost: 0.6 }], agents: [{ agent: 'rag_agent', calls: 12, tokens: 4000, cost: 0.5, retry_cost: 0.1 }], nodes: [{ node: 'executor', calls: 12, tokens: 4000, cost: 0.5 }], per_day: days };
const mocks: Record<string, unknown> = {
  '**/api/auth/config': { login_enabled: true, registration_enabled: true, sso_enabled: false },
  '**/api/admin/overview': { accounts: { total: 3, pending: 1, locked: 0, env: 1 }, organization: { tenants: 2, departments: 3 }, approvals_pending: 2, jobs: { queued: 1, running: 0, done_24h: 4, failed_24h: 1 }, cost: { today: 0.2, week_total: 0.6, week_calls: 18, per_day: days }, content: { conversations: 4, dashboards: 1, documents: 2, feedback_up: 3, feedback_down: 1 }, activity: [{ at: '2026-10-08T07:42:00Z', actor: 'sysadmin', action: 'admin.user_update', target: 'alice', outcome: 'ok' }] },
  '**/api/admin/health': { checked_at: '2026-10-08T07:50:00Z', status: 'ok', services: { postgres: { status: 'ok', ms: 3 }, redis: { status: 'ok', ms: 1 }, reranker: { status: 'ok', ms: 20 }, sandbox: { status: 'off', ms: 0 }, langfuse: { status: 'off', ms: 0 } }, instance: { hostname: 'b1', uptime_seconds: 5000, db_revision: '0013', db_head: '0013', db_current: true }, http: { uptime_seconds: 5000, total: 10, by_class: { '2xx': 10, '4xx': 0, '5xx': 0 }, rate_limited: 0, error_rate: 0, routes: [] }, queue: { queued: 1, running: 0, failed_24h: 1, oldest_queued_seconds: 30, recent_failures: [] } },
  '**/api/admin/alerts': { configured: true, alerts: [{ name: 'HighErrorRate', severity: 'critical', summary: '5xx above 5%', since: '2026-10-08T07:00:00Z' }] },
  '**/api/admin/backup': { configured: true, count: 3, total_bytes: 3000000, latest: { name: 'db-20261006.sql.gz', size: 1048576, at: '2026-10-06T01:00:00Z', age_seconds: 200000 } },
  '**/api/admin/approvals': { available: true, two_person: true, ttl_seconds: 600, items: [{ action_id: 'act_12345678', agent: 'db_agent', action_type: 'sql', description: 'Đọc bảng lương', risk_level: 'high', requested_by: 'bob', tenant_id: 'acme', department_id: 'hr', expires_in: 420 }] },
  '**/api/admin/jobs*': { jobs: [{ id: 'j1', kind: 'kb.ingest', tenant_id: 'acme', user_id: 'bob', status: 'queued', attempts: 0, error: '', created_at: '2026-10-08T07:00:00Z', started_at: null, finished_at: null }], counts: { queued: 1 }, retention_days: 7 },
  '**/api/admin/config': { groups: [{ group: 'access', items: [{ key: 'AUTH_MODE', value: 'jwt' }, { key: 'RAG_TENANT_IDS', value: null }] }, { group: 'secrets', items: [{ key: 'OPENROUTER_API_KEY', value: true }] }] },
  '**/api/admin/feedback*': { days: 30, up: 3, down: 2, satisfaction: 0.6, per_day: [{ day: '2026-10-06', up: 2, down: 0 }, { day: '2026-10-08', up: 1, down: 2 }], tenants: [{ tenant_id: 'acme', up: 2, down: 1 }, { tenant_id: 'globex', up: 1, down: 1 }], agents: [{ agent: 'rag_agent', up: 3, down: 2 }], reasons: [{ reason: 'wrong', count: 2 }], recent_down: [{ at: '2026-10-08T07:00:00Z', tenant_id: 'acme', user_id: 'bob', query: 'Chính sách nghỉ phép?', comment: 'sai tệp', agent: 'rag_agent', answer: 'Mười hai ngày.', run_id: 'r1', verified: false, retries: 1, reasons: ['wrong'] }], reviews: { graded: 4, average: 3.5, low: 1, sample_rate: 0.05, agents: [{ agent: 'rag_agent', graded: 4, average: 3.5 }], recent_low: [{ at: '2026-10-08T08:00:00Z', tenant_id: 'acme', agent: 'rag_agent', query: 'NDA bao lâu?', answer: 'Không rõ.', score: 2, reason: 'né câu hỏi', verified: true, retries: 0 }] } },
  '**/api/admin/policies': { agents: ['rag_agent', 'data_agent', 'search_agent', 'db_agent', 'integration_agent'], upload_roles: ['admin'], policies: [{ tenant_id: 'initech', department_id: 'hr', allowed_agents: ['rag_agent'], can_upload_knowledge: false }] },
  '**/api/knowledge/documents': [{ doc_key: 'policy/nghi-phep.pdf', filename: 'nghi-phep.pdf', category: 'policy', chunks: 12, pages: 4, chars: 9000, updated_at: '2026-10-07T08:00:00Z', has_pdf: true }],
};

const PAGES: [string, string][] = [
  ['Tổng quan hệ thống', '/admin'], ['Giám sát hệ thống', '/admin/monitoring'], ['Vận hành', '/admin/operations'], ['Nhật ký kiểm toán', '/admin/audit'],
  ['Quản trị tài khoản', '/admin/accounts'], ['Tenant và phòng ban', '/admin/organization'], ['Kho tri thức', '/admin/knowledge'], ['Phê duyệt', '/admin/approvals'],
  ['Chi phí LLM', '/admin/costs'], ['Chất lượng câu trả lời', '/admin/quality'],
];

/** Mock the API for a signed-in administrator; returns the requests the console made to `/api/admin/*` (method, url and body). */
async function mockConsole(page: Page, signedInAs: unknown = me) {
  const seen: { method: string; url: string; body: string }[] = [];
  const reply = (body: unknown) => (route: Route) => route.fulfill(json(body));
  await page.route('**/api/auth/me', reply(signedInAs));
  for (const [pattern, body] of Object.entries(mocks)) await page.route(pattern, reply(body));
  await page.route('**/api/admin/org', reply(org));
  await page.route('**/api/admin/policies/**', reply({ tenant_id: 'initech', department_id: 'hr', allowed_agents: ['rag_agent'], can_upload_knowledge: true }));
  await page.route('**/api/admin/users', reply(users));
  await page.route('**/api/admin/audit*', reply({ rows: [{ id: 2, at: '2026-10-08T07:42:00Z', tenant_id: 'acme', actor: 'sysadmin', action: 'admin.user_update', target: 'alice', outcome: 'ok', detail: { after: { disabled: true } } }], next_before: null }));
  await page.route('**/api/admin/usage*', reply(usage));
  page.on('request', (request) => {
    if (/\/api\/admin\//.test(request.url())) seen.push({ method: request.method(), url: request.url(), body: request.postData() ?? '' });
  });
  return seen;
}

function collectErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(`pageerror: ${error}`));
  page.on('console', (message) => {
    if (message.type() === 'error' && !/Failed to load resource|favicon|net::ERR/.test(message.text())) errors.push(`console: ${message.text()}`);
  });
  return errors;
}

for (const [label, size] of [['desktop', { width: 1440, height: 900 }], ['phone', { width: 390, height: 844 }]] as const) {
  test.describe(`6. Console quản trị (${label})`, () => {
    test.use({ viewport: size });

    test(`6.1 Mười trang đều mở được, đúng tiêu đề, không lỗi và không tràn ngang (${label})`, async ({ page }) => {
      test.setTimeout(120 * 1000); // ten pages, each compiled on first visit by the dev server
      const errors = collectErrors(page);
      await mockConsole(page);
      for (const [heading, route] of PAGES) {
        await page.goto(route);
        await expect(page.getByRole('heading', { level: 1, name: heading })).toBeVisible({ timeout: 30 * 1000 });
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
        expect(overflow, `${route} overflows by ${overflow}px`).toBeLessThanOrEqual(0);
      }
      expect(errors).toEqual([]);
    });
  });
}

test.describe('6. Console quản trị: quyền và hành động', () => {
  test('6.2 Người không phải quản trị viên chỉ thấy thông báo, không thấy nội dung', async ({ page }) => {
    await mockConsole(page, { ...me, user: 'bob', roles: [], can_admin: false });
    await page.goto('/admin');
    await expect(page.getByRole('alert').filter({ hasText: 'Chỉ quản trị viên' })).toBeVisible();
    await expect(page.getByTestId('admin-overview')).toHaveCount(0);
  });

  test('6.3 Khoá tài khoản phải qua hộp xác nhận; huỷ thì không gửi gì', async ({ page }) => {
    const seen = await mockConsole(page);
    await page.goto('/admin/accounts');
    await page.getByRole('button', { name: 'Khoá', exact: true }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    await dialog.getByRole('button', { name: 'Huỷ' }).click();
    await expect(dialog).toHaveCount(0);
    expect(seen.filter((r) => r.method === 'PATCH')).toEqual([]);
  });

  test('6.4 Tạo tài khoản: mật khẩu tạm và khoá khôi phục hiện đúng một lần trong hộp thoại', async ({ page }) => {
    const seen = await mockConsole(page);
    await page.route('**/api/admin/users', (route) =>
      route.request().method() === 'POST'
        ? route.fulfill(json({ user: { ...users.users[1], username: 'dana', pending: false, tenant_id: 'initech', department_id: 'hr' }, temporary_password: 'Tmp-Pass-12345', recovery_key: 'aaaa-bbbb-cccc-dddd-eeee-ffff' }, 201))
        : route.fulfill(json(users)),
    );
    await page.goto('/admin/accounts');
    await page.getByRole('button', { name: 'Tạo tài khoản' }).first().click();
    const dialog = page.getByRole('dialog');
    await dialog.getByLabel(/^Tên đăng nhập/).fill('dana');
    await dialog.getByLabel('Tenant', { exact: true }).selectOption('initech');
    await dialog.getByLabel('Phòng ban', { exact: true }).selectOption('hr');
    await dialog.getByRole('button', { name: 'Tạo tài khoản' }).click();
    await expect(page.getByText('Tmp-Pass-12345')).toBeVisible();
    await expect(page.getByText('aaaa-bbbb-cccc-dddd-eeee-ffff')).toBeVisible();
    const created = seen.find((r) => r.method === 'POST' && r.url.endsWith('/api/admin/users'));
    expect(JSON.parse(created?.body ?? '{}')).toMatchObject({ username: 'dana', tenant_id: 'initech', department_id: 'hr', roles: [] });
    await page.getByRole('button', { name: 'Tôi đã lưu lại' }).click();
    await expect(page.getByText('Tmp-Pass-12345')).toHaveCount(0);
  });

  test('6.5 Tổ chức: đổi tên gửi PATCH, xoá phải xác nhận', async ({ page }) => {
    const seen = await mockConsole(page);
    await page.route('**/api/admin/tenants/**', (route) => route.fulfill(route.request().method() === 'DELETE' ? { status: 204 } : json(org[1])));
    await page.goto('/admin/organization');
    await expect(page.getByRole('button', { name: 'Xoá: emptyco', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Xoá: initech', exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Đổi tên: initech', exact: true }).click();
    await page.getByRole('dialog').getByLabel('Tên hiển thị (tuỳ chọn)').fill('Initech JSC');
    await page.getByRole('dialog').getByRole('button', { name: 'Lưu' }).click();
    await expect.poll(() => seen.some((r) => r.method === 'PATCH' && r.url.endsWith('/tenants/initech'))).toBe(true);
    const renamed = seen.find((r) => r.method === 'PATCH' && r.url.endsWith('/tenants/initech'));
    expect(JSON.parse(renamed?.body ?? '{}')).toEqual({ name: 'Initech JSC' });
    await page.getByRole('button', { name: 'Xoá: emptyco', exact: true }).click();
    await page.getByRole('dialog').getByRole('button', { name: 'Xoá' }).click();
    await expect.poll(() => seen.some((r) => r.method === 'DELETE' && r.url.endsWith('/tenants/emptyco'))).toBe(true);
  });

  test('6.6 Nhật ký: bộ lọc đi vào truy vấn và nút xuất CSV mang đúng bộ lọc', async ({ page }) => {
    const seen = await mockConsole(page);
    await page.goto('/admin/audit');
    await page.getByLabel('Người thực hiện', { exact: true }).fill('sysadmin');
    await page.getByRole('button', { name: 'Lọc', exact: true }).click();
    await expect.poll(() => seen.some((r) => r.url.includes('/api/admin/audit') && r.url.includes('actor=sysadmin'))).toBe(true);
    await expect(page.getByRole('link', { name: 'Xuất CSV' })).toHaveAttribute('href', /\/api\/admin\/audit\/export\?.*actor=sysadmin/);
  });

  test('6.7 Chi phí: chọn tenant gọi lại báo cáo với tenant đó và ghi chú hạn mức cứng hiện ra', async ({ page }) => {
    const seen = await mockConsole(page);
    await page.goto('/admin/costs');
    await expect(page.getByText(/bị chặn đến nửa đêm/)).toBeVisible();
    await page.getByRole('combobox', { name: /^Tenant/ }).selectOption('initech');
    await expect.poll(() => seen.some((r) => r.url.includes('/api/admin/usage') && r.url.includes('tenant=initech'))).toBe(true);
  });

  test('6.8 Xoá phòng ban hay tenant còn tài khoản: bắt buộc chọn nơi chuyển họ đến và gửi move_to', async ({ page }) => {
    const seen = await mockConsole(page);
    await page.route('**/api/admin/tenants/**', (route) => route.fulfill(route.request().method() === 'DELETE' ? { status: 204 } : json(org[1])));
    await page.goto('/admin/organization');
    // the only department of its tenant: nowhere to move the 3 accounts, so the delete stays disabled and says why
    await page.getByRole('button', { name: 'Xoá: tenant_enterprise/dept_general', exact: true }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('alert')).toBeVisible();
    await expect(dialog.getByRole('button', { name: 'Xoá', exact: true })).toBeDisabled();
    await dialog.getByRole('button', { name: 'Huỷ' }).click();
    // the tenant can go to another tenant's department
    await page.getByRole('button', { name: 'Xoá: tenant_enterprise', exact: true }).click();
    await expect(dialog.getByRole('button', { name: 'Xoá', exact: true })).toBeDisabled();
    await dialog.getByRole('combobox').selectOption('initech/hr');
    await dialog.getByRole('button', { name: 'Xoá', exact: true }).click();
    await expect.poll(() => seen.some((r) => r.method === 'DELETE' && /\/tenants\/tenant_enterprise\?move_to=initech%2Fhr$/.test(r.url))).toBe(true);
  });

  test('6.9 Quyền phòng ban: bảng cho thấy quyền hiệu lực và lưu gửi đúng agent và quyền tải tài liệu', async ({ page }) => {
    const seen = await mockConsole(page);
    await page.goto('/admin/organization');
    const policies = page.getByTestId('admin-policies');
    await expect(policies.getByRole('row', { name: /Initech \/ Nhân sự/ })).toBeVisible();
    await expect(policies.getByRole('row', { name: /Initech \/ Nhân sự/ }).getByText('Không được', { exact: true })).toBeVisible(); // its own policy denies the upload
    await page.getByRole('button', { name: 'Sửa quyền: Initech / Nhân sự' }).click();
    const dialog = page.getByRole('dialog');
    await dialog.getByLabel('Được phép', { exact: true }).check();
    await dialog.getByRole('button', { name: 'Lưu' }).click();
    await expect.poll(() => seen.some((r) => r.method === 'PUT' && r.url.endsWith('/policies/initech/hr'))).toBe(true);
    const saved = seen.find((r) => r.method === 'PUT' && r.url.endsWith('/policies/initech/hr'));
    expect(JSON.parse(saved?.body ?? '{}')).toEqual({ allowed_agents: ['rag_agent'], can_upload_knowledge: true });
  });

  test('6.10 Phòng ban vừa tạo hiện ngay trong ô chọn của trang Tài khoản, không cần tải lại trang', async ({ page }) => {
    await mockConsole(page);
    await page.goto('/admin/accounts');
    await page.getByRole('button', { name: 'Tạo tài khoản' }).first().click();
    const tenant = page.getByRole('dialog').getByLabel('Tenant', { exact: true });
    await expect(tenant.locator('option', { hasText: 'Newco' })).toHaveCount(0);
    // the organization changes elsewhere (another page or tab) and announces it
    await page.route('**/api/admin/org', (route) => route.fulfill(json([...org, { id: 'newco', name: 'Newco', users: 0, registered: true, pending: false, departments: [{ id: 'hq', name: 'HQ', users: 0, registered: true }] }])));
    await page.evaluate(() => window.dispatchEvent(new Event('admin:org-changed')));
    await expect(tenant.locator('option', { hasText: 'Newco' })).toHaveCount(1);
  });
});
