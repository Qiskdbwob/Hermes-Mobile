"""Cron View - Cron job management interface"""

import asyncio

import flet as ft

from hermes_mobile.cron.scheduler import (
    create_job,
    delete_job,
    disable_job,
    enable_job,
    get_job_output,
    get_ticker_status,
    list_jobs,
    run_job_now,
)
from hermes_mobile.cron.scheduler import (
    update_job as _update_job,
)
from hermes_mobile.ui.common import (
    close_dialog,
    empty_state,
    flat_button,
    flat_list_row,
    open_dialog,
    page_header,
    snack,
)
from hermes_mobile.ui.theme import mode_colors


class CronView:
    """Cron job management interface"""

    def __init__(self, app):
        self.app = app
        self.page = app.page

    def build(self) -> ft.Control:
        """Build the cron view"""
        status = get_ticker_status()
        running = status.get("running", False)
        actions = ft.Row(
            [
                ft.IconButton(
                    icon=ft.Icons.REFRESH,
                    tooltip="Refresh",
                    on_click=lambda e: self._refresh(),
                ),
                ft.IconButton(
                    icon=ft.Icons.ADD,
                    tooltip="Add Job",
                    on_click=lambda e: self._show_add_job_dialog(),
                ),
            ],
            spacing=0,
        )
        return ft.Column(
            [
                page_header(
                    self.app.dark_mode,
                    "Cron Jobs",
                    f"{'Running' if running else 'Stopped'} · every {status.get('interval', 60)}s",
                    actions,
                ),
                ft.Container(content=self._build_jobs_list(), expand=True),
            ],
            expand=True,
            spacing=0,
        )

    def _build_ticker_status(self) -> ft.Control:
        """Build ticker status indicator"""
        status = get_ticker_status()
        running = status.get("running", False)

        return ft.Container(
            content=ft.Row(
                [
                    ft.Icon(
                        ft.Icons.CIRCLE,
                        size=12,
                        color=ft.Colors.GREEN if running else ft.Colors.RED,
                    ),
                    ft.Text(
                        "Running" if running else "Stopped",
                        size=12,
                        color=ft.Colors.GREEN if running else ft.Colors.RED,
                    ),
                    ft.Text(
                        f" | Interval: {status.get('interval', 60)}s",
                        size=12,
                        color=ft.Colors.OUTLINE,
                    ),
                ],
                spacing=4,
            ),
            padding=ft.Padding.symmetric(horizontal=12, vertical=6),
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            border_radius=16,
        )

    def _build_jobs_list(self) -> ft.Control:
        """Build the jobs list"""
        jobs = list_jobs()

        if not jobs:
            return empty_state(
                self.app.dark_mode,
                "No cron jobs",
                "Create a scheduled job to get started.",
                ft.Icons.SCHEDULE,
                flat_button(
                    "Create Job",
                    ft.Icons.ADD,
                    lambda e: self._show_add_job_dialog(),
                    self.app.dark_mode,
                    primary=True,
                ),
            )

        return ft.ListView(
            controls=[self._build_job_card(job) for job in jobs],
            padding=ft.Padding.symmetric(horizontal=12),
            spacing=0,
        )

    def _build_job_card(self, job) -> ft.Control:
        """Build a dense, mobile-safe job row."""
        c = mode_colors(self.app.dark_mode)
        status_colors = {
            "success": c["success"],
            "failed": ft.Colors.ERROR,
            "running": ft.Colors.ORANGE,
            None: c["muted_foreground"],
        }
        status_color = status_colors.get(job.last_status, c["muted_foreground"])
        status_label = job.last_status.upper() if job.last_status else "NEVER RUN"
        next_run = job.next_run[:16] if job.next_run else "N/A"
        subtitle = (
            f"{job.schedule} · {job.description}\n"
            f"Runs {job.run_count} · Failures {job.failure_count} · Next {next_run}"
        )
        menu = ft.PopupMenuButton(
            icon=ft.Icons.MORE_VERT,
            tooltip="Job actions",
            items=[
                ft.PopupMenuItem(
                    content=ft.Text("Run now"),
                    on_click=lambda e, j=job: self._run_job_now(j),
                ),
                ft.PopupMenuItem(
                    content=ft.Text("Disable" if job.enabled else "Enable"),
                    on_click=lambda e, j=job: self._toggle_job(j),
                ),
                ft.PopupMenuItem(
                    content=ft.Text("View output"),
                    on_click=lambda e, j=job: self._show_job_output(j),
                ),
                ft.PopupMenuItem(
                    content=ft.Text("Edit"),
                    on_click=lambda e, j=job: self._show_edit_job_dialog(j),
                ),
                ft.PopupMenuItem(
                    content=ft.Text("Delete"),
                    on_click=lambda e, j=job: self._confirm_delete_job(j),
                ),
            ],
        )
        trailing = ft.Row(
            [ft.Text(status_label, size=10, color=status_color), menu],
            spacing=0,
            tight=True,
        )
        return flat_list_row(
            self.app.dark_mode,
            job.name,
            subtitle,
            ft.Icon(
                ft.Icons.SCHEDULE,
                size=18,
                color=ft.Colors.PRIMARY if job.enabled else c["muted_foreground"],
            ),
            trailing,
        )

    def _show_add_job_dialog(self):
        """Show add job dialog"""
        name_field = ft.TextField(label="Job Name", hint_text="my_backup_job")
        schedule_field = ft.TextField(label="Cron Schedule", hint_text="0 3 * * * (daily at 3 AM)")
        command_field = ft.TextField(
            label="Command",
            hint_text="python3 -m hermes_mobile.cron.backup_data",
            multiline=True,
            min_lines=2,
        )
        description_field = ft.TextField(label="Description", hint_text="Backup data to cloud")
        timeout_field = ft.TextField(
            label="Timeout (seconds)", value="300", keyboard_type=ft.KeyboardType.NUMBER
        )
        enabled_switch = ft.Switch(label="Enabled", value=True)

        def handle_create(e):
            try:
                create_job(
                    name=name_field.value,
                    schedule=schedule_field.value,
                    command=command_field.value,
                    description=description_field.value,
                    timeout=int(timeout_field.value),
                    enabled=enabled_switch.value,
                )
                close_dialog(self.page, dialog)
                self._refresh()
                snack(self.page, "Job created successfully")
            except Exception as ex:
                snack(self.page, f"Error: {ex}")

        dialog = ft.AlertDialog(
            title=ft.Text("Create Cron Job"),
            content=ft.Container(
                content=ft.Column(
                    [
                        name_field,
                        schedule_field,
                        command_field,
                        description_field,
                        timeout_field,
                        enabled_switch,
                    ],
                    tight=True,
                    spacing=12,
                    scroll=ft.ScrollMode.AUTO,
                ),
                width=400,
            ),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: close_dialog(self.page, dialog)),
                ft.Button("Create", on_click=handle_create),
            ],
        )
        open_dialog(self.page, dialog)

    def _show_edit_job_dialog(self, job):
        """Show edit job dialog"""
        name_field = ft.TextField(label="Job Name", value=job.name)
        schedule_field = ft.TextField(label="Cron Schedule", value=job.schedule)
        command_field = ft.TextField(
            label="Command", value=job.command, multiline=True, min_lines=2
        )
        description_field = ft.TextField(label="Description", value=job.description)
        timeout_field = ft.TextField(
            label="Timeout (seconds)", value=str(job.timeout), keyboard_type=ft.KeyboardType.NUMBER
        )
        enabled_switch = ft.Switch(label="Enabled", value=job.enabled)

        def handle_update(e):
            try:
                _update_job(
                    job.id,
                    name=name_field.value,
                    schedule=schedule_field.value,
                    command=command_field.value,
                    description=description_field.value,
                    timeout=int(timeout_field.value),
                    enabled=enabled_switch.value,
                )
                close_dialog(self.page, dialog)
                self._refresh()
                snack(self.page, "Job updated successfully")
            except Exception as ex:
                snack(self.page, f"Error: {ex}")

        dialog = ft.AlertDialog(
            title=ft.Text(f"Edit Job: {job.name}"),
            content=ft.Container(
                content=ft.Column(
                    [
                        name_field,
                        schedule_field,
                        command_field,
                        description_field,
                        timeout_field,
                        enabled_switch,
                    ],
                    tight=True,
                    spacing=12,
                    scroll=ft.ScrollMode.AUTO,
                ),
                width=400,
            ),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: close_dialog(self.page, dialog)),
                ft.Button("Save", on_click=handle_update),
            ],
        )
        open_dialog(self.page, dialog)

    def _run_job_now(self, job):
        """Run a job immediately (off the UI thread, back on the event loop)."""
        asyncio.create_task(self._run_job_now_async(job))

    async def _run_job_now_async(self, job):
        """Execute the job in a worker thread, then update the UI on the loop.

        Previously the worker thread called snack()/_refresh() directly, which
        mutates Flet controls from a non-UI thread (not thread-safe).
        """
        try:
            output = await asyncio.to_thread(run_job_now, job.id)
            snack(self.page, f"Job completed: {output.status} ({output.duration:.1f}s)")
        except Exception as exc:
            snack(self.page, f"Job failed: {exc}", error=True)
        self._refresh()

    def _toggle_job(self, job):
        """Enable/disable a job"""
        if job.enabled:
            disable_job(job.id)
        else:
            enable_job(job.id)
        self._refresh()

    def _show_job_output(self, job):
        """Show job output history"""
        outputs = get_job_output(job.id, limit=20)
        c = mode_colors(self.app.dark_mode)

        content = ft.Column(
            [
                ft.Text(f"Output for: {job.name}", weight=ft.FontWeight.BOLD, size=16),
                ft.Divider(),
                ft.Column(
                    [
                        ft.Container(
                            content=ft.Column(
                                [
                                    ft.Row(
                                        [
                                            ft.Text(
                                                out.timestamp[:19].replace("T", " "),
                                                size=11,
                                                color=ft.Colors.OUTLINE,
                                            ),
                                            ft.Container(
                                                content=ft.Text(
                                                    out.status.upper(),
                                                    size=10,
                                                    color=ft.Colors.GREEN
                                                    if out.status == "success"
                                                    else ft.Colors.RED,
                                                    weight=ft.FontWeight.BOLD,
                                                ),
                                                padding=ft.Padding.symmetric(
                                                    horizontal=6, vertical=2
                                                ),
                                                bgcolor=ft.Colors.with_opacity(
                                                    0.1,
                                                    ft.Colors.GREEN
                                                    if out.status == "success"
                                                    else ft.Colors.RED,
                                                ),
                                                border_radius=8,
                                            ),
                                        ],
                                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                    ),
                                    ft.Text(
                                        (
                                            f"Duration: {out.duration:.1f}s | "
                                            f"Code: {out.return_code}"
                                        ),
                                        size=10,
                                        color=ft.Colors.OUTLINE,
                                    ),
                                    ft.Text(
                                        (out.stdout[:200] + "...")
                                        if len(out.stdout) > 200
                                        else out.stdout,
                                        size=10,
                                        font_family="monospace",
                                        color=ft.Colors.OUTLINE,
                                    ),
                                ],
                                spacing=4,
                            ),
                            padding=12,
                            border=ft.Border.all(1, c["border"]),
                            border_radius=ft.BorderRadius.all(8),
                        )
                        for out in outputs
                    ]
                    or [ft.Text("No output history", color=ft.Colors.OUTLINE)],
                    spacing=8,
                    scroll=ft.ScrollMode.AUTO,
                ),
            ],
            spacing=8,
            tight=True,
            scroll=ft.ScrollMode.AUTO,
        )

        dialog = ft.AlertDialog(
            title=ft.Text(f"Job Output: {job.name}"),
            content=ft.Container(content=content, width=500, height=600),
            actions=[ft.TextButton("Close", on_click=lambda e: close_dialog(self.page, dialog))],
        )
        open_dialog(self.page, dialog)

    def _confirm_delete_job(self, job):
        """Confirm job deletion"""

        def delete(e):
            delete_job(job.id)
            close_dialog(self.page, dialog)
            self._refresh()
            snack(self.page, "Job deleted")

        dialog = ft.AlertDialog(
            title=ft.Text("Delete Job"),
            content=ft.Text(
                f"Are you sure you want to delete '{job.name}'? This cannot be undone."
            ),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: close_dialog(self.page, dialog)),
                ft.Button("Delete", color=ft.Colors.ERROR, on_click=delete),
            ],
        )
        open_dialog(self.page, dialog)

    def _refresh(self):
        """Refresh the view"""
        self.app.content_area.content = self.build()
        self.page.update()
