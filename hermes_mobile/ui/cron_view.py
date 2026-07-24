"""Cron View - Cron job management interface"""

import flet as ft

from hermes_mobile.cron.scheduler import (
    delete_job,
    disable_job,
    enable_job,
    get_job_output,
    get_ticker_status,
    list_jobs,
    run_job_now,
)


class CronView:
    """Cron job management interface"""

    def __init__(self, app):
        self.app = app
        self.page = app.page

    def build(self) -> ft.Control:
        """Build the cron view"""
        return ft.Column(
            [
                # Header with ticker status
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Text("Cron Jobs", size=24, weight=ft.FontWeight.BOLD),
                            ft.Row(
                                [
                                    self._build_ticker_status(),
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
                                spacing=8,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    padding=ft.padding.symmetric(horizontal=20, vertical=16),
                ),
                ft.Divider(height=1),
                # Jobs list
                ft.Container(
                    content=self._build_jobs_list(),
                    expand=True,
                ),
            ],
            expand=True,
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
            padding=ft.padding.symmetric(horizontal=12, vertical=6),
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            border_radius=16,
        )

    def _build_jobs_list(self) -> ft.Control:
        """Build the jobs list"""
        jobs = list_jobs()

        if not jobs:
            return ft.Container(
                content=ft.Column(
                    [
                        ft.Icon(ft.Icons.SCHEDULE, size=64, color=ft.Colors.OUTLINE),
                        ft.Text("No cron jobs", size=18, color=ft.Colors.OUTLINE),
                        ft.Text("Create a job to get started", color=ft.Colors.OUTLINE),
                        ft.ElevatedButton(
                            "Create Job",
                            icon=ft.Icons.ADD,
                            on_click=lambda e: self._show_add_job_dialog(),
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.CENTER,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=16,
                ),
                alignment=ft.alignment.center,
                expand=True,
            )

        return ft.ListView(
            controls=[self._build_job_card(job) for job in jobs],
            padding=20,
            spacing=12,
        )

    def _build_job_card(self, job) -> ft.Control:
        """Build a job card"""
        status_colors = {
            "success": ft.Colors.GREEN,
            "failed": ft.Colors.RED,
            "running": ft.Colors.ORANGE,
            None: ft.Colors.OUTLINE,
        }

        status_color = status_colors.get(job.last_status, ft.Colors.OUTLINE)

        return ft.Card(
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Icon(
                                    ft.Icons.SCHEDULE,
                                    color=ft.Colors.PRIMARY if job.enabled else ft.Colors.OUTLINE,
                                ),
                                ft.Column(
                                    [
                                        ft.Text(job.name, weight=ft.FontWeight.BOLD, size=16),
                                        ft.Text(
                                            f"Schedule: {job.schedule} | {job.description}",
                                            size=12,
                                            color=ft.Colors.OUTLINE,
                                            max_lines=2,
                                            overflow=ft.TextOverflow.ELLIPSIS,
                                        ),
                                    ],
                                    spacing=2,
                                    expand=True,
                                ),
                                ft.Container(
                                    content=ft.Text(
                                        job.last_status.upper() if job.last_status else "NEVER RUN",
                                        size=11,
                                        color=status_color,
                                        weight=ft.FontWeight.BOLD,
                                    ),
                                    padding=ft.padding.symmetric(horizontal=8, vertical=4),
                                    bgcolor=ft.Colors.with_opacity(0.1, status_color),
                                    border_radius=12,
                                ),
                            ],
                            spacing=12,
                        ),
                        ft.Divider(height=1),
                        ft.Row(
                            [
                                ft.Text(
                                    f"Runs: {job.run_count} | Failures: {job.failure_count}",
                                    size=11,
                                    color=ft.Colors.OUTLINE,
                                ),
                                ft.Text(
                                    f"Next: {job.next_run[:16] if job.next_run else 'N/A'}",
                                    size=11,
                                    color=ft.Colors.OUTLINE,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Divider(height=1),
                        ft.Row(
                            [
                                ft.TextButton(
                                    "Run Now",
                                    icon=ft.Icons.PLAY_ARROW,
                                    on_click=lambda e, j=job: self._run_job_now(j),
                                ),
                                ft.TextButton(
                                    "Disable" if job.enabled else "Enable",
                                    icon=ft.Icons.PAUSE_CIRCLE
                                    if job.enabled
                                    else ft.Icons.PLAY_CIRCLE,
                                    on_click=lambda e, j=job: self._toggle_job(j),
                                ),
                                ft.TextButton(
                                    "Output",
                                    icon=ft.Icons.VISIBILITY,
                                    on_click=lambda e, j=job: self._show_job_output(j),
                                ),
                                ft.TextButton(
                                    "Edit",
                                    icon=ft.Icons.EDIT,
                                    on_click=lambda e, j=job: self._show_edit_job_dialog(j),
                                ),
                                ft.TextButton(
                                    "Delete",
                                    icon=ft.Icons.DELETE,
                                    style=ft.ButtonStyle(color=ft.Colors.ERROR),
                                    on_click=lambda e, j=job: self._confirm_delete_job(j),
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.END,
                        ),
                    ],
                    spacing=8,
                ),
                padding=16,
            ),
        )

    def _show_add_job_dialog(self):
        """Show add job dialog"""
        name_field = ft.TextField(label="Job Name", hint_text="my_backup_job")
        schedule_field = ft.TextField(label="Cron Schedule", hint_text="0 3 * * * (daily at 3 AM)")
        command_field = ft.TextField(
            label="Command",
            hint_text="python -m hermes_mobile.cron.backup_data",
            multiline=True,
            min_lines=2,
        )
        description_field = ft.TextField(label="Description", hint_text="Backup data to cloud")
        timeout_field = ft.TextField(
            label="Timeout (seconds)", value="300", keyboard_type=ft.KeyboardType.NUMBER
        )
        enabled_switch = ft.Switch(label="Enabled", value=True)

        def create_job(e):
            try:
                create_job(
                    name=name_field.value,
                    schedule=schedule_field.value,
                    command=command_field.value,
                    description=description_field.value,
                    timeout=int(timeout_field.value),
                    enabled=enabled_switch.value,
                )
                self.page.close(dialog)
                self._refresh()
                self.page.show_snack_bar(ft.SnackBar(content=ft.Text("Job created successfully")))
            except Exception as ex:
                self.page.show_snack_bar(ft.SnackBar(content=ft.Text(f"Error: {ex}")))

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
                ft.TextButton("Cancel", on_click=lambda e: self.page.close(dialog)),
                ft.ElevatedButton("Create", on_click=create_job),
            ],
        )
        self.page.open(dialog)

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

        def update_job(e):
            try:
                update_job(
                    job.id,
                    name=name_field.value,
                    schedule=schedule_field.value,
                    command=command_field.value,
                    description=description_field.value,
                    timeout=int(timeout_field.value),
                    enabled=enabled_switch.value,
                )
                self.page.close(dialog)
                self._refresh()
                self.page.show_snack_bar(ft.SnackBar(content=ft.Text("Job updated successfully")))
            except Exception as ex:
                self.page.show_snack_bar(ft.SnackBar(content=ft.Text(f"Error: {ex}")))

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
                ft.TextButton("Cancel", on_click=lambda e: self.page.close(dialog)),
                ft.ElevatedButton("Save", on_click=update_job),
            ],
        )
        self.page.open(dialog)

    def _run_job_now(self, job):
        """Run a job immediately"""

        def run_async():
            output = run_job_now(job.id)
            self.page.show_snack_bar(
                ft.SnackBar(
                    content=ft.Text(f"Job completed: {output.status} ({output.duration:.1f}s)")
                )
            )
            self._refresh()

        import threading

        threading.Thread(target=run_async, daemon=True).start()

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

        content = ft.Column(
            [
                ft.Text(f"Output for: {job.name}", weight=ft.FontWeight.BOLD, size=16),
                ft.Divider(),
                ft.Column(
                    [
                        ft.Card(
                            content=ft.Container(
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
                                                    padding=ft.padding.symmetric(
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
                                            f"Duration: {out.duration:.1f}s | Code: {out.return_code}",
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
                            ),
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
            actions=[ft.TextButton("Close", on_click=lambda e: self.page.close(dialog))],
        )
        self.page.open(dialog)

    def _confirm_delete_job(self, job):
        """Confirm job deletion"""

        def delete(e):
            delete_job(job.id)
            self.page.close(dialog)
            self._refresh()
            self.page.show_snack_bar(ft.SnackBar(content=ft.Text("Job deleted")))

        dialog = ft.AlertDialog(
            title=ft.Text("Delete Job"),
            content=ft.Text(
                f"Are you sure you want to delete '{job.name}'? This cannot be undone."
            ),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: self.page.close(dialog)),
                ft.ElevatedButton("Delete", color=ft.Colors.ERROR, on_click=delete),
            ],
        )
        self.page.open(dialog)

    def _refresh(self):
        """Refresh the view"""
        self.app.content_area.content = self.build()
        self.page.update()
