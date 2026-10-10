"""Select a declared time window without filling gaps or changing source evidence."""
import argparse
import csv
import json
from pathlib import Path
from app.cli.kraken_history import checksum, write_json
from app.ml.research import timestamp


def select_window(manifest_path, start, end, output):
    manifest_path=Path(manifest_path)
    manifest=json.loads(manifest_path.read_text())
    beginning,ending=timestamp(start),timestamp(end)
    if beginning>=ending:
        raise ValueError('Window start must precede end')
    output=Path(output)
    output.mkdir(parents=True,exist_ok=False)
    assets=[]
    for asset in manifest['assets']:
        source=manifest_path.parent/asset['file']
        if checksum(source)!=asset['sha256']:
            raise ValueError('Source checksum changed before window selection')
        target=output/Path(asset['file']).name
        with source.open(newline='',encoding='utf-8') as stream, target.open('x',newline='',encoding='utf-8') as destination:
            reader=csv.DictReader(stream)
            writer=csv.DictWriter(destination,fieldnames=reader.fieldnames,lineterminator='\n')
            writer.writeheader()
            count=0
            for row in reader:
                if beginning<=timestamp(row['timestamp'])<ending:
                    writer.writerow(row); count+=1
        if not count:
            raise ValueError(f'{asset["symbol"]}: no data in declared window')
        assets.append({'symbol':asset['symbol'],'file':target.name,'sha256':checksum(target),'source':asset['source'],
                       'source_manifest':str(manifest_path.resolve()),'source_sha256':asset['sha256'],'rows':count})
    record={'assets':assets,'timeframe':manifest.get('timeframe','1h'),
            'window_start':start,'window_end':end,'source_manifest_sha256':checksum(manifest_path),
            'limitations':['Window selection preserves missing intervals; research validation must still pass.']}
    write_json(output/'manifest.json',record)
    return output/'manifest.json'


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest'); parser.add_argument('--start',required=True)
    parser.add_argument('--end',required=True); parser.add_argument('--output',required=True)
    args=parser.parse_args()
    print(select_window(args.manifest,args.start,args.end,args.output))
