from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp


class AuthStoreMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, authentication: bool) -> None:
        super().__init__(app)
        self.authentication = authentication

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request.state.authentication = self.authentication
        if not self.authentication:
            request.session.pop("_authenticated_id", None)
        return await call_next(request)
