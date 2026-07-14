#!/usr/bin/env python3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
import calendar
from email.message import EmailMessage
import json
import os
import re
import smtplib
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid

DATA_DIR = Path(os.environ.get('METASPN_EMAIL_DATA_DIR', '/var/lib/metaspn-email-capture'))
SUBSCRIBERS_PATH = DATA_DIR / 'subscribers.json'
SEND_LOG_PATH = DATA_DIR / 'email-send-log.jsonl'
MAX_BODY = 50_000
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
BASE_URL = os.environ.get('METASPN_EMAIL_BASE_URL', 'https://inbound.metaspn.network')
SCHEDULER_INTERVAL_SECONDS = int(os.environ.get('METASPN_EMAIL_SCHEDULER_INTERVAL_SECONDS', '900'))

SEQUENCE = [
    {
        'id': 'T0',
        'day_offset': 0,
        'subject': 'Your September Attention Camera is a receipt machine',
        'body': '''You signed up for the September Attention Camera sequence.

The short version: captures are dated receipts of public attention. A browser saw a public tweet/profile/page, recorded the visible context, and kept a bounded observation.

Use captures for three things:
1. prove what you actually saw,
2. submit public receipts to endpoints that want the data,
3. help measure mindshare without pretending we have private analytics.

Install/update the extension:
https://github.com/leo-guinan/september-attention-camera/releases/latest

Official inbound endpoint:
https://inbound.metaspn.network/api/sensor

No seed phrases. No private keys. Wallet address only if an endpoint asks where to credit you.
'''
    },
    {
        'id': 'T1',
        'day_offset': 1,
        'subject': 'What counts as a useful capture',
        'body': '''A useful capture is not everything your browser touched. It is a bounded observation with context.

Strong receipts usually include:
- a tweet/status URL or profile URL,
- visible engagement/audience numbers,
- timestamp,
- operator label,
- optional wallet address for credit,
- coverage caveats: visible DOM only, private analytics missing.

Weak receipts are still allowed. They just should not be over-scored.

A scroll receipt is not a corpus. Marvin insisted on that sentence. Annoyingly, he is right.
'''
    },
    {
        'id': 'T2',
        'day_offset': 3,
        'subject': 'How capture rewards should work',
        'body': '''MetaSPN inbound is data infrastructure, not the rewards authority.

The clean model:
- users submit receipts to inbound,
- inbound stores and relays eligible data,
- downstream endpoints decide their own filters and rewards,
- downstream endpoints return credit/reward claims,
- MetaSPN records those claims without pretending to own the money.

This avoids one central scoreboard becoming a casino cashier with worse fonts.
'''
    },
    {
        'id': 'T3',
        'day_offset': 7,
        'subject': 'How to run your own reward endpoint',
        'body': '''A downstream reward endpoint can register with inbound.

It should expose:
- GET /api/sensor/ping
- GET /api/sensor/policy.json
- POST /api/sensor

Register with:
POST https://inbound.metaspn.network/api/sensor/endpoints/register

Inbound requires public HTTPS and rejects private/localhost targets. This is not moral virtue. It is SSRF not being invited to dinner.
'''
    },
    {
        'id': 'T4',
        'day_offset': 14,
        'subject': 'How we evaluate mindshare before September',
        'body': '''Mindshare is not one number.

We look for breadth and propagation:
- distinct operators capturing the same idea,
- distinct tweets/pages/surfaces,
- independent duplicate validation,
- visible public engagement,
- cross-network movement,
- time persistence.

The system should reward communication that expands through the network, not one person refreshing the same tweet until the dashboard gives up and calls it growth.
'''
    },
    {
        'id': 'T5',
        'day_offset': 21,
        'subject': 'September reveal: what the receipts are for',
        'body': '''At the September event, receipts can be revealed, audited, and compared.

The point is not to crown whoever shouts loudest. The point is to see which ideas travelled, through whom, and with what independent evidence.

Bring receipts. Preferably real ones.

Inbound:
https://inbound.metaspn.network/
Receipt repo:
https://github.com/leo-guinan/september-attention-receipts
'''
    },
]


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
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def append_jsonl(path, payload):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with path.open('a') as f:
        f.write(json.dumps(payload, separators=(',', ':')) + '\n')


def transport_status():
    if os.environ.get('RESEND_API_KEY'):
        return {'configured': True, 'type': 'resend'}
    if os.environ.get('SMTP_HOST'):
        return {'configured': True, 'type': 'smtp', 'host': os.environ.get('SMTP_HOST')}
    sendmail = os.environ.get('SENDMAIL_PATH') or '/usr/sbin/sendmail'
    if Path(sendmail).exists() and os.access(sendmail, os.X_OK):
        return {'configured': True, 'type': 'sendmail', 'path': sendmail}
    return {'configured': False, 'type': 'none', 'error': 'not_configured'}


