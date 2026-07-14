#!/usr/bin/env python3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
import ipaddress
import json
import os
import re
import socket
import time
import urllib.error
import urllib.request
import uuid

DATA_DIR = Path(os.environ.get('ATTENTION_SENSOR_DATA_DIR', '/var/lib/metaspn-guide-sensor'))
LOG_PATH = DATA_DIR / 'sensor-receipts.jsonl'
SEEN_TWEETS_PATH = DATA_DIR / 'seen-tweets.json'
BOUNTY_QUEUE_PATH = DATA_DIR / 'quai-bounty-queue.jsonl'
VALIDATION_QUEUE_PATH = DATA_DIR / 'duplicate-validation-queue.jsonl'
DOWNSTREAM_ENDPOINTS_PATH = DATA_DIR / 'downstream-endpoints.json'
RELAY_LOG_PATH = DATA_DIR / 'relay-results.jsonl'
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


def append_jsonl(path, payload):
    with path.open('a') as f:
        f.write(json.dumps(payload, separators=(',', ':')) + '\n')


def load_jsonl(path):
    if not path.exists():
        return []
    out = []
    for line in path.read_text(errors='ignore').splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def normalize_tweet_ids(event):
    ids = set()
    candidates = [event.get('page_url') or '']
    candidates.extend(str(x) for x in event.get('tweet_ids') or [])
    for key in ['status_urls', 'quoted_status_urls']:
        candidates.extend(str(x) for x in ((event.get('dom_features') or {}).get(key) or []))
    text = '\n'.join(candidates)
    for match in re.finditer(r'(?:x\.com|twitter\.com)/[^\s/?#]+/status/(\d{5,25})', text, re.I):
        ids.add(match.group(1))
    explicit_ids = {str(x) for x in event.get('tweet_ids') or []}
    for match in re.finditer(r'(?<!\d)(\d{5,25})(?!\d)', text):
        if str(match.group(1)) in explicit_ids:
            ids.add(match.group(1))
    return sorted(ids)


def endpoint_policy():
    return {
        'schema_version': 'attention-endpoint-policy-v2',
        'name': 'MetaSPN inbound',
        'endpoint': 'https://inbound.metaspn.network/api/sensor',
        'status': 'online',
        'role': 'data_router',
        'description': 'MetaSPN captures receipts, stores a local ledger, and relays eligible receipt data to registered downstream endpoints. Downstream endpoints handle their own rewards and money.',
        'accepts_schema_versions': [ALLOWED_SCHEMA],
        'registration': {
            'url': 'https://inbound.metaspn.network/api/sensor/endpoints/register',
            'requires_https_public_host': True,
            'requires_ping_or_policy': False,
            'ssrf_private_ip_rejection': True,
        },
        'relay': {
            'mode': 'fanout_to_registered_endpoints',
            'result_logging': True,
            'reward_claim_capture': True,
        },
        'local_compatibility_ledger': {
            'first_seen_tweet_quai': BOUNTY_QUAI_PER_NEW_TWEET,
            'duplicate_status': 'validation_pending',
            'payment_mode': 'manual_queue_no_hot_wallet',
            'note': 'Compatibility ledger only. MetaSPN is data, not the rewards authority.'
        },
        'filters': {
            'synthetic_smoke_relay': False,
            'accepted_targets': ['hitchhiker', 'psyop', 'rivalvoices', 'vatstack', 'unknown']
        },
        'generated_at': now_iso()
    }


def load_downstream_endpoints():
    payload = read_json(DOWNSTREAM_ENDPOINTS_PATH, {'schema_version': 'attention-downstream-registry-v1', 'endpoints': []})
    endpoints = payload.get('endpoints') if isinstance(payload, dict) else []
    return [e for e in endpoints if isinstance(e, dict)]


