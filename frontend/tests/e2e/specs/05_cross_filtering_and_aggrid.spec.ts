import { test, expect } from '@playwright/test';
import path from 'path';
import { ChatPage } from '../pages/ChatPage';
import { DashboardPage } from '../pages/DashboardPage';

test.describe('5. Test Lọc Chéo (Cross-Filtering) & Bảng AG Grid', () => {
  let chatPage: ChatPage;
  let dashboardPage: DashboardPage;
  const sampleFilePath = path.resolve(__dirname, '../fixtures/sample_sales.csv');

  test.beforeEach(async ({ page }) => {
    chatPage = new ChatPage(page);
    dashboardPage = new DashboardPage(page);
    await chatPage.goto();

    await page.route('**/api/analyze', async (route) => {
      const rows = Array.from({ length: 500 }, (_, i) => {
        const artists = ['Drake', 'Taylor Swift', 'Kendrick Lamar', 'Beyoncé', 'Ed Sheeran'];
        const artist = artists[i % artists.length];
        return {
          Order_ID: `ORD-${1001 + i}`,
          Date: `2024-01-${String((i % 28) + 1).padStart(2, '0')}`,
          Customer_Name: `Customer ${i + 1}`,
          Artist: artist,
          Category: artist === 'Taylor Swift' ? 'Pop' : 'Hip-Hop',
          Quantity: (i % 4) + 1,
          Unit_Price: 150.0,
          Revenue: 150.0 * ((i % 4) + 1),
          Payment_Method: i % 2 === 0 ? 'Credit Card' : 'E-Wallet',
          Status: 'Completed',
        };
      });

      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          explanation: 'Bảng chi tiết 500 bản ghi bán hàng.',
          dashboard_spec: {
            dashboard_title: 'Executive Sales Analytics Dashboard',
            totalRows: 500,
            totalColumns: 10,
            kpis: [
              { title: 'TỔNG BẢN GHI', value: '500', change: '100%', changeType: 'positive', type: 'count' },
            ],
            charts: [
              { title: 'Doanh Số Theo Nghệ Sĩ', type: 'bar', x_axis_key: 'Artist', series_keys: ['Revenue'] },
              { title: 'Tỷ Trọng Phương Thức Thanh Toán', type: 'pie', name_key: 'Payment_Method', value_key: 'Revenue' },
            ],
            table: {
              title: 'Bảng Chi Tiết Dữ Liệu',
              rows: rows,
            },
          },
        }),
      });
    });

    await chatPage.uploadFileViaPlusButton(sampleFilePath);
    await page.waitForTimeout(300);
    await chatPage.sendMessage('Dựng dashboard phân tích 500 bản ghi');
  });

  test('5.1 Thanh thông tin AG Grid báo đúng Hiển thị 500 / 500 bản ghi (không nghẽn ở 10 bản ghi)', async () => {
    await dashboardPage.assertDynamicDashboardRendered();
    await dashboardPage.assertAGGridRecordCount(/Hiển thị 500 \/ 500 bản ghi/i);
  });

  test('5.2 Phân Trang AG Grid: Thay đổi Page Size (20 -> 100 -> 500) mượt mà', async () => {
    await dashboardPage.assertDynamicDashboardRendered();
    await dashboardPage.changeAGGridPageSize('100');
    await dashboardPage.changeAGGridPageSize('500');
    await dashboardPage.assertAGGridRecordCount(/Hiển thị 500 \/ 500 bản ghi/i);
  });

  test('5.3 Lọc Chéo (Cross-Filter Click): Click cột trên biểu đồ tự động lọc AG Grid không bị No Rows To Show', async () => {
    await dashboardPage.assertDynamicDashboardRendered();
    await dashboardPage.clickChartBarForCrossFilter('Drake');
    await dashboardPage.assertAGGridFilteredBy('Drake');
  });
});
