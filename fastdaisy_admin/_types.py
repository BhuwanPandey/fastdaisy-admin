from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.engine import Connection, Engine
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine
from sqlalchemy.orm import ColumnProperty, InstrumentedAttribute, RelationshipProperty
from sqlalchemy.sql.expression import Select
from starlette.requests import Request

MODEL_PROPERTY = ColumnProperty | RelationshipProperty
ENGINE_TYPE = Engine | AsyncEngine | Connection | AsyncConnection
SYNC_ENGINE_TYPE = Engine | Connection
ASYNC_ENGINE_TYPE = AsyncEngine | AsyncConnection
MODEL_ATTR = str | InstrumentedAttribute


@runtime_checkable
class ColumnFilter(Protocol):
    title: str
    parameter_name: str

    async def lookups(
        self, request: Request, model: Any, run_query: Callable[[Select], Any]
    ) -> list[tuple[str, bool, str]]: ...

    async def get_filtered_query(self, query: Select, value: Any, model: Any) -> Select: ...

    def get_query_values(self, request): ...


@runtime_checkable
class AdminAction(Protocol):
    _action: bool
    _title: str
    _has_confirmation: bool

    def __call__(self, *args: Any, **kwargs: Any) -> Any: ...
