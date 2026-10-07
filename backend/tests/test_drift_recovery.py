import asyncio
from types import SimpleNamespace

import pytest

from tests.test_autonomous import setup_bot, candles
from app.services.model_recovery import ModelTrainer
from app.services.risk_service import risk_manager_from_config


class Candidate:
    name = 'recovery-test'
    is_fitted = True
    failure_reason = ''

    def __init__(self, schema='legacy', score=.2, drift=False):
        self.feature_schema = schema
        self.validation = {'brier_score': score, 'baseline_brier': .25}
        self.drift = drift
        self.saved = False
        self.fit_calls = 0

    def fit(self, *args, **kwargs):
        self.fit_calls += 1

    def needs_retrain(self, *args):
        return False

    def entry_qualified(self):
        return self.validation['brier_score'] < .25

    def predict(self, data):
        return dict(action='HOLD' if self.drift else 'BUY', drift_detected=self.drift,
                    status='drift' if self.drift else 'ready', diagnostics={})

    def _save(self):
        self.saved = True


@pytest.mark.asyncio
async def test_automatic_switch_requires_qualification_and_preserves_idempotency(setup_bot):
    c = setup_bot
    data = candles(objects=True)
    old = Candidate(drift=True)
    legacy = Candidate(drift=True)
    normalized = Candidate('normalized-v1', .15)
    trainer = ModelTrainer(lambda name: legacy, alternate_factory=lambda name: normalized)
    risk = risk_manager_from_config(c.risk)
    args = (c.db, c.portfolio.id, 'PEPE/EUR', old, risk, data)
    prediction, active = await trainer.evaluate(*args, None)
    assert prediction['status'] == 'training'
    await asyncio.wait_for(trainer.tasks[(c.portfolio.id, 'PEPE/EUR')], 5)
    prediction, active = await trainer.evaluate(*args, None)
    assert active is normalized and normalized.saved and not legacy.saved
    latest = SimpleNamespace(action='BUY', features={'candle_timestamp': data[-1].timestamp.isoformat()})
    prediction, active = await trainer.evaluate(c.db, c.portfolio.id, 'PEPE/EUR', active, risk, data, latest)
    assert prediction is None
    assert normalized.fit_calls == legacy.fit_calls == 1
    await trainer.close()


@pytest.mark.asyncio
async def test_failed_candidates_keep_incumbent_and_do_not_retry_same_data_after_restart(setup_bot):
    c = setup_bot
    data = candles(objects=True)
    old, failed = Candidate(drift=True), Candidate(score=.3)
    trainer = ModelTrainer(lambda name: failed)
    args = (c.db, c.portfolio.id, 'PEPE/EUR', old, risk_manager_from_config(c.risk), data, None)
    await trainer.evaluate(*args)
    await asyncio.wait_for(trainer.tasks[(c.portfolio.id, 'PEPE/EUR')], 5)
    prediction, active = await trainer.evaluate(*args)
    assert prediction['status'] == 'blocked' and active is old and not failed.saved
    restarted = ModelTrainer(lambda name: failed)
    prediction, active = await restarted.evaluate(*args)
    assert prediction['status'] == 'blocked' and not restarted.tasks
    assert failed.fit_calls == 1
    await trainer.close()
    await restarted.close()


def test_training_reports_specific_missing_outcomes():
    from app.ml.models import SignalModel
    model = SignalModel(persist=False).fit(candles(count=500, drift=0, swing=0, objects=True))
    assert not model.is_fitted
    assert 'calibration: 0 cost-covering rises' in model.failure_reason
    assert model.validation['class_counts']['calibration']['cost_covering'] == 0


@pytest.mark.asyncio
async def test_candidate_prediction_failure_does_not_discard_good_alternate(setup_bot):
    c=setup_bot
    class Broken(Candidate):
        def predict(self, data):
            raise ValueError('bad artifact')
    old=Candidate(drift=True)
    good=Candidate('normalized-v1')
    trainer=ModelTrainer(lambda name: Broken(), alternate_factory=lambda name: good)
    args=(c.db,c.portfolio.id,'PEPE/EUR',old,risk_manager_from_config(c.risk),candles(objects=True),None)
    await trainer.evaluate(*args)
    await asyncio.wait_for(trainer.tasks[(c.portfolio.id,'PEPE/EUR')],5)
    prediction,active=await trainer.evaluate(*args)
    assert active is good and good.saved
    assert 'Prediction failed' in prediction['diagnostics']['candidate_comparison'][0]['reason']
    await trainer.close()
