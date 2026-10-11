"""Bounded public-only quote/depth collection and past-only observation lookup."""
import asyncio
import math
from datetime import datetime, timezone, timedelta
from statistics import median

from sqlalchemy.exc import IntegrityError
from app.models.portfolio import MarketObservation
from app.services.market_data import utc

MAX_SYMBOLS=30
DEPTH_LEVELS=20
MAX_AGE_SECONDS=30
RETENTION_DAYS=14


def positive(value):
    try:
        value=float(value)
        return value if math.isfinite(value) and value>0 else None
    except (ValueError,TypeError):
        return None


def source_time(value):
    try:
        if isinstance(value,datetime):
            return utc(value)
        if value is not None:
            return datetime.fromtimestamp(float(value)/1000,tz=timezone.utc)
    except (ValueError,TypeError,OverflowError,OSError):
        pass
    return None


def levels(book,side):
    rows=[]
    for row in (book.get(side) or [])[:DEPTH_LEVELS]:
        if not isinstance(row,(list,tuple)) or len(row)<2 or not positive(row[0]) or not positive(row[1]):
            raise ValueError('Invalid order-book level')
        rows.append([float(row[0]),float(row[1])])
    if not rows:
        raise ValueError('Empty order book')
    prices=[row[0] for row in rows]
    if prices!=sorted(prices,reverse=side=='bids') or len(set(prices))!=len(prices):
        raise ValueError('Unordered order book')
    return rows


def depth_probe(rows,side,notional,mid):
    remaining=notional if side=='BUY' else notional/mid
    quantity=cost=0.
    for price,available in rows:
        taken=min(available,remaining/price if side=='BUY' else remaining)
        quantity+=taken; cost+=taken*price
        remaining-=taken*price if side=='BUY' else taken
        if remaining<=1e-9:
            break
    average=cost/quantity if quantity else None
    return {'notional_eur':notional,'complete':remaining<=1e-9,'vwap':average,
            'filled_fraction':min(1.,cost/notional if side=='BUY' else quantity/(notional/mid)),
            'adverse_vs_mid_pct':((average/mid-1)*(1 if side=='BUY' else -1)) if average else None}


def observation(ticker,book,received,errors=None):
    errors=dict(errors or {})
    evidence={'errors':errors,'depth_levels':DEPTH_LEVELS,
              'limitations':['Snapshot liquidity can change before execution; probes are not fills.',
                             'Ticker timestamp is supplied by the adapter and may use a local fallback.']}
    quote_at=book_at=None
    if ticker is not None:
        bid,ask=positive(getattr(ticker,'bid',None)),positive(getattr(ticker,'ask',None))
        quote_at=source_time(getattr(ticker,'timestamp',None))
        if bid and ask and bid<=ask:
            evidence.update(bid=bid,ask=ask,spread_pct=(ask-bid)/((ask+bid)/2),
                            quote_source=str(getattr(ticker,'source','unknown'))[:40])
        else:
            errors['quote']='Invalid/crossed quote'
    if book is not None:
        try:
            if not isinstance(book,dict):
                raise ValueError('Invalid order book')
            bids,asks=levels(book,'bids'),levels(book,'asks')
            if bids[0][0]>asks[0][0]:
                raise ValueError('Crossed order book')
            book_at=source_time(book.get('timestamp'))
            mid=(bids[0][0]+asks[0][0])/2
            evidence.update(bids=bids,asks=asks,book_source=str(book.get('source','rest'))[:40],
                book_spread_pct=(asks[0][0]-bids[0][0])/mid,
                bid_depth_eur=sum(p*q for p,q in bids),ask_depth_eur=sum(p*q for p,q in asks),
                probes={side:[depth_probe(bids if side=='SELL' else asks,side,size,mid)
                              for size in (25.,100.,500.)] for side in ('BUY','SELL')})
        except (ValueError,TypeError,KeyError) as exc:
            errors['book']=str(exc)
    ages=[(received-stamp).total_seconds() for stamp in (quote_at,book_at) if stamp]
    evidence['quote_age_seconds']=(received-quote_at).total_seconds() if quote_at else None
    evidence['book_age_seconds']=(received-book_at).total_seconds() if book_at else None
    if any(age < -5 for age in ages):
        status='INVALID_TIME'
    elif any(age>MAX_AGE_SECONDS for age in ages):
        status='STALE'
    elif errors or not quote_at or not book_at:
        status='PARTIAL' if 'spread_pct' in evidence or 'bids' in evidence else 'FAILED'
    else:
        status='VALID'
    return status,evidence,quote_at,book_at


