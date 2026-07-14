#!/usr/bin/env python3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
import json, os, time, uuid

DATA_DIR = Path(os.environ.get('ATTENTION_SENSOR_DATA_DIR', '/var/lib/metaspn-guide-sensor'))
LOG_PATH = DATA_DIR / 'sensor-receipts.jsonl'
MAX_BODY = 200_000

ALLOWED_SCHEMA = 'attention-sensor-v1'


def now_iso():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def load_events(days=7):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - days * 86400
    events = []
    if not LOG_PATH.exists():
        return events
    for line in LOG_PATH.read_text(errors='ignore').splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
            ts = event.get('server_received_epoch', 0)
            if ts >= cutoff:
                events.append(event)
        except Exception:
            continue
    return events


def summarize(days=7):
    events = load_events(days)
    by_target = {}
    by_operator = {}
    for e in events:
        target = ((e.get('target') or {}).get('id')) or 'unknown'
        operator = e.get('operator_label') or 'anonymous-sensor'
        stats = e.get('visible_stats') or {}
        derived = e.get('derived') or {}
        bucket = by_target.setdefault(target, {'target': target, 'captures': 0, 'operators': set(), 'attention': 0, 'latest': None, 'followers': None, 'subscribers': None, 'views': 0, 'interactions': 0})
        bucket['captures'] += 1
        bucket['operators'].add(operator)
        bucket['attention'] += int(derived.get('attention') or 0)
        bucket['views'] += int(stats.get('views') or 0)
        bucket['interactions'] += int(derived.get('interactions') or 0)
        for key in ['followers', 'subscribers']:
            if stats.get(key) is not None:
                bucket[key] = max(bucket[key] or 0, int(stats[key]))
        bucket['latest'] = max(bucket['latest'] or '', e.get('server_received_at') or '')
        by_operator[operator] = by_operator.get(operator, 0) + 1
    public_targets = []
    for bucket in by_target.values():
        bucket['operators'] = len(bucket['operators'])
        public_targets.append(bucket)
    public_targets.sort(key=lambda x: x['attention'], reverse=True)
    return {'schema_version': 'attention-sensor-summary-v1', 'generated_at': now_iso(), 'window_days': days, 'events': len(events), 'targets': public_targets, 'operators': by_operator}


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, payload, content_type='application/json'):
        body = json.dumps(payload, indent=2).encode() if isinstance(payload, (dict, list)) else payload
        self.send_response(status)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(204, b'', 'text/plain')

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ['/healthz', '/api/sensor/healthz']:
            self._send(200, {'ok': True, 'time': now_iso()})
        elif path in ['/summary.json', '/api/sensor/summary.json']:
            self._send(200, summarize())
        else:
            self._send(404, {'error': 'not_found'})

    def do_POST(self):
        path = urlparse(self.path).path
        if path not in ['/', '/api/sensor']:
            self._send(404, {'error': 'not_found'})
            return
        length = int(self.headers.get('content-length') or '0')
        if length <= 0 or length > MAX_BODY:
            self._send(413, {'error': 'invalid_body_size'})
            return
        try:
            event = json.loads(self.rfile.read(length).decode('utf-8'))
        except Exception:
            self._send(400, {'error': 'invalid_json'})
            return
        if event.get('schema_version') != ALLOWED_SCHEMA:
            self._send(422, {'error': 'invalid_schema'})
            return
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        event['server_received_at'] = now_iso()
        event['server_received_epoch'] = time.time()
        event['receipt_id'] = event.get('receipt_id') or str(uuid.uuid4())
        with LOG_PATH.open('a') as f:
            f.write(json.dumps(event, separators=(',', ':')) + '\n')
        self._send(202, {'ok': True, 'receipt_id': event['receipt_id']})

    def log_message(self, fmt, *args):
        print('%s - %s' % (self.address_string(), fmt % args), flush=True)


def main():
    port = int(os.environ.get('PORT', '4197'))
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    print(f'attention collector listening on 127.0.0.1:{port}', flush=True)
    server.serve_forever()

if __name__ == '__main__':
    main()
