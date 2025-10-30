from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, declarative_base, mapped_column

from fastdaisy_admin.exceptions import FastDaisyAdminException

UTC = UTC
Base = declarative_base()


class BaseUser:
    __abstract__ = True

    id: Mapped[int] = mapped_column("id", autoincrement=True, nullable=False, unique=True, primary_key=True)
    username: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    date_joined: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )

    def __str__(self):
        return self.username


class User(Base, BaseUser):
    __tablename__ = "users"

    def __init_subclass__(cls, **kwargs):
        raise FastDaisyAdminException(f"Subclassing of '{User.__name__}' is not allowed.")


all = [BaseUser, User]
