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
                if status == 200: break
            except Exception:
                time.sleep(0.1)
        event = {'schema_version':'attention-sensor-v1','target':{'id':'psyop'},'visible_stats':{'followers':123,'views':1000},'derived':{'attention':42,'interactions':7},'operator_label':'test-sensor'}
        status, out = request('POST', 'http://127.0.0.1:4198/api/sensor', event)
        assert status == 202 and out['ok']
        status, summary = request('GET', 'http://127.0.0.1:4198/api/sensor/summary.json')
        assert status == 200
        assert summary['events'] == 1
        assert summary['targets'][0]['target'] == 'psyop'
        assert summary['targets'][0]['attention'] == 42
        print('COLLECTOR_TEST_OK')
    finally:
        proc.terminate()
        proc.wait(timeout=5)
