from fastapi import APIRouter, Depends, HTTPException, Request, status
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
