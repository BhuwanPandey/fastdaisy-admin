from collections.abc import Generator

import pytest
from bs4 import BeautifulSoup
from sqlalchemy import Column, String
from sqlalchemy.orm import declarative_base, sessionmaker
from starlette.applications import Starlette
from starlette.testclient import TestClient

from fastdaisy_admin import Admin, ModelView
from fastdaisy_admin.auth.models import BaseUser
from fastdaisy_admin.auth.models import User as DefinedUser
from fastdaisy_admin.exceptions import FastDaisyAdminException
from tests.common import sync_engine as engine

pytestmark = pytest.mark.anyio

# --- Database setup ---
Base = declarative_base()
SessionLocal = sessionmaker(bind=engine)


class User(Base, BaseUser):
    __tablename__ = "users"
    address = Column(String(32), default="butwal")


# --- App and Admin setup ---
app = Starlette()
admin = Admin(
    app=app,
    secret_key="test",
    session_maker=SessionLocal,
    authentication=True,
    auth_model=User,
)


# --- Fixtures ---
@pytest.fixture(scope="function", autouse=True)
def prepare_database() -> Generator[None, None, None]:
    """Create tables before each test and drop them afterward."""
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def session():
    """Provide a clean SQLAlchemy session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="function")
def client() -> Generator[TestClient, None, None]:
    """Provide a Starlette test client."""
    with TestClient(app=app, base_url="http://testserver") as c:
        yield c


@pytest.fixture(scope="function")
def create_superuser(session):
    """Create a reusable superuser for authentication tests."""
    username = "superuser"
    password = "canwewecan"
    hashed_password = admin.auth_service.get_password_hash(password)
    superuser = User(username=username, hashed_password=hashed_password, is_superuser=True)
    session.add(superuser)
    session.commit()
    return username, password


# --- Tests ---
def test_create_user():
    """Ensure subclassing DefinedUser is prohibited."""
    with pytest.raises(FastDaisyAdminException, match="Subclassing of 'User' is not allowed."):

        class SomeTable(DefinedUser):
            __tablename__ = "sometable"


async def test_login(client, create_superuser):
    """Test admin login functionality."""
    username, password = create_superuser
    admin.add_view(type("UserAdmin", (ModelView,), {"model": User}))

    response = client.post("/admin/login", data={"username": username, "password": password})
    assert response.status_code == 200

    soup = BeautifulSoup(response.text, "html.parser")
    assert soup.find("li", class_="editprofile").text.strip() == "Edit Profile"


async def test_authenticate_user(create_superuser):
    """Test backend authentication service."""
    username, password = create_superuser
    auth_user = await admin.auth_service.authenticate_user(username, password)
    assert auth_user and auth_user.is_superuser


async def test_logout(client, create_superuser):
    """Test logout endpoint and redirect behavior."""
    username, password = create_superuser
    client.post("/admin/login", data={"username": username, "password": password})

    response = client.post("/admin/logout")
    assert response.status_code == 200
    assert response.json().get("redirect_url") == "http://testserver/admin/login"
