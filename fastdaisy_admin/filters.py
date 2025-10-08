from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import DATE, DATETIME, inspect, or_
from sqlalchemy.sql.expression import Select, select
from starlette.requests import Request

if TYPE_CHECKING:
    pass


def prettify_attribute_name(column: str) -> str:
    return re.sub(r"_([A-Za-z])", r" \1", column)


def get_column_obj(column: str, model: Any = None) -> Any:
    if model is None:
        raise ValueError("model is required for string column filters")
    return getattr(model, column)


def get_foreign_column(col: str, model):
    rel_prop = inspect(model).relationships[col]
    column = next(iter(rel_prop.local_columns))
    fk = next(iter(column.foreign_keys))
    return column, fk.column.name, rel_prop.mapper.class_


class BooleanFilter:
    def __init__(self, column: str, model):
        self.column = column
        self.lookup_isnull = f"{self.column}__isnull"
        self.field = get_column_obj(self.column, model)

    async def lookups(self, request: Request, run_query: Callable[[Select], Any]) -> list[tuple[str, bool, str]]:
        param_value = self.get_query_values(request)
        lookups = [("?", param_value is None, "All")]

        for display in ("True", "False"):
            val = display.lower()
            query = f"?{self.column}={val}"
            is_selected = val == param_value
            lookups.append((query, is_selected, display))

        if self.field.nullable:
            unknown = "Unknown"
            is_selected = unknown == param_value
            lookups.append((f"?{self.lookup_isnull}=True", is_selected, unknown))
        return lookups

    async def get_filtered_query(self, query: Select, value: Any) -> Select:
        if value == "true":
            return query.filter(self.field.is_(True))
        elif value == "false":
            return query.filter(self.field.is_(False))
        elif value == "Unknown":
            return query.filter(self.field.is_(None))
        return query

    def get_query_values(self, request):
        if request.query_params.get(self.lookup_isnull) == "True":
            return "Unknown"
        return request.query_params.get(self.column)

    def has_parameter(self, request: Request) -> bool:
        return any(param in request.query_params for param in self.parameter_name.split(","))

    @property
    def parameter_name(self) -> str:
        parameter = self.column
        if self.field.nullable:
            parameter += f",{self.lookup_isnull}"
        return parameter

    @property
    def title(self) -> str:
        return prettify_attribute_name(self.column)

    @property
    def has_multiple_choice(self):
        return ""


class AllUniqueStringValuesFilter:
    def __init__(self, column: str, model):
        self.column = column
        self.field = get_column_obj(self.column, model)
        self.lookup_isnull = f"{self.column}__isnull"
        self.isnull = "True"

    async def lookups(self, request: Request, run_query: Callable[[Select], Any]) -> list[tuple[str, bool, str]]:
        param_value = self.get_query_values(request)
        selected = param_value == []
        result = await run_query(select(self.field).where(self.field.is_not(None)).distinct())
        lookup = [("?", selected, "All")]
        for val in result:
            is_selected = param_value and str(val[0]) in param_value
            query = f"?{self.column}={val[0]}"
            lookup.append((query, is_selected, val[0]))

        if self.field.nullable:
            is_selected = True in param_value
            lookup.append((f"?{self.lookup_isnull}={self.isnull}", is_selected, "----"))

        return lookup

    async def get_filtered_query(self, query: Select, values: list[Any]) -> Select:
        if not values:
            return query
        include_null = True in values
        values = [v for v in values if v != True]
        conditions = []
        if values:
            conditions.append(self.field.in_(values))
        if include_null:
            conditions.append(self.field.is_(None))

        if conditions:
            query = query.where(or_(*conditions))

        return query

    def get_query_values(self, request):
        query_keys = request.query_params
        keys = [self.column, f"{self.column}__in"]
        values = []
        for key in keys:
            if key in query_keys:
                values.extend(query_keys.get(key).split(","))
                break
        if self.field.nullable:
            isnull = query_keys.get(self.lookup_isnull)
            if isnull:
                values.append(isnull == self.isnull)
        return values

    def has_parameter(self, request):
        query_keys = request.query_params
        if self.field.nullable:
            if self.lookup_isnull in query_keys:
                return True
        return any(key in query_keys for key in (self.column, f"{self.column}__in"))

    @property
    def parameter_name(self) -> str:
        parameter = self.column
        if self.field.nullable:
            parameter += f",{self.lookup_isnull}"
        return parameter

    @property
    def title(self):
        return prettify_attribute_name(self.column)

    @property
    def has_multiple_choice(self):
        return "multiple"


