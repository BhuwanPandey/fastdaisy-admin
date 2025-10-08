from __future__ import annotations

import builtins
import inspect as inzpect
import json
import time
from collections import defaultdict
from collections.abc import AsyncGenerator, Callable, Generator, ItemsView, Sequence
from enum import Enum
from typing import TYPE_CHECKING, Any, ClassVar, no_type_check

import anyio
from sqlalchemy import DATE, DATETIME, Boolean, Column, String, asc, cast, desc, func, inspect, or_
from sqlalchemy.exc import NoInspectionAvailable
from sqlalchemy.ext.declarative import DeclarativeMeta
from sqlalchemy.orm import Mapper, RelationshipProperty, class_mapper, selectinload, sessionmaker
from sqlalchemy.orm.exc import DetachedInstanceError
from sqlalchemy.sql.elements import ClauseElement
from sqlalchemy.sql.expression import Select, select
from starlette.datastructures import URL
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import StreamingResponse
from wtforms import Field, Form
from wtforms.fields.core import UnboundField

from fastdaisy_admin._queries import Query
from fastdaisy_admin._types import MODEL_ATTR, AdminAction, ColumnFilter
from fastdaisy_admin.actions import delete_selected
from fastdaisy_admin.exceptions import InvalidField, InvalidModelError
from fastdaisy_admin.filters import AllUniqueStringValuesFilter, BooleanFilter, DateFieldFilter, ForeignKeyFilter
from fastdaisy_admin.formatters import BASE_FORMATTERS
from fastdaisy_admin.forms import ModelConverter, ModelConverterBase, get_model_form
from fastdaisy_admin.helpers import (
    T,
    Writer,
    get_object_identifier,
    get_primary_keys,
    is_relationship,
    object_identifier_values,
    secure_filename,
    slugify_class_name,
    stream_to_csv,
)

# stream_to_csv,
from fastdaisy_admin.pagination import Pagination
from fastdaisy_admin.templating import Jinja2Templates

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from fastdaisy_admin.application import BaseAdmin

__all__ = [
    "BaseView",
    "ModelView",
]


class BaseModelView:
    def is_visible(self, request: Request) -> bool:
        """Override this method if you want dynamically
        hide or show administrative views from admin menu structure
        By default, item is visible in menu.
        Both is_visible and is_accessible to be displayed in menu.
        """
        return True

    def is_accessible(self, request: Request) -> bool:
        """Override this method to add permission checks.
        Admin section does not make any assumptions about the authentication system
        used in your application, so it is up to you to implement it.
        By default, it will allow access for everyone.
        """
        return True


class BaseView(BaseModelView):
    """Base class for defining admnistrative views for the model.

    ???+ usage
        ```python
        from fastdaisy_admin import BaseView, expose

        class CustomAdmin(BaseView):
            name = "Custom Page"
            icon = "fa-solid fa-chart-line"

            @expose("/custom", methods=["GET"])
            async def test_page(self, request: Request):
                return await self.templates.TemplateResponse(request, "custom.html")

        admin.add_base_view(CustomAdmin)
        ```
    """

    # Internals
    is_model: ClassVar[bool] = False
    templates: ClassVar[Jinja2Templates]
    _admin_ref: ClassVar[BaseAdmin]

    name: ClassVar[str]
    """Name of the view to be displayed."""

    divider_title: ClassVar[str] = ""

    identity: ClassVar[str] = ""
    """Same as name but it will be used for URL of the endpoints."""

    methods: ClassVar[list[str]] = ["GET"]
    """List of method names for the endpoint.
    By default it's set to `["GET"]` only.
    """

    include_in_schema: ClassVar[bool] = True
    """Control whether this endpoint
    should be included in the schema.
    """

    icon: ClassVar[str] = ""
    """Display icon for ModelAdmin in the sidebar.
    Currently only supports FontAwesome icons.
    """

    category: ClassVar[str] = ""
    """Category name to group views together."""

    category_icon: ClassVar[str] = ""
    """Display icon for category in the sidebar."""


class ModelViewMeta(type):
    """Metaclass used to specify class variables in ModelView.

    Danger:
        This class should almost never be used directly.
    """

    @no_type_check
    def __new__(mcls, name, bases, attrs: dict):
        cls: type[ModelView] = super().__new__(mcls, name, bases, attrs)

        model = attrs.get("model")

        if not model:
            return cls

        try:
            inspect(model)
        except NoInspectionAvailable:
            raise InvalidModelError(f"Class {model.__name__} is not a SQLAlchemy model.")

        cls.pk_columns = get_primary_keys(model)
        cls.identity = slugify_class_name(model.__name__)
        cls.model = model

        cls.name = attrs.get("name", cls.model.__name__).capitalize()
        cls.name_plural = attrs.get("name_plural", f"{cls.name}s").capitalize()

        mcls._check_conflicting_options(["column_list", "column_exclude_list"], attrs)
        mcls._check_conflicting_options(["form_columns", "form_excluded_columns"], attrs)
        mcls._check_conflicting_options(["column_export_list", "column_export_exclude_list"], attrs)

        return cls

    @classmethod
    def _check_conflicting_options(mcls, keys: list[str], attrs: dict) -> None:
        if all(k in attrs for k in keys):
            raise AssertionError(f"Cannot use {' and '.join(keys)} together.")


