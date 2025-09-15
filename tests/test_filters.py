from collections.abc import AsyncGenerator
from typing import Any

import pytest
from bs4 import BeautifulSoup
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport
from sqlalchemy import Boolean, Column, ForeignKey, Integer, String
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker
from starlette.applications import Starlette
from sqlalchemy.ext.asyncio import async_sessionmaker
from fastdaisy_admin import Admin, ModelView
from tests.common import async_engine as engine

Base = declarative_base()  # type: Any
session_maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

app = Starlette()
admin = Admin(app=app, secret_key="test", engine=engine)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    name = Column(String)
    title = Column(String)
    is_admin = Column(Boolean)
    office_id = Column(Integer, ForeignKey("offices.id"), nullable=True)


class Address(Base):
    __tablename__ = "addresses"

    id = Column(Integer, primary_key=True)
    street = Column(String)


class Office(Base):
    __tablename__ = "offices"

    id = Column(Integer, primary_key=True)
    name = Column(String)


class UserAdmin(ModelView):
    model = User
    column_list = [User.name, User.title]
    column_filters = [User.title, User.is_admin]


class AddressAdmin(ModelView):
    model = Address
    column_list = [Address.street]
    # This admin will NOT have filters defined


admin.add_view(UserAdmin)
admin.add_view(AddressAdmin)


@pytest.fixture
async def prepare_database() -> AsyncGenerator[None, None]:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest.fixture
async def prepare_data(prepare_database: Any) -> AsyncGenerator[None, None]:
    # Add test data
    async with session_maker() as session:
        office1 = Office(name="Office1")
        office2 = Office(name="Office2")
        session.add_all([office1, office2])
        await session.commit()

        # Create users with different boolean values and titles
        user1 = User(name="Admin User", title="Manager", is_admin=True, office_id=office1.id)
        user2 = User(
            name="Regular User",
            title="Developer",
            is_admin=False,
            office_id=office2.id,
        )
        session.add_all([user1, user2])
        await session.commit()

    yield


@pytest.fixture
async def client(prepare_database: Any, prepare_data: Any) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest.mark.anyio
async def test_column_filters_sidebar_existence(client: AsyncClient) -> None:
    """Test that the filter list sidebar appears only when filters are defined."""
    # Test view with filters (UserAdmin)
    response = await client.get("/admin/user/list")
    assert response.status_code == 200

    # Check for the filter sidebar container
    soup = BeautifulSoup(response.text, "html.parser")
    filter_field = soup.find("div", id="filter-sidebar")
    assert filter_field

    # Test view without filters (AddressAdmin)
    response = await client.get("/admin/address/list")
    assert response.status_code == 200
    soup = BeautifulSoup(response.text, "html.parser")
    filter_field = soup.find("div", id="filter-sidebar")

    # Verify filter sidebar does not appear
    assert not filter_field


@pytest.mark.anyio
async def test_filter_lookups(client: AsyncClient) -> None:
    """Test that the filter lookups are correct."""
    response = await client.get("/admin/user/list")
    assert response.status_code == 200

    # Check for the filter sidebar container
    soup = BeautifulSoup(response.text, "html.parser")
    filter_field = soup.find("div", id="filter-sidebar")
    assert filter_field

    # Check for the filter lookups
    assert "All" in response.text
    assert "Manager" in response.text
    assert "Developer" in response.text


@pytest.mark.anyio
async def test_boolean_filter_functionality(client: AsyncClient) -> None:
    """Test that boolean filters correctly filter users
    based on their is_admin status."""
    #     # Test with no filter or 'all' filter - should show both users
    response = await client.get("/admin/user/list")
    assert response.status_code == 200
    soup = BeautifulSoup(response.text, "html.parser")
    td_tags = soup.find_all("td", class_="break-all")
    td_texts = [td.get_text(strip=True) for td in td_tags]

    # Assert both users appear
    assert "Admin User" in td_texts
    assert "Regular User" in td_texts

    # Test filtering for admin users (is_admin=true)
    response = await client.get("/admin/user/list?is_admin=true")
    assert response.status_code == 200
    soup = BeautifulSoup(response.text, "html.parser")
    td_tags = soup.find_all("td", class_="break-all")
    td_texts = [td.get_text(strip=True) for td in td_tags]
    assert "Admin User" in td_texts
    assert "Regular User" not in td_texts

    # Test filtering for non-admin users (is_admin=false)
    response = await client.get("/admin/user/list?is_admin=false")
    soup = BeautifulSoup(response.text, "html.parser")
    td_tags = soup.find_all("td", class_="break-all")
    td_texts = [td.get_text(strip=True) for td in td_tags]
    assert "Admin User" not in td_texts
    assert "Regular User" in td_texts
