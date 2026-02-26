"""
Extract YouTube cookies from Chrome using Selenium.
Selenium uses ChromeDriver which communicates with Chrome natively,
bypassing App-Bound Encryption completely.
"""

import os
import sys
import time

COOKIES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cookies.txt')
CHROME_USER_DATA = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Google', 'Chrome', 'User Data')


def refresh_cookies():
    """Extract cookies from Chrome profile using Selenium and save to cookies.txt."""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager

    print('[CookieHelper] Setting up Chrome via Selenium...')

    opts = Options()
    opts.add_argument(f'--user-data-dir={CHROME_USER_DATA}')
    opts.add_argument('--profile-directory=Default')
    opts.add_argument('--headless=new')
    opts.add_argument('--no-sandbox')
    opts.add_argument('--disable-dev-shm-usage')
    opts.add_argument('--disable-gpu')

    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=opts)
    except Exception as e:
        print(f'[CookieHelper] Failed to start Chrome: {e}')
        return False

    try:
        # Navigate to YouTube to load cookies
        print('[CookieHelper] Navigating to YouTube...')
        driver.get('https://www.youtube.com')
        time.sleep(3)

        # Get all cookies
        all_cookies = driver.get_cookies()
        print(f'[CookieHelper] Got {len(all_cookies)} cookies from YouTube')

        # Also get Google cookies
        driver.get('https://www.google.com')
        time.sleep(1)
        all_cookies.extend(driver.get_cookies())

        # Filter and format
        cookies = []
        seen = set()
        for c in all_cookies:
            domain = c.get('domain', '')
            name = c.get('name', '')
            key = f'{domain}:{name}'

            if key in seen:
                continue
            seen.add(key)

            if 'youtube.com' not in domain and 'google.com' not in domain:
                continue

            value = c.get('value', '')
            if not value:
                continue

            path = c.get('path', '/')
            expires = int(c.get('expiry', 0))
            secure = 'TRUE' if c.get('secure', False) else 'FALSE'
            domain_dot = 'TRUE' if domain.startswith('.') else 'FALSE'

            cookies.append(f'{domain}\t{domain_dot}\t{path}\t{secure}\t{expires}\t{name}\t{value}')

        if cookies:
            with open(COOKIES_FILE, 'w', encoding='utf-8') as f:
                f.write('# Netscape HTTP Cookie File\n')
                f.write(f'# Auto-exported via Selenium: {time.strftime("%Y-%m-%d %H:%M:%S")}\n\n')
                for cookie in cookies:
                    f.write(cookie + '\n')
            print(f'[CookieHelper] Exported {len(cookies)} cookies to {COOKIES_FILE}')
            return True
        else:
            print('[CookieHelper] No YouTube/Google cookies found')
            return False

    except Exception as e:
        print(f'[CookieHelper] Error: {e}')
        import traceback
        traceback.print_exc()
        return False

    finally:
        driver.quit()
        print('[CookieHelper] Chrome closed')


if __name__ == '__main__':
    # Make sure Chrome is closed first
    print('Make sure Chrome is CLOSED before running this script!')
    print()
    success = refresh_cookies()
    sys.exit(0 if success else 1)