def save_downstream_endpoints(endpoints):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    write_json(DOWNSTREAM_ENDPOINTS_PATH, {
        'schema_version': 'attention-downstream-registry-v1',
        'updated_at': now_iso(),
        'endpoints': endpoints
    })


def host_resolves_public(hostname):
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        return False, f'dns_failed:{exc}'
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            return False, f'non_public_ip:{ip}'
    return True, ''


def normalize_downstream_endpoint(payload):
    endpoint = payload.get('endpoint') or payload.get('url') if isinstance(payload, dict) else None
    if not endpoint:
        return None, 'missing_endpoint'
    endpoint = str(endpoint).strip().rstrip('/')
    parsed = urlparse(endpoint)
    if parsed.scheme != 'https':
        # Local tests may opt into http loopback with explicit env flag.
        if not (os.environ.get('ALLOW_LOCAL_DOWNSTREAM') == '1' and parsed.scheme == 'http' and parsed.hostname in {'127.0.0.1', 'localhost'}):
            return None, 'https_required'
    if not parsed.hostname:
        return None, 'missing_hostname'
    if parsed.scheme == 'https':
        ok, reason = host_resolves_public(parsed.hostname)
        if not ok:
            return None, reason
    filters = payload.get('filters') if isinstance(payload.get('filters'), dict) else {}
    normalized = {
        'id': payload.get('id') or str(uuid.uuid5(uuid.NAMESPACE_URL, endpoint)),
        'name': str(payload.get('name') or parsed.hostname),
        'endpoint': endpoint,
        'enabled': payload.get('enabled', True) is not False,
        'reward_policy_url': str(payload.get('reward_policy_url') or '').strip() or None,
        'reward_hint': str(payload.get('reward_hint') or payload.get('rewardHint') or '').strip(),
        'filters': {
            'targetIds': [str(x) for x in filters.get('targetIds', []) if x],
            'urlPatterns': [str(x) for x in filters.get('urlPatterns', []) if x],
        },
        'registered_at': payload.get('registered_at') or now_iso(),
        'last_ping': None,
    }
    return normalized, ''


def register_downstream_endpoint(payload):
    endpoint, error = normalize_downstream_endpoint(payload)
    if error:
        return None, error
    endpoints = load_downstream_endpoints()
    replaced = False
    for i, existing in enumerate(endpoints):
        if existing.get('endpoint') == endpoint['endpoint'] or existing.get('id') == endpoint['id']:
            endpoint['registered_at'] = existing.get('registered_at') or endpoint['registered_at']
            endpoints[i] = endpoint
            replaced = True
            break
    if not replaced:
        endpoints.append(endpoint)
    save_downstream_endpoints(endpoints)
    return endpoint, ''


def endpoint_matches(endpoint, event):
    filters = endpoint.get('filters') or {}
    target_ids = filters.get('targetIds') or []
    url_patterns = filters.get('urlPatterns') or []
    if target_ids and ((event.get('target') or {}).get('id') not in target_ids):
        return False
    if url_patterns:
        page_url = event.get('page_url') or ''
        matched = False
        for pattern in url_patterns:
            try:
                if re.search(pattern, page_url):
                    matched = True
                    break
            except re.error:
                if pattern in page_url:
                    matched = True
                    break
        if not matched:
            return False
    return True


