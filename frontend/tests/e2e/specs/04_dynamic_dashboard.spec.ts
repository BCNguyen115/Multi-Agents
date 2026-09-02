import { test, expect } from '@playwright/test';
import path from 'path';
import { ChatPage } from '../pages/ChatPage';
import { DashboardPage } from '../pages/DashboardPage';

test.describe('4. Test Tóm tắt Dữ liệu & Dựng Dashboard', () => {
  let chatPage: ChatPage;
  let dashboardPage: DashboardPage;
  const sampleFilePath = path.resolve(__dirname, '../fixtures/sample_sales.csv');

  test.beforeEach(async ({ page }) => {
    chatPage = new ChatPage(page);
    dashboardPage = new DashboardPage(page);
    await chatPage.goto();
  });

  test('4.1 Thẻ Chỉ Số Overview hiển thị đúng số liệu thực tế (không bị --)', async ({ page }) => {
    await page.route('**/api/analyze', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          explanation: '### 📊 Tóm Tắt Dữ Liệu Tập Tin Bán Hàng\n\n- **Tổng số dòng (Rows)** | `500`\n- **Tổng số cột (Columns)** | `10`',
          metadata: {
            total_rows: 500,
            total_cols: 10,
            columns: ['Order_ID', 'Date', 'Customer_Name', 'Artist', 'Category', 'Quantity', 'Unit_Price', 'Revenue', 'Payment_Method', 'Status'],
          },
        }),
      });
    });

    await chatPage.uploadFileViaPlusButton(sampleFilePath);
    await page.waitForTimeout(300);
    await chatPage.sendMessage('Phân tích tổng quan tập dữ liệu này');

    await dashboardPage.assertOverviewCardsMetrics();
  });

  test('4.2 Nút CTA Dựng Dashboard giữ đúng Session File Context và render <DynamicDashboard />', async ({ page }) => {
    let callCount = 0;
    await page.route('**/api/analyze', async (route) => {
      callCount++;
      if (callCount === 1) {
        // Lần 1: Trả về Data Summary kèm nút CTA
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            explanation: '### 📊 Tóm Tắt Dữ Liệu Tập Tin Bán Hàng\n\n- **Tổng số dòng (Rows)** | `500`\n- **Tổng số cột (Columns)** | `10`',
            metadata: { total_rows: 500, total_cols: 10 },
          }),
        });
      } else {
        // Lần 2 (khi bấm CTA Dựng Dashboard): Trả về dashboard_spec
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            explanation: 'Đã tạo Dashboard trực quan thành công.',
            dashboard_spec: {
              dashboard_title: 'Executive Sales Analytics Dashboard',
              totalRows: 500,
              totalColumns: 10,
              kpis: [
                { title: 'TỔNG DOANH THU', value: '$135,400.00', change: '+12.5%', changeType: 'positive', type: 'currency' },
                { title: 'TỔNG ĐƠN HÀNG', value: '500', change: '+5.2%', changeType: 'positive', type: 'count' },
              ],
              charts: [
                { title: 'Doanh Số Theo Nghệ Sĩ', type: 'bar', x_axis_key: 'Artist', series_keys: ['Revenue'] },
              ],
              table: {
                title: 'Bảng Chi Tiết Dữ Liệu Bán Hàng',
                rows: Array.from({ length: 500 }, (_, i) => ({
                  Order_ID: `ORD-${1001 + i}`,
                  Artist: i % 2 === 0 ? 'Drake' : 'Taylor Swift',
                  Revenue: 150 * ((i % 3) + 1),
                })),
              },
            },
          }),
        });
      }
    });

    await chatPage.uploadFileViaPlusButton(sampleFilePath);
    await page.waitForTimeout(300);
    await chatPage.sendMessage('Tóm tắt dữ liệu');

    // Click nút CTA "📌 Dựng Dashboard trực quan từ dữ liệu này"
    await dashboardPage.clickGenerateDashboardCTA();

    // Verify component <DynamicDashboard /> render thành công
    await dashboardPage.assertDynamicDashboardRendered();
  });

  test('4.3 Chế độ Single Chart View hiển thị 1 Biểu đồ đường mượt mà (không bị nhiễu 5000 chấm)', async ({ page }) => {
    await page.route('**/api/analyze', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          explanation: 'Biểu đồ đường xu hướng doanh thu hàng tháng.',
          dashboard_spec: {
            layout_type: 'single_chart',
            dashboard_title: 'Xu Hướng Doanh Thu Hàng Tháng',
            charts: [
              {
                title: 'Biểu Đồ Đường Doanh Thu Hàng Tháng',
                type: 'line',
                x_axis_key: 'Month',
                series_keys: ['Revenue'],
              },
            ],
            table: {
              rows: [
                { Month: 'Tháng 1', Revenue: 12000 },
                { Month: 'Tháng 2', Revenue: 15000 },
                { Month: 'Tháng 3', Revenue: 18000 },
                { Month: 'Tháng 4', Revenue: 22000 },
                { Month: 'Tháng 5', Revenue: 25000 },
                { Month: 'Tháng 6', Revenue: 21000 },
                { Month: 'Tháng 7', Revenue: 27000 },
                { Month: 'Tháng 8', Revenue: 30000 },
                { Month: 'Tháng 9', Revenue: 32000 },
                { Month: 'Tháng 10', Revenue: 28000 },
                { Month: 'Tháng 11', Revenue: 35000 },
                { Month: 'Tháng 12', Revenue: 40000 },
              ],
            },
          },
        }),
      });
    });

    await chatPage.uploadFileViaPlusButton(sampleFilePath);
    await page.waitForTimeout(300);
    await chatPage.sendMessage('Tạo biểu đồ đường xu hướng doanh thu hàng tháng');

    await dashboardPage.assertSingleChartView();
  });
});
