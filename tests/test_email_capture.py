import json, os, subprocess, tempfile, time, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def request(method, url, body=None, expect_error=False):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={'content-type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=5) as res:
            return res.status, json.loads(res.read().decode() or '{}')
    except urllib.error.HTTPError as exc:
        if not expect_error:
            raise
        return exc.code, json.loads(exc.read().decode() or '{}')


with tempfile.TemporaryDirectory() as td:
    env = os.environ.copy()
    env['METASPN_EMAIL_DATA_DIR'] = td
    env['PORT'] = '4200'
    env.pop('SMTP_HOST', None)
    env['SENDMAIL_PATH'] = str(Path(td) / 'missing-sendmail')
    env['METASPN_EMAIL_DISABLE_SCHEDULER'] = '1'
    proc = subprocess.Popen(['python3', str(ROOT / 'email/email_capture_service.py')], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                status, _ = request('GET', 'http://127.0.0.1:4200/api/email/healthz')
                if status == 200:
                    break
            except Exception:
                time.sleep(0.1)

        status, health = request('GET', 'http://127.0.0.1:4200/api/email/healthz')
        assert status == 200
        assert health['ok'] is True
        assert health['email_transport']['configured'] is False

        status, sequence = request('GET', 'http://127.0.0.1:4200/api/email/sequence.json')
        assert status == 200
        assert sequence['schema_version'] == 'metaspn-email-sequence-v1'
        assert len(sequence['messages']) == 6
        assert sequence['messages'][0]['day_offset'] == 0

        status, bad = request('POST', 'http://127.0.0.1:4200/api/email/signup', {'email': 'not-an-email'}, expect_error=True)
        assert status == 422
        assert bad['error'] == 'invalid_email'

        payload = {
            'email': 'alice@example.com',
            'name': 'Alice',
            'interest': 'capturing receipts',
            'quai_wallet': '0x0000000000000000000000000000000000000001',
        }
        status, signup = request('POST', 'http://127.0.0.1:4200/api/email/signup', payload)
        assert status == 201
        assert signup['ok'] is True
        assert signup['created'] is True
        assert signup['sent_count'] == 0
        assert signup['queued_count'] >= 1
        assert signup['email_transport']['error'] == 'not_configured'
        assert 'email' not in signup['subscriber']
        assert signup['subscriber']['sequence'][0]['status'] == 'queued_transport_missing'

        status, dup = request('POST', 'http://127.0.0.1:4200/api/email/signup', payload)
        assert status == 201
        assert dup['created'] is False

        store = json.loads((Path(td) / 'subscribers.json').read_text())
        assert len(store['subscribers']) == 1
        log = (Path(td) / 'email-send-log.jsonl').read_text()
        assert 'not_configured' in log
        print('EMAIL_CAPTURE_TEST_OK')
    finally:
        proc.terminate()
        proc.wait(timeout=5)
