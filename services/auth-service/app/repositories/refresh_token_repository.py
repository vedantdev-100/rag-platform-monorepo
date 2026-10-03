import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.refresh_token import RefreshToken
from app.utils import is_expired


class RefreshTokenRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, token: RefreshToken) -> RefreshToken:
        self.session.add(token)
        await self.session.commit()
        await self.session.refresh(token)
        return token

    async def get_active_by_user(self, user_id: uuid.UUID) -> list[RefreshToken]:
        result = await self.session.execute(
            select(RefreshToken).where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked.is_(False),
            )
        )
        return list(result.scalars().all())

    async def revoke(self, token: RefreshToken) -> None:
        token.revoked = True
        await self.session.commit()

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> None:
        tokens = await self.get_active_by_user(user_id)
        for t in tokens:
            t.revoked = True
        await self.session.commit()

    @staticmethod
    def is_expired(token: RefreshToken) -> bool:
        return is_expired(token.expires_at)
