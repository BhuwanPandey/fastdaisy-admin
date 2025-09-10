from typing import Any

from markupsafe import Markup


def empty_formatter(value: Any) -> str:
    """Return empty string for `None` value"""
    return ""


def bool_formatter(value: bool) -> Markup:
    """Return check icon if value is `True` or X otherwise."""
    icon_class = "fa-circle-check text-success" if value else "fa-circle-xmark text-error"
    return Markup(f"<i class='fa {icon_class}'></i>")


BASE_FORMATTERS = {
    type(None): empty_formatter,
    bool: bool_formatter,
}
