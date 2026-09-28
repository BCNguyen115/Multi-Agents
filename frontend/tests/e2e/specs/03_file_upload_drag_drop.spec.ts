import { test, expect } from '@playwright/test';
import path from 'path';
import { ChatPage } from '../pages/ChatPage';

test.describe('3. Test Đính kèm File & Kéo thả Drag & Drop', () => {
  let chatPage: ChatPage;
  const sampleFilePath = path.resolve(__dirname, '../fixtures/sample_sales.csv');

  test.beforeEach(async ({ page }) => {
    chatPage = new ChatPage(page);
    await chatPage.goto();
  });

  test('3.1 Nút + Upload: Đính kèm file sample_sales.csv và hiển thị File Chip Badge chuẩn xác', async () => {
    // 1. Upload file bằng hidden file input (tương ứng click nút +)
    await chatPage.uploadFileViaPlusButton(sampleFilePath);

    // 2. Verify File Chip Badge chứa tên file, dung lượng, nút xóa x
    await chatPage.assertFileChipBadgeVisible('sample_sales.csv');

    // 3. Test bấm nút x để gỡ file đính kèm
    await chatPage.removeAttachedFile();
    await expect(chatPage.page.locator('text=sample_sales.csv')).not.toBeVisible();
  });

  test('3.2 Drag & Drop Overlay: Hiển thị lớp Overlay chuẩn kỹ thuật khi kéo file qua màn hình', async () => {
    // Kéo file đè lên màn hình
    await chatPage.triggerDragOver();

    // Verify hiển thị lớp Overlay "Kéo & thả file CSV / Excel / Document vào đây để nạp tự động"
    await chatPage.assertDragOverlayVisible();

    // Verify không chứa các văn bản tạm nham nhở hay chữ Gemini UX rác
    const overlayText = await chatPage.dragOverlay.textContent();
    expect(overlayText).not.toContain('Gemini UX');
    expect(overlayText).toContain('Kéo & thả file CSV / Excel / Document vào đây để nạp tự động');
  });

  test('3.3 Thả File (Drop): Drop file -> UI đính kèm hiển thị giống hệt 100% như bấm nút +', async () => {
    // Drop file vào main container
    await chatPage.dropFile(sampleFilePath);

    // Verify UI File Chip Badge xuất hiện đồng nhất 100%
    await chatPage.assertFileChipBadgeVisible('sample_sales.csv');
  });
});
