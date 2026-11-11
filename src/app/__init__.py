"""Thumbnails of entitycore assets for the Open Brain Institute platform.

Layers (one direction only, as in workspace-manager spec 06 C-L1..C-L4)::

    api (routes, problems)
      -> application (previews, ports)
           -> domain (values, errors, guards)
           -> rendering (pure: asset bytes in, image bytes out)
      infrastructure (entitycore over HTTP) implements application.ports
"""