class ModelView(BaseView, metaclass=ModelViewMeta):
    """Base class for defining admnistrative behaviour for the model.

    ???+ usage
        ```python
        from fastdaisy_admin import ModelView

        from mymodels import User # SQLAlchemy model

        class UserAdmin(ModelView):
            model = User
            can_create = True
        ```
    """

    model: ClassVar[type]

    # Internals
    pk_columns: ClassVar[tuple[Column]]
    session_maker: ClassVar[sessionmaker | async_sessionmaker]
    is_async: ClassVar[bool] = False
    is_model: ClassVar[bool] = True

    name_plural: ClassVar[str]
    """Plural name of ModelView.
    Default value is Model class name + `s`.
    """

    # Permissions
    can_create: ClassVar[bool] = True
    """Permission for creating new Models. Default value is set to `True`."""

    can_edit: ClassVar[bool] = True
    """Permission for editing Models. Default value is set to `True`."""

    only_view: ClassVar[bool] = False
    """Permission for displaying Models records. Default value is set to `False`."""

    can_delete: ClassVar[bool] = True
    """Permission for deleting Models. Default value is set to `True`."""

    can_export: ClassVar[bool] = True
    """Permission for exporting lists of Models.
    Default value is set to `True`.
    """

    # List page
    column_list: ClassVar[Sequence[MODEL_ATTR]]
    """List of columns to display in `List` page.
    Columns can either be string names or SQLAlchemy columns.

    ???+ note
        By default only Model string representation is displayed.

    ???+ example
        ```python
        class UserAdmin(ModelView):
            model = User
            column_list = [User.id, User.name]
        ```
    """

    column_exclude_list: ClassVar[Sequence[MODEL_ATTR]] = []
    """List of columns to exclude in `List` page.
    Columns can either be string names or SQLAlchemy columns.

    ???+ example
        ```python
        class UserAdmin(ModelView):
            model = User
            column_exclude_list = [User.id, User.name]
        ```
    """
    column_display_link: ClassVar[Sequence[MODEL_ATTR]]
    """List of columns that allow user to navigate to `Edit` page.
    Columns can either be string names or SQLAlchemy columns.

    ???+ example
        ```python
        class UserAdmin(ModelView):
            model = User
            column_display_link = [User.id, User.name]
        ```
    """

    column_formatters: ClassVar[dict[MODEL_ATTR, Callable[[type, Column], Any]]] = {}
    """Dictionary of list view column formatters.
    Columns can either be string names or SQLAlchemy columns.

    ???+ example
        ```python
        class UserAdmin(ModelView):
            column_formatters = {User.name: lambda m, a: m.name[:10]}
        ```

    The format function has the prototype:
    ???+ formatter
        ```python
        def formatter(model, attribute):
            # `model` is model instance
            # `attribute` is a Union[ColumnProperty, RelationshipProperty]
            pass
        ```
    """

    list_per_page: ClassVar[int] = 10
    """Default number of items to display in `List` page pagination.
    Default value is set to `10`.

    ???+ example
        ```python
        class UserAdmin(ModelView):
            model = User
            list_per_page = 25
        ```
    """

    column_searchable_list: ClassVar[Sequence[MODEL_ATTR]] = []
    """A collection of the searchable columns.
    It is assumed that only text-only fields are searchable,
    but it is up to the model implementation to decide.

    ???+ example
        ```python
        class UserAdmin(ModelView):
            model = User
            column_searchable_list = [User.name]
        ```
    """

    column_filters: ClassVar[Sequence[MODEL_ATTR]] = []
    """Collection of the filterable columns for the list view.
    Columns can either be string names or SQLAlchemy columns.

    ???+ example
        ```python
        class UserAdmin(ModelView):
            model = User
            column_filters = [User.is_admin]
        ```
    """
    actions: ClassVar[Sequence[AdminAction]] = []
    """Collection of the decorated action functions.

    ???+ example
        ```python

        @action(name='action_name')
        def some_action(modelview,request,objects):
            ...

        class UserAdmin(ModelView):
            model = User
            actions = [some_action]
        ```
    """

    column_sortable_list: ClassVar[Sequence[MODEL_ATTR]] = []
    """Collection of the sortable columns for the list view.

    ???+ example
        ```python
        class UserAdmin(ModelView):
            model = User
            column_sortable_list = [User.name]
        ```
    """

    column_default_sort: ClassVar[MODEL_ATTR | tuple[MODEL_ATTR, bool] | list] = []
    """Default sort column if no sorting is applied.

    ???+ example
        ```python
        class UserAdmin(ModelView):
            model = User
            column_default_sort = "email"
        ```

    You can use tuple to control ascending descending order. In following example, items
    will be sorted in descending order:

    ???+ example
        ```python
        class UserAdmin(ModelView):
            model = User
            column_default_sort = ("email", True)
        ```

    If you want to sort by more than one column, you can pass a list of tuples

    ???+ example
        ```python
        class UserAdmin(ModelView):
            model = User
            column_default_sort = [("email", True), ("name", False)]
        ```
    """

    save_as: ClassVar[bool] = False
    """Set `save_as` to enable a "save as new" feature on admin change forms.

    Normally, objects have three save options:
    ``Save`, `Save and continue editing` and `Save and add another`.

    If save_as is True, `Save and add another` will be replaced
    by a `Save as new` button
    that creates a new object (with a new ID)
    rather than updating the existing object.

    By default, `save_as` is set to `False`.
    """

    save_as_continue: ClassVar[bool] = True
    """When `save_as=True`, the default redirect after saving the new object
    is to the edit view for that object.
    If you set `save_as_continue=False`, the redirect will be to the list view.

    By default, `save_as_continue` is set to `True`.
    """

    # Templates
    list_template: ClassVar[str] = "fastdaisy_admin/list.html"
    """List view template. Default is `fastdaisy_admin/list.html`."""

    create_template: ClassVar[str] = "fastdaisy_admin/create.html"
    """Create view template. Default is `fastdaisy_admin/create.html`."""

    edit_template: ClassVar[str] = "fastdaisy_admin/edit.html"
    """Edit view template. Default is `fastdaisy_admin/edit.html`."""

    # Template configuration
    show_compact_lists: ClassVar[bool] = True
    """Show compact lists. Default is `True`. 
    If False, when showing lists of objects, each object will be \
    displayed in a separate line."""

    # Export
    column_export_list: ClassVar[list[MODEL_ATTR]] = []
    """List of columns to include when exporting.
    Columns can either be string names or SQLAlchemy columns.

    ???+ example
        ```python
        class UserAdmin(ModelView):
            model = User
            column_export_list = [User.id, User.name]
        ```
    """

    column_export_exclude_list: ClassVar[list[MODEL_ATTR]] = []
    """List of columns to exclude when exporting.
    Columns can either be string names or SQLAlchemy columns.

    ???+ example
        ```python
        class UserAdmin(ModelView):
            model = User
            column_export_exclude_list = [User.id, User.name]
        ```
    """

    export_types: ClassVar[list[str]] = ["csv", "json"]
    """A list of available export filetypes.
    Currently only `csv` is supported.
    """

    export_max_rows: ClassVar[int] = 0
    """Maximum number of rows allowed for export.
    Unlimited by default.
    """

    # Form
    form: ClassVar[type[Form] | None] = None
    """Form class.
    Override if you want to use custom form for your model.
    Will completely disable form scaffolding functionality.

    ???+ example
        ```python
        class MyForm(Form):
            name = StringField('Name')

        class MyModelView(ModelView):
            model = MyModel
            form = MyForm
        ```
    """

    form_base_class: ClassVar[type[Form]] = Form
    """Base form class.
    Will be used by form scaffolding function when creating model form.
    Useful if you want to have custom constructor or override some fields.

    ???+ example
        ```python
        class MyBaseForm(Form):
            def do_something(self):
                pass

        class MyModelView(ModelView):
            model = MyModel
            form_base_class = MyBaseForm
        ```
    """

    form_args: ClassVar[dict[str, dict[str, Any]]] = {}
    """Dictionary of form field arguments.
    Refer to WTForms documentation for list of possible options.

    ???+ example
        ```python
        from wtforms.validators import DataRequired

        class MyModelView(ModelView):
            model = MyModel
            form_args = dict(
                name=dict(label="User Name", validators=[DataRequired()])
            )
        ```
    """

    form_widget_args: ClassVar[dict[str, dict[str, Any]]] = {}
    """Dictionary of form widget rendering arguments.
    Use this to customize how widget is rendered without using custom template.

    ???+ example
        ```python
        class UserAdmin(ModelView):
            model = User
            form_widget_args = {
                "email": {
                    "readonly": True,
                },
            }
        ```
    """

    form_columns: ClassVar[Sequence[MODEL_ATTR]] = []
    """List of columns to include in the form.
    Columns can either be string names or SQLAlchemy columns.

    ???+ note
        By default all columns of Model are included in the form.

    ???+ example
        ```python
        class UserAdmin(ModelView):
            form_columns = [User.name, User.mail]
        ```
    """

    form_excluded_columns: ClassVar[Sequence[MODEL_ATTR]] = []
    """List of columns to exclude from the form.
    Columns can either be string names or SQLAlchemy columns.

    ???+ example
        ```python
        class UserAdmin(ModelView):
            model = User
            form_excluded_columns = [User.id]
        ```
    """

    form_overrides: ClassVar[dict[str, type[Field]]] = {}
    """Dictionary of form column overrides.

    ???+ example
        ```python
        class UserAdmin(ModelView):
            model = User
            form_overrides = dict(name=wtf.FileField)
        ```
    """

    form_converter: ClassVar[type[ModelConverterBase]] = ModelConverter
    """Custom form converter class.
    Useful if you want to add custom form conversion in addition to the defaults.

    ???+ example
        ```python
        class PhoneNumberConverter(ModelConverter):
            pass

        class UserAdmin(ModelAdmin):
            model = User
            form_converter = PhoneNumberConverter
        ```
    """

    form_rules: ClassVar[list[str]] = []
    """List of rendering rules for model creation and edit form.
    This property changes default form rendering behavior and to rearrange
    order of rendered fields, add some text between fields, group them, etc.
    If not set, will use default Flask-Admin form rendering logic.

    ???+ example
        ```python
        class UserAdmin(ModelAdmin):
            model = User
            form_rules = [
                "first_name",
                "last_name",
            ]
        ```
    """

    form_create_rules: ClassVar[list[str]] = []
    """Customized rules for the create form. Cannot be specified with `form_rules`."""

    form_edit_rules: ClassVar[list[str]] = []
    """Customized rules for the edit form. Cannot be specified with `form_rules`."""

    # General options
    column_labels: ClassVar[dict[MODEL_ATTR, str]] = {}
    """A mapping of column labels, used to map column names to new names.
    Dictionary keys can be string names or SQLAlchemy columns with string values.

    ???+ example
        ```python
        class UserAdmin(ModelView):
            model = User
            column_labels = {User.mail: "Email"}
        ```
    """

    column_type_formatters: ClassVar[dict[type, Callable]] = BASE_FORMATTERS
    """Dictionary of value type formatters to be used in the list view.

    By default, two types are formatted:

        - None will be displayed as an empty string
        - bool will be displayed as a checkmark if it is True otherwise as an X.

    If you don't like the default behavior and don't want any type formatters applied,
    just override this property with an empty dictionary:

    ???+ example
        ```python
        class UserAdmin(ModelView):
            model = User
            column_type_formatters = dict()
        ```
    """

    def __init__(self) -> None:
        self._mapper: Mapper = inspect(self.model)
        self._has_column_link: dict[str, bool] = {}

        if self.model.__str__ == object.__str__:

            def custom_str(self_obj):
                first_pk = [pk.name for pk in self.pk_columns][0]
                pk = getattr(self_obj, first_pk, None)
                return f"{self.model.__name__} object ({pk})"

            setattr(self.model, "__str__", custom_str)

        if self.model.__repr__ == object.__repr__:

            def custom_repr(self_obj):
                return f"<{self.model.__name__}: {self_obj.__str__()}>"

            setattr(self.model, "__repr__", custom_repr)

        # Exclude foreignkey field
        self._prop_names = [
            attr.key
            for attr in self._mapper.attrs
            if (hasattr(attr, "columns") and not bool(attr.columns[0].foreign_keys)) or is_relationship(attr)
        ]

        self._delete_relations = [
            getattr(self.model, rel.key) for rel in self._mapper.relationships if "delete" in rel.cascade
        ]
        self._relation_names = [relation.key for relation in self._mapper.relationships]

        self.model_columns = {col.name: col.type for col in self._mapper.columns}
        self._column_labels = self._build_column_pairs(self.column_labels)
        self._column_labels_value_by_key = {v: k for k, v in self._column_labels.items()}

        self._list_prop_names = self.get_list_columns()
        self._list_relation_names = [name for name in self._list_prop_names if name in self._relation_names]
        self._list_relations = [getattr(self.model, name) for name in self._list_relation_names]

        self._list_formatters = self._build_column_pairs(self.column_formatters)

        self._form_prop_names = self.get_form_columns()
        self._form_relation_names = [name for name in self._form_prop_names if name in self._relation_names]
        self._form_relations = [getattr(self.model, name) for name in self._form_relation_names]
        self._export_prop_names = self.get_export_columns()

        self._search_fields = [self._get_prop_name(attr) for attr in self.column_searchable_list]
        self._sort_fields = [self._get_prop_name(attr) for attr in self.column_sortable_list]

        self._refresh_form_rules_cache()

        self._custom_actions_in_list: dict[str, AdminAction] = {}
        self._default_action = {"delete_selected": delete_selected}
        # self._custom_actions_confirmation: Dict[str, str] = {}

    def _str_to_model(self, column: str):
        if column == "__str__":
            return str(self.model.__name__).capitalize()

        return column.upper() if column == self.pk_columns[0].name else column.capitalize()

    def _run_arbitrary_query_sync(self, stmt: ClauseElement) -> Any:
        with self.session_maker(expire_on_commit=False) as session:
            result = session.execute(stmt)
            return result.all()

    async def _run_arbitrary_query(self, stmt: ClauseElement) -> Any:
        if self.is_async:
            async with self.session_maker(expire_on_commit=False) as session:
                result = await session.execute(stmt)
                return result.all()
        else:
            return self._run_arbitrary_query_sync(stmt)

    def _run_query_sync(self, stmt: ClauseElement) -> Any:
        with self.session_maker(expire_on_commit=False) as session:
            result = session.execute(stmt)
            return result.scalars().unique().all()

    async def _run_query(self, stmt: ClauseElement) -> Any:
        if self.is_async:
            async with self.session_maker(expire_on_commit=False) as session:
                result = await session.execute(stmt)
                return result.scalars().unique().all()
        else:
            return await anyio.to_thread.run_sync(self._run_query_sync, stmt)

    def _build_url_for(self, name: str, request: Request, obj: Any) -> URL:
        return request.url_for(
            name,
            identity=slugify_class_name(obj.__class__.__name__),
            pk=get_object_identifier(obj),
        )

    def _get_prop_name(self, prop: MODEL_ATTR) -> str:
        return prop if isinstance(prop, str) else prop.key

    def _get_default_sort(self) -> list[tuple[str, bool]]:
        if self.column_default_sort:
            if isinstance(self.column_default_sort, list):
                return self.column_default_sort
            if isinstance(self.column_default_sort, tuple):
                return [self.column_default_sort]
            else:
                return [(self.column_default_sort, False)]

        return [(pk.name, False) for pk in self.pk_columns]

    def _default_formatter(self, value: Any) -> Any:
        if type(value) in self.column_type_formatters:
            formatter = self.column_type_formatters[type(value)]
            return formatter(value)
        return value

    def validate_page_number(self, number: int | None, default: int) -> int:
        if not number:
            return default

        try:
            num = int(number)
            if num < 1 or isinstance(num, float):
                raise ValueError

            return num
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid page or Page Not an Integer")

    def validate_page(self, number: int | str, default: int) -> int:
        try:
            num = int(number)
            if num < 1 or isinstance(num, float):
                raise ValueError
            return num
        except ValueError:
            return default

    async def count(self, request: Request, stmt: Select | None = None) -> int:
        if stmt is None:
            stmt = self.count_query(request)
        rows = await self._run_query(stmt)
        return rows[0]

    async def list(self, request: Request) -> Pagination:
        is_filter_applied = False
        page = self.validate_page(request.query_params.get("page", 0), 1)
        page_size = self.validate_page_number(self.list_per_page, 10)
        search = request.query_params.get("search", None)

        stmt = self.list_query(request)

        for relation in self._list_relations:
            stmt = stmt.options(selectinload(relation))

        for filter in self.get_filters(self.model):
            if filter.has_parameter(request):
                is_filter_applied = True
                values = filter.get_query_values(request)
                stmt = await filter.get_filtered_query(stmt, values)

        stmt = self.sort_query(stmt, request)
        total = count = await self.count(request)
        if search or is_filter_applied:
            if search:
                stmt = self.search_query(stmt=stmt, term=search)
            count = await self.count(request, select(func.count()).select_from(stmt.subquery()))

        stmt = stmt.limit(page_size).offset((page - 1) * page_size)
        rows = await self._run_query(stmt)

        pagination = Pagination(
            rows=rows,
            page=page,
            per_page=page_size,
            count=count,
        )
        pagination.is_filter_applied = is_filter_applied  # type: ignore[attr-defined]
        pagination.total = total  # type: ignore[attr-defined]
        return pagination

    async def get_model_objects(self, request: Request, limit: int | None = 0) -> builtins.list[Any]:
        # For unlimited rows this should pass None
        limit = None if limit == 0 else limit
        stmt = self.list_query(request).limit(limit)

        for relation in self._list_relations:
            stmt = stmt.options(selectinload(relation))

        rows = await self._run_query(stmt)
        return rows

    def get_relations_to_delete(self, model: type[DeclarativeMeta]) -> Generator[RelationshipProperty, None, None]:
        """
        Returns a generator of relationships from other models to this model
        that are either one-to-one or one-to-many and could be deleted (like in Django).
        """
        mapper = class_mapper(model)
        # mapper = inspect(model)
        for rel in mapper.relationships:
            # Ignore many-to-many relationships
            if rel.secondary is not None:
                continue
            if rel.direction.name in ("ONETOMANY", "ONETOONE"):
                yield rel

    async def get_deleted_objects(self, objects):
        model_container = defaultdict(set)

        async def nested_objects(obj, model_objs):
            model_name = f"{type(obj).__name__}s"
            model_objs[model_name].add(obj)
            for rel in self.get_relations_to_delete(type(obj)):
                try:
                    related = getattr(obj, rel.key)
                except DetachedInstanceError:
                    related = await self._lazyload_prop(obj, rel.key)

                if not related:
                    continue
                if rel.uselist:
                    for item in related:
                        await nested_objects(item, model_objs)
                else:
                    await nested_objects(related, model_objs)

        for obj in objects:
            await nested_objects(obj, model_container)
        return model_container

    async def get_model_objects_with_pk(self, selected):
        stmt = select(self.model)
        pks = get_primary_keys(self.model)
        pk_col = pks[0]
        stmt = stmt.where(pk_col.in_(selected))
        rows = await self._run_query(stmt)
        return rows

    async def _get_object_by_pk(self, stmt: Select) -> Any:
        rows = await self._run_query(stmt)
        return rows[0] if rows else None

    async def get_object_for_edit(self, request: Request) -> Any:
        stmt = self.form_edit_query(request)
        return await self._get_object_by_pk(stmt)

    async def get_object_for_delete(self, value: Any) -> Any:
        stmt = self._stmt_by_identifier(value)
        for rel in self._delete_relations:
            stmt = stmt.options(selectinload(rel))
        return await self._get_object_by_pk(stmt)

    def _stmt_by_identifier(self, identifier: str) -> Select:
        stmt: Select = select(self.model)
        pks = get_primary_keys(self.model)
        values = object_identifier_values(identifier, self.model)
        conditions = [pk == value for (pk, value) in zip(pks, values)]
        return stmt.where(*conditions)

    async def get_prop_value(self, obj: Any, prop: str) -> Any:
        _obj = obj
        for part in prop.split("."):
            try:
                obj = getattr(obj, part, None)
            except DetachedInstanceError:
                obj = await self._lazyload_prop(obj, part)

        if obj and isinstance(obj, Enum):
            obj = obj.name

        if callable(obj):
            obj = obj()

        if obj is None and hasattr(self, prop):
            attr = getattr(self, prop)
            if inzpect.ismethod(attr):
                obj = attr(_obj)

        return obj

    async def _lazyload_prop(self, obj: Any, prop: str) -> Any:
        if self.is_async:
            async with self.session_maker() as session:
                session.add(obj)
                return await session.run_sync(lambda: getattr(obj, prop))
        else:
            with self.session_maker() as session:
                session.add(obj)
                return await anyio.to_thread.run_sync(lambda: getattr(obj, prop))

    def has_link(self, column_name) -> bool:
        if column_name in self._has_column_link:
            return self._has_column_link[column_name]
        display_link = getattr(self, "column_display_link", None)
        column_props = self._list_prop_names
        if display_link:
            link_props = [self._get_prop_name(item) for item in self.column_display_link]
            result = column_name in set(column_props) & set(link_props)
        elif result := "__str__" == column_name:
            result = result
        else:
            result = column_name == column_props[0]

        self._has_column_link[column_name] = result
        return result

    @property
    def get_actions(self) -> ItemsView[str, tuple[str, Callable]]:
        actions = dict()
        if self.can_delete:
            key, func = next(iter(self._default_action.items()))
            title = f"{func._title} {self.name_plural}"
            description = title
            actions = {key: (description, func)}
        for name, func in self._custom_actions_in_list.items():
            actions[name] = (func._title, func)
        return actions.items()

    async def get_list_value(self, obj: Any, prop: str) -> tuple[Any, Any, bool]:
        """Get tuple of (value, formatted_value) for the list view."""

        value = await self.get_prop_value(obj, prop)
        formatter = self._list_formatters.get(prop)
        formatted_value = formatter(obj, prop) if formatter else self._default_formatter(value)
        has_column_link = self.has_link(prop)
        return value, formatted_value, has_column_link

    def reorder_columns(self, col: builtins.list[str]) -> builtins.list[str]:
        """
        Reorders columns such that relationship fields always at last position
        """
        original_set = set(col)
        to_move_set = set(self._relation_names)
        valid_to_move = [item for item in self._relation_names if item in original_set]
        reordered = [item for item in col if item not in to_move_set]

        return reordered + valid_to_move

    def _build_column_list(
        self,
        defaults: builtins.list[str],
        include: str | Sequence[MODEL_ATTR] | None = None,
        exclude: str | Sequence[MODEL_ATTR] | None = None,
    ) -> builtins.list[str]:
        """This function generalizes constructing a list of columns
        for any sequence of inclusions or exclusions.
        """
        if include == "__all__":
            return self._prop_names
        elif include:
            return [self._get_prop_name(item) for item in include]
        elif exclude:
            exclude = [self._get_prop_name(item) for item in exclude]
            return [prop for prop in self._prop_names if prop not in exclude]
        return defaults

    def get_list_columns(self) -> builtins.list[str]:
        """Get list of properties to display in List page."""

        column_list = getattr(self, "column_list", None)
        column_exclude_list = getattr(self, "column_exclude_list", None)
        columns = self._build_column_list(
            include=column_list,
            exclude=column_exclude_list,
            defaults=["__str__"],
        )
        ordered_columns = self.reorder_columns(columns)
        return ordered_columns

    def get_form_columns(self) -> builtins.list[str]:
        """Get list of properties to display in the form."""

        form_columns = getattr(self, "form_columns", None)
        form_excluded_columns = getattr(self, "form_excluded_columns", None)

        return self._build_column_list(
            include=form_columns,
            exclude=form_excluded_columns,
            defaults=self._prop_names,
        )

    def get_export_columns(self) -> builtins.list[str]:
        """Get list of properties to export."""

        columns = getattr(self, "column_export_list", None)
        excluded_columns = getattr(self, "column_export_exclude_list", None)

        columns = self._build_column_list(
            include=columns,
            exclude=excluded_columns,
            defaults=self._list_prop_names,
        )
        ordered_columns = self.reorder_columns(columns)
        return ordered_columns

    def get_column_type(self, column_name):
        """Return the column type class of a given model and column name."""
        for col in self._mapper.columns:
            if col.name == column_name:
                return type(col.type)

    def get_filter_for_column(self, columns: Sequence[MODEL_ATTR], model) -> builtins.list[ColumnFilter]:
        filters: builtins.list[ColumnFilter] = []

        for column in columns:
            column = self._get_prop_name(column)
            if column in self.model_columns:
                col_type = type(self.model_columns.get(column))
                if col_type is Boolean:
                    filters.append(BooleanFilter(column, model))
                elif col_type is DATE or col_type is DATETIME:
                    filters.append(DateFieldFilter(column, model))
                else:
                    filters.append(AllUniqueStringValuesFilter(column, model))
            elif column in self._relation_names and self._mapper.relationships[column].direction.name == "MANYTOONE":
                filters.append(ForeignKeyFilter(column, self))
            else:
                raise InvalidField(f"{column} is unsupported {self.model.__name__} Field")
        return filters

    def get_filters(self, model) -> builtins.list[ColumnFilter]:
        """Get list of filters."""

        fields: Sequence[MODEL_ATTR] = getattr(self, "column_filters")
        filters = self.get_filter_for_column(fields, model)
        return filters

    async def on_model_change(self, data: dict, model: Any, is_created: bool, request: Request) -> None:
        """Perform some actions before a model is created or updated.
        By default does nothing.
        """

    async def after_model_change(self, data: dict, model: Any, is_created: bool, request: Request) -> None:
        """Perform some actions after a model was created
        or updated and committed to the database.
        By default does nothing.
        """

    def _build_column_pairs(
        self,
        pair: dict[Any, Any],
    ) -> dict[str, Any]:
        pairs = {}
        for label, value in pair.items():
            pairs[self._get_prop_name(label)] = value
        return pairs

    async def delete_model(self, request: Request, pk: str | ModelView) -> None:
        await Query(self).delete(pk, request)

    async def insert_model(self, request: Request, data: dict) -> Any:
        return await Query(self).insert(data, request)

    async def update_model(self, request: Request, pk: str, data: dict) -> Any:
        return await Query(self).update(pk, data, request)

    async def on_model_delete(self, model: Any, request: Request) -> None:
        """Perform some actions before a model is deleted.
        By default does nothing.
        """

    async def after_model_delete(self, model: Any, request: Request) -> None:
        """Perform some actions after a model is deleted.
        By default do nothing.
        """

    async def scaffold_form(self, rules: builtins.list[str] | None = None) -> type[Form]:
        if self.form is not None:
            return self.form

        form = await get_model_form(
            model=self.model,
            session_maker=self.session_maker,
            only=self._form_prop_names,
            column_labels=self._column_labels,
            form_args=self.form_args,
            form_widget_args=self.form_widget_args,
            form_class=self.form_base_class,
            form_overrides=self.form_overrides,
            form_converter=self.form_converter,
        )

        if rules:
            self._validate_form_class(rules, form)

        return form

    def search_placeholder(self) -> str:
        """Return search placeholder text.

        ???+ example
            ```python
            class UserAdmin(ModelView):
                column_labels = dict(name="Name", email="Email")
                column_searchable_list = [User.name, User.email]

            # placeholder is: "Name, Email"
            ```
        """

        field_names = [self._column_labels.get(field, field) for field in self._search_fields]
        return ", ".join(field_names)

    def search_query(self, stmt: Select, term: str) -> Select:
        """Specify the search query given the SQLAlchemy statement
        and term to search for.
        It can be used for doing more complex queries like JSON objects. For example:

        ```py
        return stmt.filter(MyModel.name == term)
        ```
        """

        expressions = []
        for field in self._search_fields:
            model = self.model
            parts = field.split(".")
            for part in parts[:-1]:
                model = getattr(model, part).mapper.class_
                stmt = stmt.join(model)

            field = getattr(model, parts[-1])
            expressions.append(cast(field, String).ilike(f"%{term}%"))

        return stmt.filter(or_(*expressions))

    def list_query(self, request: Request) -> Select:
        """
        The SQLAlchemy select expression used for the list page which can be customized.
        By default it will select all objects without any filters.
        """

        return select(self.model)

    def form_edit_query(self, request: Request) -> Select:
        """
        The SQLAlchemy select expression used for the edit form page which can be
        customized. By default it will select the object by primary key(s) without any
        additional filters.
        """

        stmt = self._stmt_by_identifier(request.path_params["pk"])
        for relation in self._form_relations:
            stmt = stmt.options(selectinload(relation))
        return stmt

    def count_query(self, request: Request) -> Select:
        """
        The SQLAlchemy select expression used for the count query
        which can be customized.
        By default it will select all objects without any filters.
        """

        return select(func.count(self.pk_columns[0]))

    def sort_query(self, stmt: Select, request: Request) -> Select:
        """
        A method that is called every time the fields are sorted
        and that can be customized.
        By default, sorting takes place by default fields.

        The 'sortBy' and 'sort' query parameters are available in this request context.
        """
        sort_by = request.query_params.get("sortBy", None)
        sort = request.query_params.get("sort", "asc")

        if sort_by:
            sort_fields = [(sort_by, sort == "desc")]
        else:
            sort_fields = self._get_default_sort()

        for sort_field, is_desc in sort_fields:
            model = self.model

            parts = self._get_prop_name(sort_field).split(".")
            for part in parts[:-1]:
                model = getattr(model, part).mapper.class_
                stmt = stmt.join(model)

            if is_desc:
                stmt = stmt.order_by(desc(getattr(model, parts[-1])))
            else:
                stmt = stmt.order_by(asc(getattr(model, parts[-1])))

        return stmt

    def get_export_name(self, export_type: str) -> str:
        """The file name when exporting."""

        return f"{self.name}_{time.strftime('%Y-%m-%d_%H-%M-%S')}.{export_type}"

    async def export_data(
        self,
        data: builtins.list[T],
        export_type: str = "csv",
    ) -> StreamingResponse:
        if export_type == "csv":
            return await self._export_csv(data)
        elif export_type == "json":
            return await self._export_json(data)
        raise NotImplementedError("Only export_type='csv' or 'json' is implemented.")

    async def _export_csv(
        self,
        data: builtins.list[T],
    ) -> StreamingResponse:
        async def generate(writer: Writer) -> AsyncGenerator[Any, None]:
            # Append the column titles at the beginning
            yield writer.writerow(self._export_prop_names)

            for row in data:
                vals = [str(await self.get_prop_value(row, name)) for name in self._export_prop_names]
                yield writer.writerow(vals)

        # `get_export_name` can be subclassed.
        # So we want to keep the filename secure outside that method.
        filename = secure_filename(self.get_export_name(export_type="csv"))

        return StreamingResponse(
            content=stream_to_csv(generate),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f"attachment;filename={filename}"},
        )

    async def _export_json(
        self,
        data: builtins.list[T],
    ) -> StreamingResponse:
        async def generate() -> AsyncGenerator[str, None]:
            yield "["
            len_data = len(data)
            last_idx = len_data - 1
            separator = "," if len_data > 1 else ""

            for idx, row in enumerate(data):
                row_dict = {name: str(await self.get_prop_value(row, name)) for name in self._export_prop_names}
                yield json.dumps(row_dict, ensure_ascii=False) + (separator if idx < last_idx else "")

            yield "]"

        filename = secure_filename(self.get_export_name(export_type="json"))
        return StreamingResponse(
            content=generate(),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment;filename={filename}"},
        )

    def _refresh_form_rules_cache(self) -> None:
        if self.form_rules:
            self._form_create_rules = self.form_rules
            self._form_edit_rules = self.form_rules
        else:
            self._form_create_rules = self.form_create_rules
            self._form_edit_rules = self.form_edit_rules

    def _validate_form_class(self, ruleset: builtins.list[Any], form_class: type[Form]) -> None:
        form_fields = []
        for name, obj in form_class.__dict__.items():
            if isinstance(obj, UnboundField):
                form_fields.append(name)

        missing_fields = [field_name for field_name in form_fields if field_name not in ruleset]
        for field_name in missing_fields:
            delattr(form_class, field_name)
