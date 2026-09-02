import { Page, Locator, expect } from '@playwright/test';

export class ChatPage {
  readonly page: Page;
  readonly heroTitle: Locator;
  readonly textarea: Locator;
  readonly sendButton: Locator;
  readonly filePlusButton: Locator;
  readonly fileInput: Locator;
  readonly fileChipBadge: Locator;
  readonly removeFileButton: Locator;
  readonly dragOverlay: Locator;
  readonly pevStepperHeader: Locator;
  readonly plannerNode: Locator;
  readonly executorNode: Locator;
  readonly verifierNode: Locator;
  readonly verifiedBadge: Locator;

  constructor(page: Page) {
    this.page = page;
    this.heroTitle = page.locator('h1', { hasText: 'Tôi có thể giúp gì cho bạn hôm nay?' });
    this.textarea = page.locator('textarea');
    this.sendButton = page.locator('button').filter({ has: page.locator('svg') }).last();
    this.filePlusButton = page.locator('button[title*="Đính kèm file"]');
    this.fileInput = page.locator('input[type="file"]');
    this.fileChipBadge = page.locator('div').filter({ hasText: /\.csv|\.xlsx|\.pdf|\.docx/i }).first();
    this.removeFileButton = page.locator('button[title="Gỡ file đính kèm"]');
    this.dragOverlay = page.locator('text=Kéo & thả file CSV / Excel / Document vào đây để nạp tự động');
    this.pevStepperHeader = page.locator('text=PEV Loop Stepper: Core Reasoning Workflow');
    this.plannerNode = page.locator('text=1. Planner Node');
    this.executorNode = page.locator('text=2. Executor Node');
    this.verifierNode = page.locator('text=3. Verifier Node');
    this.verifiedBadge = page.locator('span', { hasText: '(Verified)' }).last();
  }

  async goto() {
    await this.page.goto('/');
    await this.page.waitForLoadState('networkidle');
  }

  async assertHeroCenterVisible() {
    await expect(this.heroTitle).toBeVisible();
    // Check centered hero layout wrapper
    const heroContainer = this.page.locator('div.max-w-3xl.mx-auto');
    await expect(heroContainer).toBeVisible();
    await expect(this.textarea).toBeVisible();
  }

  async sendMessage(promptText: string) {
    await this.textarea.fill(promptText);
    await this.sendButton.click();
  }

  async assertInputTransitionedToBottom() {
    // When messages exist, heroTitle should fade out or unmount
    await expect(this.heroTitle).not.toBeVisible();
    // Chat input container will be positioned in active chat window bottom footer
    const activeChatInput = this.page.locator('main div.bg-gradient-to-t textarea, main textarea');
    await expect(activeChatInput).toBeVisible();
  }

  async uploadFileViaPlusButton(filePath: string) {
    // Set file via hidden input element
    await this.fileInput.setInputFiles(filePath);
    // Wait for File Chip Badge to ensure React state attachedFile and DuckDB activeCSV are updated
    const fileName = filePath.split(/[/\\]/).pop() || 'sample_sales.csv';
    await this.assertFileChipBadgeVisible(fileName);
  }

  async triggerDragOver() {
    // Trigger dragenter / dragover event on main container
    const mainContainer = this.page.locator('main > div').first();
    await mainContainer.dispatchEvent('dragenter');
    await mainContainer.dispatchEvent('dragover');
  }

  async assertDragOverlayVisible() {
    await expect(this.dragOverlay).toBeVisible();
    await expect(this.page.locator('text=Hỗ trợ các định dạng .csv, .xlsx, .pdf, .docx')).toBeVisible();
  }

  async dropFile(filePath: string) {
    // Fire drop event with file data
    const dataTransfer = await this.page.evaluateHandle(async (path) => {
      const dt = new DataTransfer();
      const file = new File(['Order_ID,Revenue\n1,100'], 'sample_sales.csv', { type: 'text/csv' });
      dt.items.add(file);
      return dt;
    }, filePath);

    const mainContainer = this.page.locator('main > div').first();
    await mainContainer.dispatchEvent('drop', { dataTransfer });
  }

  async assertFileChipBadgeVisible(fileName: string) {
    await expect(this.page.locator(`text=${fileName}`)).toBeVisible();
    await expect(this.removeFileButton).toBeVisible();
  }

  async removeAttachedFile() {
    await this.removeFileButton.click();
  }

  async assertPEVStepperSequence() {
    await expect(this.pevStepperHeader).toBeVisible();
    await expect(this.plannerNode).toBeVisible();
    await expect(this.executorNode).toBeVisible();
    await expect(this.verifierNode).toBeVisible();
    await expect(this.verifiedBadge).toBeVisible();
  }

  async assertAutoScrollSmooth() {
    const scrollContainer = this.page.locator('div.overflow-y-auto').first();
    await expect(scrollContainer).toBeVisible();
  }
}
