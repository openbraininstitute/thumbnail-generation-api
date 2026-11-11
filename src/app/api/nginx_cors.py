"""nginx's CORS allow-list, written from the app's settings at start (entrypoint.sh).

A cached image is shared by every origin, so nginx adds ``Access-Control-Allow-Origin`` per request.
"""

from app.settings import ApiSettings, get_settings


def map_conf(api: ApiSettings) -> str:
    """The nginx ``map`` from the request's Origin to the allowed origin, or empty.

    Examples:
        >>> print(map_conf(ApiSettings(cors_origins=["http://a.test"], cors_origin_regex="http://b.*")))
        map $http_origin $cors_allow_origin {
            default "";
            "http://a.test" $http_origin;
            "~^(?:http://b.*)$" $http_origin;
        }
    """
    lines = ["map $http_origin $cors_allow_origin {", '    default "";']
    for origin in sorted(set(api.cors_origins)):
        pattern = "~." if origin == "*" else origin
        lines.append(f'    "{pattern}" $http_origin;')
    if api.cors_origin_regex is not None:  # Starlette matches the whole origin: anchor it
        lines.append(f'    "~^(?:{api.cors_origin_regex.pattern})$" $http_origin;')
    lines.append("}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(map_conf(get_settings().api))  # noqa: T201 - entrypoint.sh writes it to a file
