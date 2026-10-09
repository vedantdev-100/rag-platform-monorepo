"""Exercise the uploaded auth functions without importing an incomplete auth app."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest

AUTH_ROOT=Path(__file__).resolve().parents[4]/'auth-service/app'

class InvalidTokenError(Exception):pass

@pytest.mark.asyncio
@pytest.mark.parametrize('user',[None,SimpleNamespace(id='u',is_active=False)])
async def test_refresh_rejects_missing_or_inactive_user(user):
    tree=ast.parse((AUTH_ROOT/'services/auth_service.py').read_text())
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='AuthService')
    fn=next(n for n in cls.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='refresh')
    fn.returns=None
    from sqlalchemy import Table, Column, String, Boolean, MetaData
    token_table=Table('refresh_tokens',MetaData(),Column('token_hash',String),Column('revoked',Boolean))
    token_table.token_hash=token_table.c.token_hash;token_table.revoked=token_table.c.revoked
    ns={'RefreshToken':token_table,'verify_refresh_token':lambda *args:True,'InvalidTokenError':InvalidTokenError,
        'TokenExpiredError':InvalidTokenError,'logger':SimpleNamespace(warning=lambda *a,**k:None,info=lambda *a,**k:None)}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'auth_refresh','exec'),ns)
    service=SimpleNamespace(_find_all_active_tokens=AsyncMock(return_value=[SimpleNamespace(token_hash='h',user_id='u')]),
        token_repo=SimpleNamespace(is_expired=lambda *a:False,revoke=AsyncMock(),
            session=SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
                scalar_one_or_none=lambda:SimpleNamespace(token_hash='h',user_id='u'))))),
        user_repo=SimpleNamespace(get_by_id=AsyncMock(return_value=user)),_issue_tokens=AsyncMock())
    with pytest.raises(InvalidTokenError):await ns['refresh'](service,'token')
    service._issue_tokens.assert_not_called()

def test_auth_route_injects_blacklist():
    tree=ast.parse((AUTH_ROOT/'api/v1/endpoints/auth.py').read_text())
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='get_auth_service')
    for arg in fn.args.args:arg.annotation=None
    fn.args.defaults=[];fn.returns=None
    ns={'UserRepository':lambda session:'users','RefreshTokenRepository':lambda session:'refresh',
        'AuthService':lambda *args,**kwargs:kwargs}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'auth_dependency','exec'),ns)
    marker=object();request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(token_blacklist=marker)))
    assert ns['get_auth_service'](request,None)['token_blacklist'] is marker

@pytest.mark.asyncio
async def test_browser_cookie_session_and_csrf(monkeypatch):
    import importlib.util
    import sys
    from types import ModuleType
    from fastapi import FastAPI
    from pydantic import BaseModel
    import httpx
    class LoginRequest(BaseModel):
        email:str
        password:str
    class Limiter:
        def limit(self,*args):return lambda fn:fn
    fake_settings=SimpleNamespace(ALLOWED_ORIGINS=['http://localhost:5173'],API_V1_PREFIX='/api/v1',
        REFRESH_TOKEN_EXPIRE_DAYS=7,RATE_LIMIT_LOGIN='5/minute',RATE_LIMIT_REFRESH='10/minute',RATE_LIMIT_LOGOUT='10/minute')
    def dependency():return None
    replacements={
        'app.core.config':{'get_settings':lambda:fake_settings},
        'app.core.rate_limit':{'limiter':Limiter()},
        'app.api.v1.endpoints.auth':{'get_auth_service':dependency},
        'app.schemas.auth':{'LoginRequest':LoginRequest},
        'app.services':{},
        'app.services.auth_service':{'AuthService':object},
    }
    for name,items in replacements.items():
        m=ModuleType(name)
        for key,value in items.items():setattr(m,key,value)
        monkeypatch.setitem(sys.modules,name,m)
    spec=importlib.util.spec_from_file_location('_browser_auth_test',AUTH_ROOT/'api/v1/endpoints/browser_auth.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.setattr(module,'browser_settings',lambda:module.BrowserSettings(_env_file=None,AUTH_BROWSER_COOKIE_SECURE=False))
    tokens=SimpleNamespace(access_token='access',refresh_token='secret-refresh',token_type='bearer',expires_in=900)
    service=SimpleNamespace(login=AsyncMock(return_value=tokens),refresh=AsyncMock(return_value=tokens),logout=AsyncMock())
    app=FastAPI();app.include_router(module.router,prefix='/api/v1');app.dependency_overrides[dependency]=lambda:service
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://localhost') as client:
        r=await client.post('/api/v1/auth/browser/login',json={'email':'a@example.com','password':'password'})
        assert r.status_code==403
        for origin in ['null','http://evil.example']:
            r=await client.post('/api/v1/auth/browser/refresh',headers={'Origin':origin})
            assert r.status_code==403
        origin={'Origin':'http://localhost:5173'}
        r=await client.post('/api/v1/auth/browser/login',json={'email':'a@example.com','password':'password'},headers=origin)
        assert r.status_code==200 and 'refresh_token' not in r.json()
        assert 'HttpOnly' in r.headers['set-cookie'] and 'SameSite=lax' in r.headers['set-cookie']
        assert r.headers['cache-control']=='no-store'
        r=await client.post('/api/v1/auth/browser/refresh',headers=origin)
        assert r.status_code==200;service.refresh.assert_awaited_once_with('secret-refresh')
        r=await client.post('/api/v1/auth/browser/logout',headers=origin)
        assert r.status_code==204;service.logout.assert_awaited_once_with('secret-refresh')
        r=await client.post('/api/v1/auth/browser/refresh',headers=origin)
        assert r.status_code==401

@pytest.mark.asyncio
async def test_refresh_rechecks_consumed_token_under_lock():
    from sqlalchemy import Table, Column, String, Boolean, MetaData
    from sqlalchemy.dialects import postgresql
    tree=ast.parse((AUTH_ROOT/'services/auth_service.py').read_text())
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='AuthService')
    fn=next(n for n in cls.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='refresh');fn.returns=None
    table=Table('refresh_tokens',MetaData(),Column('token_hash',String),Column('revoked',Boolean))
    table.token_hash=table.c.token_hash;table.revoked=table.c.revoked
    ns={'RefreshToken':table,'verify_refresh_token':lambda *args:True,'InvalidTokenError':InvalidTokenError,
        'TokenExpiredError':InvalidTokenError,'logger':SimpleNamespace(warning=lambda *a,**k:None,info=lambda *a,**k:None)}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'auth_refresh','exec'),ns)
    execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda:None))
    service=SimpleNamespace(_find_all_active_tokens=AsyncMock(return_value=[SimpleNamespace(token_hash='h',user_id='u')]),
        token_repo=SimpleNamespace(session=SimpleNamespace(execute=execute),revoke=AsyncMock()),_issue_tokens=AsyncMock())
    with pytest.raises(InvalidTokenError):await ns['refresh'](service,'token')
    query=execute.call_args.args[0]
    sql=str(query.compile(dialect=postgresql.dialect()))
    assert 'FOR UPDATE' in sql and 'revoked IS false' in sql
    service._issue_tokens.assert_not_called()
