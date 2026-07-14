#!/usr/bin/env python3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
import json, os, re, time, uuid

DATA_DIR = Path(os.environ.get('ATTENTION_SENSOR_DATA_DIR', '/var/lib/metaspn-guide-sensor'))
LOG_PATH = DATA_DIR / 'sensor-receipts.jsonl'
SEEN_TWEETS_PATH = DATA_DIR / 'seen-tweets.json'
BOUNTY_QUEUE_PATH = DATA_DIR / 'quai-bounty-queue.jsonl'
MAX_BODY = 200_000

ALLOWED_SCHEMA = 'attention-sensor-v1'
BOUNTY_QUAI_PER_NEW_TWEET = 1


def now_iso():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def read_json(path, fallback):
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text())
    except Exception:
        return fallback


def write_json(path, payload):
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def normalize_tweet_ids(event):
    ids = set()
    candidates = [event.get('page_url') or '']
    candidates.extend(str(x) for x in event.get('tweet_ids') or [])
    for key in ['status_urls', 'quoted_status_urls']:
        candidates.extend(str(x) for x in ((event.get('dom_features') or {}).get(key) or []))
    text = '\n'.join(candidates)
    for match in re.finditer(r'(?:x\.com|twitter\.com)/[^\s/?#]+/status/(\d{5,25})', text, re.I):
        ids.add(match.group(1))
    for match in re.finditer(r'(?<!\d)(\d{5,25})(?!\d)', text):
        # only accept bare IDs if they came from explicit tweet_ids, not arbitrary visible stats
        if str(match.group(1)) in {str(x) for x in event.get('tweet_ids') or []}:
            ids.add(match.group(1))
    return sorted(ids)


def append_jsonl(path, payload):
    with path.open('a') as f:
        f.write(json.dumps(payload, separators=(',', ':')) + '\n')


def apply_tweet_bounties(event):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if (event.get('coverage') or {}).get('synthetic_smoke'):
        return {'tweet_ids': normalize_tweet_ids(event), 'new_bounties': [], 'seen_count': len(read_json(SEEN_TWEETS_PATH, {}))}
    tweet_ids = normalize_tweet_ids(event)
    seen = read_json(SEEN_TWEETS_PATH, {})
    created = []
    for tweet_id in tweet_ids:
        if tweet_id in seen:
            continue
        bounty = {
            'schema_version': 'quai-tweet-bounty-v1',
            'created_at': now_iso(),
            'tweet_id': tweet_id,
            'tweet_url': f'https://x.com/i/web/status/{tweet_id}',
            'amount_quai': BOUNTY_QUAI_PER_NEW_TWEET,
            'status': 'queued_manual_payment',
            'receipt_id': event.get('receipt_id'),
            'operator_label': event.get('operator_label') or 'anonymous-sensor',
            'payout_address': event.get('quai_payout_address') or None,
            'payment_tx': None,
            'note': 'First-seen tweet. Manual payment required; no hot wallet is configured.'
        }
        seen[tweet_id] = bounty
        append_jsonl(BOUNTY_QUEUE_PATH, bounty)
        created.append(bounty)
    if tweet_ids:
        write_json(SEEN_TWEETS_PATH, seen)
    return {'tweet_ids': tweet_ids, 'new_bounties': created, 'seen_count': len(seen)}


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


def load_bounties():
    if not BOUNTY_QUEUE_PATH.exists():
        return []
    out = []
    for line in BOUNTY_QUEUE_PATH.read_text(errors='ignore').splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def summarize(days=7):
    events = load_events(days)
    by_target = {}
    by_operator = {}
    for e in events:
        target = ((e.get('target') or {}).get('id')) or 'unknown'
        operator = e.get('operator_label') or 'anonymous-sensor'
        stats = e.get('visible_stats') or {}
        derived = e.get('derived') or {}
        bucket = by_target.setdefault(target, {'target': target, 'captures': 0, 'operators': set(), 'attention': 0, 'latest': None, 'followers': None, 'subscribers': None, 'views': 0, 'interactions': 0, 'tweets': set()})
        bucket['captures'] += 1
        bucket['operators'].add(operator)
        bucket['attention'] += int(derived.get('attention') or 0)
        bucket['views'] += int(stats.get('views') or 0)
        bucket['interactions'] += int(derived.get('interactions') or 0)
        for tweet_id in normalize_tweet_ids(e):
            bucket['tweets'].add(tweet_id)
        for key in ['followers', 'subscribers']:
            if stats.get(key) is not None:
                bucket[key] = max(bucket[key] or 0, int(stats[key]))
        bucket['latest'] = max(bucket['latest'] or '', e.get('server_received_at') or '')
        by_operator[operator] = by_operator.get(operator, 0) + 1
    public_targets = []
    for bucket in by_target.values():
        bucket['operators'] = len(bucket['operators'])
        bucket['tweets'] = len(bucket['tweets'])
        public_targets.append(bucket)
    public_targets.sort(key=lambda x: x['attention'], reverse=True)
    bounties = load_bounties()
    queued = [b for b in bounties if b.get('status') == 'queued_manual_payment']
    return {
        'schema_version': 'attention-sensor-summary-v1',
        'generated_at': now_iso(),
        'window_days': days,
        'events': len(events),
        'targets': public_targets,
        'operators': by_operator,
        'bounties': {
            'amount_quai_per_new_tweet': BOUNTY_QUAI_PER_NEW_TWEET,
            'queued_count': len(queued),
            'queued_quai': sum(float(b.get('amount_quai') or 0) for b in queued),
            'latest': queued[-10:],
            'payment_mode': 'manual_queue_no_hot_wallet'
        }
    }


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
        elif path in ['/bounties.json', '/api/sensor/bounties.json']:
            self._send(200, {'schema_version': 'quai-tweet-bounty-list-v1', 'generated_at': now_iso(), 'bounties': load_bounties()})
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
        bounty_result = apply_tweet_bounties(event)
        event['tweet_bounty'] = {
            'tweet_ids': bounty_result['tweet_ids'],
            'new_bounty_count': len(bounty_result['new_bounties']),
            'amount_quai_per_new_tweet': BOUNTY_QUAI_PER_NEW_TWEET,
            'payment_mode': 'manual_queue_no_hot_wallet'
        }
        append_jsonl(LOG_PATH, event)
        self._send(202, {'ok': True, 'receipt_id': event['receipt_id'], 'tweet_bounty': event['tweet_bounty']})

    def log_message(self, fmt, *args):
        print('%s - %s' % (self.address_string(), fmt % args), flush=True)


def main():
    port = int(os.environ.get('PORT', '4197'))
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    print(f'attention collector listening on 127.0.0.1:{port}', flush=True)
    server.serve_forever()

if __name__ == '__main__':
    main()
