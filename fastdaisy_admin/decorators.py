import functools
import inspect
from collections.abc import Callable
from typing import Any, no_type_check

from starlette.responses import RedirectResponse, Response

from fastdaisy_admin.helpers import shorten_name


def login_required(func: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator to check authentication of Admin routes.
    If no authentication backend is setup, this will do nothing.
    """

    @functools.wraps(func)
    async def wrapper_decorator(*args: Any, **kwargs: Any) -> Any:
        view, request = args[0], args[1]
        admin = getattr(view, "_admin_ref", view)
        auth_backend = getattr(admin, "authentication_backend", None)
        if auth_backend is not None:
            response = await auth_backend.authenticate(request)
            if isinstance(response, Response):
                return response
            if not bool(response):
                return RedirectResponse(request.url_for("admin:login"), status_code=302)

        if inspect.iscoroutinefunction(func):
            return await func(*args, **kwargs)
        return func(*args, **kwargs)

    return wrapper_decorator


def action(name: str | None) -> Callable[..., Any]:
    """Decorate a [`ModelView`][fastdaisy_admin.models.ModelView] function
    with this to:

    When invoked from the admin panel, the following query parameter(s) are passed:
    Args:
        name: Unique name for the action - should be alphanumeric, dash and underscore
    """

    @no_type_check
    def wrap(func):
        title = name or func.__name__
        func._action = True
        func._title = shorten_name(title)
        func.name = shorten_name(func.__name__)
        return login_required(func)

    return wrap


def expose(
    path: str,
    *,
    methods: list[str] = ["GET"],
    identity: str | None = None,
    include_in_schema: bool = True,
) -> Callable[..., Any]:
    """Expose View with information."""

    @no_type_check
    def wrap(func):
        func._exposed = True
        func._path = path
        func._methods = methods
        func._identity = identity or func.__name__
        func._include_in_schema = include_in_schema
        return login_required(func)

    return wrap
