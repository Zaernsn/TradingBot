"""Offline, checksum-gated Kraken OHLCVT conversion; never touches a trading book.

Keeps missing intervals missing. The hourly research loader intentionally rejects
gapped output until a contiguous evaluation window has been explicitly selected.
"""
import argparse
import csv
import hashlib
import json
import math
import re
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

SOURCE = 'https://support.kraken.com/articles/360047124832-downloadable-historical-ohlcvt-open-high-low-close-volume-trades-data'
FULL_2026Q2_SHA256 = 'fc81b54cba6e12af3e9422dde9416179e6ef76af4831d48d839fbdb43018eaa4'
CONVERTER_VERSION = 1


def checksum(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verified_archive(path, expected):
    if not re.fullmatch(r'[0-9a-fA-F]{64}', expected) or checksum(path) != expected.lower():
        raise ValueError('Archive SHA256 does not match the published checksum')
    return zipfile.ZipFile(path)


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)


def convert_rows(source, target, minutes, now=None):
    if minutes not in (15, 60):
        raise ValueError('Only 15-minute and hourly research exports are supported')
    interval = minutes * 60
    now = (now or datetime.now(timezone.utc)).timestamp()
    writer = csv.writer(target, lineterminator='\n')
    writer.writerow(('timestamp', 'open', 'high', 'low', 'close', 'volume'))
    previous = first = None
    count = gaps = missing = 0
    for line, row in enumerate(csv.reader(source), 1):
        if len(row) != 7:
            raise ValueError(f'Row {line}: expected seven headerless OHLCVT fields')
        stamp = int(row[0])
        trades = int(row[6])
        values = [float(value) for value in row[1:6]]
        opening, high, low, close, volume = values
        if (stamp < 0 or stamp % interval or stamp + interval > now
                or any(not math.isfinite(value) for value in values)
                or min(values[:4]) <= 0 or volume < 0 or trades < 1
                or low > min(opening, close) or high < max(opening, close) or high < low):
            raise ValueError(f'Row {line}: invalid, unaligned or unfinished candle')
        if previous is not None:
            if stamp <= previous:
                raise ValueError(f'Row {line}: duplicate or unordered timestamp')
            absent = (stamp - previous) // interval - 1
            if absent:
                gaps += 1
                missing += absent
        first = stamp if first is None else first
        previous = stamp
        count += 1
        writer.writerow((datetime.fromtimestamp(stamp, timezone.utc).isoformat(), *row[1:6]))
    if not count:
        raise ValueError('Empty historical series')
    return {'rows': count, 'first': datetime.fromtimestamp(first, timezone.utc).isoformat(),
            'last': datetime.fromtimestamp(previous, timezone.utc).isoformat(),
            'gap_count': gaps, 'missing_intervals': missing, 'synthetic_candles': 0}


def convert_archive(archive_path, expected, pairs, output, minutes=60):
    """Map explicit SYMBOL -> member names; never extract arbitrary archive paths."""
    if not pairs or minutes not in (15, 60):
        raise ValueError('Specify pairs and a supported interval')
    output = Path(output)
    if output.exists():
        raise ValueError('Use a new output directory to preserve previous evidence')
    with verified_archive(archive_path, expected) as archive:
        names = archive.namelist()
        manifests = [name for name in names if Path(name).name == 'MANIFEST.json']
        if len(manifests) != 1:
            raise ValueError('Exactly one Kraken MANIFEST.json is required')
        for symbol, member in pairs.items():
            if not re.fullmatch(r'[A-Z0-9]+/EUR', symbol):
                raise ValueError('Only explicit EUR pair names are accepted')
            if names.count(member) != 1 or not member.endswith(f'_{minutes}.csv'):
                raise ValueError(f'{symbol}: ambiguous/missing archive member or wrong interval')
        # Preserve the source manifest bytes, even if the upstream format evolves.
        if archive.getinfo(manifests[0]).file_size > 10_000_000:
            raise ValueError('Unexpectedly large source manifest')
        manifest_bytes = archive.read(manifests[0])
        json.loads(manifest_bytes)
        output.mkdir(parents=True)
        with (output / 'kraken-MANIFEST.json').open('xb') as target:
            target.write(manifest_bytes)
        assets = []
        try:
            for symbol, member in sorted(pairs.items()):
                stem = symbol.replace('/', '-')
                original = output / f'{stem}-{minutes}-original.csv'
                with archive.open(member) as source, original.open('xb') as target:
                    shutil.copyfileobj(source, target, length=1024 * 1024)
                converted = output / f'{stem}-{minutes}.csv'
                with original.open(encoding='utf-8-sig', newline='') as source, converted.open('x', newline='', encoding='utf-8') as target:
                    stats = convert_rows(source, target, minutes)
                assets.append({'symbol': symbol, 'file': converted.name, 'source': SOURCE,
                               'sha256': checksum(converted), 'original_file': original.name,
                               'original_sha256': checksum(original), 'archive_member': member, **stats})
            report = {'assets': assets, 'timeframe': '1h' if minutes == 60 else '15m',
                      'archive_sha256': expected.lower(), 'archive_path': str(Path(archive_path).resolve()),
                      'source': SOURCE, 'verified_at': datetime.now(timezone.utc).isoformat(),
                      'converter_version': CONVERTER_VERSION,
                      'kraken_manifest_sha256': hashlib.sha256(manifest_bytes).hexdigest(),
                      'limitations': ['No-trade intervals remain missing; no fabricated candles.',
                                      'Hourly replay rejects gaps; 15m output is not a live strategy.']}
            # Publish the usable manifest only when every asset has passed validation.
            write_json(output / 'manifest.json', report)
            return report
        except Exception as exc:
            write_json(output / 'FAILED.json', {'error': str(exc), 'usable_dataset': False})
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--sha256', required=True, help='Published archive checksum, not a self-computed trust claim')
    parser.add_argument('--list', action='store_true', help='Verify archive and list EUR CSV members')
    parser.add_argument('--pair', action='append', default=[], help='SYMBOL=exact/member_60.csv (repeatable)')
    parser.add_argument('--minutes', type=int, choices=(15, 60), default=60)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.list:
        with verified_archive(args.archive, args.sha256) as archive:
            print('\n'.join(name for name in archive.namelist() if 'EUR' in name and name.endswith(f'_{args.minutes}.csv')))
        return
    if args.output is None or not args.pair:
        parser.error('--output and at least one --pair are required')
    entries = [item.split('=', 1) for item in args.pair]
    if any(len(item) != 2 for item in entries) or len({item[0] for item in entries}) != len(entries):
        parser.error('Use unique SYMBOL=member pair mappings')
    print(json.dumps(convert_archive(args.archive, args.sha256, dict(entries), args.output, args.minutes), indent=2))


if __name__ == '__main__':
    main()
