"""Hermes Mobile - Main Package.

Flet 0.86 requires Python 3.10+, while Hermes Mobile still supports Python 3.9
with Flet 0.28. Keep the narrow constructor helpers used by the UI available on
both generations without forking every view.
"""

import flet as ft


def _install_flet_compatibility() -> None:
    if not hasattr(ft, "run") and hasattr(ft, "app"):
        ft.run = ft.app

    for class_name, module_name in (
        ("Padding", "padding"),
        ("Margin", "margin"),
        ("BorderRadius", "border_radius"),
        ("Border", "border"),
    ):
        control_class = getattr(ft, class_name, None)
        legacy_module = getattr(ft, module_name, None)
        if control_class is None or legacy_module is None:
            continue
        for helper in ("all", "symmetric", "only"):
            if not hasattr(control_class, helper) and hasattr(legacy_module, helper):
                setattr(control_class, helper, staticmethod(getattr(legacy_module, helper)))


_install_flet_compatibility()

__version__ = "0.1.0"
__author__ = "Hermes Mobile Team"
