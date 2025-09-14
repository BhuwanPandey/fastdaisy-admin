from typing import Generator

import pytest
from sqlalchemy.orm import declarative_base
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.testclient import TestClient

from fastdaisy_admin import Admin, BaseView, expose
from tests.common import sync_engine as engine
from bs4 import BeautifulSoup

Base = declarative_base()

app = Starlette()
admin = Admin(app=app, secret_key='test',engine=engine, templates_dir="tests/templates")


class CustomAdmin(BaseView):
    name = "test"
    icon = "fa fa-test"

    @expose("/custom", methods=["GET"])
    async def custom(self, request: Request):
        return await self.templates.TemplateResponse(request, "custom.html")

    @expose("/custom/report")
    async def custom_report(self, request: Request):
        return await self.templates.TemplateResponse(request, "custom.html")


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(app=app, base_url="http://testserver") as c:
        yield c


def test_base_view(client: TestClient) -> None:
    admin.add_view(CustomAdmin)

    response = client.get("/admin/custom")

    assert response.status_code == 200
    soup = BeautifulSoup(response.text,'html.parser')
    p_tag = soup.find('p', class_='custom')
    assert p_tag and p_tag.text.strip() == "Here I'm going to display some data."

    response = client.get("/admin/custom/report")
    assert response.status_code == 200

