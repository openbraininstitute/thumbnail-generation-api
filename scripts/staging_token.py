"""A staging access token for the QA user, the way obi-e2e gets one, without a browser.

    uv run python scripts/staging_token.py      # prints the token on stdout

obi-e2e signs in through the web app in a browser (fixtures/run/auth.ts) and then reads the token
from the app's session (fixtures/run/token.ts). This does the same over HTTP: next-auth's sign-in,
Keycloak's login form, the callback, then GET /api/auth/session.

Credentials: E2E_TEST_USERNAME and E2E_TEST_PASSWORD from the environment, else from obi-e2e's
.env.staging.local (E2E_ENV_FILE, default ../obi-e2e/.env.staging.local). They are never printed.
The web app: E2E_BASE_URL, default the one obi-e2e's .env.staging names.
"""

import os
import re
import sys
from html import unescape
from pathlib import Path

import httpx2

DEFAULT_ENV_FILE = Path(__file__).parent.parent.parent / "obi-e2e" / ".env.staging.local"
DEFAULT_BASE_URL = "https://main.preview.openbraininstitute.org"
# The OBI theme (keycloakify) draws the form in the browser; the address it posts to is in the
# page's kcContext JSON. A classic theme has it in the form tag.
FORM_ACTION = re.compile(
    r'"loginAction":\s*"([^"]+)"|<form[^>]*id="kc-form-login"[^>]*action="([^"]+)"', re.DOTALL
)


def credentials() -> tuple[str, str]:
    """The QA user's username and password: environment first, then obi-e2e's env file."""
    values = dict(os.environ)
    env_file = Path(os.environ.get("E2E_ENV_FILE", DEFAULT_ENV_FILE))
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            key, sep, value = line.partition("=")
            if sep and not line.startswith("#"):
                values.setdefault(key.strip(), value.strip().strip("'\""))
    username, password = values.get("E2E_TEST_USERNAME"), values.get("E2E_TEST_PASSWORD")
    if not username or not password:
        sys.exit(f"E2E_TEST_USERNAME / E2E_TEST_PASSWORD not set, and not found in {env_file}")
    return username, password


def token(base_url: str | None = None) -> str:
    """Sign in through the web app and return the session's access token."""
    base = (base_url or os.environ.get("E2E_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    username, password = credentials()
    with httpx2.Client(follow_redirects=True, timeout=30) as http:
        csrf = http.get(f"{base}/api/auth/csrf").json()["csrfToken"]
        # next-auth answers with Keycloak's login page (after its redirects).
        login = http.post(
            f"{base}/api/auth/signin/keycloak",
            data={"csrfToken": csrf, "callbackUrl": base, "json": "true"},
        )
        if login.headers.get("content-type", "").startswith("application/json"):
            login = http.get(login.json()["url"])
        action = FORM_ACTION.search(login.text)
        if action is None:
            sys.exit(f"Keycloak's login form was not found (status {login.status_code})")
        target = unescape(action.group(1) or action.group(2)).replace("\\/", "/")
        # Keycloak checks the password, then redirects to the app's callback, which sets the
        # session cookie.
        done = http.post(
            target,
            data={"username": username, "password": password, "credentialId": ""},
        )
        if FORM_ACTION.search(done.text):
            sys.exit("Keycloak refused the credentials")
        session = http.get(f"{base}/api/auth/session").json()
    access = session.get("accessToken")
    if not access:
        sys.exit("signed in, but the session holds no access token")
    return access


if __name__ == "__main__":
    print(token())
