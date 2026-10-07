from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from app.ml.models import SignalModel


@pytest.mark.parametrize('validation,qualified', [
    ({'brier_score': .20, 'baseline_brier': .25, 'validation_rows': 30}, True),
    ({'brier_score': .26, 'baseline_brier': .25, 'validation_rows': 30}, False),
    ({'brier_score': .25, 'baseline_brier': .25, 'validation_rows': 30}, False),
    ({'brier_score': .20, 'baseline_brier': .25, 'validation_rows': 29}, False),
    ({'brier_score': float('nan'), 'baseline_brier': .25, 'validation_rows': 30}, False),
    ({'brier_score': .20, 'baseline_brier': float('inf'), 'validation_rows': 30}, False),
    ({}, False),
])
@pytest.mark.parametrize('probability', [.8, .2])
def test_validation_blocks_only_entries(monkeypatch, validation, qualified, probability):
    model = SignalModel(persist=False)
    model.is_fitted = True
    model.validation = validation
    model.feature_cols = ['returns']
    model.train_mean = pd.Series({'returns': 0.})
    model.train_std = pd.Series({'returns': 1.})
    monkeypatch.setattr('app.ml.models.build_features', lambda _: pd.DataFrame({'returns': [0.]}))
    monkeypatch.setattr(model, '_raw', lambda _: np.array([probability]))
    model.calibrator = SimpleNamespace(predict_proba=lambda _: np.array([[1-probability, probability]]))

    result = model.predict([])

    assert result['entry_qualified'] is qualified
    assert result['action'] == ('SELL' if probability < .4 else 'BUY' if qualified else 'HOLD')
    if probability > .6 and not qualified:
        assert 'Entry withheld' in result['explanation']


def test_unfitted_model_cannot_qualify():
    model = SignalModel(persist=False)
    model.validation = {'brier_score': .1, 'baseline_brier': .25, 'validation_rows': 100}
    assert not model.entry_qualified()
