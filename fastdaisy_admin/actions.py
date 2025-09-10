from fastdaisy_admin.helpers import slugify_action_name,shorten_name
from typing import (
    Any,
    Callable,
    no_type_check,
    TYPE_CHECKING
)
from fastdaisy_admin.authentication import login_required
from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.datastructures import URL


if TYPE_CHECKING:
    from fastdaisy_admin import ModelView

def action(
    name: str | None
) -> Callable[..., Any]:
    """Decorate a [`ModelView`][fastdaisy_admin.models.ModelView] function
    with this to:

    * expose it as a custom "action" route
    * add a button to the admin panel to invoke the action

    When invoked from the admin panel, the following query parameter(s) are passed:

    * `pks`: the comma-separated list of selected object PKs - can be empty

    Args:
        name: Unique name for the action - should be alphanumeric, dash and underscore
        label: Human-readable text describing action
        confirmation_message: Message to show before confirming action
        include_in_schema: Indicating if the endpoint be included in the schema
        add_in_detail: Indicating if action should be dispalyed on model detail page
        add_in_list: Indicating if action should be dispalyed on model list page
    """
    
    @no_type_check
    def wrap(func):
        title = name or func.__name__
        func._action = True
        func._slug = slugify_action_name(name)
        func._title = shorten_name(title)
        func.name = shorten_name(func.__name__)
        return login_required(func)

    return wrap

@action(name="Delete selected")
async def delete_selected(model_view:"ModelView",request:Request,objects):
    to_delete = await model_view.get_deleted_objects(objects)
    model_count = {
        model:len(objs) for model,objs in dict(to_delete).items()
    }
    if request.state.form.get("post",None) == "yes":
        for obj in objects:
            await model_view.delete_model(request, obj)
        url = URL(str(request.url_for("admin:list", identity=model_view.identity)))
        return RedirectResponse(url=url,status_code=302)
    context = {
        "model_view": model_view,
        "model_count": dict(model_count).items(),
        "to_delete": dict(to_delete).items(),
        "models":objects
        }
    return await model_view.templates.TemplateResponse(
        request, "fastdaisy_admin/delete_selected_confirmation.html", context
    )

