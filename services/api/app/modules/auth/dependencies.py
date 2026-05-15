from fastapi import Depends, HTTPException, status

from app.modules.auth.service import get_current_user
from app.modules.users.models import User, UserRole


def require_role(*roles: UserRole):
    async def _check(user: User = Depends(get_current_user)) -> User:
        if UserRole(user.role) not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return user

    return _check
