"""Verify five published Kraken archive parts and assemble without overwriting."""
import argparse
import hashlib
import re
from pathlib import Path
from app.cli.kraken_history import checksum, FULL_2026Q2_SHA256, write_json, SOURCE
from datetime import datetime, timezone


def assemble(directory):
    directory=Path(directory)
    expected={}
    for line in (directory/'OHLCVT_Full_PARTS_SHA256SUMS.txt').read_text().splitlines():
        match=re.fullmatch(r'([a-f0-9]{64})\s+\*?Kraken_OHLCVT_Full(?:_2026Q2)?\.zip\.part(0[0-4])',line.strip())
        if not match or match[2] in expected:
            raise ValueError('Unexpected or duplicate entry in published checksum file')
        expected[match[2]]=match[1]
    if set(expected)!={'00','01','02','03','04'}:
        raise ValueError('All five part checksums are required')
    parts=[]; checks=[]
    for suffix,value in sorted(expected.items()):
        path=directory/f'Kraken_OHLCVT_Full_2026Q2.zip.part{suffix}'
        actual=checksum(path)
        checks.append({'file':path.name,'published_sha256':value,'actual_sha256':actual,'matches':actual==value})
        parts.append(path)
        print(f'Checked part {suffix}: {"matches" if actual==value else "part-list mismatch; whole-archive verification required"}',flush=True)
    output=directory/'Kraken_OHLCVT_Full_2026Q2.zip'
    if output.exists():
        if checksum(output)!=FULL_2026Q2_SHA256:
            raise ValueError('Existing combined archive has a different checksum; preserved for review')
        return output
    temporary=directory/'Kraken_OHLCVT_Full_2026Q2.zip.assembling'
    digest=hashlib.sha256()
    with temporary.open('xb') as target:
        for path in parts:
            with path.open('rb') as source:
                while chunk:=source.read(4*1024*1024):
                    digest.update(chunk); target.write(chunk)
    if digest.hexdigest()!=FULL_2026Q2_SHA256:
        raise ValueError('Combined archive checksum mismatch; incomplete output preserved, not published')
    temporary.rename(output)
    write_json(directory/'verified-archive.json', {
        'source':SOURCE,'sha256':FULL_2026Q2_SHA256,'verified_at':datetime.now(timezone.utc).isoformat(),
        'part_checks':checks,'verification_basis':'Published whole-archive SHA256 (mandatory)',
        'parts':[{ 'file':p.name,'sha256':expected[p.name[-2:]],
                   'url':f'https://assets.kraken.com/marketing/institutions/{p.name}'} for p in parts]})
    return output


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    print(assemble(parser.parse_args().directory))
