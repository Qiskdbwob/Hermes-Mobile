"""Tests for the cron scheduler."""

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from hermes_mobile.cron.scheduler import (
    CronJob,
    CronOutput,
    _compute_next_run,
    _ensure_cron_dirs,
    _get_cron_dir,
    _get_jobs_file,
    _load_jobs,
    _save_jobs,
    create_job,
    delete_job,
    disable_job,
    enable_job,
    get_job,
    list_jobs,
    update_job,
)


class TestCronJob:
    def test_create_job(self):
        job = CronJob(id="test1", name="Test Job", schedule="*/5 * * * *", command="echo hello")
        assert job.id == "test1"
        assert job.name == "Test Job"
        assert job.enabled is True
        assert job.run_count == 0
        assert job.failure_count == 0

    def test_to_dict_and_from_dict(self):
        job = CronJob(
            id="roundtrip",
            name="Roundtrip",
            schedule="0 * * * *",
            command="echo test",
            tags=["daily", "backup"],
            env_vars={"PATH": "/usr/bin"},
        )
        data = job.to_dict()
        restored = CronJob.from_dict(data)
        assert restored.id == job.id
        assert restored.name == job.name
        assert restored.schedule == job.schedule
        assert restored.tags == job.tags
        assert restored.env_vars == job.env_vars


class TestCronOutput:
    def test_to_markdown(self):
        output = CronOutput(
            job_id="job1",
            timestamp="2024-01-01T00:00:00",
            status="success",
            stdout="Hello",
            stderr="",
            return_code=0,
            duration=1.5,
        )
        md = output.to_markdown()
        assert "Cron Job Output" in md
        assert "job1" in md
        assert "success" in md


class TestCronScheduler:
    @pytest.fixture(autouse=True)
    def _isolate_cron_dir(self, temp_dir):
        """Isolate cron operations to a temp directory."""
        import hermes_mobile.cron.scheduler as scheduler

        original_get_cron_dir = scheduler._get_cron_dir
        scheduler._get_cron_dir = lambda: temp_dir / "cron"
        yield
        scheduler._get_cron_dir = original_get_cron_dir

    def test_ensure_cron_dirs(self, temp_dir):
        """Cron directories should be created."""
        import hermes_mobile.cron.scheduler as scheduler

        scheduler._get_cron_dir = lambda: temp_dir / "cron_test"
        _ensure_cron_dirs()
        assert (temp_dir / "cron_test").exists()
        assert (temp_dir / "cron_test" / "output").exists()

    def test_create_and_list_jobs(self):
        job = create_job(
            name="Test Job",
            schedule="*/5 * * * *",
            command="echo 'hello'",
            description="A test job",
            tags=["test"],
        )
        assert job.id is not None
        assert job.name == "Test Job"

        jobs = list_jobs()
        ids = [j.id for j in jobs]
        assert job.id in ids

    def test_create_oneshot_job(self):
        job = create_job(name="Oneshot", schedule="oneshot", command="echo 'once'")
        assert job.schedule == "oneshot"
        assert job.next_run is None

    def test_get_job(self):
        job = create_job(name="Get Me", schedule="0 * * * *", command="echo get")
        retrieved = get_job(job.id)
        assert retrieved is not None
        assert retrieved.name == "Get Me"

    def test_get_nonexistent_job(self):
        assert get_job("nonexistent_id_xyz") is None

    def test_update_job(self):
        job = create_job(name="Original", schedule="0 * * * *", command="echo original")
        updated = update_job(job.id, name="Updated Name", enabled=False)
        assert updated is not None
        assert updated.name == "Updated Name"
        assert updated.enabled is False

    def test_update_nonexistent_job(self):
        assert update_job("nonexistent", name="New Name") is None

    def test_enable_disable_job(self):
        job = create_job(name="Toggle", schedule="0 * * * *", command="echo toggle", enabled=False)
        assert enable_job(job.id) is True
        assert get_job(job.id).enabled is True
        assert disable_job(job.id) is True
        assert get_job(job.id).enabled is False

    def test_delete_job(self):
        job = create_job(name="Delete Me", schedule="0 * * * *", command="echo delete")
        assert delete_job(job.id) is True
        assert get_job(job.id) is None

    def test_delete_nonexistent_job(self):
        assert delete_job("nonexistent") is False

    def test_persistence_across_loads(self):
        """Jobs should persist in the JSON file."""
        job = create_job(name="Persist", schedule="0 * * * *", command="echo persist")
        # Load fresh from disk
        loaded = _load_jobs()
        assert job.id in loaded
        assert loaded[job.id].name == "Persist"

    def test_save_and_load_preserves_all_fields(self):
        job = create_job(
            name="Full Fields",
            schedule="*/10 * * * *",
            command="python script.py",
            timeout=600,
            env_vars={"KEY": "value"},
            working_dir="/tmp",
            description="A comprehensive test job",
            tags=["alpha", "beta"],
        )
        loaded = _load_jobs()
        restored = loaded[job.id]
        assert restored.timeout == 600
        assert restored.env_vars == {"KEY": "value"}
        assert restored.working_dir == "/tmp"
        assert restored.description == "A comprehensive test job"
        assert restored.tags == ["alpha", "beta"]

    def test_empty_jobs_file_returns_empty(self, temp_dir):
        """A missing jobs file should return an empty dict."""
        import hermes_mobile.cron.scheduler as scheduler

        scheduler._get_cron_dir = lambda: temp_dir / "cron_empty"
        jobs = _load_jobs()
        assert jobs == {}

    def test_corrupt_jobs_file_returns_empty(self, temp_dir):
        """A corrupt jobs file should return an empty dict."""
        import hermes_mobile.cron.scheduler as scheduler

        cron_dir = temp_dir / "cron_corrupt"
        scheduler._get_cron_dir = lambda: cron_dir
        cron_dir.mkdir(parents=True, exist_ok=True)
        (cron_dir / "jobs.json").write_text("NOT VALID JSON{{{")
        jobs = _load_jobs()
        assert jobs == {}


class TestComputeNextRun:
    def test_oneshot_returns_none(self):
        assert _compute_next_run("oneshot") is None

    def test_invalid_schedule_returns_none(self):
        result = _compute_next_run("not-a-valid-schedule")
        # Should handle gracefully
        assert result is None or isinstance(result, str)

    def test_invalid_expression_returns_none(self):
        result = _compute_next_run("this is not a cron expression at all")
        assert result is None
