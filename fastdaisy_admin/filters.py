import re
from collections.abc import Callable
from typing import Any

from sqlalchemy.sql.expression import Select, select
from starlette.requests import Request

from fastdaisy_admin._types import MODEL_ATTR


def get_parameter_name(column: MODEL_ATTR) -> str:
    if isinstance(column, str):
        return column
    else:
        return column.key


def prettify_attribute_name(name: str) -> str:
    return re.sub(r"_([A-Za-z])", r" \1", name).title()


def get_title(column: MODEL_ATTR) -> str:
    name = get_parameter_name(column)
    return prettify_attribute_name(name)


def get_column_obj(column: MODEL_ATTR, model: Any = None) -> Any:
    if isinstance(column, str):
        if model is None:
            raise ValueError("model is required for string column filters")
        return getattr(model, column)
    return column


def get_foreign_column_name(column_obj: Any) -> str:
    fk = next(iter(column_obj.foreign_keys))
    return fk.column.name


def get_model_from_column(column: Any) -> Any:
    return column.parent.class_


class BooleanFilter:
    def __init__(
        self,
        column: MODEL_ATTR,
        title: str | None = None,
        parameter_name: str | None = None,
    ):
        self.column = column
        self.title = title or get_title(column)
        self.parameter_name = parameter_name or get_parameter_name(column)

    async def lookups(
        self, request: Request, model: Any, run_query: Callable[[Select], Any]
    ) -> list[tuple[str, bool, str]]:
        param = request.query_params.get(self.parameter_name)
        lookup = []
        for display in ["All", "Yes", "No"]:
            if display == "All":
                query = "?"
                is_selected = param is None
                lookup.append((query, is_selected, display))
            else:
                val = str(display == "Yes").lower()
                query = f"?{self.parameter_name}={val}"
                is_selected = val == param
                lookup.append((query, is_selected, display))
        return lookup

    async def get_filtered_query(self, query: Select, value: Any, model: Any) -> Select:
        column_obj = get_column_obj(self.column, model)
        if value == "true":
            return query.filter(column_obj.is_(True))
        elif value == "false":
            return query.filter(column_obj.is_(False))
        else:
            return query

    def get_query_values(self, request):
        return request.query_params.get(self.parameter_name)


class AllUniqueStringValuesFilter:
    def __init__(
        self,
        column: MODEL_ATTR,
        title: str | None = None,
        parameter_name: str | None = None,
    ):
        self.column = column
        self.title = title or get_title(column)
        self.parameter_name = parameter_name or get_parameter_name(column)

    async def lookups(
        self, request: Request, model: Any, run_query: Callable[[Select], Any]
    ) -> list[tuple[str, bool, str]]:
        column_obj = get_column_obj(self.column, model)
        param = request.query_params.getlist(self.parameter_name)
        selected = not param
        result = await run_query(select(column_obj).distinct())
        lookup = [("?", selected, "All")]
        for val in result:
            is_selected = val[0] in param
            query = f"?{self.parameter_name}={val[0]}"
            lookup.append((query, is_selected, val[0]))
        return lookup

    async def get_filtered_query(self, query: Select, value: Any, model: Any) -> Select:
        if value == "":
            return query

        column_obj = get_column_obj(self.column, model)
        stmt = query.filter(column_obj.in_(value))
        return stmt

    def get_query_values(self, request):
        return request.query_params.getlist(self.parameter_name)
