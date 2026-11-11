"""Thumbnails of entitycore assets for the Open Brain Institute platform.

Layers, each importing only the ones below it::

    api (routes, problems)
      -> application (previews, ports)
           -> domain (values, errors, guards)
           -> rendering (pure: asset bytes in, image bytes out)
      infrastructure (entitycore over HTTP) implements application.ports
"""