class DateFieldFilter:
    def __init__(self, column: str, model):
        self.column = column
        self.field = get_column_obj(self.column, model)
        self.lookup_since = f"{self.column}__gte"
        self.lookup_until = f"{self.column}__lt"
        self.lookup_isnull = f"{self.column}__isnull"
        today: date | datetime
        if isinstance(self.field.type, DATETIME):
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        elif isinstance(self.field.type, DATE):
            today = datetime.now().date()

        self.options = (
            ("Today", {"start": today, "end": today + timedelta(days=1)}),
            ("Past 7 days", {"start": today - timedelta(days=7), "end": today + timedelta(days=1)}),
            (
                "This month",
                {
                    "start": today.replace(day=1),
                    "end": today.replace(year=today.year + 1, month=1, day=1)
                    if today.month == 12
                    else today.replace(month=today.month + 1, day=1),
                },
            ),
            (
                "This year",
                {"start": today.replace(month=1, day=1), "end": today.replace(year=today.year + 1, month=1, day=1)},
            ),
        )

    async def lookups(self, request: Request, run_query: Callable[[Select], Any]) -> list[tuple[str, bool, str]]:
        param_value = self.get_query_values(request)
        lookups = [("?", param_value is None, "All")]

        for display, dates in self.options:
            start_str = dates["start"].isoformat()
            end_str = dates["end"].isoformat()
            query = f"?{self.lookup_since}={start_str}&{self.lookup_until}={end_str}"
            is_selected = isinstance(param_value, tuple) and param_value == (start_str, end_str)
            lookups.append((query, is_selected, display))

        if self.field.nullable:
            is_selected = isinstance(param_value, bool)
            lookups.append((f"?{self.lookup_isnull}=True", is_selected, "No date"))
        return lookups

    async def get_filtered_query(self, query: Select, value: Any) -> Select:
        if not value:
            return query

        if isinstance(value, tuple):
            start, end = tuple(map(lambda x: datetime.fromisoformat(x), value))
            query = query.filter(self.field >= start, self.field < end)
        elif isinstance(value, bool):
            query = query.filter(self.field.is_(None))
        return query

    def get_query_values(self, request):
        since = request.query_params.get(self.lookup_since)
        until = request.query_params.get(self.lookup_until)
        is_null = request.query_params.get(self.lookup_isnull)
        if since and until:
            return (since, until)
        if is_null == "True":
            return True
        return None

    def has_parameter(self, request):
        parameters = self.parameter_name.split(",")[:-1]
        if self.field.nullable:
            if self.lookup_isnull in request.query_params:
                return True
        return all(param in request.query_params for param in parameters)

    @property
    def parameter_name(self) -> str:
        parameter = f"{self.lookup_since},{self.lookup_until}"
        if self.field.nullable:
            parameter += f",{self.lookup_isnull}"
        return parameter

    @property
    def title(self) -> str:
        return prettify_attribute_name(self.column)

    @property
    def has_multiple_choice(self) -> str:
        return ""


class ForeignKeyFilter:
    def __init__(self, column: str, model):
        self.column = column
        self.isnull = "True"
        self.fk_column, self.fk_target_column_name, self.relation_class = get_foreign_column(column, model)
        self.lookup_isnull = f"{self.fk_column.name}__isnull"

    async def lookups(self, request: Request, run_query: Callable[[Select], Any]) -> list[tuple[str, bool, str]]:
        param = self.get_query_values(request)
        selected = param == []
        result = await run_query(select(self.relation_class).distinct())
        lookup = [("?", selected, "All")]
        for val in result:
            id_ = getattr(val[0], self.fk_target_column_name)
            is_selected = param and str(id_) in param
            query = f"?{self.fk_column.name}={id_}"
            lookup.append((query, is_selected, val[0]))

        if self.fk_column.nullable:
            is_selected = True in param
            lookup.append((f"?{self.lookup_isnull}={self.isnull}", is_selected, "----"))

        return lookup

    async def get_filtered_query(self, query: Select, values: list[Any]) -> Select:
        if not values:
            return query
        include_null = True in values
        values = [v for v in values if v != True]
        conditions = []
        if values:
            conditions.append(self.fk_column.in_(values))
        if include_null:
            conditions.append(self.fk_column.is_(None))
        if conditions:
            query = query.where(or_(*conditions))

        return query

    def get_query_values(self, request):
        query_keys = request.query_params
        keys = [self.fk_column.name, f"{self.fk_column.name}__in"]
        values = []
        for key in keys:
            if key in query_keys:
                values.extend(query_keys.get(key).split(","))
                break
        if self.fk_column.nullable:
            isnull = query_keys.get(self.lookup_isnull)
            if isnull:
                values.append(isnull == self.isnull)
        return values

    def has_parameter(self, request):
        query_keys = request.query_params
        if self.fk_column.nullable:
            if self.lookup_isnull in query_keys:
                return True
        return any(key in query_keys for key in (self.fk_column.name, f"{self.fk_column.name}__in"))

    @property
    def parameter_name(self) -> str:
        parameter = self.fk_column.name
        if self.fk_column.nullable:
            parameter += f",{self.lookup_isnull}"
        return parameter

    @property
    def title(self):
        return prettify_attribute_name(self.column)

    @property
    def has_multiple_choice(self):
        return "multiple"
