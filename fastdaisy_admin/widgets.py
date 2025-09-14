import json
from typing import Any

from markupsafe import Markup
from wtforms import Field, widgets
from wtforms.widgets import html_params

__all__ = [
    "DatePickerWidget",
    "DateTimePickerWidget",
    "Select2TagsWidget",
]


class DatePickerWidget(widgets.TextInput):
    """
    Date picker widget.
    """

    def __call__(self, field: Field, **kwargs: Any) -> str:
        kwargs.setdefault("data-role", "datepicker")
        return super().__call__(field, **kwargs)


class DateTimePickerWidget(widgets.TextInput):
    """
    Datetime picker widget.
    """

    def __call__(self, field: Field, **kwargs: Any) -> str:
        kwargs.setdefault("data-role", "datetimepicker")
        return super().__call__(field, **kwargs)

class Select2TagsWidget(widgets.Select):
    def __call__(self, field: Field, **kwargs: Any) -> str:
        kwargs.setdefault("data-role", "select2-tags")
        kwargs.setdefault("data-json", json.dumps(field.data))
        kwargs.setdefault("multiple", "multiple")
        return super().__call__(field, **kwargs)


class FileInputWidget(widgets.FileInput):
    """
    File input widget with clear checkbox.
    """

    def __call__(self, field: Field, **kwargs: Any) -> str:
        if not field.flags.required:
            checkbox_id = f"{field.id}_checkbox"
            checkbox_label = Markup(
                f'<label class="form-check-label" for="{checkbox_id}">Clear</label>'
            )
            checkbox_input = Markup(
                f'<input class="form-check-input" type="checkbox" id="{checkbox_id}" name="{checkbox_id}">'  # noqa: E501
            )
            checkbox = Markup(
                f'<div class="form-check">{checkbox_input}{checkbox_label}</div>'
            )
        else:
            checkbox = Markup()

        if field.data:
            current_value = Markup(f"<p>Currently: {field.data}</p>")
            field.flags.required = False
            return current_value + checkbox + super().__call__(field, **kwargs)
        else:
            return super().__call__(field, **kwargs)
