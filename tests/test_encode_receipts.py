import json, subprocess, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    raw = td / 'receipts.jsonl'
    bundle = td / 'bundle.json'
    revealed = td / 'revealed.jsonl'
    raw.write_text('{"schema_version":"attention-sensor-v1","target":{"id":"psyop"}}\n')
    enc = subprocess.run(['python3', str(ROOT/'scripts/encode_receipts.py'), 'encode', str(raw), '-o', str(bundle)], text=True, capture_output=True, check=True)
    assert 'COMMITMENT_SHA256' in enc.stderr
    payload = json.loads(bundle.read_text())
    assert payload['schema_version'] == 'attention-camera-bundle-v1'
    dec = subprocess.run(['python3', str(ROOT/'scripts/encode_receipts.py'), 'decode', str(bundle), '-o', str(revealed)], text=True, capture_output=True, check=True)
    assert 'VERIFIED_SHA256' in dec.stderr
    assert revealed.read_text() == raw.read_text()
    print('ENCODE_RECEIPTS_TEST_OK')
