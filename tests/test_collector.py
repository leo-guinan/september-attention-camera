import json, os, subprocess, tempfile, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def request(method, url, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={'content-type':'application/json'})
    with urllib.request.urlopen(req, timeout=5) as res:
        return res.status, json.loads(res.read().decode() or '{}')

with tempfile.TemporaryDirectory() as td:
    env = os.environ.copy()
    env['ATTENTION_SENSOR_DATA_DIR'] = td
    env['PORT'] = '4198'
    proc = subprocess.Popen(['python3', str(ROOT/'collector/attention_collector.py')], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                status, _ = request('GET', 'http://127.0.0.1:4198/healthz')
                if status == 200:
                    break
            except Exception:
                time.sleep(0.1)
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

        status, duplicate = request('POST', 'http://127.0.0.1:4198/api/sensor', event)
        assert status == 202 and duplicate['tweet_bounty']['new_bounty_count'] == 0
        assert duplicate['tweet_bounty']['duplicate_validation_count'] == 1

        status, summary = request('GET', 'http://127.0.0.1:4198/api/sensor/summary.json')
        assert status == 200
        assert summary['events'] == 2
        assert summary['targets'][0]['target'] == 'psyop'
        assert summary['targets'][0]['attention'] == 84
        assert summary['targets'][0]['tweets'] == 1
        assert summary['bounties']['queued_count'] == 1
        assert summary['bounties']['queued_quai'] == 1
        assert summary['bounties']['payment_mode'] == 'manual_queue_no_hot_wallet'
        assert summary['duplicate_validations']['pending_count'] == 1
        assert summary['duplicate_validations']['funding_model'] == 'quadratic_validation_pending'

        status, bounties = request('GET', 'http://127.0.0.1:4198/api/sensor/bounties.json')
        assert status == 200
        assert len(bounties['bounties']) == 1
        assert len(bounties['duplicate_validations']) == 1
        assert bounties['bounties'][0]['tweet_id'] == '1234567890123456789'
        assert bounties['bounties'][0]['payout_address'].endswith('0001')
        assert bounties['duplicate_validations'][0]['status'] == 'validation_pending'

        smoke = dict(event)
        smoke['page_url'] = 'https://x.com/DefenderOfBasic/status/9999999999999999991'
        smoke['tweet_ids'] = ['9999999999999999991']
        smoke['coverage'] = {'synthetic_smoke': True}
        status, smoke_out = request('POST', 'http://127.0.0.1:4198/api/sensor', smoke)
        assert status == 202
        assert smoke_out['tweet_bounty']['new_bounty_count'] == 0
        assert smoke_out['tweet_bounty']['duplicate_validation_count'] == 0
        print('COLLECTOR_TEST_OK')
    finally:
        proc.terminate()
        proc.wait(timeout=5)
