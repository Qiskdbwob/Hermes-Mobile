"""Hermes Mobile - Main Package.

Flet 0.86 requires Python 3.10+, while Hermes Mobile still supports Python 3.9
with Flet 0.28. Keep the narrow constructor helpers used by the UI available on
both generations without forking every view.
"""

import inspect

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

    alignment_class = getattr(ft, "Alignment", None)
    legacy_alignment = getattr(ft, "alignment", None)
    if alignment_class is not None and legacy_alignment is not None:
        for name in (
            "bottom_center",
            "bottom_left",
            "bottom_right",
            "center",
            "center_left",
            "center_right",
            "top_center",
            "top_left",
            "top_right",
        ):
            if not hasattr(alignment_class, name.upper()) and hasattr(legacy_alignment, name):
                setattr(alignment_class, name.upper(), getattr(legacy_alignment, name))

    if not hasattr(ft, "BoxFit") and hasattr(ft, "ImageFit"):
        ft.BoxFit = ft.ImageFit

    dropdown = getattr(ft, "Dropdown", None)
    if dropdown is not None and "on_select" not in inspect.signature(dropdown).parameters:
        original_init = dropdown.__init__

        def dropdown_init(self, *args, on_select=None, **kwargs):
            if on_select is not None and "on_change" not in kwargs:
                kwargs["on_change"] = on_select
            original_init(self, *args, **kwargs)

        dropdown.__init__ = dropdown_init


_install_flet_compatibility()

__version__ = "0.1.0"
__author__ = "Hermes Mobile Team"