async def collect_market_observations(db,exchange,symbols,now=None,deadline_seconds=30):
    now=utc(now or datetime.now(timezone.utc))
    bucket=now.replace(minute=now.minute//5*5,second=0,microsecond=0)
    universe=sorted(set(symbols))
    # Rotate batches so large unions cannot permanently starve later symbols.
    batches=max(1,math.ceil(len(universe)/MAX_SYMBOLS))
    offset=(int(bucket.timestamp()/300)%batches)*MAX_SYMBOLS
    selected=universe[offset:offset+MAX_SYMBOLS]
    existing={row[0] for row in db.query(MarketObservation.symbol).filter(
        MarketObservation.exchange=='kraken',MarketObservation.bucket_at==bucket,
        MarketObservation.symbol.in_(selected))}
    pending=[symbol for symbol in selected if symbol not in existing]
    db.commit()  # No database transaction held during network waits.
    semaphore=asyncio.Semaphore(2)
    async def fetch(symbol):
        async with semaphore:
            requested=datetime.now(timezone.utc)
            results=await asyncio.gather(
                asyncio.wait_for(exchange.get_ticker(symbol),timeout=10),
                asyncio.wait_for(exchange.get_order_book(symbol),timeout=10),return_exceptions=True)
            received=datetime.now(timezone.utc)
            errors={name:type(value).__name__ for name,value in zip(('quote','book'),results) if isinstance(value,Exception)}
            ticker,book=[None if isinstance(value,Exception) else value for value in results]
            return requested,received,ticker,book,errors
    tasks={symbol:asyncio.create_task(fetch(symbol)) for symbol in pending}
    if tasks:
        try:
            _,unfinished=await asyncio.wait(tasks.values(),timeout=deadline_seconds)
            for task in unfinished:
                task.cancel()
            await asyncio.gather(*unfinished,return_exceptions=True)
        except BaseException:
            for task in tasks.values():
                task.cancel()
            await asyncio.gather(*tasks.values(),return_exceptions=True)
            raise
    counts={}; persisted=[]
    for symbol,task in tasks.items():
        if task.cancelled():
            requested,received,ticker,book,errors=now,datetime.now(timezone.utc),None,None,{'collection':'Cycle deadline exceeded'}
        elif task.exception():
            requested,received,ticker,book,errors=now,datetime.now(timezone.utc),None,None,{'collection':type(task.exception()).__name__}
        else:
            requested,received,ticker,book,errors=task.result()
        status,evidence,quote_at,book_at=observation(ticker,book,received,errors)
        try:
            with db.begin_nested():
                db.add(MarketObservation(exchange='kraken',symbol=symbol,bucket_at=bucket,
                    requested_at=requested,received_at=received,quote_at=quote_at,book_at=book_at,
                    status=status,evidence=evidence)); db.flush()
            counts[status]=counts.get(status,0)+1; persisted.append(symbol)
        except IntegrityError:
            pass  # Another collector already archived this bucket.
    removed=db.query(MarketObservation).filter(MarketObservation.received_at<now-timedelta(days=RETENTION_DAYS)).delete(synchronize_session=False)
    db.commit()
    return {'persisted':persisted,'already_recorded':sorted(existing),'counts':counts,
            'selected':len(selected),'universe':len(universe),'retention_days':RETENTION_DAYS,'pruned':removed}


def available_observation(db,symbol,decision_at):
    """Never borrow a later snapshot; bucket time is not availability time."""
    decision_at=utc(decision_at)
    rows=db.query(MarketObservation).filter(MarketObservation.symbol==symbol,
        MarketObservation.status=='VALID',MarketObservation.received_at<=decision_at,
        MarketObservation.received_at>=decision_at-timedelta(seconds=MAX_AGE_SECONDS)).order_by(
        MarketObservation.received_at.desc()).all()
    return next((row for row in rows if all(stamp and 0<=(decision_at-utc(stamp)).total_seconds()<=MAX_AGE_SECONDS
                                           for stamp in (row.quote_at,row.book_at))),None)


def observation_summary(db,symbols,now=None):
    now=utc(now or datetime.now(timezone.utc))
    rows=db.query(MarketObservation).filter(MarketObservation.symbol.in_(list(symbols)),
        MarketObservation.received_at>=now-timedelta(days=1),MarketObservation.received_at<=now).order_by(
        MarketObservation.received_at.desc()).limit(5000).all()
    latest={}; counts={}; spreads=[]
    for row in rows:
        counts[row.status]=counts.get(row.status,0)+1
        spread=row.evidence.get('spread_pct')
        if row.status=='VALID' and spread is not None:
            spreads.append(spread)
        if row.symbol not in latest:
            latest[row.symbol]={'status':row.status,'received_at':utc(row.received_at).isoformat(),
                'age_seconds':max(0.,(now-utc(row.received_at)).total_seconds()),
                'spread_pct':spread,'bid_depth_eur':row.evidence.get('bid_depth_eur'),
                'ask_depth_eur':row.evidence.get('ask_depth_eur'),'probes':row.evidence.get('probes'),
                'errors':row.evidence.get('errors')}
    return {'observations':len(rows),'counts':counts,'latest':latest,'retention_days':RETENTION_DAYS,
            'median_valid_spread_pct':median(spreads) if spreads else None,
            'limitations':['Five-minute samples are not continuous execution history.',
                           'Depth is limited to 20 levels; probes exclude fees and do not predict fills.']}
