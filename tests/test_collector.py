import json, os, subprocess, tempfile, threading, time, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOWNSTREAM_RECEIPTS = []


def request(method, url, body=None, expect_error=False):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={'content-type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=5) as res:
            return res.status, json.loads(res.read().decode() or '{}')
    except urllib.error.HTTPError as exc:
        if not expect_error:
            raise
        try:
            payload = json.loads(exc.read().decode() or '{}')
        except Exception:
            payload = {}
        return exc.code, payload


class DownstreamHandler(BaseHTTPRequestHandler):
    def _send(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('content-type', 'application/json')
        self.send_header('content-length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.endswith('/ping'):
            self._send(200, {'ok': True})
        elif self.path.endswith('/policy.json'):
            self._send(200, {'schema_version': 'attention-endpoint-policy-v1', 'name': 'test downstream'})
        else:
            self._send(404, {'error': 'not_found'})

    def do_POST(self):
        length = int(self.headers.get('content-length') or '0')
        body = json.loads(self.rfile.read(length).decode())
        DOWNSTREAM_RECEIPTS.append(body)
        self._send(202, {
            'ok': True,
            'reward_claims': [{
                'schema_version': 'downstream-reward-claim-v1',
                'type': 'credit',
                'units': 3,
                'note': 'test downstream credit'
            }]
        })

    def log_message(self, format, *args):
        pass


downstream = ThreadingHTTPServer(('127.0.0.1', 4199), DownstreamHandler)
downstream_thread = threading.Thread(target=downstream.serve_forever, daemon=True)
downstream_thread.start()

with tempfile.TemporaryDirectory() as td:
    env = os.environ.copy()
    env['ATTENTION_SENSOR_DATA_DIR'] = td
    env['PORT'] = '4198'
    env['ALLOW_LOCAL_DOWNSTREAM'] = '1'
    proc = subprocess.Popen(['python3', str(ROOT / 'collector/attention_collector.py')], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                status, _ = request('GET', 'http://127.0.0.1:4198/healthz')
                if status == 200:
                    break
            except Exception:
                time.sleep(0.1)

        status, ping = request('GET', 'http://127.0.0.1:4198/api/sensor/ping')
        assert status == 200
        assert ping['ok'] is True
        assert ping['schema_version'] == 'attention-endpoint-ping-v1'
        assert ping['endpoints_url'] == '/api/sensor/endpoints.json'

        status, policy = request('GET', 'http://127.0.0.1:4198/api/sensor/policy.json')
        assert status == 200
        assert policy['schema_version'] == 'attention-endpoint-policy-v2'
        assert policy['role'] == 'data_router'
        assert policy['relay']['mode'] == 'fanout_to_registered_endpoints'

        status, bad = request('POST', 'http://127.0.0.1:4198/api/sensor/endpoints/register', {'name': 'bad', 'endpoint': 'http://127.0.0.1:4199/api/sensor'}, expect_error=True)
        # Local downstream is permitted only because ALLOW_LOCAL_DOWNSTREAM=1 for tests, so reject a real private https target instead.
        status, bad = request('POST', 'http://127.0.0.1:4198/api/sensor/endpoints/register', {'name': 'bad', 'endpoint': 'https://127.0.0.1/api/sensor'}, expect_error=True)
        assert status == 422
        assert bad['error'] in {'non_public_ip:127.0.0.1', 'https_required', 'dns_failed:[Errno 8] nodename nor servname provided, or not known'}

        downstream_endpoint = {
            'name': 'Test downstream',
            'endpoint': 'http://127.0.0.1:4199/api/sensor',
            'enabled': True,
            'reward_hint': 'test credits',
            'filters': {'targetIds': ['psyop'], 'urlPatterns': ['DefenderOfBasic']}
        }
        status, registered = request('POST', 'http://127.0.0.1:4198/api/sensor/endpoints/register', downstream_endpoint)
        assert status == 201
        assert registered['endpoint']['name'] == 'Test downstream'

        status, endpoints = request('GET', 'http://127.0.0.1:4198/api/sensor/endpoints.json')
        assert status == 200
        assert len(endpoints['endpoints']) == 1

        event = {
            'schema_version': 'attention-sensor-v1',
            'page_url': 'https://x.com/DefenderOfBasic/status/1234567890123456789',
            'tweet_ids': ['1234567890123456789'],
            'target': {'id': 'psyop'},
            'visible_stats': {'followers': 123, 'views': 1000},
            'derived': {'attention': 42, 'interactions': 7},
            'operator_label': 'test-sensor',
            'quai_payout_address': '0x0000000000000000000000000000000000000001',
        }
        status, out = request('POST', 'http://127.0.0.1:4198/api/sensor', event)
        assert status == 202 and out['ok']
        assert out['tweet_bounty']['new_bounty_count'] == 1
        assert out['tweet_bounty']['amount_quai_per_new_tweet'] == 1
        assert out['relay']['attempted'] == 1
        assert out['relay']['results'][0]['ok'] is True
        assert out['relay']['results'][0]['reward_claims'][0]['units'] == 3
        assert len(DOWNSTREAM_RECEIPTS) == 1
        assert DOWNSTREAM_RECEIPTS[0]['relayed_by'] == 'https://inbound.metaspn.network/api/sensor'

        status, duplicate = request('POST', 'http://127.0.0.1:4198/api/sensor', event)
        assert status == 202 and duplicate['tweet_bounty']['new_bounty_count'] == 0
        assert duplicate['tweet_bounty']['duplicate_validation_count'] == 1
        assert duplicate['relay']['attempted'] == 1

        status, summary = request('GET', 'http://127.0.0.1:4198/api/sensor/summary.json')
        assert status == 200
        assert summary['events'] == 2
        assert summary['targets'][0]['target'] == 'psyop'
        assert summary['targets'][0]['attention'] == 84
        assert summary['bounties']['queued_count'] == 1
        assert summary['bounties']['payment_mode'] == 'manual_queue_no_hot_wallet_compatibility_ledger'
        assert summary['duplicate_validations']['funding_model'] == 'downstream_reward_authority'
        assert summary['relay']['registered_endpoints'] == 1
        assert summary['relay']['attempts'] == 2
        assert summary['relay']['successes'] == 2
        assert summary['relay']['reward_claims'] == 2

        status, relay = request('GET', 'http://127.0.0.1:4198/api/sensor/relay-results.json')
        assert status == 200
        assert len(relay['results']) == 2

        smoke = dict(event)
        smoke['page_url'] = 'https://x.com/DefenderOfBasic/status/9999999999999999991'
        smoke['tweet_ids'] = ['9999999999999999991']
        smoke['coverage'] = {'synthetic_smoke': True}
        status, smoke_out = request('POST', 'http://127.0.0.1:4198/api/sensor', smoke)
        assert status == 202
        assert smoke_out['tweet_bounty']['new_bounty_count'] == 0
        assert smoke_out['relay']['attempted'] == 0
        print('COLLECTOR_TEST_OK')
    finally:
        proc.terminate()
        proc.wait(timeout=5)
        downstream.shutdown()
