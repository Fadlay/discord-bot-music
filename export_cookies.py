"""
Simple cookie export helper.
Starts a local server that receives cookies from Chrome DevTools Console.

Usage:
1. Run: python export_cookies.py
2. Open Chrome, go to https://www.youtube.com (make sure you're logged in)
3. Press F12 to open DevTools -> Console tab
4. Paste the command shown by this script and press Enter
5. Cookies will be saved automatically!
"""

import http.server
import json
import os
import sys
import time
import threading
import webbrowser

COOKIES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cookies.txt')
PORT = 8457
received = threading.Event()


class CookieHandler(http.server.BaseHTTPRequestHandler):
    def do_OPTIONS(self, *args, **kwargs):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_POST(self, *args, **kwargs):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length).decode('utf-8')

        try:
            cookies = json.loads(body)
            lines = []
            for c in cookies:
                domain = c.get('domain', '')
                name = c.get('name', '')
                value = c.get('value', '')
                path = c.get('path', '/')
                expires = c.get('expirationDate', 0)
                secure = 'TRUE' if c.get('secure', False) else 'FALSE'
                http_only = c.get('httpOnly', False)
                domain_dot = 'TRUE' if domain.startswith('.') else 'FALSE'
                if value and ('youtube.com' in domain or 'google.com' in domain):
                    lines.append(f'{domain}\t{domain_dot}\t{path}\t{secure}\t{int(expires)}\t{name}\t{value}')

            if lines:
                with open(COOKIES_FILE, 'w', encoding='utf-8') as f:
                    f.write('# Netscape HTTP Cookie File\n')
                    f.write(f'# Exported: {time.strftime("%Y-%m-%d %H:%M:%S")}\n\n')
                    for line in lines:
                        f.write(line + '\n')

                self.send_response(200)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Content-Type', 'text/plain')
                self.end_headers()
                self.wfile.write(f'OK: {len(lines)} cookies saved'.encode())
                print(f'\n[SUCCESS] {len(lines)} cookies saved to {COOKIES_FILE}')
                received.set()
            else:
                self.send_response(400)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(b'No valid cookies found')
                print('[WARN] No YouTube/Google cookies in the data')

        except Exception as e:
            self.send_response(500)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(str(e).encode())
            print(f'[ERROR] {e}')

    def log_message(self, format, *args):
        pass  # Suppress HTTP logs


def main():
    server = http.server.HTTPServer(('127.0.0.1', PORT), CookieHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    print('=' * 60)
    print('  YouTube Cookie Exporter')
    print('=' * 60)
    print()
    print('LANGKAH-LANGKAH:')
    print()
    print('1. Buka Chrome, pergi ke https://www.youtube.com')
    print('   (pastikan sudah LOGIN ke akun YouTube)')
    print()
    print('2. Tekan F12 untuk buka DevTools')
    print('   Pilih tab "Console"')
    print()
    print('3. COPY-PASTE perintah di bawah ini ke Console, lalu tekan Enter:')
    print()
    print('-' * 60)
    # The JS code to run in Chrome DevTools Console
    js_code = (
        "fetch('https://www.youtube.com').then(()=>{"
        "let c=document.cookie.split(';').map(s=>s.trim()).filter(s=>s).map(s=>{"
        "let[n,...v]=s.split('=');"
        "return{domain:'.youtube.com',name:n.trim(),value:v.join('='),path:'/',secure:location.protocol==='https:',expirationDate:Date.now()/1000+86400*365}"
        "});"
        "fetch('http://127.0.0.1:" + str(PORT) + "',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(c)}).then(r=>r.text()).then(t=>console.log(t)).catch(e=>console.error(e))"
        "})"
    )
    print(js_code)
    print('-' * 60)
    print()
    print('Menunggu cookies...')

    # Wait for cookies
    if received.wait(timeout=300):
        print('\nBerhasil! Sekarang jalankan bot: python main.py')
    else:
        print('\nTimeout setelah 5 menit. Coba lagi.')

    server.shutdown()


if __name__ == '__main__':
    main()
