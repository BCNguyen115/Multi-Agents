import os
import time
from playwright.sync_api import sync_playwright

def run_browser_check():
    csv_path = os.path.abspath("dataset/test_data/ecommerce_sales_analytics_5000.csv")
    screenshot_path = os.path.abspath("scratch/dashboard_ecommerce_verified.png")

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        context = browser.new_context(viewport={"width": 1600, "height": 1200})
        page = context.new_page()

        print("Navigating to http://localhost:3001...", flush=True)
        page.goto("http://localhost:3001", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1000)

        # Clear localStorage to ensure fresh session
        print("Clearing storage for a fresh session...", flush=True)
        page.evaluate("() => { localStorage.clear(); sessionStorage.clear(); }")
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(2000)

        # Upload CSV file
        print(f"Uploading file {csv_path}...", flush=True)
        file_input = page.locator('input[type="file"]').first
        file_input.set_input_files(csv_path)

        page.wait_for_timeout(1500)

        # Type query
        print("Typing query...", flush=True)
        textarea = page.locator('textarea').first
        textarea.fill("Dựng dashboard phân tích doanh thu và cơ cấu kinh doanh từ file bán hàng")

        page.wait_for_timeout(500)
        print("Clicking send button...", flush=True)
        send_btn = page.locator('[data-testid="send-button"]').first
        if send_btn.is_visible():
            send_btn.click()
        else:
            textarea.press("Enter")

        try:
            print("Waiting for PEV loop execution and dashboard render...", flush=True)
            dash_elem = page.wait_for_selector(
                'canvas, [data-testid="dynamic-dashboard"], .echarts-for-react',
                timeout=95000
            )
            print("Dashboard element detected! Waiting 6s for charts to settle...", flush=True)
            page.wait_for_timeout(6000)
            if dash_elem:
                dash_elem.scroll_into_view_if_needed()
            page.wait_for_timeout(3000)
        except Exception as exc:
            print(f"Exception during wait: {exc}", flush=True)
        finally:
            page.screenshot(path=screenshot_path, full_page=True)
            print(f"Captured screenshot at {screenshot_path}", flush=True)

        browser.close()

if __name__ == "__main__":
    run_browser_check()
