from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.datastructures import URL
from starlette.requests import Request
from starlette.responses import RedirectResponse

from fastdaisy_admin.decorators import action, expose  # noqa: F401

if TYPE_CHECKING:
    from fastdaisy_admin import ModelView


@action(name="Delete selected")
async def delete_selected(model_view: ModelView, request: Request, objects):
    to_delete = await model_view.get_deleted_objects(objects)
    model_count = {model: len(objs) for model, objs in dict(to_delete).items()}
    if request.state.form.get("post", None) == "yes":
        for obj in objects:
            await model_view.delete_model(request, obj)
        url = URL(str(request.url_for("admin:list", identity=model_view.identity)))
        return RedirectResponse(url=url, status_code=302)
    context = {
        "model_view": model_view,
        "model_count": dict(model_count).items(),
        "to_delete": dict(to_delete).items(),
        "models": objects,
    }
    return await model_view.templates.TemplateResponse(
        request, "fastdaisy_admin/delete_selected_confirmation.html", context
    )
