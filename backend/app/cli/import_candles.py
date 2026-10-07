"""Import completed hourly/daily UTC OHLCV CSV data into the persistent archive."""
import argparse
import csv
from datetime import datetime
from app.db.session import SessionLocal
from app.exchanges.base import OHLCV
from app.exchanges.universe import SUPPORTED_PAIRS
from app.services.market_data import archive, completed_candles, INTERVALS


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file'); parser.add_argument('--symbol',required=True,choices=SUPPORTED_PAIRS)
    parser.add_argument('--timeframe',choices=INTERVALS,default='1h')
    args=parser.parse_args()
    with open(args.file,newline='',encoding='utf-8-sig') as stream:
        rows=[OHLCV(datetime.fromisoformat(row['timestamp'].replace('Z','+00:00')),
            *[float(row[k]) for k in ['open','high','low','close','volume']]) for row in csv.DictReader(stream)]
    if any(row.timestamp.tzinfo is None for row in rows):
        parser.error('Timestamps must include a UTC offset or Z')
    clean=completed_candles(rows,args.timeframe)
    if len(clean)!=len(rows): parser.error('CSV contains duplicate or incomplete candles')
    if any(b.timestamp-a.timestamp!=INTERVALS[args.timeframe] for a,b in zip(clean,clean[1:])):
        parser.error('CSV must be contiguous at the selected timeframe')
    with SessionLocal() as db: archive(db,args.symbol,args.timeframe,clean)
    print(f'Imported {len(clean)} validated candles (existing timestamps preserved).')

if __name__=='__main__': main()
