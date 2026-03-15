import http.server
import urllib.request
import json
import threading
import time
import hashlib
import os
from collections import deque
from http.cookies import SimpleCookie

WALLET = "47gJdujRwZuQN386r2X8f98L37b4dVpMvXmtR5YfzxcfDEXB4wykEc6UULS3C9Wg2MKMUwQZi2s9e5okiiSkpVPA1DxGscr"

ADMIN_USER = "diacg"
ADMIN_PASS_HASH = hashlib.sha256("Aa778899!!".encode()).hexdigest()
SESSION_TOKEN = hashlib.sha256(os.urandom(32)).hexdigest()

worker_names = {}
NAMES_FILE = "/root/mining-dashboard/worker_names.json"

def load_names():
    global worker_names
    if os.path.exists(NAMES_FILE):
        try:
            with open(NAMES_FILE) as f:
                worker_names = json.load(f)
        except:
            worker_names = {}

def save_names():
    with open(NAMES_FILE, 'w') as f:
        json.dump(worker_names, f, ensure_ascii=False)

def get_worker_display_name(raw_name, index):
    return worker_names.get(raw_name, f"礦機-{index+1}")

load_names()

history = deque(maxlen=1440)
latest_stats = {}
latest_price = {}
latest_workers = {}
total_checks = 0
online_checks = 0

def fetch_data():
    global latest_stats, latest_price, latest_workers, total_checks, online_checks
    while True:
        try:
            req = urllib.request.Request(
                f'https://api.moneroocean.stream/miner/{WALLET}/stats',
                headers={'User-Agent': 'Mozilla/5.0'}
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                stats = json.loads(r.read())
            latest_stats = stats
            hashrate = stats.get('hash', 0)
            total_checks += 1
            if hashrate > 0:
                online_checks += 1
            history.append({'ts': int(time.time()), 'hs': hashrate})
            vals = [d['hs'] for d in history if d['hs'] > 0]
            if vals:
                avg = sum(vals) / len(vals)
                variance = sum((v-avg)**2 for v in vals) / len(vals)
                cv = (variance**0.5) / avg if avg > 0 else 1
                stability = max(0, min(100, (1-cv)*100))
            else:
                avg = 0
                stability = 0
            uptime = (online_checks / total_checks * 100) if total_checks > 0 else 100
            latest_stats['serverAvg'] = avg
            latest_stats['serverStability'] = round(stability, 1)
            latest_stats['serverUptime'] = round(uptime, 1)
        except Exception as e:
            print(f'stats失敗: {e}')

        try:
            req2 = urllib.request.Request(
                f'https://api.moneroocean.stream/miner/{WALLET}/stats/allWorkers',
                headers={'User-Agent': 'Mozilla/5.0'}
            )
            with urllib.request.urlopen(req2, timeout=10) as r:
                latest_workers = json.loads(r.read())
        except Exception as e:
            print(f'workers失敗: {e}')

        try:
            req3 = urllib.request.Request(
                'https://api.coingecko.com/api/v3/simple/price?ids=monero&vs_currencies=twd,usd',
                headers={'User-Agent': 'Mozilla/5.0'}
            )
            with urllib.request.urlopen(req3, timeout=10) as r:
                latest_price = json.loads(r.read()).get('monero', {})
        except Exception as e:
            print(f'price失敗: {e}')

        time.sleep(30)

def check_session(headers):
    cookie_str = headers.get('Cookie', '')
    c = SimpleCookie()
    c.load(cookie_str)
    token = c.get('session')
    return token and token.value == SESSION_TOKEN

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path == '/':
            self.serve_file('/root/mining-dashboard/index.html', 'text/html')
        elif self.path == '/admin':
            if check_session(self.headers):
                self.serve_file('/root/mining-dashboard/admin.html', 'text/html')
            else:
                self.serve_file('/root/mining-dashboard/login.html', 'text/html')
        elif self.path == '/api/all':
            workers_with_names = {}
            index = 0
            for k, v in latest_workers.items():
                if k == 'global':
                    continue
                display = get_worker_display_name(k, index)
                workers_with_names[display] = v
                index += 1
            data = {
                'stats': latest_stats,
                'price': latest_price,
                'history': list(history)[-60:],
                'workers': workers_with_names
            }
            self.send_json(data)
        elif self.path == '/api/worker_names':
            if check_session(self.headers):
                names_with_defaults = {}
                index = 0
                for k in latest_workers.keys():
                    if k == 'global':
                        continue
                    names_with_defaults[k] = get_worker_display_name(k, index)
                    index += 1
                self.send_json(names_with_defaults)
            else:
                self.send_response(403)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length)

        if self.path == '/api/login':
            try:
                data = json.loads(body)
                user = data.get('username', '')
                pw_hash = hashlib.sha256(data.get('password', '').encode()).hexdigest()
                if user == ADMIN_USER and pw_hash == ADMIN_PASS_HASH:
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Set-Cookie', f'session={SESSION_TOKEN}; Path=/; HttpOnly')
                    self.end_headers()
                    self.wfile.write(json.dumps({'ok': True}).encode())
                else:
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({'ok': False}).encode())
            except:
                self.send_response(400)
                self.end_headers()

        elif self.path == '/api/save_names':
            if check_session(self.headers):
                try:
                    data = json.loads(body)
                    worker_names.update(data)
                    save_names()
                    self.send_json({'ok': True})
                except:
                    self.send_response(400)
                    self.end_headers()
            else:
                self.send_response(403)
                self.end_headers()

    def send_json(self, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def serve_file(self, path, mime):
        try:
            with open(path, 'rb') as f:
                data = f.read()
            self.send_response(200)
            self.send_header('Content-Type', mime + '; charset=utf-8')
            self.end_headers()
            self.wfile.write(data)
        except FileNotFoundError:
            self.send_response(404)
            self.end_headers()

if __name__ == '__main__':
    t = threading.Thread(target=fetch_data, daemon=True)
    t.start()
    print('Server running on :19234')
    http.server.HTTPServer(('0.0.0.0', 19234), Handler).serve_forever()
