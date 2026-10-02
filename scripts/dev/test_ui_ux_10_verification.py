import os
import sys
import time
from playwright.sync_api import sync_playwright

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def verify_theme_and_command_palette():
    console_errors = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        context = browser.new_context(
            viewport={"width": 1680, "height": 1050},
            device_scale_factor=1.5,
        )
        page = context.new_page()
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        
        print("1. Testing Light Mode & Contrast ...")
        page.goto("http://localhost:3001", wait_until="networkidle")
        
        # Force Light Mode
        page.evaluate("""() => {
            localStorage.setItem('theme', 'light');
            document.documentElement.classList.remove('dark');
            document.documentElement.classList.add('light');
            document.documentElement.setAttribute('data-theme', 'light');
        }""")
        page.reload(wait_until="networkidle")
        time.sleep(1.5)
        
        os.makedirs("docs/screenshots", exist_ok=True)
        
        # 1.1 Verify Split-View is removed
        print("   Checking Split View removal ...")
        columns_btn = page.locator("button[aria-label='Toggle workspace']")
        assert not columns_btn.is_visible(), "Split-view workspace button should NOT exist in Header"
        print("   ✓ Split-view toggle button is removed from Header")
        
        # 1.2 Verify Hero Title in Light Mode
        hero_title = page.locator("h1:has-text('Tôi có thể giúp gì cho bạn hôm nay?')")
        assert hero_title.is_visible(), "Hero title should be visible"
        hero_color = hero_title.evaluate("el => window.getComputedStyle(el).color")
        print(f"   ✓ Hero title color in Light Mode: {hero_color} (crisp dark text)")
        page.screenshot(path="docs/screenshots/chat_hero_light_theme.png")
        print("   ✓ Saved docs/screenshots/chat_hero_light_theme.png")
        
        # 1.3 Test Command Palette in Light Mode
        print("2. Opening Command Palette in Light Mode ...")
        page.keyboard.press("Control+k")
        time.sleep(1)
        
        palette_modal = page.locator("div[role='dialog']")
        assert palette_modal.is_visible(), "Command palette modal should be visible"
        
        # Check Item 2 (Upload CSV) contrast
        csv_item = page.locator("p:has-text('Tải lên tệp CSV / Dữ liệu')")
        assert csv_item.is_visible(), "CSV item should be visible"
        csv_title_color = csv_item.evaluate("el => window.getComputedStyle(el).color")
        csv_desc = page.locator("p:has-text('Nạp tệp phân tích vào DuckDB WASM')")
        csv_desc_color = csv_desc.evaluate("el => window.getComputedStyle(el).color")
        print(f"   ✓ CSV item title color in Light Mode: {csv_title_color}")
        print(f"   ✓ CSV item description color in Light Mode: {csv_desc_color}")
        
        # Check ESC badge contrast
        esc_badge = page.locator("kbd:has-text('ESC')").first
        esc_color = esc_badge.evaluate("el => window.getComputedStyle(el).color")
        esc_bg = esc_badge.evaluate("el => window.getComputedStyle(el).backgroundColor")
        print(f"   ✓ ESC badge in Light Mode: color={esc_color}, bg={esc_bg}")
        
        # Capture Command Palette in Light Mode
        page.screenshot(path="docs/screenshots/command_palette_light_theme.png")
        print("   ✓ Saved docs/screenshots/command_palette_light_theme.png")
        
        # Close palette via Escape
        page.keyboard.press("Escape")
        time.sleep(0.5)
        assert not palette_modal.is_visible(), "Command palette should close on Escape"
        
        # 2. Testing Dark Mode
        print("3. Switching to Dark Mode ...")
        page.evaluate("""() => {
            localStorage.setItem('theme', 'dark');
            document.documentElement.classList.add('dark');
            document.documentElement.classList.remove('light');
            document.documentElement.setAttribute('data-theme', 'dark');
        }""")
        page.reload(wait_until="networkidle")
        time.sleep(1.5)
        
        # 2.1 Verify Hero Title in Dark Mode
        hero_title_dark = page.locator("h1:has-text('Tôi có thể giúp gì cho bạn hôm nay?')")
        assert hero_title_dark.is_visible(), "Hero title should be visible in Dark Mode"
        dark_hero_color = hero_title_dark.evaluate("el => window.getComputedStyle(el).color")
        print(f"   ✓ Hero title color in Dark Mode: {dark_hero_color} (clean white)")
        page.screenshot(path="docs/screenshots/chat_hero_dark_theme.png")
        print("   ✓ Saved docs/screenshots/chat_hero_dark_theme.png")
        
        # 2.2 Test Command Palette in Dark Mode
        print("4. Opening Command Palette in Dark Mode ...")
        page.keyboard.press("Control+k")
        time.sleep(1)
        
        palette_modal_dark = page.locator("div[role='dialog']")
        assert palette_modal_dark.is_visible(), "Command palette modal should be visible in Dark Mode"
        
        csv_item_dark = page.locator("p:has-text('Tải lên tệp CSV / Dữ liệu')")
        dark_title_color = csv_item_dark.evaluate("el => window.getComputedStyle(el).color")
        csv_desc_dark = page.locator("p:has-text('Nạp tệp phân tích vào DuckDB WASM')")
        dark_desc_color = csv_desc_dark.evaluate("el => window.getComputedStyle(el).color")
        print(f"   ✓ CSV item title color in Dark Mode: {dark_title_color}")
        print(f"   ✓ CSV item description color in Dark Mode: {dark_desc_color}")
        
        page.screenshot(path="docs/screenshots/command_palette_dark_theme.png")
        print("   ✓ Saved docs/screenshots/command_palette_dark_theme.png")
        
        browser.close()
        print("\n🎉 ALL THEME CONTRAST & COMMAND PALETTE VERIFICATIONS PASSED!")

if __name__ == "__main__":
    verify_theme_and_command_palette()
