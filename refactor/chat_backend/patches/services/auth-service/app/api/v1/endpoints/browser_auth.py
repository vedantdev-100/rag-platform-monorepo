"""Browser session endpoints; original JSON token endpoints remain available."""
from functools import lru_cache
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from app.core.config import get_settings
from app.core.rate_limit import limiter
from app.api.v1.endpoints.auth import get_auth_service
from app.schemas.auth import LoginRequest
from app.services.auth_service import AuthService

class BrowserSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env',extra='ignore')
    AUTH_BROWSER_COOKIE_SECURE: bool = True
    AUTH_BROWSER_COOKIE_NAME: str = Field('rag_refresh',pattern=r'^[A-Za-z0-9_]+$',max_length=50)

@lru_cache
def browser_settings(): return BrowserSettings()

class AccessTokenOut(BaseModel):
    access_token: str
    token_type: str = 'bearer'
    expires_in: int

router=APIRouter(prefix='/auth/browser',tags=['browser-auth'])
settings=get_settings()

def allowed_origin(request):
    # Reject absent/null origins and wildcards, even when a refresh cookie exists.
    origin=request.headers.get('origin')
    if origin is None or origin == 'null' or origin not in settings.ALLOWED_ORIGINS:
        raise HTTPException(403,{'code':'origin_not_allowed'})


def cookie_path(): return settings.API_V1_PREFIX.rstrip('/')+'/auth/browser'

def clear(response):
    cfg=browser_settings()
    response.delete_cookie(cfg.AUTH_BROWSER_COOKIE_NAME,path=cookie_path(),
                           secure=cfg.AUTH_BROWSER_COOKIE_SECURE,httponly=True,samesite='lax')

def tokens_response(tokens,response):
    cfg=browser_settings()
    response.headers['Cache-Control']='no-store'
    response.set_cookie(cfg.AUTH_BROWSER_COOKIE_NAME,tokens.refresh_token,path=cookie_path(),
                        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS*86400,
                        secure=cfg.AUTH_BROWSER_COOKIE_SECURE,httponly=True,samesite='lax')
    return AccessTokenOut(access_token=tokens.access_token,token_type=tokens.token_type,expires_in=tokens.expires_in)

@router.post('/login',response_model=AccessTokenOut)
@limiter.limit(settings.RATE_LIMIT_LOGIN)
async def login(request:Request,response:Response,payload:LoginRequest,
                service:AuthService=Depends(get_auth_service)):
    allowed_origin(request)
    return tokens_response(await service.login(payload.email,payload.password),response)

@router.post('/refresh',response_model=AccessTokenOut)
@limiter.limit(settings.RATE_LIMIT_REFRESH)
async def refresh(request:Request,response:Response,service:AuthService=Depends(get_auth_service)):
    allowed_origin(request)
    token=request.cookies.get(browser_settings().AUTH_BROWSER_COOKIE_NAME)
    if not token: raise HTTPException(401,{'code':'session_missing'})
    return tokens_response(await service.refresh(token),response)

@router.post('/logout',status_code=204)
@limiter.limit(settings.RATE_LIMIT_LOGOUT)
async def logout(request:Request,service:AuthService=Depends(get_auth_service)):
    allowed_origin(request)
    token=request.cookies.get(browser_settings().AUTH_BROWSER_COOKIE_NAME)
    if token: await service.logout(token)
    response=Response(status_code=204,headers={'Cache-Control':'no-store'})
    clear(response)
    return response