def forward_to_endpoint(endpoint, event):
    payload = dict(event)
    payload['relayed_by'] = 'https://inbound.metaspn.network/api/sensor'
    payload['relayed_at'] = now_iso()
    started = time.time()
    result = {
        'schema_version': 'attention-relay-result-v1',
        'created_at': now_iso(),
        'receipt_id': event.get('receipt_id'),
        'endpoint_id': endpoint.get('id'),
        'endpoint': endpoint.get('endpoint'),
        'ok': False,
        'status': None,
        'latency_ms': None,
        'reward_claims': [],
        'error': None,
    }
    try:
        req = urllib.request.Request(
            endpoint['endpoint'],
            data=json.dumps(payload).encode(),
            headers={'content-type': 'application/json', 'user-agent': 'MetaSPN-Attention-Relay/1.0'},
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=8) as res:
            body = res.read(100_000).decode(errors='replace')
            result['status'] = res.status
            result['ok'] = 200 <= res.status < 300
            try:
                response = json.loads(body) if body else {}
            except Exception:
                response = {'raw': body[:2000]}
            result['response'] = response
            claims = response.get('reward_claims') or response.get('rewards') or response.get('credits') or []
            if isinstance(claims, dict):
                claims = [claims]
            if isinstance(claims, list):
                result['reward_claims'] = claims[:20]
    except urllib.error.HTTPError as exc:
        result['status'] = exc.code
        result['error'] = exc.read(2000).decode(errors='replace')
    except Exception as exc:
        result['error'] = str(exc)
    result['latency_ms'] = round((time.time() - started) * 1000)
    append_jsonl(RELAY_LOG_PATH, result)
    return result


def relay_receipt(event):
    if (event.get('coverage') or {}).get('synthetic_smoke'):
        return {'attempted': 0, 'results': [], 'skipped': 'synthetic_smoke'}
    results = []
    for endpoint in load_downstream_endpoints():
        if endpoint.get('enabled') is False:
            continue
        if not endpoint_matches(endpoint, event):
            continue
        results.append(forward_to_endpoint(endpoint, event))
    return {'attempted': len(results), 'results': results}


def apply_tweet_bounties(event):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if (event.get('coverage') or {}).get('synthetic_smoke'):
        return {'tweet_ids': normalize_tweet_ids(event), 'new_bounties': [], 'duplicate_validations': [], 'seen_count': len(read_json(SEEN_TWEETS_PATH, {}))}
    tweet_ids = normalize_tweet_ids(event)
    seen = read_json(SEEN_TWEETS_PATH, {})
    created = []
    validations = []
    for tweet_id in tweet_ids:
        if tweet_id in seen:
            validation = {
                'schema_version': 'quai-duplicate-validation-v1',
                'created_at': now_iso(),
                'tweet_id': tweet_id,
                'tweet_url': f'https://x.com/i/web/status/{tweet_id}',
                'status': 'validation_pending',
                'possible_future_payment': True,
                'possible_future_quai': None,
                'first_seen_receipt_id': (seen.get(tweet_id) or {}).get('receipt_id'),
                'receipt_id': event.get('receipt_id'),
                'operator_label': event.get('operator_label') or 'anonymous-sensor',
                'payout_address': event.get('quai_payout_address') or None,
                'note': 'Compatibility ledger only. Downstream endpoints own rewards.'
            }
            append_jsonl(VALIDATION_QUEUE_PATH, validation)
            validations.append(validation)
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
            'note': 'Compatibility ledger. Manual payment required; downstream endpoints handle their own rewards.'
        }
        seen[tweet_id] = bounty
        append_jsonl(BOUNTY_QUEUE_PATH, bounty)
        created.append(bounty)
    if tweet_ids:
        write_json(SEEN_TWEETS_PATH, seen)
    return {'tweet_ids': tweet_ids, 'new_bounties': created, 'duplicate_validations': validations, 'seen_count': len(seen)}


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
            if event.get('server_received_epoch', 0) >= cutoff:
                events.append(event)
        except Exception:
            continue
    return events


def load_bounties():
    return load_jsonl(BOUNTY_QUEUE_PATH)


def load_validations():
    return load_jsonl(VALIDATION_QUEUE_PATH)


