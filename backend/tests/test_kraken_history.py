import io
import json
import zipfile

import pytest

from app.cli.kraken_history import checksum, convert_archive, convert_rows


def row(stamp=1704067200, values='100,102,99,101,20,3'):
    return f'{stamp},{values}\n'


def test_converter_preserves_gaps_and_original_numeric_precision():
    target = io.StringIO()
    stats = convert_rows(io.StringIO(row() + row(1704074400)), target, 60)
    assert stats['missing_intervals'] == 1 and stats['synthetic_candles'] == 0
    assert stats['rows'] == 2 and '+00:00' in target.getvalue()
    assert len(target.getvalue().splitlines()) == 3


@pytest.mark.parametrize('source', [row()+row(), row(1704067201), row(values='nan,102,99,101,20,3'),
    row(values='100,98,99,101,20,3'), row(values='100,102,99,101,-1,3'),
    row(values='100,102,99,101,20,0'), 'timestamp,open,high,low,close,volume,trades\n'])
def test_rejects_invalid_data(source):
    with pytest.raises(ValueError):
        convert_rows(io.StringIO(source), io.StringIO(), 60)


def make_archive(tmp_path, content=None):
    path = tmp_path / 'data.zip'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('nested/MANIFEST.json', '{"origin":"test fixture"}')
        archive.writestr('nested/XXBTZEUR_60.csv', content or row())
    return path


def test_verified_archive_preserves_originals_and_research_manifest(tmp_path):
    archive = make_archive(tmp_path)
    output = tmp_path/'converted'
    result = convert_archive(archive, checksum(archive), {'BTC/EUR':'nested/XXBTZEUR_60.csv'}, output)
    assert result['assets'][0]['sha256'] == checksum(output/'BTC-EUR-60.csv')
    assert (output/'BTC-EUR-60-original.csv').read_text() == row()
    assert json.loads((output/'manifest.json').read_text())['timeframe'] == '1h'
    from app.ml.research import load_dataset
    data, _ = load_dataset(output/'manifest.json')
    assert len(data['BTC/EUR']) == 1
    with pytest.raises(ValueError, match='new output'):
        convert_archive(archive, checksum(archive), {'BTC/EUR':'nested/XXBTZEUR_60.csv'}, output)


def test_checksum_or_interval_mismatch_publishes_nothing(tmp_path):
    archive = make_archive(tmp_path)
    output = tmp_path/'output'
    with pytest.raises(ValueError, match='SHA256'):
        convert_archive(archive, '0'*64, {'BTC/EUR':'nested/XXBTZEUR_60.csv'}, output)
    assert not output.exists()
    with pytest.raises(ValueError, match='interval'):
        convert_archive(archive, checksum(archive), {'BTC/EUR':'nested/XXBTZEUR_60.csv'}, output, 15)
    assert not output.exists()


def test_failed_conversion_does_not_publish_usable_manifest(tmp_path):
    archive = make_archive(tmp_path, row()+row())
    output = tmp_path/'bad'
    with pytest.raises(ValueError):
        convert_archive(archive, checksum(archive), {'BTC/EUR':'nested/XXBTZEUR_60.csv'}, output)
    assert not (output/'manifest.json').exists()
    assert (output/'FAILED.json').exists()


def test_fifteen_minute_conversion_does_not_fill_missing_intervals():
    stats = convert_rows(io.StringIO(row()+row(1704069000)), io.StringIO(), 15)
    assert stats['missing_intervals'] == 1


def test_whole_archive_verification_handles_outdated_part_list(tmp_path,monkeypatch):
    from app.cli import kraken_archive
    import hashlib
    parts=[f'part{i}'.encode() for i in range(5)]
    for i,part in enumerate(parts):
        (tmp_path/f'Kraken_OHLCVT_Full_2026Q2.zip.part{i:02}').write_bytes(part)
    (tmp_path/'OHLCVT_Full_PARTS_SHA256SUMS.txt').write_text('\n'.join(
        f'{"0"*64}  Kraken_OHLCVT_Full.zip.part{i:02}' for i in range(5)))
    monkeypatch.setattr(kraken_archive,'FULL_2026Q2_SHA256',hashlib.sha256(b''.join(parts)).hexdigest())
    output=kraken_archive.assemble(tmp_path)
    assert output.read_bytes()==b''.join(parts)
    record=json.loads((tmp_path/'verified-archive.json').read_text())
    assert not any(item['matches'] for item in record['part_checks'])
    assert record['verification_basis']=='Published whole-archive SHA256 (mandatory)'


def test_wrong_whole_archive_hash_is_never_published(tmp_path,monkeypatch):
    from app.cli import kraken_archive
    import hashlib
    for i in range(5):
        (tmp_path/f'Kraken_OHLCVT_Full_2026Q2.zip.part{i:02}').write_bytes(b'x')
    (tmp_path/'OHLCVT_Full_PARTS_SHA256SUMS.txt').write_text('\n'.join(
        f'{hashlib.sha256(b"x").hexdigest()}  Kraken_OHLCVT_Full.zip.part{i:02}' for i in range(5)))
    with pytest.raises(ValueError,match='Combined archive checksum'):
        kraken_archive.assemble(tmp_path)
    assert not (tmp_path/'Kraken_OHLCVT_Full_2026Q2.zip').exists()
