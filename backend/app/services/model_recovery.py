"""Bounded background training. Workers never access books or submit orders."""
import asyncio
from datetime import datetime, timezone, timedelta

from app.models.portfolio import ModelRecovery
from app.services.market_data import utc


class ModelTrainer:
    def __init__(self, factory, concurrency=1, alternate_factory=None):
        self.factory = factory
        self.alternate_factory = alternate_factory
        self.slots = asyncio.Semaphore(concurrency)
        self.tasks = {}

    async def _fit(self, name, candles, signature):
        async with self.slots:
            candidates=[]
            for factory in [self.factory]+([self.alternate_factory] if self.alternate_factory else []):
                candidate = factory(name)
                candidate.persist = False
                try:
                    await asyncio.to_thread(candidate.fit, candles, horizon=signature[0],
                                            fee_pct=signature[1], slippage_pct=signature[2])
                except Exception as exc:
                    candidate.is_fitted=False
                    candidate.failure_reason=f'Training failed ({type(exc).__name__})'
                candidates.append(candidate)
            return candidates

    async def close(self):
        # Running to_thread work may finish, but cannot save a model or trade.
        for task in self.tasks.values(): task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)
        self.tasks.clear()

    @staticmethod
    def hold(record, diagnostics=None):
        return {'action':'HOLD', 'probability':.5, 'confidence':0., 'entry_qualified':False,
                'status':record.state, 'explanation':record.message,
                'diagnostics':{**(diagnostics or record.diagnostics or {}), 'recovery':{
                    'state':record.state, 'attempted_candle':record.candle_timestamp,
                    'attempted_at':utc(record.attempted_at).isoformat(),
                    'retry_after':utc(record.retry_after).isoformat()}}}

    async def evaluate(self, db, portfolio_id, symbol, model, risk, candles, latest):
        """Return (prediction or None for unchanged candle, active model).

        A persisted attempt is recorded before queueing work. Restarted attempts
        wait for fresh data and cooldown; the same input is never retried.
        """
        now = datetime.now(timezone.utc)
        stamp = candles[-1].timestamp.isoformat()
        signature = (risk.prediction_horizon, risk.fee_pct, risk.slippage_pct)
        signature_key = repr((model.name, signature))
        key = (portfolio_id, symbol)
        record = db.query(ModelRecovery).filter_by(portfolio_id=portfolio_id, symbol=symbol).first()
        task = self.tasks.get(key)
        if task is not None and not task.done():
            return self.hold(record), model
        if task is not None:
            self.tasks.pop(key)
            try:
                candidates = task.result()
                if record.signature != signature_key:
                    record.state, record.message = 'blocked', 'Training settings changed; obsolete result discarded.'
                    db.commit()
                else:
                    choices=[]; comparison=[]; outputs=[]
                    for candidate in candidates:
                        try:
                            prediction=await asyncio.to_thread(candidate.predict,candles)
                        except Exception as exc:
                            prediction={'status':'prediction_failed','diagnostics':{},
                                        'explanation':f'Prediction failed ({type(exc).__name__})'}
                        qualified=bool(candidate.is_fitted and candidate.entry_qualified() and
                            not prediction.get('drift_detected') and prediction.get('status') not in
                            {'data_unavailable','model_unavailable','prediction_failed'})
                        reason = (candidate.failure_reason if not candidate.is_fitted else
                                  prediction.get('explanation','') if prediction.get('drift_detected') or
                                  prediction.get('status') in {'data_unavailable','prediction_failed'} else
                                  'Validation did not beat the baseline or had insufficient samples.' if not candidate.entry_qualified() else '')
                        comparison.append({'feature_schema':getattr(candidate,'feature_schema','legacy'),
                            'brier_score':candidate.validation.get('brier_score'),
                            'baseline_brier':candidate.validation.get('baseline_brier'),
                            'qualified':qualified,'drift_detected':bool(prediction.get('drift_detected')),
                            'reason':reason,'class_counts':candidate.validation.get('class_counts')})
                        outputs.append((candidate,prediction))
                        if qualified: choices.append((candidate,prediction))
                    if choices:
                        candidate,prediction=min(choices,key=lambda pair:(pair[0].validation['brier_score'],
                            getattr(pair[0],'feature_schema','legacy')!=getattr(model,'feature_schema','legacy')))
                        prediction.setdefault('diagnostics',{})['candidate_comparison']=comparison
                        candidate._save()  # Atomic replacement only after qualification.
                        candidate.persist = True
                        record.state, record.message = 'ready', f'Automatically selected {candidate.feature_schema}: validation passed and current drift check cleared.'
                        record.diagnostics=prediction['diagnostics']
                        db.commit()
                        prediction['diagnostics']['recovery'] = {'state':'ready','selection':record.message}
                        # An already evaluated BUY must not execute twice during recovery.
                        if latest and (latest.features or {}).get('candle_timestamp') == stamp and latest.action != 'HOLD':
                            return None, candidate
                        return prediction, candidate
                    candidate,prediction=outputs[0]
                    record.diagnostics={**prediction.get('diagnostics',{}),'candidate_comparison':comparison}
                    record.state = 'blocked'
                    reasons = ' '.join(f'{item["feature_schema"]}: {item["reason"]}' for item in comparison)
                    record.message = 'No replacement qualified. '+reasons+' Next retry after '+utc(record.retry_after).isoformat()+' and a new completed candle.'
                    db.commit()
                    return self.hold(record), model
            except Exception as exc:
                record.state, record.message = 'blocked', f'Retraining failed ({type(exc).__name__}); waiting for new data and the retry window.'
                db.commit()
                return self.hold(record), model
        if record and record.state == 'training':
            record.state, record.message = 'blocked', 'Training was interrupted; waiting for new data and the retry window.'
            db.commit()
        same_signature = record and record.signature == signature_key
        if same_signature and record.state == 'blocked' and (record.candle_timestamp == stamp or now < utc(record.retry_after)):
            return self.hold(record), model
        same_candle = latest and (latest.features or {}).get('candle_timestamp') == stamp
        drift_pending = same_candle and (
            (latest.features or {}).get('model_status') == 'drift'
            or 'feature drift' in (getattr(latest, 'explanation', '') or '').lower())
        needs_training = model.needs_retrain(*signature)
        if same_candle and not drift_pending and not needs_training and not (record and record.state=='blocked'):
            return None, model
        prediction = None
        if not needs_training:
            prediction = await asyncio.to_thread(model.predict, candles)
            if not prediction.get('drift_detected'):
                return prediction, model
        reason = 'drift' if drift_pending or (prediction or {}).get('drift_detected') else 'scheduled'
        if same_signature and (record.candle_timestamp == stamp or now < utc(record.retry_after)):
            return self.hold(record, (prediction or {}).get('diagnostics')), model
        if record is None:
            record = ModelRecovery(portfolio_id=portfolio_id, symbol=symbol)
            db.add(record)
        record.signature, record.candle_timestamp = signature_key, stamp
        record.state, record.attempted_at = 'training', now
        record.retry_after = now + timedelta(hours=24 if reason=='drift' else 1)
        record.message = 'Retraining queued in the background; entries paused while protective exits remain active.'
        record.diagnostics = (prediction or {}).get('diagnostics') or (model.diagnostics(candles) if hasattr(model,'diagnostics') else {})
        db.commit()
        self.tasks[key] = asyncio.create_task(self._fit(model.name, list(candles), signature))
        return self.hold(record), model
