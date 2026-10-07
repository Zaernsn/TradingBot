"""Portable research metadata; imports never grant trading authority."""
import json
import math
from datetime import datetime, timezone

from app.models.portfolio import StrategyCandidate, ShadowRun
from app.ml.strategy_factory import candidate_id, definition_from_parameters, candidate_parameters

SCHEMA_VERSION=1
MAX_CANDIDATES=200


def export_metadata(db,user_id):
    candidates=db.query(StrategyCandidate).filter_by(user_id=user_id).order_by(StrategyCandidate.tested_at).all()
    runs=db.query(ShadowRun).filter_by(user_id=user_id).order_by(ShadowRun.started_at).all()
    return {'schema_version':SCHEMA_VERSION,'kind':'trading-bot-research-metadata',
        'exported_at':datetime.now(timezone.utc).isoformat(),
        'candidates':[{'candidate_id':row.candidate_id,'parameters':row.parameters,
            'status':row.status,'metrics':row.metrics,'tested_at':row.tested_at.isoformat()}
            for row in candidates],
        'shadow_runs':[{'candidate_id':row.candidate_id,'version':row.version,
            'status':row.status,'started_at':row.started_at.isoformat(),
            'last_candle_at':row.last_candle_at.isoformat() if row.last_candle_at else None,
            'metrics':row.metrics} for row in runs]}


def import_metadata(db,user_id,payload):
    if not isinstance(payload,dict) or payload.get('schema_version')!=SCHEMA_VERSION or payload.get('kind')!='trading-bot-research-metadata':
        raise ValueError('Unsupported research metadata format')
    rows=payload.get('candidates')
    if not isinstance(rows,list) or len(rows)>MAX_CANDIDATES:
        raise ValueError('Research metadata candidate count is invalid')
    try:
        json.dumps(payload,allow_nan=False)
    except (TypeError,ValueError) as exc:
        raise ValueError('Research metadata must contain finite JSON values') from exc
    imported=0
    for item in rows:
        if not isinstance(item,dict) or not isinstance(item.get('parameters'),dict):
            raise ValueError('Invalid candidate metadata')
        try:
            parameters=definition_from_parameters(item['parameters'])
        except (TypeError,ValueError) as exc:
            raise ValueError('Imported candidate parameters are outside the allowed strategy grammar') from exc
        expected=candidate_id(parameters)
        if item.get('candidate_id')!=expected:
            raise ValueError('Imported candidate identity does not match its parameters')
        existing=db.query(StrategyCandidate).filter_by(user_id=user_id,candidate_id=expected).first()
        imported_record={'source_status':str(item.get('status','UNKNOWN'))[:40],
                         'source_metrics':item.get('metrics') if isinstance(item.get('metrics'),dict) else {}}
        if existing:
            metrics=dict(existing.metrics or {})
            imports=list(metrics.get('imports') or [])[-4:]
            imports.append(imported_record)
            existing.metrics={**metrics,'imports':imports}
        else:
            db.add(StrategyCandidate(user_id=user_id,candidate_id=expected,
                parameters=candidate_parameters(parameters),status='IMPORTED_UNVERIFIED',
                metrics={'imports':[imported_record]},tested_at=datetime.now(timezone.utc)))
        imported+=1
    db.commit()
    return {'imported':imported,'live_authorized':False,
            'detail':'Imported evidence is informational until locally re-evaluated.'}
