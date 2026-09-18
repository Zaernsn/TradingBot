from pydantic import BaseModel


class ExchangeCredentialsIn(BaseModel):
    api_key: str
    api_secret: str


class ExchangeStatusOut(BaseModel):
    connected: bool
    masked_key: str
