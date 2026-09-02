import { test, expect } from '@playwright/test';
import { ChatPage } from '../pages/ChatPage';

test.describe('2. Test Màn hình New Chat & SSE Streaming', () => {
  let chatPage: ChatPage;

  test.beforeEach(async ({ page }) => {
    chatPage = new ChatPage(page);
    await chatPage.goto();
  });

  test('2.1 Căn giữa Hero Center khi mới mở New Chat', async () => {
    await chatPage.assertHeroCenterVisible();
  });

  test('2.2 Single ChatInput Transition mượt mà không bị dual-mount khi gửi tin nhắn', async ({ page }) => {
    // Intercept SSE / API route to control stream response
    await page.route('/api/chat/stream*', async (route) => {
      const ssePayload = [
        'event: plan\ndata: {"plan": "Phân tích câu hỏi hợp đồng NDA", "target_agent": "rag_agent"}\n\n',
        'event: executing\ndata: {"target_agent": "rag_agent", "execution_result": "Đang truy vấn vector database"}\n\n',
        'event: verifying\ndata: {"is_verified": true, "verifier_feedback": "Thông tin chính xác", "retry_count": 0}\n\n',
        'event: final_response\ndata: {"response": "Hợp đồng NDA có thời hạn 2 năm kể từ ngày ký.", "target_agent": "rag_agent", "is_verified": true}\n\n',
      ].join('');

      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: ssePayload,
      });
    });

    // 1. Kiểm tra trạng thái ban đầu ở Hero Center
    await chatPage.assertHeroCenterVisible();

    // 2. Nhập câu hỏi và gửi tin nhắn
    await chatPage.sendMessage('Điều khoản bảo mật trong NDA kéo dài bao lâu?');

    // 3. Verify Hero Title ẩn đi và ChatInput duy nhất trượt xuống đáy
    await chatPage.assertInputTransitionedToBottom();

    // 4. Verify không có dual-mount ChatInput (chỉ có 1 duy nhất trong DOM)
    const textareas = page.locator('textarea');
    await expect(textareas).toHaveCount(1);
  });

  test('2.3 Trạng thái PEV Stepper nhảy từ Planner -> Executor -> Verifier Node (Verified)', async ({ page }) => {
    await page.route('/api/chat/stream*', async (route) => {
      const ssePayload = [
        'event: plan\ndata: {"plan": "Lập kế hoạch tra cứu hợp đồng", "target_agent": "rag_agent"}\n\n',
        'event: executing\ndata: {"target_agent": "rag_agent", "execution_result": "Thực thi truy vấn hoàn tất"}\n\n',
        'event: verifying\ndata: {"is_verified": true, "verifier_feedback": "Kiểm duyệt thành công", "retry_count": 0}\n\n',
        'event: final_response\ndata: {"response": "Kết quả hợp đồng đã được xác minh.", "target_agent": "rag_agent", "is_verified": true}\n\n',
      ].join('');

      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: ssePayload,
      });
    });

    await chatPage.sendMessage('Tra cứu thời hạn hợp đồng dịch vụ IT');
    await chatPage.assertPEVStepperSequence();
  });

  test('2.4 Cuộn màn hình Auto-scroll mượt mà trong khi AI streaming', async ({ page }) => {
    await page.route('/api/chat/stream*', async (route) => {
      const chunk = 'Hợp đồng này quy định chi tiết trách nhiệm của các bên liên quan... '.repeat(10);
      const ssePayload = `event: final_response\ndata: {"response": "${chunk}", "target_agent": "rag_agent", "is_verified": true}\n\n`;

      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: ssePayload,
      });
    });

    await chatPage.sendMessage('Tóm tắt toàn bộ hợp đồng dịch vụ');
    await chatPage.assertAutoScrollSmooth();
  });
});
