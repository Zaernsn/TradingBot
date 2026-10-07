from fastapi import APIRouter, Depends, HTTPException, Request, status, BackgroundTasks
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.schemas.auth import UserCreate, UserLoginJSON, UserOut, Token
from app.services.auth_service import create_user, authenticate_user, generate_token

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut)
def register(payload: UserCreate, db: Session = Depends(get_db)):
    return create_user(db, payload.email, payload.password)


class LoginData:
    def __init__(self, email: str, password: str):
        self.email = email
        self.password = password


async def get_login_data(request: Request) -> LoginData:
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("application/json"):
        body = await request.json()
        email = body.get("email")
        password = body.get("password")
    else:
        form = await request.form()
        email = form.get("username")
        password = form.get("password")
    if not email or not password:
        raise HTTPException(status_code=422, detail="Email and password are required")
    return LoginData(email=email, password=password)


@router.post("/login", response_model=Token)
def login(data: LoginData = Depends(get_login_data), db: Session = Depends(get_db)):
    user = authenticate_user(db, data.email, data.password)
    return {"access_token": generate_token(user), "token_type": "bearer"}


from app.schemas.auth import PasswordResetRequest, PasswordResetConfirm
from app.services import password_reset
from app.core.config import settings


@router.post('/forgot-password')
def forgot_password(payload: PasswordResetRequest, request: Request, tasks: BackgroundTasks, db: Session = Depends(get_db)):
    if not settings.RESEND_API_KEY or not settings.RESEND_FROM:
        raise HTTPException(status_code=503, detail='Password reset email delivery is not configured. Contact the administrator.')
    peer=request.client.host if request.client else 'unknown'
    allowed=password_reset.rate_allowed(db,'reset-ip:'+peer,10)
    allowed=password_reset.rate_allowed(db,'reset-email:'+str(payload.email).lower(),3) and allowed
    if allowed:
        token=password_reset.issue_reset(db,str(payload.email))
        if token: tasks.add_task(password_reset.send_reset,str(payload.email),token)
    return {'detail':password_reset.GENERIC}


@router.post('/reset-password')
def reset_password(payload: PasswordResetConfirm, request: Request, db: Session = Depends(get_db)):
    peer=request.client.host if request.client else 'unknown'
    if not password_reset.rate_allowed(db,'reset-consume:'+peer,20):
        raise HTTPException(status_code=429,detail='Too many reset attempts. Try again later.')
    if not password_reset.consume_reset(db,payload.token,payload.password):
        raise HTTPException(status_code=400,detail='Reset link is invalid or expired. Request a new link.')
    return {'detail':'Password changed. Existing sessions have been signed out and the bot stopped. Sign in again.'}
