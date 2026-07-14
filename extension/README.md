# MetaSPN Attention Sensor

Unpacked Chrome/Chromium MV3 extension for audience-side attention receipts.

## What it measures

When an opted-in browser views one of the tracked public pages/profiles, the content script captures visible DOM stats:

- X profile/tweet visible counts when rendered (`Followers`, `Likes`, `Reposts`, `Views`, etc.)
- Substack/publication visible subscriber/post/engagement numbers when rendered
- page URL/title, target identity, capture mode, timestamp
- derived attention estimate from visible audience + interaction counts

It sends the receipt to `https://guide.metaspn.network/api/sensor` and keeps a local copy for export.

## Boundary

This is not omniscient scraping. It only records what the browser rendered for the operator. Hidden replies, private analytics, deleted/protected content, and platform API-only metrics are marked missing by design.

## Install

1. Chrome → Extensions → Manage Extensions.
2. Enable Developer Mode.
3. Load unpacked.
4. Select this `extension/` directory.
5. Open Options and set an operator label if desired.

## Tracked targets

- `@hitchhikerglitch` / `hitchhikersguidetothefuture.com`
- `@DefenderOfBasic` / `psyop.report`
- `@nosilverv` / `rivalvoices.substack.com`
- `@TheVatStack` / `thevatstack.substack.com`

## Verify

Run from repo root:

```bash
npm run test:extension
```
