from __future__ import annotations

import inspect
import io
import logging
from collections.abc import Awaitable, Callable, Sequence
from types import MethodType
from typing import (
    Any,
    cast,
)

from jinja2 import ChoiceLoader, FileSystemLoader, PackageLoader
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session, sessionmaker
from starlette.applications import Starlette
from starlette.datastructures import URL, FormData, UploadFile
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from fastdaisy_admin._menu import CategoryMenu, Menu, ViewMenu
from fastdaisy_admin._types import ASYNC_ENGINE_TYPE, ENGINE_TYPE, AdminAction
from fastdaisy_admin.authentication import AuthenticationBackend
from fastdaisy_admin.decorators import login_required
from fastdaisy_admin.forms import WTFORMS_ATTRS, WTFORMS_ATTRS_REVERSED
from fastdaisy_admin.helpers import (
    add_message,
    apply_class,
    get_messages,
    get_object_identifier,
    get_pk,
    is_async_session_maker,
)
from fastdaisy_admin.models import BaseView, ModelView
from fastdaisy_admin.templating import Jinja2Templates

__all__ = [
    "Admin",
]

logger = logging.getLogger(__name__)


class BaseAdmin:
    """Base class for implementing Admin interface.

    Danger:
        This class should almost never be used directly.
    """

    def __init__(
        self,
        app: Starlette,
        secret_key: str,
        engine: ENGINE_TYPE | None = None,
        session_maker: sessionmaker | async_sessionmaker | None = None,
        base_url: str = "/admin",
        title: str = "Admin",
        logo_url: str | None = None,
        favicon_url: str | None = None,
        templates_dir: str = "templates",
        middlewares: Sequence[Middleware] | None = None,
        authentication_backend: AuthenticationBackend | None = None,
    ) -> None:
        self.app = app
        self.engine = engine
        self.base_url = base_url
        self.templates_dir = templates_dir
        self.title = title
        self.logo_url = logo_url
        self.favicon_url = favicon_url

        assert isinstance(secret_key, str), f"SECRET KEY should be String but It contains {secret_key}"

        if session_maker:
            self.session_maker = session_maker
        elif isinstance(engine, Engine):
            self.session_maker = sessionmaker(bind=engine, class_=Session)
        else:
            engine = cast(ASYNC_ENGINE_TYPE, self.engine)
            self.session_maker = async_sessionmaker(bind=engine, class_=AsyncSession)

        self.session_maker.configure(autoflush=False, autocommit=False)
        self.is_async = is_async_session_maker(self.session_maker)

        self.authentication_backend = authentication_backend

        middlewares = list(middlewares) if middlewares is not None else []
        middlewares.insert(0, Middleware(SessionMiddleware, secret_key=secret_key))

        self.admin = Starlette(middleware=middlewares)
        self.templates = self.init_templating_engine()
        self._views: list[BaseView | ModelView] = []
        self._menu = Menu()

    def init_templating_engine(self) -> Jinja2Templates:
        templates = Jinja2Templates("templates")
        loaders = [
            FileSystemLoader(self.templates_dir),
            PackageLoader("fastdaisy_admin", "templates"),
        ]
        templates.env.loader = ChoiceLoader(loaders)
        templates.env.globals["min"] = min
        templates.env.globals["zip"] = zip
        templates.env.globals["admin"] = self
        templates.env.globals["is_list"] = lambda x: isinstance(x, list)
        templates.env.globals["get_object_identifier"] = get_object_identifier
        templates.env.globals["get_messages"] = get_messages
        templates.env.globals["get_pk"] = get_pk
        templates.env.filters["apply_class"] = apply_class
        return templates

    @property
    def views(self) -> list[BaseView | ModelView]:
        """Get list of ModelView and BaseView instances lazily.

        Returns:
            List of ModelView and BaseView instances added to Admin.
        """

        return self._views

    def has_modelview(self, name: str, obj) -> ModelView | None:
        for view in self.views:
            if isinstance(view, ModelView) and type(obj).__name__ == name:
                return view
        return None

    def _find_model_view(self, identity: str) -> ModelView:
        for view in self.views:
            if isinstance(view, ModelView) and view.identity == identity:
                return view
        raise HTTPException(status_code=404)

    def add_view(self, view: type[ModelView] | type[BaseView]) -> None:
        """Add ModelView or BaseView classes to Admin.
        This is a shortcut that will handle both `add_model_view` and `add_base_view`.
        """

        view._admin_ref = self
        if view.is_model:
            self.add_model_view(view)  # type: ignore
        else:
            self.add_base_view(view)

    def _find_decorated_funcs(
        self,
        view: type[BaseView | ModelView],
        view_instance: BaseView | ModelView,
        handle_fn: Callable[
            [MethodType, type[BaseView | ModelView], BaseView | ModelView],
            None,
        ],
    ) -> None:
        funcs = inspect.getmembers(view_instance, predicate=inspect.ismethod)
        for _, func in funcs[::-1]:
            handle_fn(func, view, view_instance)

    def _handle_action_decorated_func(self, view_instance: BaseView | ModelView) -> None:
        custom_action: list[AdminAction] = getattr(view_instance, "actions", [])
        for func in custom_action:
            if hasattr(func, "_action"):
                view_instance = cast(ModelView, view_instance)
                view_instance._custom_actions_in_list[getattr(func, "_title")] = func

    def _handle_expose_decorated_func(
        self,
        func: MethodType,
        view: type[BaseView | ModelView],
        view_instance: BaseView | ModelView,
    ) -> None:
        if hasattr(func, "_exposed"):
            if view.is_model:
                path = f"/{view_instance.identity}" + getattr(func, "_path")
                name = f"view-{view_instance.identity}-{func.__name__}"
            else:
                view.identity = getattr(func, "_identity")
                path = getattr(func, "_path")
                name = getattr(func, "_identity")
            self.admin.add_route(
                route=func,
                path=path,
                methods=getattr(func, "_methods"),
                name=name,
                include_in_schema=getattr(func, "_include_in_schema"),
            )

    def add_model_view(self, view: type[ModelView]) -> None:
        """Add ModelView to the Admin.

        **Example**
            ```python
            from fastdaisy_admin import Admin, ModelView

            class UserAdmin(ModelView):
                model = User

            admin.add_model_view(UserAdmin)
            ```
        """

        # Set database engine from Admin instance
        view.session_maker = self.session_maker
        view.is_async = self.is_async
        view.templates = self.templates
        view_instance = view()

        self._handle_action_decorated_func(view_instance)

        self._find_decorated_funcs(view, view_instance, self._handle_expose_decorated_func)

        self._views.append(view_instance)
        self._build_menu(view_instance)

    def add_base_view(self, view: type[BaseView]) -> None:
        """Add BaseView to the Admin.

        **Example**
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

        view.templates = self.templates
        view_instance = view()

        self._find_decorated_funcs(view, view_instance, self._handle_expose_decorated_func)
        self._views.append(view_instance)
        self._build_menu(view_instance)

    def _build_menu(self, view: ModelView | BaseView) -> None:
        if view.category:
            menu = CategoryMenu(name=view.category, icon=view.category_icon, divider=view.divider_title)
            menu.add_child(ViewMenu(view=view, name=view.name, icon=view.icon))
            self._menu.add(menu)
        else:
            self._menu.add(ViewMenu(view=view, icon=view.icon, name=view.name, divider=view.divider_title))


class BaseAdminView(BaseAdmin):
    """
    Manage right to access to an action from a model
    """

    async def _list(self, request: Request) -> None:
        model_view = self._find_model_view(request.path_params["identity"])
        if not model_view.is_accessible(request):
            raise HTTPException(status_code=403)

    async def _create(self, request: Request) -> None:
        model_view = self._find_model_view(request.path_params["identity"])
        if model_view.only_view or not model_view.can_create or not model_view.is_accessible(request):
            raise HTTPException(status_code=403)

    async def _delete(self, request: Request) -> None:
        model_view = self._find_model_view(request.path_params["identity"])
        if not model_view.can_delete or not model_view.is_accessible(request):
            raise HTTPException(status_code=403)

    async def _edit(self, request: Request) -> None:
        model_view = self._find_model_view(request.path_params["identity"])
        if not model_view.can_edit or not model_view.is_accessible(request):
            raise HTTPException(status_code=403)

    async def _export(self, request: Request) -> None:
        model_view = self._find_model_view(request.path_params["identity"])
        if not model_view.can_export or not model_view.is_accessible(request):
            raise HTTPException(status_code=403)
        if request.path_params["export_type"] not in model_view.export_types:
            raise HTTPException(status_code=404)


class Admin(BaseAdminView):
    """Main entrypoint to admin interface.

    **Example**
        ```python
        from fastapi import FastAPI
        from fastdaisy_admin import Admin, ModelView

        from mymodels import User # SQLAlchemy model


        app = FastAPI()
        secret_key = "SECRET"
        admin = Admin(app, secret_key, engine)


        class UserAdmin(ModelView):
            model = User
            column_list = [User.id, User.name]


        admin.add_view(UserAdmin)
        ```
    """

    def __init__(
        self,
        app: Starlette,
        secret_key: str,
        engine: ENGINE_TYPE | None = None,
        session_maker: sessionmaker | async_sessionmaker | None = None,
        base_url: str = "/admin",
        title: str = "Admin",
        logo_url: str | None = None,
        favicon_url: str | None = None,
        middlewares: Sequence[Middleware] | None = None,
        debug: bool = False,
        templates_dir: str = "templates",
        authentication_backend: AuthenticationBackend | None = None,
    ) -> None:
        """
        Args:
            app: Starlette or FastAPI application.
            engine: SQLAlchemy engine instance.
            session_maker: SQLAlchemy sessionmaker instance.
            base_url: Base URL for Admin interface.
            title: Admin title.
            logo_url: URL of logo to be displayed instead of title.
            favicon_url: URL of favicon to be displayed.
        """

        super().__init__(
            app=app,
            secret_key=secret_key,
            engine=engine,
            session_maker=session_maker,
            base_url=base_url,
            title=title,
            logo_url=logo_url,
            favicon_url=favicon_url,
            templates_dir=templates_dir,
            middlewares=middlewares,
            authentication_backend=authentication_backend,
        )

        statics = StaticFiles(packages=["fastdaisy_admin"])

        async def http_exception(request: Request, exc: Exception) -> Response | Awaitable[Response]:
            assert isinstance(exc, HTTPException)
            context = {
                "status_code": exc.status_code,
                "message": exc.detail,
            }
            return await self.templates.TemplateResponse(
                request, "fastdaisy_admin/error.html", context, status_code=exc.status_code
            )

        routes = [
            Mount("/statics", app=statics, name="statics"),
            Route("/", endpoint=self.index, name="index"),
            Route("/{identity}/list", endpoint=self.list, name="list", methods=["GET", "POST"]),
            Route(
                "/{identity}/create",
                endpoint=self.create,
                name="create",
                methods=["GET", "POST"],
            ),
            Route(
                "/{identity}/edit/{pk:path}",
                endpoint=self.edit,
                name="edit",
                methods=["GET", "POST"],
            ),
            Route(
                "/{identity}/delete/{pk:path}",
                endpoint=self.delete,
                name="delete",
                methods=["GET", "POST"],
            ),
            Route("/{identity}/export/{export_type}", endpoint=self.export, name="export"),
            Route("/login", endpoint=self.login, name="login", methods=["GET", "POST"]),
            Route("/logout", endpoint=self.logout, name="logout", methods=["POST"]),
        ]

        self.admin.router.routes = routes
        self.admin.exception_handlers = {HTTPException: http_exception}
        self.admin.debug = debug

        self.app.mount(base_url, app=self.admin, name="admin")

    @login_required
    async def index(self, request: Request) -> Response:
        """Index route which can be overridden to create dashboards."""

        return await self.templates.TemplateResponse(request, "fastdaisy_admin/index.html")

    @login_required
    async def list(self, request: Request) -> Response:
        """List route to display paginated Model instances."""

        identity = request.path_params["identity"]
        await self._list(request)
        model_view = self._find_model_view(identity)
        form = await request.form()
        selected = form.getlist("_selected_action")
        actions = model_view.get_actions
        if actions and request.method == "POST":
            if selected:
                response = await self.response_action(form, request, model_view)
                return response
            else:
                msg = "Items must be selected in order to perform \
                    actions on them. No items have been changed."
                add_message(request, msg, "warning")
                url = URL(str(request.url_for("admin:list", identity=identity)))
                return RedirectResponse(url=url, status_code=302)

        pagination = await model_view.list(request)
        pagination.add_pagination_urls(request.url)
        request_page = model_view.validate_page(request.query_params.get("page", 0), 1)
        if request_page > pagination.page:
            return RedirectResponse(request.url.include_query_params(page=pagination.page), status_code=302)
        context = {"model_view": model_view, "pagination": pagination}
        return await self.templates.TemplateResponse(request, model_view.list_template, context)

    @login_required
    async def create(self, request: Request) -> Response:
        """Create model endpoint."""
        await self._create(request)

        identity = request.path_params["identity"]
        model_view = self._find_model_view(identity)

        Form = await model_view.scaffold_form(model_view._form_create_rules)
        form_data = await self._handle_form_data(request)
        form = Form(form_data)

        context = {
            "model_view": model_view,
            "form": form,
        }
        if request.method == "GET":
            return await self.templates.TemplateResponse(request, model_view.create_template, context)

        if not form.validate():
            return await self.templates.TemplateResponse(request, model_view.create_template, context, status_code=400)

        form_data_dict = self._denormalize_wtform_data(form.data, model_view.model)

        try:
            obj = await model_view.insert_model(request, form_data_dict)
        except Exception as e:
            logger.exception(e)
            context["error"] = str(e)
            return await self.templates.TemplateResponse(request, model_view.create_template, context, status_code=400)
        url = self.get_save_redirect_url(
            request=request,
            form=form_data,
            obj=obj,
            model_view=model_view,
        )
        return RedirectResponse(url=url, status_code=302)

    @login_required
    async def edit(self, request: Request) -> Response:
        """Edit model endpoint."""

        await self._edit(request)
        identity = request.path_params["identity"]
        model_view = self._find_model_view(identity)
        pk = request.path_params["pk"]
        if not pk:
            url = URL(str(request.url_for("admin:list", identity=identity)))
            return RedirectResponse(url=url, status_code=302)
        model = await model_view.get_object_for_edit(request)
        if not model:
            raise HTTPException(status_code=404)

        Form = await model_view.scaffold_form(model_view._form_edit_rules)

        form = Form(obj=model, data=self._normalize_wtform_data(model))
        context = {
            "model": model,
            "model_view": model_view,
            "form": form,
        }

        if request.method == "GET":
            return await self.templates.TemplateResponse(request, model_view.edit_template, context)

        form_data = await self._handle_form_data(request, model)
        form = Form(form_data)
        if not form.validate():
            context["form"] = form
            return await self.templates.TemplateResponse(request, model_view.edit_template, context, status_code=400)

        form_data_dict = self._denormalize_wtform_data(form.data, model)
        try:
            if model_view.save_as and "_saveasnew" in form_data:
                obj = await model_view.insert_model(request, form_data_dict)
            else:
                obj = await model_view.update_model(request, pk=request.path_params["pk"], data=form_data_dict)
        except Exception as e:
            logger.exception(e)
            context["error"] = str(e)
            return await self.templates.TemplateResponse(request, model_view.edit_template, context, status_code=400)

        url = self.get_save_redirect_url(
            request=request,
            form=form_data,
            obj=obj,
            model_view=model_view,
        )
        return RedirectResponse(url=url, status_code=302)

    @login_required
    async def delete(self, request: Request) -> Response:
        """Delete route."""

        await self._delete(request)

        identity = request.path_params["identity"]
        model_view = self._find_model_view(identity)
        pk = request.path_params["pk"]
        if not pk:
            url = URL(str(request.url_for("admin:list", identity=identity)))
            return RedirectResponse(url=url, status_code=302)

        model = await model_view.get_object_for_delete(pk)
        if not model:
            raise HTTPException(status_code=404)
        to_delete = await model_view.get_deleted_objects([model])

        if request.method == "POST":
            await model_view.delete_model(request, pk)
            url = URL(str(request.url_for("admin:list", identity=identity)))
            return RedirectResponse(url=url, status_code=302)

        model_count = {model: len(objs) for model, objs in dict(to_delete).items()}
        context = {
            "model": model,
            "model_view": model_view,
            "model_count": dict(model_count).items(),
            "to_delete": dict(to_delete).items(),
        }
        return await self.templates.TemplateResponse(request, "fastdaisy_admin/delete_confirmation.html", context)

    @login_required
    async def export(self, request: Request) -> Response:
        """Export model endpoint."""

        await self._export(request)

        identity = request.path_params["identity"]
        export_type = request.path_params["export_type"]

        model_view = self._find_model_view(identity)
        rows = await model_view.get_model_objects(request=request, limit=model_view.export_max_rows)
        return await model_view.export_data(rows, export_type=export_type)

    async def login(self, request: Request) -> Response:
        assert self.authentication_backend is not None

        context = {}
        if request.method == "GET":
            return await self.templates.TemplateResponse(request, "fastdaisy_admin/login.html")

        ok = await self.authentication_backend.login(request)
        if not ok:
            context["error"] = "Invalid credentials."
            return await self.templates.TemplateResponse(
                request, "fastdaisy_admin/login.html", context, status_code=400
            )

        return RedirectResponse(request.url_for("admin:index"), status_code=302)

    async def logout(self, request: Request) -> Response:
        assert self.authentication_backend is not None

        await self.authentication_backend.logout(request)

        url = str(request.url_for("admin:login"))
        return JSONResponse({"redirect_url": url})

    async def response_action(self, form, request: Request, model_view: ModelView):
        selected = form.getlist("_selected_action")
        action = form.get("action")
        action_entry = cast(tuple[str, Callable], dict(model_view.get_actions).get(action))
        func = action_entry[1]
        objects = await model_view.get_model_objects_with_pk(selected)
        request.state.form = form
        response = await func(model_view, request, objects)
        return response

    async def _handle_form_data(self, request: Request, obj: Any = None) -> FormData:
        """
        Handle form data and modify in case of UploadFile.
        This is needed since in edit page
        there's no way to show current file of object.
        """

        form = await request.form()
        form_data: list[tuple[str, str | UploadFile]] = []
        for key, value in form.multi_items():
            if not isinstance(value, UploadFile):
                form_data.append((key, value))
                continue

            should_clear = form.get(key + "_checkbox")
            empty_upload = len(await value.read(1)) != 1
            await value.seek(0)
            if should_clear:
                form_data.append((key, UploadFile(io.BytesIO(b""))))
            elif empty_upload and obj and getattr(obj, key):
                f = getattr(obj, key)  # In case of update, imitate UploadFile
                form_data.append((key, UploadFile(filename=f.name, file=f.open())))
            else:
                form_data.append((key, value))
        return FormData(form_data)

    def get_save_redirect_url(self, request: Request, form: FormData, model_view: ModelView, obj: Any) -> URL:
        """
        Get the redirect URL after a save action
        which is triggered from create/edit page.
        """

        identity = request.path_params["identity"]
        identifier = get_object_identifier(obj)
        name = model_view.name.capitalize()
        identity = request.path_params["identity"]
        action = form.get("_form_type", None)

        # Determine message and target URL
        if "_save" in form:
            msg = f"The {name} “{obj}” was {action} successfully."
            url = request.url_for("admin:list", identity=identity)

        elif "_continue" in form or ("_saveasnew" in form and model_view.save_as_continue):
            final_action = "added" if model_view.save_as else action
            msg = f"The {name} “{obj}” was {final_action} successfully. You may edit it again below."
            url = request.url_for("admin:edit", identity=identity, pk=identifier)

        elif "_saveasnew" in form:
            msg = f"The {name} “{obj}” was added successfully."
            url = request.url_for("admin:list", identity=identity)

        else:
            msg = f"The {name} “{obj}” was {action} successfully. You may add another {name} below."
            url = request.url_for("admin:create", identity=identity)

        add_message(request, msg, "success")
        return url

    def _normalize_wtform_data(self, obj: Any) -> dict:
        form_data = {}
        for field_name in WTFORMS_ATTRS:
            if value := getattr(obj, field_name, None):
                form_data[field_name + "_"] = value
        return form_data

    def _denormalize_wtform_data(self, form_data: dict, obj: Any) -> dict:
        data = form_data.copy()
        for field_name in WTFORMS_ATTRS_REVERSED:
            reserved_field_name = field_name[:-1]
            if field_name in data and not getattr(obj, field_name, None) and getattr(obj, reserved_field_name, None):
                data[reserved_field_name] = data.pop(field_name)
        return data
