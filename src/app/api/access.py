"""nginx's access check (``auth_request``), before a cached image is sent or stored.

``/_access{path}?{query}`` runs the route of ``{path}`` as the caller, up to entitycore's answer:
metadata only, no download, no drawing. 204 and the image's ``ETag``: allowed. 403: anything
else; nginx then lets the route answer the real error.

External authorization: entitycore decides, nginx enforces, no access rule here.
"""

from starlette.types import ASGIApp, Message, Receive, Scope, Send

PREFIX = "/_access"  # internal in nginx.conf: no client reaches it
CHECK = "app.access_check"  # scope key: ``routes.answer`` stops after the check
ALLOWED, REFUSED = 204, 403  # all auth_request reads


class AccessGate:
    """ASGI middleware: under ``PREFIX``, the real route as an access check only."""

    def __init__(self, app: ASGIApp) -> None:
        """Wrap ``app``."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """204 or 403 for an access check; any other request goes through untouched."""
        if scope["type"] != "http" or not scope["path"].startswith(PREFIX):
            await self.app(scope, receive, send)
            return

        async def yes_or_no(message: Message) -> None:
            # One "no" for every refusal: auth_request fails on any other status.
            if message["type"] == "http.response.start" and message["status"] != ALLOWED:
                message = {**message, "status": REFUSED}
            await send(message)

        path = scope["path"].removeprefix(PREFIX)
        await self.app({**scope, "path": path, CHECK: True}, receive, yes_or_no)
