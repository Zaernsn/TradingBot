import hashlib
import hmac
import logging
import secrets
import httpx
from datetime import datetime, timezone, timedelta
from sqlalchemy import case
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from app.core.config import settings
from app.core.security import get_password_hash
from app.models.user import User, PasswordResetToken, AuthRateLimit
from app.models.portfolio import BotState

GENERIC='If an account exists for that address, a password reset link will be sent.'


def rate_allowed(db,scope,limit=5):
    now=datetime.now(timezone.utc)
    cutoff=now-timedelta(minutes=15)
    key=hmac.new(settings.SECRET_KEY.encode(),scope.encode(),hashlib.sha256).hexdigest()
    insert=postgres_insert if db.bind.dialect.name=='postgresql' else sqlite_insert
    old=AuthRateLimit.window_at<cutoff
    statement=insert(AuthRateLimit).values(key=key,window_at=now,attempts=1).on_conflict_do_update(
        index_elements=['key'],set_={'attempts':case((old,1),else_=AuthRateLimit.attempts+1),
                                    'window_at':case((old,now),else_=AuthRateLimit.window_at)})
    db.execute(statement); db.commit()
    return db.get(AuthRateLimit,key,populate_existing=True).attempts<=limit


def issue_reset(db,email):
    user=db.query(User).filter(User.email==email,User.is_active.is_(True)).first()
    if not user: return None
    token=secrets.token_urlsafe(32)
    now=datetime.now(timezone.utc)
    db.query(PasswordResetToken).filter(PasswordResetToken.user_id==user.id,PasswordResetToken.used.is_(False)).update({'used':True})
    db.add(PasswordResetToken(user_id=user.id,token_hash=hashlib.sha256(token.encode()).hexdigest(),
                             expires_at=now+timedelta(minutes=30),used=False))
    db.commit()
    return token


def send_reset(email,token):
    # Never log tokens, credentials, recipients or full reset URLs.
    url=f'{settings.APP_PUBLIC_URL.rstrip("/")}/reset-password#token={token}'
    body=(f'Use this link within 30 minutes to reset your password:\n\n{url}\n\n'
          'If you did not request this, ignore this email. Your password has not changed.')
    try:
        if not settings.RESEND_API_KEY or not settings.RESEND_FROM:
            raise ValueError('Resend API key and verified sender are required')
        with httpx.Client(timeout=15) as client:
            response=client.post('https://api.resend.com/emails', headers={
                'Authorization': f'Bearer {settings.RESEND_API_KEY}',
                'Idempotency-Key': 'password-reset/' + hashlib.sha256(token.encode()).hexdigest(),
            }, json={'from':settings.RESEND_FROM, 'to':[email], 'subject':'Reset your WACG password', 'text':body})
            response.raise_for_status()
            if not response.json().get('id'): raise ValueError('Missing delivery acknowledgement')
        return True
    except Exception as exc:
        logging.getLogger(__name__).error('Password reset delivery failed (%s)',type(exc).__name__)
        return False


def consume_reset(db,token,password):
    digest=hashlib.sha256(token.encode()).hexdigest()
    now=datetime.now(timezone.utc)
    reset=db.get(PasswordResetToken,digest)
    if not reset: return False
    # Conditional update serializes concurrent use of the same token.
    changed=db.query(PasswordResetToken).filter(PasswordResetToken.token_hash==digest,
        PasswordResetToken.used.is_(False),PasswordResetToken.expires_at>now).update({'used':True},synchronize_session=False)
    if changed!=1:
        db.rollback(); return False
    user=db.get(User,reset.user_id)
    if not user or not user.is_active:
        db.rollback(); return False
    user.hashed_password=get_password_hash(password)
    user.token_version+=1
    db.query(PasswordResetToken).filter(PasswordResetToken.user_id==user.id).update({'used':True})
    db.query(BotState).filter(BotState.user_id==user.id).update({'is_running':False})
    db.commit()
    return True
