from datetime import datetime, timezone, timedelta
from dataclasses import replace
import asyncio
import contextlib
import math
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from app.models.portfolio import Portfolio, Position, BotState, Signal, ExecutionOrder, Trade, RiskConfig
from app.models.user import User
from app.exchanges.paper import PaperExchange
from app.exchanges.base import OrderSide
from app.exchanges.universe import CURATED_PAIRS, is_memecoin, WATCHLIST_LIMIT
from app.services.memecoin_service import LiquidityLimitError, eligible_universe, check_liquidity, memecoin_budget
from app.services.portfolio_service import get_or_create_portfolio, recalculate_equity, update_position_price, get_position
from app.services.trading_service import execute_paper_trade, exit_reason
from app.services.risk_service import get_risk_config, risk_manager_from_config, entry_budget, check_drawdown
from app.services.asset_selector import AssetSelector
from app.services.market_data import load_history, utc
from app.services import execution_lease as lease
from app.services.live_execution import live_exchange, assert_live_enabled, reconcile_all, unresolved, verify_balances, execute_live, TERMINAL
from app.ml.models import SignalModel, apply_buy_threshold
from app.ml.strategies import (
    MomentumModel, FastMomentumModel, AdaptiveMomentumModel,
    AdaptiveParameters, MarketRegime, classify_market_regime, rank_entries,
)
from app.ml.strategy_factory import definition_from_parameters, candidate_factory
from app.services.model_recovery import ModelTrainer
from app.services.momentum_policy import depth_capacity
from app.services.preflight_errors import (
    preflight_error, retryable_preflight_error, retry_delay_seconds,
)

CANARY_MAX_POSITIONS = 2
CANARY_MAX_EXPOSURE_PCT = .25


def canary_entry_budget(portfolio, positions, normal_budget):
    """Apply a portfolio-wide canary ceiling without weakening normal limits."""
    exposure=sum(max(0.,float(position.quantity)*float(position.current_price)) for position in positions)
    remaining=max(0.,max(0.,float(portfolio.equity))*CANARY_MAX_EXPOSURE_PCT-exposure)
    return min(max(0.,float(normal_budget)),remaining)


def with_verified_taker_fee(risk, taker):
    """Use the higher of configured research costs and the live pair fee."""
    try:
        taker=float(taker)
    except (TypeError,ValueError):
        raise ValueError('Kraken returned no usable taker fee')
    if not math.isfinite(taker) or not 0<=taker<1:
        raise ValueError('Kraken returned no usable taker fee')
    return replace(risk,fee_pct=max(risk.fee_pct,taker))