def from_header():
    from_email = os.environ.get('METASPN_EMAIL_FROM') or os.environ.get('GUIDE_EMAIL_FROM') or 'receipts@metaspn.network'
    from_name = os.environ.get('METASPN_EMAIL_FROM_NAME', 'MetaSPN Receipts')
    if '<' in from_email:
        return from_email
    return f'{from_name} <{from_email}>'


def reply_to_header():
    return os.environ.get('METASPN_EMAIL_REPLY_TO') or os.environ.get('GUIDE_EMAIL_REPLY_TO') or None


def load_subscribers():
    return read_json(SUBSCRIBERS_PATH, {'schema_version': 'metaspn-email-subscribers-v1', 'subscribers': {}})


def save_subscribers(payload):
    payload['updated_at'] = now_iso()
    write_json(SUBSCRIBERS_PATH, payload)


def sequence_schedule(start_epoch):
    out = []
    for msg in SEQUENCE:
        due_epoch = start_epoch + msg['day_offset'] * 86400
        out.append({
            'id': msg['id'],
            'subject': msg['subject'],
            'day_offset': msg['day_offset'],
            'due_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(due_epoch)),
            'sent_at': None,
            'status': 'scheduled'
        })
    return out


def render_body(template, subscriber):
    return template + f"\n\n---\nYou are receiving this because {subscriber['email']} signed up at {BASE_URL}.\n"


def send_email(to_email, subject, body):
    status = transport_status()
    if not status['configured']:
        return False, status['error']
    if status['type'] == 'resend':
        payload = {
            'from': from_header(),
            'to': [to_email],
            'subject': subject,
            'text': body,
        }
        reply_to = reply_to_header()
        if reply_to:
            payload['reply_to'] = reply_to
        req = urllib.request.Request(
            'https://api.resend.com/emails',
            data=json.dumps(payload).encode(),
            headers={
                'authorization': f"Bearer {os.environ['RESEND_API_KEY']}",
                'content-type': 'application/json',
                'accept': 'application/json',
                'user-agent': 'MetaSPN-Email-Capture/1.0',
            },
            method='POST'
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as res:
                response = json.loads(res.read().decode() or '{}')
            return True, response.get('id') or ''
        except urllib.error.HTTPError as exc:
            body_text = exc.read(2000).decode(errors='replace')
            try:
                error_payload = json.loads(body_text)
                return False, error_payload.get('message') or error_payload.get('error') or body_text
            except Exception:
                return False, body_text
        except Exception as exc:
            return False, str(exc)
    msg = EmailMessage()
    msg['From'] = from_header()
    msg['To'] = to_email
    msg['Subject'] = subject
    reply_to = reply_to_header()
    if reply_to:
        msg['Reply-To'] = reply_to
    msg.set_content(body)
    if status['type'] == 'smtp':
        port = int(os.environ.get('SMTP_PORT', '587'))
        username = os.environ.get('SMTP_USERNAME')
        password = os.environ.get('SMTP_PASSWORD')
        with smtplib.SMTP(os.environ['SMTP_HOST'], port, timeout=15) as smtp:
            if os.environ.get('SMTP_STARTTLS', '1') != '0':
                smtp.starttls()
            if username and password:
                smtp.login(username, password)
            smtp.send_message(msg)
        return True, ''
    proc = subprocess.run([status['path'], '-t', '-oi'], input=msg.as_bytes(), capture_output=True, timeout=15)
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout).decode(errors='replace')[:1000]
    return True, ''


def attempt_due_sends(subscriber):
    sent = 0
    queued = 0
    now = time.time()
    by_id = {m['id']: m for m in SEQUENCE}
    for item in subscriber['sequence']:
        if item.get('sent_at'):
            continue
        due_struct = time.strptime(item['due_at'], '%Y-%m-%dT%H:%M:%SZ')
        due_epoch = calendar.timegm(due_struct)
        if due_epoch > now:
            queued += 1
            continue
        msg = by_id[item['id']]
        ok, delivery_detail = send_email(subscriber['email'], msg['subject'], render_body(msg['body'], subscriber))
        if ok:
            item['sent_at'] = now_iso()
            item['status'] = 'sent'
            item['provider_message_id'] = delivery_detail or None
            sent += 1
        else:
            item['status'] = 'queued_transport_missing' if delivery_detail == 'not_configured' else 'send_failed'
            item['last_error'] = delivery_detail
            queued += 1
        append_jsonl(SEND_LOG_PATH, {
            'created_at': now_iso(),
            'email_hash': subscriber['email_hash'],
            'message_id': item['id'],
            'sent': ok,
            'provider_message_id': delivery_detail if ok else None,
            'error': None if ok else delivery_detail,
        })
    return sent, queued


