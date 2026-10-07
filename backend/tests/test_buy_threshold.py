import pytest
from app.ml.models import apply_buy_threshold


@pytest.mark.parametrize('probability,action',[(.451,'BUY'),(.45,'HOLD'),(.399,'SELL')])
def test_lower_threshold_is_strict(probability,action):
    p=dict(status='ready',entry_qualified=True,probability=probability,action='HOLD')
    assert apply_buy_threshold(p,.45)['action']==action


@pytest.mark.parametrize('status',['drift','validation_failed','blocked','training','data_unavailable'])
def test_threshold_does_not_bypass_model_gates(status):
    p=dict(status=status,entry_qualified=False,probability=.9,action='HOLD')
    assert apply_buy_threshold(p,.45)['action']=='HOLD'


def test_unqualified_ready_model_cannot_be_promoted():
    p=dict(status='ready',entry_qualified=False,probability=.9,action='HOLD')
    assert apply_buy_threshold(p,.45)['action']=='HOLD'
    assert apply_buy_threshold(None,.45) is None


@pytest.mark.parametrize('probability,action',[(.399,'SELL'),(.4,'HOLD'),(.4001,'BUY')])
def test_forty_percent_boundary_has_no_overlap(probability,action):
    from app.schemas.portfolio import RiskConfigUpdate
    from app.services.risk_service import RiskManager
    assert RiskConfigUpdate(buy_probability_threshold=.4).buy_probability_threshold==.4
    RiskManager(.2,.03,.06,.0026,10,None,12,buy_probability_threshold=.4)
    assert apply_buy_threshold(dict(status='ready',entry_qualified=True,probability=probability),.4)['action']==action


@pytest.mark.parametrize('value',[.399,float('nan'),float('inf')])
def test_invalid_threshold_rejected(value):
    from app.schemas.portfolio import RiskConfigUpdate
    with pytest.raises(ValueError):
        RiskConfigUpdate(buy_probability_threshold=value)
