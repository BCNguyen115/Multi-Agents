import { test, expect } from '@playwright/test';
import { SidebarPage } from '../pages/SidebarPage';

test.describe('1. Test Sidebar & Quản lý Cuộc trò chuyện', () => {
  let sidebarPage: SidebarPage;

  test.beforeEach(async ({ page }) => {
    sidebarPage = new SidebarPage(page);
    await sidebarPage.goto();
  });

  test('1.1 Co / Giãn Sidebar (w-64 -> w-16 -> w-64) mà không bị vỡ icon cố định', async () => {
    // Ban đầu Sidebar mở rộng (w-64)
    await sidebarPage.assertSidebarExpanded();

    // Click nút Toggle để thu gọn
    await sidebarPage.toggleSidebar();
    await sidebarPage.assertSidebarCollapsed();

    // Click lại nút Toggle để mở rộng
    await sidebarPage.toggleSidebar();
    await sidebarPage.assertSidebarExpanded();
  });

  test('1.2 Menu Hành động (⋮) nổi lên trên Portal & thực hiện lần lượt Ghim, Đổi tên, Xóa conversation', async () => {
    const originalTitle = 'Cuộc trò chuyện mới';
    const renamedTitle = 'Báo cáo Doanh thu Q1 2024';

    // 1. Kiểm tra Dropdown Menu nổi lên trên (React Portal zIndex 9999 không bị overflow cut)
    await sidebarPage.openConversationMenu(originalTitle);
    await sidebarPage.assertPortalMenuVisible();

    // 2. Test Ghim (Pin): Đưa conversation lên đầu danh sách Pinned
    await sidebarPage.pinConversation(originalTitle);
    await sidebarPage.assertPinnedSectionContains(originalTitle);

    // 3. Test Đổi tên (Rename): Nhập tên mới và lưu lại
    await sidebarPage.renameConversation(originalTitle, renamedTitle);
    await expect(sidebarPage.sidebarContainer.locator(`text=${renamedTitle}`)).toBeVisible();

    // 4. Test Xóa (Delete): Xóa conversation khỏi danh sách
    await sidebarPage.deleteConversation(renamedTitle);
    await sidebarPage.assertConversationDeleted(renamedTitle);
  });
});
