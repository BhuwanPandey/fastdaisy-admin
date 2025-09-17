from collections.abc import Generator

import pytest
from bs4 import BeautifulSoup
from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import declarative_base
from starlette.applications import Starlette
from starlette.datastructures import MutableHeaders
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.testclient import TestClient
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from fastdaisy_admin import Admin, ModelView
from tests.common import sync_engine as engine

Base = declarative_base()


class DataModel(Base):  # type: ignore
    __tablename__ = "datamodel"
    id = Column(Integer, primary_key=True)
    data = Column(String)


class User(Base):  # type: ignore
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    name = Column(String(32), default="Fastapi")


@pytest.fixture(autouse=True)
def prepare_database() -> Generator[None, None, None]:
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


def test_application_title() -> None:
    app = Starlette()
    Admin(app=app, secret_key="test", engine=engine)

    with TestClient(app) as client:
        response = client.get("/admin")

    soup = BeautifulSoup(response.text, "html.parser")
    assert response.status_code == 200
    div = soup.find("div", class_="w-full")
    assert div and div.text.strip() == "Admin"
    title = soup.find("title")
    assert title and title.text.strip() == "Admin"


def test_middlewares() -> None:
    class CorrelationIdMiddleware:
        def __init__(self, app: ASGIApp) -> None:
            self.app = app

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            async def send_wrapper(message: Message) -> None:
                if message["type"] == "http.response.start":
                    headers = MutableHeaders(scope=message)
                    headers.append("X-Correlation-ID", "UUID")
                await send(message)

            await self.app(scope, receive, send_wrapper)

    app = Starlette()
    Admin(
        app=app,
        secret_key="test",
        engine=engine,
        middlewares=[Middleware(CorrelationIdMiddleware)],
    )

    with TestClient(app) as client:
        response = client.get("/admin")

    assert response.status_code == 200
    assert "x-correlation-id" in response.headers


def test_get_save_redirect_url():
    app = Starlette()
    app.add_middleware(SessionMiddleware, secret_key="test-secret")
    admin = Admin(app=app, secret_key="test", engine=engine)
    added_users = []

    class UserAdmin(ModelView):
        model = User
        save_as = True

    admin.add_view(UserAdmin)

    @app.route("/{identity}", methods=["POST"])
    async def index(request: Request):
        obj = User(id=1)
        added_users.append(obj)
        form_data = await request.form()
        url = admin.get_save_redirect_url(request, form_data, admin.views[0], obj)
        return Response(str(url))

    @app.route("/get-messages")
    async def get_messages(request: Request):
        return JSONResponse({"messages": request.session.pop("_messages", [])})

    client = TestClient(app)

    response = client.post("/user", data={"_save": "Save", "_form_type": "added"})
    assert response.text == "http://testserver/admin/user/list"
    resp = client.get("/get-messages")
    assert {"level": "success", "message": f"The User “{added_users[0]}” was added successfully."} in resp.json()[
        "messages"
    ]

    response = client.post("/user", data={"_continue": "Save and continue editing"})
    assert response.text == "http://testserver/admin/user/edit/1"

    response = client.post("/user", data={"_saveasnew": "Save as new"})
    assert response.text == "http://testserver/admin/user/edit/1"

    response = client.post("/user", data={"_addanother": "Save and add another", "_form_type": "changed"})
    assert response.text == "http://testserver/admin/user/create"
    resp = client.get("/get-messages")
    message = f"The User “{added_users[0]}” was changed successfully. You may add another User below."
    assert {"level": "success", "message": message} in resp.json()["messages"]


def test_build_category_menu():
    app = Starlette()
    admin = Admin(app=app, secret_key="test", engine=engine)

    class UserAdmin(ModelView):
        model = User
        category = "Accounts"
        divider_title = "Apps"

    admin.add_view(UserAdmin)
    assert admin._menu.items[0].name == "Accounts"
    assert admin._menu.items[0].divider == "Apps"


def test_normalize_wtform_fields() -> None:
    app = Starlette()
    admin = Admin(app=app, secret_key="test", engine=engine)

    class DataModelAdmin(ModelView):
        model = DataModel

    datamodel = DataModel(id=1, data="abcdef")
    admin.add_view(DataModelAdmin)
    assert admin._normalize_wtform_data(datamodel) == {"data_": "abcdef"}


def test_denormalize_wtform_fields() -> None:
    app = Starlette()
    admin = Admin(app=app, secret_key="test", engine=engine)

    class DataModelAdmin(ModelView):
        model = DataModel

    datamodel = DataModel(id=1, data="abcdef")
    admin.add_view(DataModelAdmin)
    assert admin._denormalize_wtform_data({"data_": "abcdef"}, datamodel) == {"data": "abcdef"}


def test_validate_page():
    app = Starlette()
    admin = Admin(app=app, secret_key="test", engine=engine)

    class UserAdmin(ModelView):
        model = User

    admin.add_view(UserAdmin)

    client = TestClient(app)

    response = client.get("/admin/user/list/?page=10000")
    assert response.status_code == 200
