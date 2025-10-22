from __future__ import annotations

import logging
import re
from typing import Any

import bcrypt
from sqlalchemy import select

from fastdaisy_admin.helpers import get_object_identifier

logger = logging.getLogger(__name__)


class UserService:
    def __init__(self, session_maker, is_async, model) -> None:
        self.session = session_maker
        self.is_async = is_async
        self.model = model

    async def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify a password against its hash using bcrypt."""
        try:
            return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())
        except Exception as e:
            logger.error(f"Error verifying password: {str(e)}")
            return False

    async def validate_username(self, username, mapper):
        username_column = mapper.columns.get("username")
        if username_column is None:
            raise AttributeError("The model does not have a 'username' column.")

        if not re.match(r"^[\w.@+-]+$", username):
            raise ValueError(
                "Enter a valid username. This value may contain only letters, numbers, and @/./+/-/_ characters."
            )

        if username_column.unique:
            is_user = await self.get_user(username)
            if is_user:
                raise ValueError(f"Username '{username}' is already taken.")

    def validate_password(self, password, mapper):
        password_column = mapper.columns.get("hashed_password")
        if password_column is None:
            raise AttributeError("The model does not have a 'hashed_password' column.")

        if len(password) < 8:
            raise ValueError("This password is too short. It must contain at least 8 characters.")

    def get_password_hash(self, password: str) -> str:
        """Generate a bcrypt password hash using bcrypt."""
        try:
            return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        except Exception as e:
            logger.error(f"Error hashing password: {str(e)}")
            raise

    async def authenticate_user(
        self,
        username: str,
        password: str,
    ) -> Any:
        """
        Authenticate a user by username.
        """
        db_user = await self.get_user(username)
        if not db_user:
            logger.debug("User not found in database")
            return None

        if hasattr(db_user, "is_superuser") and not db_user.is_superuser:
            logger.debug("Not Superuser")
            return None

        hashed_password = getattr(db_user, "hashed_password", None)
        if not hashed_password:
            logger.debug("No hashed_password found in user record")
            return None

        logger.debug("Verifying password")
        if not await self.verify_password(password, hashed_password):
            logger.debug("Invalid password")
            return None

        logger.debug("Authentication successful")
        return db_user if db_user is not None else False

    async def login(self, request):
        form = await request.form()
        username, password = form["username"], form["password"]
        user = await self.authenticate_user(username, password)
        if not user:
            logger.warning(f"Authentication failed for user: {username}")
            return None
        user_id = get_object_identifier(user)
        request.session.update({"_authenticated_id": user_id})
        return True

    async def authenticate(self, request) -> bool:
        authenticated = request.session.get("_authenticated_id")
        if not authenticated:
            return False
        return True

    async def logout(self, request) -> bool:
        request.session.clear()
        return True

    async def get_user(self, username: str):
        """
        Return either user or None
        """
        stmt = select(self.model).where(self.model.username == username)
        if self.is_async:
            async with self.session() as db:
                obj = db.execute(stmt).scalar_one_or_none()
        else:
            with self.session() as db:
                obj = db.execute(stmt).scalar_one_or_none()
        return obj

    async def create_superuser(self, username, password):
        """
        Create Super User
        """
        hashed_password = self.get_password_hash(password)
        object_dict = {"username": username, "hashed_password": hashed_password, "is_superuser": True}
        if self.is_async:
            async with self.session(expire_on_commit=False) as db:
                db_object = self.model(**object_dict)
                db.add(db_object)
                await db.commit()
        else:
            with self.session(expire_on_commit=False) as db:
                db_object = self.model(**object_dict)
                db.add(db_object)
                db.commit()

        logger.debug(f"Created admin user: {username}")
