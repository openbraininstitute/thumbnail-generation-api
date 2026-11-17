"""The access check nginx runs (``auth_request``) before it sends or stores a cached image.

nginx calls ``/_access{path}?{query}``. We run the real route for ``{path}`` as the caller, but stop
right after entitycore says yes or no: we read the asset's metadata, and never download or draw.

- 204, with the image's ``ETag``: the caller may see it. nginx serves or stores it under that ETag.
- 403: anything else. nginx then sends the request to the route itself, uncached, so the caller
  gets the real error.

Pattern: external authorization. entitycore decides, nginx enforces, and no access rule lives
here. The check, the cache key and the image all come from the same route reading the same query,
so they can never disagree.
"""

from starlette.types import ASGIApp, Message, Receive, Scope, Send

PREFIX = "/_access"  # internal in nginx/nginx.conf, so no client can call it
CHECK = "app.access_check"  # set in the scope: tells ``routes.answer`` to stop after the check
ALLOWED, REFUSED = 204, 403  # the only answers auth_request understands


class AccessGate:
    """ASGI middleware: a request under ``PREFIX`` runs the real route as an access check only."""

    def __init__(self, app: ASGIApp) -> None:
        """Wrap ``app``."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Answer an access check with 204 or 403; let every other request through as is."""
        if scope["type"] != "http" or not scope["path"].startswith(PREFIX):
            await self.app(scope, receive, send)
            return

        async def yes_or_no(message: Message) -> None:
            # Any refusal or error becomes one plain "no": auth_request fails on other statuses.
            if message["type"] == "http.response.start" and message["status"] != ALLOWED:
                message = {**message, "status": REFUSED}
            await send(message)

        path = scope["path"].removeprefix(PREFIX)
        await self.app({**scope, "path": path, CHECK: True}, receive, yes_or_no)
