import { Page, Locator, expect } from '@playwright/test';

export class SidebarPage {
  readonly page: Page;
  readonly sidebarContainer: Locator;
  readonly toggleButton: Locator;
  readonly expandButtonCollapsed: Locator;
  readonly newChatButton: Locator;
  readonly searchChatsButton: Locator;
  readonly pinnedHeader: Locator;
  readonly recentsHeader: Locator;

  constructor(page: Page) {
    this.page = page;
    this.sidebarContainer = page.locator('aside');
    this.toggleButton = page.locator('button[title="Thu gọn Sidebar"]');
    this.expandButtonCollapsed = page.locator('button[title="Mở rộng Sidebar"]');
    this.newChatButton = page.locator('button[title="New chat"]');
    this.searchChatsButton = page.locator('button[title="Search chats"]');
    this.pinnedHeader = page.locator('text=Pinned');
    this.recentsHeader = page.locator('text=Recents');
  }

  async goto() {
    await this.page.goto('/');
    await this.page.waitForLoadState('networkidle');
  }

  async toggleSidebar() {
    const isExpanded = await this.sidebarContainer.evaluate(el => el.classList.contains('w-64'));
    if (isExpanded) {
      await this.toggleButton.click({ force: true });
    } else {
      await this.expandButtonCollapsed.click({ force: true });
    }
  }

  async assertSidebarCollapsed() {
    await expect(this.sidebarContainer).toHaveClass(/w-16/);
    await expect(this.sidebarContainer).not.toHaveClass(/w-64/);
  }

  async assertSidebarExpanded() {
    await expect(this.sidebarContainer).toHaveClass(/w-64/);
  }

  async createNewChat() {
    await this.newChatButton.click();
  }

  getConversationItem(title: string): Locator {
    return this.page.locator('aside div').filter({ hasText: title }).first();
  }

  async openConversationMenu(sessionTitle: string) {
    const isMenuVisible = await this.page.locator('text=Ghim cuộc trò chuyện').or(this.page.locator('text=Bỏ ghim')).isVisible();
    if (!isMenuVisible) {
      const item = this.page.locator('aside div.group').filter({ hasText: sessionTitle }).first();
      await item.hover();
      const moreBtn = item.locator('button[title="Tùy chọn"]');
      await moreBtn.click({ force: true });
      await this.page.waitForTimeout(100);
    }
  }

  async assertPortalMenuVisible() {
    await expect(this.page.locator('text=Ghim cuộc trò chuyện').or(this.page.locator('text=Bỏ ghim'))).toBeVisible();
    await expect(this.page.locator('text=Đổi tên')).toBeVisible();
    await expect(this.page.locator('text=Xóa cuộc trò chuyện')).toBeVisible();
  }

  async pinConversation(sessionTitle: string) {
    await this.openConversationMenu(sessionTitle);
    const pinOption = this.page.locator('text=Ghim cuộc trò chuyện').or(this.page.locator('text=Bỏ ghim')).first();
    await pinOption.click({ force: true });
  }

  async renameConversation(oldTitle: string, newTitle: string) {
    await this.openConversationMenu(oldTitle);
    const renameOption = this.page.locator('text=Đổi tên').first();
    await renameOption.click({ force: true });

    const input = this.sidebarContainer.locator('input[type="text"]');
    await expect(input).toBeVisible();
    await input.fill(newTitle);
    await input.press('Enter');
  }

  async deleteConversation(sessionTitle: string) {
    await this.openConversationMenu(sessionTitle);
    const deleteOption = this.page.locator('text=Xóa cuộc trò chuyện').first();
    await deleteOption.click({ force: true });
  }

  async assertPinnedSectionContains(sessionTitle: string) {
    await expect(this.pinnedHeader).toBeVisible();
    const pinnedContainer = this.sidebarContainer.locator('div').filter({ has: this.pinnedHeader }).first();
    await expect(pinnedContainer.locator(`text=${sessionTitle}`)).toBeVisible();
  }

  async assertConversationDeleted(sessionTitle: string) {
    await expect(this.sidebarContainer.locator(`text=${sessionTitle}`)).not.toBeVisible();
  }
}
