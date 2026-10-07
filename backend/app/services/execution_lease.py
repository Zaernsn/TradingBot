"""Database lease shared by bot workers and background reconciliation."""
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from sqlalchemy import or_
from app.models.portfolio import BotState


def acquire(db,user_id):
    now=datetime.now(timezone.utc)
    token=str(uuid4())
    count=db.query(BotState).filter(BotState.user_id==user_id,
        or_(BotState.lock_until.is_(None),BotState.lock_until<now)).update(
            {'lock_token':token,'lock_until':now+timedelta(seconds=120)},synchronize_session=False)
    db.commit()
    return token if count==1 else None


def renew(db,user_id,token):
    count=db.query(BotState).filter(BotState.user_id==user_id,BotState.lock_token==token).update(
        {'lock_until':datetime.now(timezone.utc)+timedelta(seconds=120)},synchronize_session=False)
    db.commit()
    return count==1


def release(db,user_id,token):
    db.query(BotState).filter(BotState.user_id==user_id,BotState.lock_token==token).update(
        {'lock_token':None,'lock_until':None},synchronize_session=False)
    db.commit()
