"""Apply fast meme entries to one named account, preserving allocation limits."""
import argparse
import json
from app.db.session import SessionLocal
from app.models.user import User
from app.models.portfolio import BotState
from app.services.risk_service import get_risk_config, risk_manager_from_config
from app.services.momentum_policy import fast_meme_preset
from dataclasses import asdict


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user-id', type=int, required=True)
    args=parser.parse_args()
    with SessionLocal() as db:
        if db.get(User,args.user_id) is None:
            parser.error('Account does not exist')
        config=fast_meme_preset(get_risk_config(db,args.user_id))
        risk=risk_manager_from_config(config)
        state=db.query(BotState).filter_by(user_id=args.user_id).first()
        if state:
            state.watchlist=[]
            state.watchlist_updated_at=None
        db.commit()
        print(json.dumps({'user_id':args.user_id,'risk':asdict(risk),
            'message':'Settings saved. Existing bot running state and trading book are unchanged.'},indent=2))


if __name__=='__main__':
    main()
