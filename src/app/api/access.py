"""The access gate: nginx asks it (``auth_request``) before an image leaves or enters its cache.

``/_access{path}?{query}`` runs the route of ``{path}`` as the caller, up to entitycore's access
check: the asset's metadata, no download, no drawing. 204 with the image's ``ETag``: the caller may
read it, and nginx serves or stores the image under that ETag. 403: anything else; nginx then sends
the request to the route itself, uncached, and the route answers the real error.

Pattern: external authorization. nginx enforces, entitycore decides; no access rule lives here.
The same route reads the query for the check, the cache key and the image, so they cannot differ.
"""

from starlette.types import ASGIApp, Message, Receive, Scope, Send

PREFIX = "/_access"  # internal in nginx/nginx.conf: a client cannot ask here
CHECK = "app.access_check"  # scope key: ``routes.answer`` stops after the access check
ALLOWED, REFUSED = 204, 403  # all auth_request reads


class AccessGate:
    """ASGI middleware: under ``PREFIX``, run the real route as an access check only."""

    def __init__(self, app: ASGIApp) -> None:
        """Wrap ``app``."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Answer a gate request with 204 or 403; pass every other request through untouched."""
        if scope["type"] != "http" or not scope["path"].startswith(PREFIX):
            await self.app(scope, receive, send)
            return

        async def yes_or_no(message: Message) -> None:
            # Every refusal and error is one "no": auth_request fails on any other status.
            if message["type"] == "http.response.start" and message["status"] != ALLOWED:
                message = {**message, "status": REFUSED}
            await send(message)

        path = scope["path"].removeprefix(PREFIX)
        await self.app({**scope, "path": path, CHECK: True}, receive, yes_or_no)
