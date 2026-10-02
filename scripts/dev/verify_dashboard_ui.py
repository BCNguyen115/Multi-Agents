import os
import time
import pandas as pd
from playwright.sync_api import sync_playwright

def generate_csv(path):
    # Tạo dữ liệu trải dài từ 2022-01 đến 2024-03 với các ngày lẻ ngẫu nhiên
    dates = pd.date_range("2022-01-01", "2024-03-31", freq="D")
    df = pd.DataFrame({
        "order_date": dates.strftime("%m/%d/%Y"),
        "revenue": [round(10000000 + (i % 30) * 500000 + (i // 30) * 800000, 2) for i in range(len(dates))],
        "category": [["Điện tử", "Gia dụng", "Thời trang", "Mỹ phẩm"][i % 4] for i in range(len(dates))],
        "region": [["Miền Bắc", "Miền Nam", "Miền Trung"][i % 3] for i in range(len(dates))],
    })
    df.to_csv(path, index=False)
    print(f"Generated sample CSV with {len(df)} rows at {path}")

def run_browser_check():
    csv_path = os.path.abspath("scratch/test_temporal_sales.csv")
    os.makedirs("scratch", exist_ok=True)
    generate_csv(csv_path)

    screenshot_path = os.path.abspath("scratch/dashboard_temporal_result.png")

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        context = browser.new_context(viewport={"width": 1600, "height": 1000})
        page = context.new_page()

        print("Navigating to http://localhost:3001...")
        page.goto("http://localhost:3001", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1500)

        # Upload CSV file
        print(f"Uploading file {csv_path}...")
        file_input = page.locator('input[type="file"]').first
        file_input.set_input_files(csv_path)

        page.wait_for_timeout(2000)

        # Type message
        print("Typing message...")
        textarea = page.locator('textarea').first
        textarea.fill("Vẽ biểu đồ xu hướng doanh thu theo tháng từ dữ liệu đính kèm")

        page.wait_for_timeout(500)
        print("Sending message...")
        send_btn = page.locator('button:has(svg.lucide-send), button[title*="Gửi"], button[type="submit"]').first
        if send_btn.is_visible():
            send_btn.click()
        else:
            textarea.press("Enter")

        try:
            print("Waiting for PEV loop execution and dynamic dashboard...")
            dash_elem = page.wait_for_selector('canvas, [data-testid="dynamic-dashboard"], .echarts-for-react', timeout=85000)
            print("Chart/Dashboard element detected! Scrolling into view and waiting 4s...")
            page.wait_for_timeout(2000)
            if dash_elem:
                dash_elem.scroll_into_view_if_needed()
            page.wait_for_timeout(3000)
        except Exception as exc:
            print(f"Exception during wait: {exc}")
        finally:
            page.screenshot(path=screenshot_path, full_page=True)
            print(f"Captured screenshot at {screenshot_path}")

        browser.close()

if __name__ == "__main__":
    run_browser_check()