def load_relay_results():
    return load_jsonl(RELAY_LOG_PATH)


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
    validations = [v for v in load_validations() if v.get('status') == 'validation_pending']
    relay_results = load_relay_results()
    relay_ok = [r for r in relay_results if r.get('ok')]
    reward_claims = [claim for r in relay_results for claim in (r.get('reward_claims') or [])]
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
            'payment_mode': 'manual_queue_no_hot_wallet_compatibility_ledger'
        },
        'duplicate_validations': {
            'pending_count': len(validations),
            'latest': validations[-10:],
            'funding_model': 'downstream_reward_authority',
            'note': 'Duplicates widen validation; downstream endpoints decide rewards.'
        },
        'relay': {
            'registered_endpoints': len(load_downstream_endpoints()),
            'attempts': len(relay_results),
            'successes': len(relay_ok),
            'reward_claims': len(reward_claims),
            'latest': relay_results[-10:]
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

    def _read_json_body(self):
        length = int(self.headers.get('content-length') or '0')
        if length <= 0 or length > MAX_BODY:
            return None, 'invalid_body_size'
        try:
            return json.loads(self.rfile.read(length).decode('utf-8')), ''
        except Exception:
            return None, 'invalid_json'

    def do_OPTIONS(self):
        self._send(204, b'', 'text/plain')

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ['/healthz', '/api/sensor/healthz']:
            self._send(200, {'ok': True, 'time': now_iso()})
        elif path in ['/ping', '/api/sensor/ping']:
            self._send(200, {'ok': True, 'schema_version': 'attention-endpoint-ping-v1', 'policy_url': '/api/sensor/policy.json', 'endpoints_url': '/api/sensor/endpoints.json', 'time': now_iso()})
        elif path in ['/policy.json', '/api/sensor/policy.json']:
            self._send(200, endpoint_policy())
        elif path in ['/endpoints.json', '/api/sensor/endpoints.json']:
            self._send(200, {'schema_version': 'attention-downstream-registry-v1', 'generated_at': now_iso(), 'endpoints': load_downstream_endpoints()})
        elif path in ['/relay-results.json', '/api/sensor/relay-results.json']:
            self._send(200, {'schema_version': 'attention-relay-results-v1', 'generated_at': now_iso(), 'results': load_relay_results()[-200:]})
        elif path in ['/summary.json', '/api/sensor/summary.json']:
            self._send(200, summarize())
        elif path in ['/bounties.json', '/api/sensor/bounties.json']:
            self._send(200, {'schema_version': 'quai-tweet-bounty-list-v1', 'generated_at': now_iso(), 'bounties': load_bounties(), 'duplicate_validations': load_validations()})
        else:
            self._send(404, {'error': 'not_found'})

    def do_POST(self):
        path = urlparse(self.path).path
        if path in ['/endpoints/register', '/api/sensor/endpoints/register']:
            payload, error = self._read_json_body()
            if error:
                self._send(413 if error == 'invalid_body_size' else 400, {'error': error})
                return
            endpoint, error = register_downstream_endpoint(payload)
            if error:
                self._send(422, {'ok': False, 'error': error})
                return
            self._send(201, {'ok': True, 'endpoint': endpoint})
            return
        if path not in ['/', '/api/sensor']:
            self._send(404, {'error': 'not_found'})
            return
        event, error = self._read_json_body()
        if error:
            self._send(413 if error == 'invalid_body_size' else 400, {'error': error})
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
            'duplicate_validation_count': len(bounty_result['duplicate_validations']),
            'amount_quai_per_new_tweet': BOUNTY_QUAI_PER_NEW_TWEET,
            'payment_mode': 'manual_queue_no_hot_wallet_compatibility_ledger'
        }
        relay_result = relay_receipt(event)
        event['relay'] = {'attempted': relay_result.get('attempted', 0)}
        append_jsonl(LOG_PATH, event)
        self._send(202, {'ok': True, 'receipt_id': event['receipt_id'], 'tweet_bounty': event['tweet_bounty'], 'relay': relay_result})

    def log_message(self, fmt, *args):
        print('%s - %s' % (self.address_string(), fmt % args), flush=True)


def main():
    port = int(os.environ.get('PORT', '4197'))
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    print(f'attention collector listening on 127.0.0.1:{port}', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
