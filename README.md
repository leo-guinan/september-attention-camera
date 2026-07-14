# September Attention Camera

A local-first Chrome extension for capturing public attention receipts — a disposable camera for Twitter/X, Substack, and network pages.

People install it, browse public player profiles/pages, and keep receipts of what captured their attention. Later, receipts can be exported, encoded, submitted, and revealed at the September event to see who collected the strongest evidence of memetic influence.

## What it captures

When an opted-in browser views a tracked public surface, the extension records what the browser can see:

- page URL and title
- target player/network
- visible follower/subscriber/post/view/reply/repost/like counts when rendered
- derived attention estimate from visible audience + interactions
- timestamp and capture mode
- coverage caveats: visible DOM only, private analytics missing, hidden replies missing

It is a receipt camera, not a scraper pretending to be God.

## Default players

- `@hitchhikerglitch` / `hitchhikersguidetothefuture.com`
- `@DefenderOfBasic` / `psyop.report`
- `@nosilverv` / `rivalvoices.substack.com`
- `@TheVatStack` / `thevatstack.substack.com`

## Privacy boundary

Default mode is local-only. The extension does not report to a server unless the user explicitly enters a report URL in Options. Users may optionally enter a Quai payout address; it is included in exported/reported receipts so first-seen tweet bounties can be paid manually.

Receipts are stored in Chrome local extension storage and can be exported as JSONL from the popup.

## Install unpacked

1. Download or clone this repo.
2. Open Chrome/Brave → Extensions → Manage Extensions.
3. Enable Developer Mode.
4. Click **Load unpacked**.
5. Select the `extension/` directory.
6. Visit tracked X/Substack/site pages.
7. Open the extension popup to scan/export receipts.

## 1 QUAI first-seen tweet bounty

The MetaSPN inbound endpoint is primarily a data router. It stores receipts and can relay them to downstream endpoints. The legacy compatibility ledger can still queue `1 QUAI` for first-seen tweet IDs, but downstream endpoints handle their own rewards and money.

If you want to be paid, add an optional Quai payout address in extension Options before exporting/reporting receipts.

Official live credit endpoint:

```text
https://inbound.metaspn.network/api/sensor
```

Use the “Use official inbound endpoint” button in extension Options after DNS/TLS is live.


## Inbound relay and downstream reward endpoints

Preferred flow: the extension submits receipts to MetaSPN inbound, then inbound beams accepted data to registered downstream endpoints. Downstream endpoints publish their own policies and handle their own rewards. MetaSPN is data, not the rewards authority.

Each endpoint can publish:

- `GET /api/sensor/ping` — online/readiness check
- `GET /api/sensor/policy.json` — accepted schema versions, reward rules, filters, and payment mode
- `POST /api/sensor` — receipt intake

Extension endpoint config example:

```json
[
  {
    "name": "MetaSPN inbound",
    "url": "https://inbound.metaspn.network/api/sensor",
    "enabled": true,
    "rewardHint": "MetaSPN data router; downstreams own rewards",
    "filters": {"targetIds": [], "urlPatterns": []}
  }
]
```

Filters are routing hints only. Endpoint servers decide credit, dedupe, rewards, and rejection. Inbound also exposes `POST /api/sensor/endpoints/register` so downstream reward endpoints can register to receive relayed receipt data.


## Email capture sequence

Inbound also exposes a receipt-operator email sequence:

- `POST https://inbound.metaspn.network/api/email/signup` — captures an email, optional operator label, optional Quai wallet, and interest note.
- `GET https://inbound.metaspn.network/api/email/sequence.json` — public sequence metadata.
- `GET https://inbound.metaspn.network/api/email/healthz` — service and email transport status.

The sequence explains how to use captures, reward capturers, register downstream endpoints, and evaluate mindshare until the September event. If SMTP/sendmail is not configured, signups are stored and sequence messages remain queued; the service does not mark them sent.

## Event submission: commit/reveal

Export receipts from the popup as `metaspn-attention-receipts.jsonl`, then encode:

```bash
python3 scripts/encode_receipts.py encode metaspn-attention-receipts.jsonl -o september-attention-bundle.json
```

The script prints a `COMMITMENT_SHA256`. Submit or timestamp that hash first if you want to prove your camera roll existed before reveal.

At the event, reveal by submitting `september-attention-bundle.json`. Anyone can verify:

```bash
python3 scripts/encode_receipts.py decode september-attention-bundle.json -o revealed-receipts.jsonl
sha256sum revealed-receipts.jsonl
```

## Scoreboard integration

A collector endpoint can ingest receipts at:

```text
POST https://guide.metaspn.network/api/sensor
```

But again: this is opt-in. Set that URL in Options only if you want live scoreboard reporting.

## Verification

```bash
npm test
```

This validates:

- manifest JSON
- JavaScript syntax
- target/stat parser
- local collector behavior

## Known limits

- X/Twitter DOM changes can break visible stat extraction.
- The extension cannot see private account analytics unless the platform renders them to the operator.
- Hidden replies, expanded threads, deleted/protected posts, and images/screenshots are incomplete unless visible on page.
- A receipt is not a comprehensive corpus. It is a bounded observation made by one browser at one time.
