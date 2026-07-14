#!/usr/bin/env python3
"""Encode local attention receipts for September event submission.

This is commit/reveal, not magic privacy.
- The encoded bundle is gzip+base64 so it travels as text.
- The commitment is sha256(raw JSONL bytes). Publish/submit that first if you want a timestamped claim.
- Reveal later by submitting the encoded bundle; judges can decode and verify the hash.
"""
from __future__ import annotations
import argparse, base64, gzip, hashlib, json, sys, time
from pathlib import Path


def encode(path: Path, out: Path | None):
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    payload = {
        'schema_version': 'attention-camera-bundle-v1',
        'created_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'source_file': path.name,
        'raw_sha256': digest,
        'raw_bytes': len(raw),
        'encoding': 'gzip+base64',
        'bundle': base64.b64encode(gzip.compress(raw, mtime=0)).decode('ascii')
    }
    text = json.dumps(payload, indent=2)
    if out:
        out.write_text(text)
    else:
        print(text)
    print(f'COMMITMENT_SHA256 {digest}', file=sys.stderr)
    return digest


def decode(path: Path, out: Path | None):
    payload = json.loads(path.read_text())
    raw = gzip.decompress(base64.b64decode(payload['bundle']))
    digest = hashlib.sha256(raw).hexdigest()
    if digest != payload.get('raw_sha256'):
        raise SystemExit(f'hash mismatch: got {digest}, expected {payload.get("raw_sha256")}')
    if out:
        out.write_bytes(raw)
    else:
        sys.stdout.buffer.write(raw)
    print(f'VERIFIED_SHA256 {digest}', file=sys.stderr)
    return digest


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    enc = sub.add_parser('encode')
    enc.add_argument('jsonl', type=Path)
    enc.add_argument('-o','--out', type=Path)
    dec = sub.add_parser('decode')
    dec.add_argument('bundle', type=Path)
    dec.add_argument('-o','--out', type=Path)
    args = ap.parse_args()
    if args.cmd == 'encode': encode(args.jsonl, args.out)
    else: decode(args.bundle, args.out)

if __name__ == '__main__':
    main()