class BotOrchestrator:
    def __init__(self):
        self.scheduler=AsyncIOScheduler()
        self.models={}
        self.selector=AssetSelector()
        self._locks={}
        self.trainer=ModelTrainer(lambda name: SignalModel(name=name, persist=False),
            alternate_factory=lambda name: SignalModel(name=name, persist=False, feature_schema='normalized-v1'))

    def _sync_watchlist_policy(self,db,state,portfolio,risk,held=None):
        """Drop markets disabled by current settings before any network work."""
        saved=list(state.watchlist or [])
        watchlist=[
            symbol for symbol in saved
            if symbol in CURATED_PAIRS or (risk.memecoins_enabled and is_memecoin(symbol))
        ][:min(WATCHLIST_LIMIT,risk.watchlist_limit)]
        changed=watchlist != saved
        if changed:
            positions=(held if held is not None else
                db.query(Position).filter(Position.portfolio_id==portfolio.id,Position.quantity>0).all())
            held_symbols={position.symbol for position in positions}
            state.watchlist=watchlist
            # Preserve the age of the last verified selection. The changed flag
            # already forces a refresh; clearing the timestamp made a temporary
            # refresh failure indistinguishable from never having valid data.
            state.entry_decisions={
                symbol: decision for symbol,decision in (state.entry_decisions or {}).items()
                if symbol in watchlist or symbol in held_symbols
            }
            db.commit()
        return watchlist,changed

    def _schedule(self,user_id,portfolio_id,risk_id):
        job=f'bot_{user_id}'
        if not self.scheduler.get_job(job):
            self.scheduler.add_job(self._run_iteration,IntervalTrigger(seconds=30),id=job,
                args=[user_id,portfolio_id,risk_id],max_instances=1,misfire_grace_time=30,
                next_run_time=datetime.now(timezone.utc))

    async def restore(self):
        if not self.scheduler.running: self.scheduler.start()
        self.scheduler.add_job(self.sweep,IntervalTrigger(seconds=30),id='restore_bots',replace_existing=True,max_instances=1)
        self.scheduler.add_job(self.research_strategies,IntervalTrigger(hours=1),id='strategy_research',
            replace_existing=True,max_instances=1,next_run_time=datetime.now(timezone.utc)+timedelta(minutes=5))
        await self.sweep()

    async def research_strategies(self):
        from app.db.session import SessionLocal
        with SessionLocal() as db:
            users=[row[0] for row in db.query(RiskConfig.user_id).filter(RiskConfig.entry_strategy=='auto').all()]
        def evaluate(user_id):
            from app.services.strategy_research import research_next_candidate, advance_shadow_candidates, review_live_canary
            with SessionLocal() as db:
                generated=[]
                # Bounded batches keep research from monopolizing the live loop;
                # all twelve candidates finish within four hourly runs.
                for _ in range(3):
                    row=research_next_candidate(db,user_id)
                    if row is None: break
                    generated.append({'candidate_id':row.candidate_id,'decision':row.status})
                shadow=advance_shadow_candidates(db,user_id)
                canary=review_live_canary(db,user_id)
                return {'generated':generated,'shadow':shadow,'canary':canary}
        for user_id in users:
            try:
                result=await asyncio.to_thread(evaluate,user_id)
                research={'status':'evaluated' if result['generated'] or result['shadow'] or result['canary'] else 'waiting',**result}
            except Exception as exc:
                research={'status':'error','message':str(exc)[:300]}
            with SessionLocal() as db:
                state=db.query(BotState).filter(BotState.user_id==user_id).first()
                if state:
                    state.discovery_stats={**(state.discovery_stats or {}),'strategy_research':research}
                    db.commit()

    async def sweep(self):
        from app.db.session import SessionLocal
        with SessionLocal() as db:
            states=db.query(BotState).all()
            for state in states:
                book=db.query(Portfolio).filter(Portfolio.user_id==state.user_id,Portfolio.is_active.is_(True)).first()
                if not book: continue
                pending=bool(unresolved(db,book)) if book.book_type=='LIVE' else False
                if state.is_running or pending:
                    config=get_risk_config(db,state.user_id)
                    self._sync_watchlist_policy(db,state,book,config)
                    self._schedule(state.user_id,book.id,config.id)
                elif self.scheduler.get_job(f'bot_{state.user_id}'):
                    self.scheduler.remove_job(f'bot_{state.user_id}')

    async def shutdown(self):
        await self.trainer.close()
        if self.scheduler.running: self.scheduler.shutdown(wait=False)
        self.scheduler=AsyncIOScheduler()

    async def start(self,db,user):
        state=db.query(BotState).filter(BotState.user_id==user.id).first()
        if not state:
            state=BotState(user_id=user.id); db.add(state); db.commit()
        portfolio=get_or_create_portfolio(db,user.id)
        risk=get_risk_config(db,user.id)
        if portfolio.book_type!=portfolio.mode:
            raise ValueError('Legacy mode flag does not match its book; switch to paper, then enable the isolated live book')
        if portfolio.book_type=='LIVE':
            from app.core.config import settings
            from app.services.live_execution import fingerprint
            if not settings.ENABLE_LIVE_TRADING or fingerprint(user)!=portfolio.account_fingerprint:
                raise ValueError('Live server flag or account binding is invalid')
        state.is_running=True; state.health='HEALTHY'; state.last_error=None
        db.commit()
        if not self.scheduler.running: self.scheduler.start()
        self._schedule(user.id,portfolio.id,risk.id)
        db.refresh(state)
        return state

    async def stop(self,db,user):
        state=db.query(BotState).filter(BotState.user_id==user.id).first()
        if not state: state=BotState(user_id=user.id); db.add(state)
        state.is_running=False; state.health='STOPPED'
        db.commit(); db.refresh(state)
        # Keep reconciliation scheduled for accepted or ambiguous live orders.
        book=get_or_create_portfolio(db,user.id)
        if book.book_type=='LIVE' and unresolved(db,book):
            config=get_risk_config(db,user.id)
            if not self.scheduler.running: self.scheduler.start()
            self._schedule(user.id,book.id,config.id)
        elif self.scheduler.get_job(f'bot_{user.id}'):
            self.scheduler.remove_job(f'bot_{user.id}')
        return state

    async def emergency_stop(self,db,user):
        state=await self.stop(db,user)
        book=get_or_create_portfolio(db,user.id)
        # Never relabel real holdings as paper assets.
        state.last_error=('Emergency stop: real holdings remain in the live book. Pending orders will be reconciled/canceled; holdings are not liquidated.'
                          if book.book_type=='LIVE' else None)
        db.commit()
        return state

    async def _heartbeat(self,user_id,token):
        from app.db.session import SessionLocal
        while True:
            await asyncio.sleep(20)
            with SessionLocal() as db:
                if not lease.renew(db,user_id,token): return

    async def _run_iteration(self,user_id,portfolio_id,risk_config_id):
        from app.db.session import SessionLocal
        lock=self._locks.setdefault(user_id,asyncio.Lock())
        if lock.locked(): return
        async with lock:
            with SessionLocal() as db: token=lease.acquire(db,user_id)
            if not token: return
            heartbeat=asyncio.create_task(self._heartbeat(user_id,token))
            try:
                await self._iterate(user_id,token)
            finally:
                heartbeat.cancel()
                with contextlib.suppress(asyncio.CancelledError): await heartbeat
                with SessionLocal() as db: lease.release(db,user_id,token)

    def _running(self,db,state,portfolio,token):
        db.refresh(state); db.refresh(portfolio)
        return state.is_running and state.lock_token==token and state.lock_until and utc(state.lock_until)>datetime.now(timezone.utc) and portfolio.is_active

    async def _await_with_protection(self, work, protect, interval=10):
        """Keep exit checks running while a slow public-data request is pending."""
        task=asyncio.create_task(work)
        try:
            while not task.done():
                done,_=await asyncio.wait({task},timeout=interval)
                if not done: await protect()
            return await task
        finally:
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError): await task

    async def _execution(self,db,portfolio,user,exchange,symbol,side,quantity,price,risk,token,reason,intent_key=None):
        state=db.query(BotState).filter(BotState.user_id==user.id).first()
        if not self._running(db,state,portfolio,token): return
        if side==OrderSide.BUY:
            latest_config=get_risk_config(db,user.id); db.refresh(latest_config)
            cap=latest_config.max_invest_per_trade_eur
            effective_fee=max(float(latest_config.fee_pct),float(risk.fee_pct))
            if cap and quantity*price*(1+latest_config.slippage_pct)*(1+effective_fee)>cap+1e-8:
                raise ValueError('Maximum investment per trade exceeded including fee and slippage reserve')
        if side==OrderSide.BUY and is_memecoin(symbol):
            latest_config=get_risk_config(db,user.id); db.refresh(latest_config)
            current_risk=risk_manager_from_config(latest_config)
            risk=replace(current_risk,fee_pct=max(current_risk.fee_pct,risk.fee_pct))
            positions=db.query(Position).filter(Position.portfolio_id==portfolio.id,Position.quantity>0).all()
            if quantity*price*(1+risk.slippage_pct)*(1+risk.fee_pct)>memecoin_budget(portfolio,risk,symbol,positions)+1e-7:
                raise ValueError('Memecoin allocation changed or its exposure cap was reached')
            await check_liquidity(exchange,symbol,risk)
        if portfolio.book_type=='LIVE':
            await verify_balances(db,portfolio,exchange)
            await execute_live(db,portfolio,user,exchange,symbol,side,quantity,price,risk,token,
                               intent_key=intent_key)
        else:
            execute_paper_trade(db,portfolio,exchange,symbol,side,quantity,price,risk.fee_pct,
                                slippage_pct=risk.slippage_pct,reason=reason)

    async def _iterate(self,user_id,token):
        import time
        iteration_started=time.monotonic()
        from app.db.session import SessionLocal
        db=SessionLocal(); state=None; exchange=None; portfolio=None; errors=[]; decisions={}
        def explain(symbol, code, message):
            decisions[symbol]={**decisions.get(symbol,{}),'code':code,'message':message,'checked_at':datetime.now(timezone.utc).isoformat()}
        def explain_retry(symbol, code, exc, signal_id):
            previous=(state.entry_decisions or {}).get(symbol,{}) if state else {}
            prior_attempts=(int(previous.get('retry_attempts',0))
                            if previous.get('retry_signal_id')==signal_id else 0)
            attempt=prior_attempts+1
            delay=retry_delay_seconds(exc,attempt)
            message=(str(exc) if isinstance(exc,ValueError) else preflight_error(exc))
            explain(symbol,code,message+f' Safe pre-submission retry {attempt} is scheduled.')
            decisions[symbol].update(retryable=True,retry_signal_id=signal_id,
                retry_attempts=attempt,
                retry_after=(datetime.now(timezone.utc)+timedelta(seconds=delay)).isoformat())
        try:
            user=db.get(User,user_id)
            portfolio=get_or_create_portfolio(db,user_id)
            state=db.query(BotState).filter(BotState.user_id==user_id).first()
            if not user or not state: return
            live=portfolio.book_type=='LIVE'
            if portfolio.mode!=portfolio.book_type: raise ValueError('Trading mode does not match the book')
            exchange=live_exchange(user) if live else self._get_exchange(portfolio.mode)
            if live:
                errors.extend(await reconcile_all(db,portfolio,exchange,cancel=not state.is_running))
                if errors: raise ValueError('; '.join(errors))
                if not state.is_running: return
                assert_live_enabled(db,portfolio,user,token)
                await exchange.validate_permissions()
                await verify_balances(db,portfolio,exchange,sync_cash=True)
                from app.services.strategy_research import review_live_canary
                review_live_canary(db,user_id)
            if not self._running(db,state,portfolio,token): return
            config=get_risk_config(db,user_id); risk=risk_manager_from_config(config)
            evaluated_strategy=risk.entry_strategy
            portfolio.target_positions=risk.max_open_positions
            now=datetime.now(timezone.utc)
            if live:
                verified_at=utc(config.verified_taker_fee_at) if config.verified_taker_fee_at else None
                try:
                    if not verified_at or now-verified_at>=timedelta(hours=1):
                        account_fee=await exchange.trading_fee('BTC/EUR')
                        verified=float(account_fee.get('taker'))
                        risk=with_verified_taker_fee(risk,verified)
                        config.verified_taker_fee_pct=verified
                        config.verified_taker_fee_at=now
                        db.commit()
                    elif config.verified_taker_fee_pct is not None:
                        risk=with_verified_taker_fee(risk,config.verified_taker_fee_pct)
                except Exception as exc:
                    # A fresh symbol-specific fee check still runs immediately
                    # before every BUY. Exits and market monitoring must continue.
                    errors.append('Kraken fee refresh: '+
                                  (str(exc).strip() if isinstance(exc,ValueError) and str(exc).strip()
                                   else preflight_error(exc)))
            selection_available=True
            held=db.query(Position).filter(Position.portfolio_id==portfolio.id,Position.quantity>0).all()
            watchlist,watchlist_policy_changed=self._sync_watchlist_policy(db,state,portfolio,risk,held)
            symbols=list(dict.fromkeys([p.symbol for p in held]+watchlist))
            histories={}; quotes={}; exited=set(); predictions={}
            async def protect():
                if not self._running(db,state,portfolio,token):
                    raise ValueError('Bot stopped or execution lease expired during data refresh')
                db.refresh(config)
                protective_risk=risk_manager_from_config(config)
                positions=db.query(Position).filter(Position.portfolio_id==portfolio.id,Position.quantity>0).all()
                semaphore=asyncio.Semaphore(4)
                async def quote(position):
                    async with semaphore:
                        return await asyncio.wait_for(exchange.get_ticker(position.symbol),timeout=10)
                results=await asyncio.gather(*(quote(p) for p in positions),return_exceptions=True)
                for position,ticker in zip(positions,results):
                    if isinstance(ticker,Exception):
                        errors.append(f'{position.symbol}: protective quote unavailable'); continue
                    price=float(ticker.last)
                    if not math.isfinite(price) or price<=0: continue
                    update_position_price(db,portfolio,position.symbol,price)
                    reason=exit_reason(position,protective_risk,price)
                    if reason:
                        await self._execution(db,portfolio,user,exchange,position.symbol,OrderSide.SELL,
                            position.quantity,ticker.bid or price,protective_risk,token,reason)
                        exited.add(position.symbol)
                recalculate_equity(db,portfolio)
                check_drawdown(portfolio,protective_risk); db.commit()
            # Monitor every existing position before doing any CPU-heavy training.
            for symbol in symbols:
                try:
                    ticker=await asyncio.wait_for(exchange.get_ticker(symbol),timeout=10)
                    price=float(ticker.last)
                    if not math.isfinite(price) or price<=0: raise ValueError('Invalid quote')
                    if not self._running(db,state,portfolio,token): return
                    quotes[symbol]=ticker
                    update_position_price(db,portfolio,symbol,price)
                    recalculate_equity(db,portfolio)
                    position=get_position(db,portfolio.id,symbol)
                    reason=exit_reason(position,risk,price) if position else None
                    if reason:
                        await self._execution(db,portfolio,user,exchange,symbol,OrderSide.SELL,position.quantity,
                                              ticker.bid or price,risk,token,reason)
                        exited.add(symbol)
                except Exception as exc:
                    db.rollback(); errors.append(f'{symbol}: {exc}')
                    explain(symbol,'market_unavailable','Market quote unavailable; entry checks are paused.')
            recalculate_equity(db,portfolio)
            check_drawdown(portfolio,risk); db.commit()
            updated=utc(state.watchlist_updated_at) if state.watchlist_updated_at else None
            if watchlist_policy_changed or not state.watchlist or not updated or now-updated>=timedelta(minutes=5 if risk.memecoins_enabled else 1440):
                daily={}
                scan={}
                previous_watchlist=list(state.watchlist or [])
                try:
                    candidates=await self._await_with_protection(eligible_universe(exchange,risk,diagnostics=scan),protect)
                except Exception as exc:
                    candidates=list(CURATED_PAIRS)
                    errors.append(f'Memecoin eligibility unavailable: {type(exc).__name__}; new memecoin entries withheld')
                statuses=dict(scan.pop('markets',{}))
                for symbol in candidates:
                    if not self._running(db,state,portfolio,token): return
                    try:
                        rows=await self._await_with_protection(asyncio.wait_for(load_history(db,exchange,symbol,
                            '1h' if is_memecoin(symbol) else '1d',limit=8760 if is_memecoin(symbol) else 60),timeout=20),protect)
                        daily[symbol]=rows[-60:]
                        if is_memecoin(symbol):
                            histories[symbol]=rows
                            previous=(state.candidate_status or {}).get(symbol,{})
                            statuses[symbol]={**statuses.get(symbol,{}),'history_rows':len(rows),
                                'history_eligible':len(rows)>=336,
                                'model_ready':previous.get('model_ready') if previous.get('model_candle')==(rows[-1].timestamp.isoformat() if rows else None) else None}
                    except Exception as exc:
                        detail=str(exc).strip() or 'no additional detail'
                        errors.append(f'{symbol} selection: {type(exc).__name__}: {detail}')
                        statuses[symbol]={**statuses.get(symbol,{}),'history_eligible':False,'reason':'Usable history unavailable'}
                if not self._running(db,state,portfolio,token): return
                if daily:
                    state.watchlist=self.selector.select_watchlist(daily,risk.max_open_positions,risk.memecoins_enabled,
                        eligibility=statuses,previous=previous_watchlist,limit=risk.watchlist_limit,
                        monitor_all=risk.entry_strategy=='auto')
                    state.watchlist_updated_at=now
                else:
                    age=(now-utc(state.watchlist_updated_at) if state.watchlist_updated_at else None)
                    selection_available=bool(state.watchlist) and age is not None and age<=timedelta(hours=6)
                    errors.append('Selection refresh unavailable; retaining a recent verified watchlist.'
                                  if selection_available else
                                  'Selection unavailable and no recent verified watchlist exists; entries paused.')
                state.candidate_status=statuses
                refreshed=bool(daily)
                watchlist_age=(now-utc(state.watchlist_updated_at)).total_seconds() if state.watchlist_updated_at else None
                state.discovery_stats={**scan,'history_eligible':sum(s.get('history_eligible') is True for s in statuses.values()),
                    'watchlist_churn':len(set(previous_watchlist)^set(state.watchlist or [])),
                    'discovery_limit':risk.discovery_limit,'watchlist_limit':risk.watchlist_limit,
                    'selection_available':selection_available,'selection_refreshed':refreshed,
                    'watchlist_age_seconds':watchlist_age,
                    'last_successful_selection':state.watchlist_updated_at.isoformat() if state.watchlist_updated_at else None}
                db.commit()
            watchlist=[s for s in state.watchlist or [] if s in CURATED_PAIRS or (risk.memecoins_enabled and is_memecoin(s))][:risk.watchlist_limit]
            symbols=list(dict.fromkeys([p.symbol for p in held]+watchlist))
            for symbol in symbols:
                if symbol in quotes or symbol in exited: continue
                try:
                    ticker=await asyncio.wait_for(exchange.get_ticker(symbol),timeout=10)
                    if not math.isfinite(float(ticker.last)) or ticker.last<=0: raise ValueError('Invalid quote')
                    quotes[symbol]=ticker
                except Exception as exc:
                    errors.append(f'{symbol}: {exc}')
                    explain(symbol,'market_unavailable','Market quote unavailable; entry checks are paused.')
            for symbol in watchlist:
                if symbol not in decisions:
                    explain(symbol,'pending','Waiting for this cycle to evaluate the completed hourly candle.')
            # Auto mode needs a point-in-time basket view before evaluating any
            # member. Preloading also keeps strategy choice independent of loop order.
            if risk.entry_strategy=='auto':
                for symbol in symbols:
                    if symbol in histories or symbol not in quotes or symbol in exited:
                        continue
                    try:
                        histories[symbol]=await self._await_with_protection(
                            asyncio.wait_for(load_history(db,exchange,symbol),timeout=20),protect)
                    except Exception as exc:
                        errors.append(f'{symbol} history: {exc}')
                round_trip=(1+risk.fee_pct)*(1+risk.slippage_pct)/((1-risk.fee_pct)*(1-risk.slippage_pct))-1
                from app.services.strategy_research import approved_candidate
                active_candidate=approved_candidate(db,user_id,portfolio.book_type)
                auto_definition=(definition_from_parameters(active_candidate.parameters)
                                 if active_candidate else None)
                regime_parameters=(auto_definition if isinstance(auto_definition,AdaptiveParameters)
                                   else AdaptiveParameters())
                auto_regime=(classify_market_regime(histories,watchlist,round_trip,regime_parameters)
                             if auto_definition else MarketRegime('insufficient',0.,0.,0.,0,3))
            else:
                auto_regime=auto_definition=active_candidate=None
            for symbol in symbols:
                if symbol not in quotes: continue
                try:
                    candles=histories.get(symbol)
                    if candles is None:
                        candles=await self._await_with_protection(asyncio.wait_for(load_history(db,exchange,symbol),timeout=20),protect)
                    histories[symbol]=candles
                    if not candles or symbol in exited:
                        explain(symbol,'history_or_exit','Waiting for usable history or the next cycle after an exit.')
                        continue
                    stamp=candles[-1].timestamp.isoformat()
                    latest=db.query(Signal).filter(Signal.portfolio_id==portfolio.id,Signal.symbol==symbol).order_by(Signal.id.desc()).first()
                    key=(user_id,symbol)
                    model=self.models.get(key)
                    reused_signal=False
                    name=f'{user_id}_{portfolio.book_type}_{symbol.replace("/","_")}_h{risk.prediction_horizon}_v2'
                    if risk.entry_strategy in {'momentum', 'fast_momentum', 'auto'}:
                        classes={'momentum':MomentumModel,'fast_momentum':FastMomentumModel,'auto':AdaptiveMomentumModel}
                        names={'momentum':'momentum-v1','fast_momentum':'fast-momentum-v1','auto':'adaptive-momentum-v1'}
                        name=names[risk.entry_strategy]
                        model=(candidate_factory(auto_definition)(symbol) if risk.entry_strategy=='auto' and auto_definition
                               else AdaptiveMomentumModel(parameters=None) if risk.entry_strategy=='auto'
                               else classes[risk.entry_strategy]())
                        if risk.entry_strategy=='auto': model.set_regime(auto_regime)
                        model.name = name
                        if latest and latest.model == name and (latest.features or {}).get('candle_timestamp') == stamp:
                            prediction = None
                        else:
                            model.fit(candles, fee_pct=risk.fee_pct, slippage_pct=risk.slippage_pct)
                            prediction = model.predict(candles)
                            move = prediction.get('momentum', 0.)
                            threshold=float(getattr(model,'threshold',getattr(getattr(model,'parameters',None),'momentum_threshold',0.)) or 0.)
                            cost=float(getattr(model,'cost',0.) or 0.)
                            explanation = prediction.get('explanation') or (
                                f'Rule strategy: observed move {move:.2%}; BUY threshold is {max(threshold,cost):.2%}.')
                            prediction.update(probability=.5, confidence=0., entry_qualified=True, status='ready',
                                diagnostics={'strategy':risk.entry_strategy,
                                             'active_strategy':prediction.get('active_strategy',risk.entry_strategy),
                                             'regime':prediction.get('regime'), 'probability_available':False,
                                             'history_rows':len(candles), 'latest_candle':stamp},
                                explanation=explanation+' Rule-based signal; no probability estimate. Final execution checks apply.')
                    elif model is None or model.name!=name:
                        model=SignalModel(name=name)
                        if hasattr(model,'load_active'): model.load_active()
                        else: model.load()
                        self.models[key]=model
                    if risk.entry_strategy not in {'momentum', 'fast_momentum', 'auto'}:
                        prediction,model=await self.trainer.evaluate(db,portfolio.id,symbol,model,risk,candles,latest)
                        prediction=apply_buy_threshold(prediction,risk.buy_probability_threshold)
                        self.models[key]=model
                    if prediction is None:
                        previous=(state.entry_decisions or {}).get(symbol,{})
                        retryable=bool(previous.get('retryable')) and previous.get('retry_signal_id')==latest.id
                        legacy_retry=(previous.get('signal')=='BUY' and previous.get('code')=='fee_check'
                            and any(marker in previous.get('message','') for marker in
                                    ('InvalidNonce','NetworkError','RateLimitExceeded','DDoSProtection','RequestTimeout','ExchangeNotAvailable')))
                        retry_after=previous.get('retry_after')
                        due=True
                        if retry_after:
                            try: due=datetime.fromisoformat(retry_after)<=datetime.now(timezone.utc)
                            except (TypeError,ValueError): due=True
                        retry_signal=(latest.action=='BUY' and not get_position(db,portfolio.id,symbol)
                                      and ((retryable and due) or legacy_retry))
                        # Model exits are also safe to reconsider while the position remains open.
                        retry_signal=retry_signal or (latest.action=='SELL' and bool(get_position(db,portfolio.id,symbol)))
                        if retry_signal:
                            reused_signal=True
                            prediction={'action':latest.action,'probability':latest.probability,
                                'confidence':latest.confidence,'entry_qualified':True,
                                'status':(latest.features or {}).get('model_status','ready'),
                                'diagnostics':(latest.features or {}).get('diagnostics',{}),
                                'explanation':latest.explanation,'_signal_id':latest.id,
                                '_candle_timestamp':stamp}
                            predictions[symbol]=prediction
                            explain(symbol,'retrying_signal','Retrying the still-current signal after a pre-submission failure.')
                            decisions[symbol].update(signal=latest.action,signal_id=latest.id,
                                diagnostics=prediction['diagnostics'],model_status=prediction['status'])
                        else:
                            explain(symbol,'retry_wait' if retryable else 'waiting_candle',
                                ('A safe pre-submission retry is waiting for its backoff period.' if retryable else
                                 'Waiting for the next completed hourly candle. '+(latest.explanation or '')))
                            decisions[symbol].update(diagnostics=(latest.features or {}).get('diagnostics',{}),
                                model_status=(latest.features or {}).get('model_status','unknown'),
                                signal=latest.action,signal_id=latest.id)
                            if retryable:
                                decisions[symbol].update(retryable=True,retry_signal_id=latest.id,
                                    retry_attempts=previous.get('retry_attempts',1),retry_after=retry_after)
                            continue
                    if not self._running(db,state,portfolio,token): return
                    if not reused_signal:
                        signal=Signal(portfolio_id=portfolio.id,symbol=symbol,model=model.name,action=prediction['action'],
                                      probability=prediction['probability'],confidence=prediction['confidence'],
                                      features={**(prediction.get('features') or {}),'candle_timestamp':stamp,
                                                'model_status':prediction.get('status','ready'), 'diagnostics':prediction.get('diagnostics',{})},
                                      explanation=prediction.get('explanation'))
                        db.add(signal); db.commit()
                        prediction.update(_signal_id=signal.id,_candle_timestamp=stamp)
                        predictions[symbol]=prediction
                        explain(symbol,prediction.get('status','signal'),prediction.get('explanation') or f'Model signal is {prediction["action"]}; no buy entry requested.')
                        decisions[symbol].update(diagnostics=prediction.get('diagnostics',{}),model_status=prediction.get('status','ready'),
                            signal=prediction['action'],signal_id=signal.id)
                        statuses=dict(state.candidate_status or {})
                        statuses[symbol]={**statuses.get(symbol,{}),'model_ready':prediction.get('entry_qualified',False),
                            'model_candle':stamp,'history_rows':len(candles),
                            'history_eligible':len(candles)>=(30 if risk.entry_strategy in {'momentum','fast_momentum','auto'} else 336)}
                        state.candidate_status=statuses
                except Exception as exc:
                    db.rollback(); errors.append(f'{symbol} model: {exc}')
                    explain(symbol,'history_unavailable','History or model evaluation unavailable. '+str(exc))
            for symbol,prediction in predictions.items():
                position=get_position(db,portfolio.id,symbol)
                if prediction['action']=='SELL' and position:
                    ticker=await exchange.get_ticker(symbol)
                    await self._execution(db,portfolio,user,exchange,symbol,OrderSide.SELL,position.quantity,
                                          ticker.bid or ticker.last,risk,token,'Model exit')
            from app.services.entry_readiness import entry_readiness
            for symbol in watchlist:
                decision=decisions.get(symbol,{})
                if decision.get('model_status')=='ready' and symbol not in exited and not get_position(db,portfolio.id,symbol):
                    positions=db.query(Position).filter(Position.portfolio_id==portfolio.id,Position.quantity>0).all()
                    readiness=await self._await_with_protection(entry_readiness(exchange,portfolio,risk,symbol,positions,histories),protect)
                    decision['eligibility']=readiness
                    # Preflight explains HOLD/SELL readiness without changing its signal.
                    if not readiness['eligible']:
                        decision['market_note']=readiness['message']
                else:
                    decision['eligibility']={'eligible':False,'checked_at':datetime.now(timezone.utc).isoformat()}
            for symbol in rank_entries(watchlist,predictions):
                if not self._running(db,state,portfolio,token): return
                db.refresh(config); risk=risk_manager_from_config(config)
                if risk.entry_strategy != evaluated_strategy:
                    explain(symbol,'strategy_changed','Entry strategy changed; waiting for a fresh evaluation.'); continue
                if get_position(db,portfolio.id,symbol):
                    explain(symbol,'held','Already held; additional entries are disabled while this position is open.'); continue
                if portfolio.risk_halted:
                    explain(symbol,'risk_halt','Drawdown limit reached; new entries are paused.'); continue
                if not selection_available or not state.watchlist_updated_at:
                    explain(symbol,'selection_unavailable','Watchlist data unavailable; new entries are paused.'); continue
                if symbol in exited:
                    explain(symbol,'just_exited','Position just exited; no re-entry in the same cycle.'); continue
                prediction = predictions.get(symbol, {})
                execution_risk=risk
                action = str(prediction.get('action', 'HOLD')).upper()
                if action == 'SELL':
                    explain(symbol,'signal_sell','Signal remains negative; moving to the next candidate.'); continue
                # Runtime and backtest must agree: only an explicit BUY may enter.
                if action != 'BUY':
                    explain(symbol,'signal_waiting','Market is not yet compelling enough for a buy; continuing the search.'); continue
                active_strategy=prediction.get('active_strategy',risk.entry_strategy)
                if active_strategy == 'fast_momentum':
                    if not is_memecoin(symbol):
                        explain(symbol,'meme_focus','Fast meme momentum opens memecoin positions only.'); continue
                    last_exit=db.query(Trade).filter(Trade.portfolio_id==portfolio.id,Trade.symbol==symbol,
                        Trade.side=='SELL').order_by(Trade.created_at.desc()).first()
                    if last_exit and datetime.now(timezone.utc)-utc(last_exit.created_at)<timedelta(hours=1):
                        explain(symbol,'cooldown','Fast momentum waits one hour after a sell before re-entry.'); continue
                positions=db.query(Position).filter(Position.portfolio_id==portfolio.id,Position.quantity>0).all()
                canary=bool(live and active_candidate and active_candidate.status=='LIVE_APPROVED_CANARY')
                if len(positions)>=(CANARY_MAX_POSITIONS if canary else risk.max_open_positions):
                    explain(symbol,'position_cap','All configured position slots are occupied.'); continue
                if not risk.can_trade_today(db,portfolio.id):
                    explain(symbol,'daily_limit','Daily entry limit reached; waiting for the next UTC day.'); continue
                try:
                    liquidity=await check_liquidity(exchange,symbol,risk)
                except Exception as exc:
                    if retryable_preflight_error(exc):
                        explain_retry(symbol,'liquidity_retry',exc,prediction.get('_signal_id'))
                    else:
                        message=str(exc) if isinstance(exc,ValueError) else preflight_error(exc)
                        explain(symbol,'liquidity',message)
                    # A spread/turnover limit is a normal "wait" decision, not a bot fault.
                    # Keep it on the coin row without degrading global health or showing a red error.
                    if not isinstance(exc, LiquidityLimitError):
                        errors.append(f'{symbol}: '+(str(exc) if isinstance(exc,ValueError) else preflight_error(exc)))
                    continue
                budget=entry_budget(portfolio,risk,symbol,positions,histories)
                if canary:
                    # Canary exposure is portfolio-wide. Existing user/global
                    # limits remain in force when they are stricter.
                    budget=canary_entry_budget(portfolio,positions,budget)
                if active_strategy == 'fast_momentum' and liquidity:
                    budget=min(budget,liquidity[0]*.001)
                if budget<=.01:
                    explain(symbol,'allocation','No available allocation: cash, exposure, correlation, or risk budget is exhausted.'); continue
                ticker=await exchange.get_ticker(symbol)
                price=ticker.ask or ticker.last
                if not price or not math.isfinite(price) or price<=0: raise ValueError('Invalid execution quote')
                if live:
                    try:
                        fee=await exchange.trading_fee(symbol)
                    except Exception as exc:
                        if retryable_preflight_error(exc):
                            explain_retry(symbol,'fee_check_retry',exc,prediction.get('_signal_id'))
                        else:
                            message=str(exc) if isinstance(exc,ValueError) else preflight_error(exc)
                            explain(symbol,'fee_check',message)
                        errors.append(str(exc) if isinstance(exc,ValueError) else preflight_error(exc))
                        continue
                    taker=fee.get('taker')
                    try:
                        execution_risk=with_verified_taker_fee(risk,taker)
                    except ValueError:
                        errors.append(f'{symbol}: Kraken returned no usable taker fee')
                        explain(symbol,'fee_check','Kraken returned no usable taker fee; no order was submitted.')
                        continue
                    config.verified_taker_fee_pct=float(taker)
                    config.verified_taker_fee_at=datetime.now(timezone.utc)
                    db.commit()
                    if float(taker)>risk.fee_pct:
                        decision['market_note']=(f'Live sizing uses Kraken taker fee {float(taker):.2%}, '
                                                 f'above configured reserve {risk.fee_pct:.2%}.')
                quantity=budget*(1-1e-10)/(price*(1+execution_risk.slippage_pct)*(1+execution_risk.fee_pct))
                if live or hasattr(exchange,'market'):
                    # Skip tiny orders that cannot satisfy the exchange minimum before the bot burns a cycle.
                    adapter=exchange if live else exchange.market
                    min_viable = getattr(adapter, 'minimum_viable_quantity', lambda *args, **kwargs: 0.0)(symbol, price)
                    if min_viable and quantity < min_viable:
                        explain(symbol,'order_size',f'Projected order is below the exchange minimum for {symbol}; skipping this candidate.')
                        continue
                    # Size paper and live orders against the same exchange precision/minimums.
                    try:
                        quantity,_=await adapter.prepare_order(symbol,quantity,price)
                        book=await adapter.get_order_book(symbol)
                        levels=book.get('asks',[])
                        available=sum(float(q) for p,q,*_ in levels if float(p)<=price*(1+risk.slippage_pct))
                        if active_strategy == 'fast_momentum':
                            available=depth_capacity(book,price,float(ticker.bid or 0),risk.slippage_pct)
                        quantity=min(quantity,available)
                        quantity,_=await adapter.prepare_order(symbol,quantity,price)
                    except Exception as exc:
                        if retryable_preflight_error(exc):
                            explain_retry(symbol,'order_size_retry',exc,prediction.get('_signal_id'))
                        else:
                            message=str(exc) if isinstance(exc,ValueError) else preflight_error(exc)
                            explain(symbol,'order_size',message)
                        errors.append(f'{symbol}: '+(str(exc) if isinstance(exc,ValueError) else preflight_error(exc)))
                        continue
                if not self._running(db,state,portfolio,token): return
                # Re-check controls after quote/orderbook waits and prior exits.
                recalculate_equity(db,portfolio)
                if check_drawdown(portfolio,risk):
                    db.commit(); explain(symbol,'risk_halt','Drawdown limit reached; new entries are paused.'); continue
                try:
                    await self._execution(db,portfolio,user,exchange,symbol,OrderSide.BUY,quantity,price,execution_risk,token,
                        f'Cost-aware {active_strategy} entry selected by {risk.entry_strategy}',
                        intent_key=f'signal:{prediction.get("_signal_id")}:BUY')
                    explain(symbol,'submitted','Entry submitted; check holdings and order status for the confirmed fill.')
                except Exception as exc:
                    db.rollback(); errors.append(f'{symbol}: {exc}')
                    if retryable_preflight_error(exc) and not unresolved(db,portfolio):
                        explain_retry(symbol,'execution_retry',exc,prediction.get('_signal_id'))
                    else:
                        explain(symbol,'execution_error','Order could not complete: '+str(exc))
                    if live: break
            if not self._running(db,state,portfolio,token): return
            state.last_run_at=datetime.now(timezone.utc)
            for symbol,decision in decisions.items():
                decision['buy_candidate']=bool(decision.get('signal')=='BUY' and
                    decision.get('eligibility',{}).get('eligible') and decision.get('code') in {'ready','submitted'})
            state.entry_decisions=decisions
            state.discovery_stats={**(state.discovery_stats or {}),
                'model_qualified':sum(d.get('model_status')=='ready' for d in decisions.values()),
                'buy_candidates':sum(d.get('buy_candidate',False) for d in decisions.values()),
                'cycle_seconds':round(time.monotonic()-iteration_started,3)}
            state.health='RISK_HALTED' if portfolio.risk_halted else 'DEGRADED' if errors else 'HEALTHY'
            state.last_error='Drawdown limit reached; new entries paused' if portfolio.risk_halted else '; '.join(errors) or None
            db.commit()
            from app.services.research_service import record_snapshot
            record_snapshot(db,portfolio,risk,errors,time.monotonic()-iteration_started)
        except Exception as exc:
            db.rollback()
            if state:
                db.refresh(state)
                state.health='ERROR'; state.last_error=str(exc); state.last_run_at=datetime.now(timezone.utc)
                db.commit()
                if portfolio and portfolio.book_type=='LIVE' and any(marker in str(exc).lower() for marker in
                        ('balance differs','reconciliation','unmanaged exchange','unresolved live order','drawdown')):
                    from app.services.strategy_research import review_live_canary
                    review_live_canary(db,user_id,critical_reason=str(exc)[:300])
        finally:
            if exchange and portfolio and portfolio.book_type=='LIVE' and state:
                db.refresh(state)
                if not state.is_running:
                    with contextlib.suppress(Exception): await reconcile_all(db,portfolio,exchange,cancel=True)
            db.close()
            if exchange: await exchange.close()

    def _get_exchange(self,mode):
        return PaperExchange()


bot_orchestrator=BotOrchestrator()