def email_hash(email):
    import hashlib
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


def subscribe(payload):
    email = str(payload.get('email') or '').strip().lower()
    if not EMAIL_RE.match(email):
        return None, 'invalid_email'
    name = str(payload.get('name') or '').strip()[:120]
    role = str(payload.get('role') or payload.get('interest') or '').strip()[:300]
    wallet = str(payload.get('quai_wallet') or '').strip()[:160]
    store = load_subscribers()
    subs = store.setdefault('subscribers', {})
    key = email_hash(email)
    created = key not in subs
    if created:
        start_epoch = time.time()
        subs[key] = {
            'subscriber_id': str(uuid.uuid4()),
            'email_hash': key,
            'email': email,
            'name': name,
            'role': role,
            'quai_wallet': wallet,
            'created_at': now_iso(),
            'created_epoch': start_epoch,
            'source': payload.get('source') or 'inbound_capture_page',
            'sequence': sequence_schedule(start_epoch),
        }
    else:
        subs[key]['updated_at'] = now_iso()
        subs[key]['name'] = name or subs[key].get('name', '')
        subs[key]['role'] = role or subs[key].get('role', '')
        subs[key]['quai_wallet'] = wallet or subs[key].get('quai_wallet', '')
    sent, queued = attempt_due_sends(subs[key])
    save_subscribers(store)
    public = dict(subs[key])
    public.pop('email', None)
    return {'created': created, 'subscriber': public, 'sent_count': sent, 'queued_count': queued, 'email_transport': transport_status()}, ''


def process_due_subscribers():
    store = load_subscribers()
    changed = False
    sent = 0
    queued = 0
    for subscriber in store.get('subscribers', {}).values():
        before = json.dumps(subscriber.get('sequence', []), sort_keys=True)
        sub_sent, sub_queued = attempt_due_sends(subscriber)
        sent += sub_sent
        queued += sub_queued
        after = json.dumps(subscriber.get('sequence', []), sort_keys=True)
        if before != after:
            changed = True
    if changed:
        save_subscribers(store)
    return {'sent_count': sent, 'queued_count': queued, 'subscriber_count': len(store.get('subscribers', {}))}


def scheduler_loop():
    while True:
        try:
            process_due_subscribers()
        except Exception as exc:
            append_jsonl(SEND_LOG_PATH, {'created_at': now_iso(), 'scheduler_error': str(exc)})
        time.sleep(SCHEDULER_INTERVAL_SECONDS)


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, payload):
        body = json.dumps(payload, indent=2).encode()
        self.send_response(status)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get('content-length') or '0')
        if length <= 0 or length > MAX_BODY:
            return None, 'invalid_body_size'
        try:
            return json.loads(self.rfile.read(length).decode()), ''
        except Exception:
            return None, 'invalid_json'

    def do_OPTIONS(self):
        self._send(204, {})

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ['/healthz', '/api/email/healthz']:
            store = load_subscribers()
            self._send(200, {'ok': True, 'schema_version': 'metaspn-email-capture-health-v1', 'subscribers': len(store.get('subscribers', {})), 'email_transport': transport_status(), 'time': now_iso()})
        elif path in ['/sequence.json', '/api/email/sequence.json']:
            self._send(200, {'schema_version': 'metaspn-email-sequence-v1', 'messages': [{k: m[k] for k in ['id', 'day_offset', 'subject']} for m in SEQUENCE]})
        else:
            self._send(404, {'error': 'not_found'})

    def do_POST(self):
        path = urlparse(self.path).path
        if path not in ['/signup', '/api/email/signup']:
            self._send(404, {'error': 'not_found'})
            return
        payload, error = self._read_json()
        if error:
            self._send(413 if error == 'invalid_body_size' else 400, {'error': error})
            return
        result, error = subscribe(payload)
        if error:
            self._send(422, {'ok': False, 'error': error})
            return
        response = {'ok': True}
        response.update(result or {})
        self._send(201, response)

    def log_message(self, format, *args):
        print('%s - %s' % (self.address_string(), format % args), flush=True)


def main():
    port = int(os.environ.get('PORT', '4198'))
    if os.environ.get('METASPN_EMAIL_DISABLE_SCHEDULER') != '1':
        threading.Thread(target=scheduler_loop, daemon=True).start()
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    print(f'email capture listening on 127.0.0.1:{port}', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
