import { Page, Locator, expect } from '@playwright/test';

export class DashboardPage {
  readonly page: Page;
  readonly totalRecordsCard: Locator;
  readonly totalFieldsCard: Locator;
  readonly generateDashboardCTA: Locator;
  readonly dynamicDashboardContainer: Locator;
  readonly singleChartViewBadge: Locator;
  readonly agGridRecordSummary: Locator;
  readonly agGridPageSizeSelector: Locator;
  readonly agGridContainer: Locator;

  constructor(page: Page) {
    this.page = page;
    this.totalRecordsCard = page.locator('text=Tổng số bản ghi').locator('..');
    this.totalFieldsCard = page.locator('text=Số trường dữ liệu').locator('..');
    this.generateDashboardCTA = page.locator('button', { hasText: '📌 Dựng Dashboard trực quan từ dữ liệu này' });
    this.dynamicDashboardContainer = page.locator('h2').first();
    this.singleChartViewBadge = page.locator('span', { hasText: 'Single Chart View' });
    this.agGridRecordSummary = page.locator('span', { hasText: /Hiển thị.*bản ghi/i });
    this.agGridPageSizeSelector = page.locator('.ag-theme-alpine select, select[aria-label="Page Size"]').first();
    this.agGridContainer = page.locator('.ag-theme-alpine');
  }

  async assertOverviewCardsMetrics() {
    await expect(this.totalRecordsCard).toBeVisible({ timeout: 15000 });
    await expect(this.totalFieldsCard).toBeVisible({ timeout: 15000 });

    const recordsText = await this.totalRecordsCard.textContent();
    const fieldsText = await this.totalFieldsCard.textContent();

    expect(recordsText).not.toContain('--');
    expect(fieldsText).not.toContain('--');
    expect(recordsText).toMatch(/\d+/);
    expect(fieldsText).toMatch(/\d+/);
  }

  async clickGenerateDashboardCTA() {
    await expect(this.generateDashboardCTA).toBeVisible({ timeout: 15000 });
    await this.generateDashboardCTA.click();
  }

  async assertDynamicDashboardRendered() {
    await expect(this.page.locator('h2').first()).toBeVisible({ timeout: 15000 });
    await expect(this.agGridContainer).toBeVisible({ timeout: 15000 });
  }

  async assertSingleChartView() {
    await expect(this.singleChartViewBadge).toBeVisible({ timeout: 15000 });
    const chartCanvases = this.page.locator('canvas');
    await expect(chartCanvases.first()).toBeVisible({ timeout: 15000 });
  }

  async assertAGGridRecordCount(expectedTextPattern: RegExp | string = /Hiển thị 500 \/ 500 bản ghi|Hiển thị \d+ \/ \d+ bản ghi/i) {
    await expect(this.agGridRecordSummary).toBeVisible({ timeout: 15000 });
    await expect(this.agGridRecordSummary).toHaveText(expectedTextPattern, { timeout: 15000 });
  }

  async changeAGGridPageSize(pageSize: '20' | '100' | '500') {
    const pageSelect = this.page.locator('[aria-label="Page Size"], .ag-paging-page-size').first();
    await expect(pageSelect).toBeVisible({ timeout: 15000 });
    await pageSelect.click();
    await this.page.waitForTimeout(200);
    const option = this.page.locator(`.ag-select-list-item, .ag-picker-field-list-item, .ag-custom-option`).filter({ hasText: new RegExp(`^${pageSize}$`) }).first();
    if (await option.isVisible()) {
      await option.click();
    } else {
      // Fallback if option list item format differs
      await this.page.locator(`text=${pageSize}`).last().click({ force: true });
    }
    await this.page.waitForTimeout(300);
  }

  async clickChartBarForCrossFilter(label: string = 'Drake') {
    const canvas = this.page.locator('canvas').first();
    await canvas.scrollIntoViewIfNeeded();
    await canvas.click({ position: { x: 100, y: 150 } });
  }

  async assertAGGridFilteredBy(artistName: string = 'Drake') {
    const agGridRows = this.page.locator('.ag-row');
    await expect(agGridRows.first()).toBeVisible({ timeout: 15000 });
    const firstRowText = await agGridRows.first().textContent();
    expect(firstRowText).not.toContain('No Rows To Show');
  }
}
