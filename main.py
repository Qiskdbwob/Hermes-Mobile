"""Hermes Mobile - Entry point for Flet build"""

from hermes_mobile.main import main

if __name__ == "__main__":
    import flet as ft

    ft.app(target=main, assets_dir="assets")
