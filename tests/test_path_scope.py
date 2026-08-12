"""Tests for the workspace-scoped path resolution (extra_dirs / base_dir).

The project workspace must be an allowed sandbox root and relative paths
must resolve against it, while traversal protection still applies.
"""

from hermes_mobile.tools.path_security import validate_and_resolve_path


class TestExtraDirs:
    def test_allows_path_inside_extra_dir(self, temp_dir):
        f = temp_dir / "file.txt"
        f.touch()
        resolved, err = validate_and_resolve_path(str(f), extra_dirs=[temp_dir])
        assert err is None
        assert resolved == f.resolve()

    def test_rejects_path_outside_extra_dir(self, temp_dir):
        outside = temp_dir.parent / "secret.txt"
        outside.touch()
        resolved, err = validate_and_resolve_path(str(outside), extra_dirs=[temp_dir])
        assert resolved is None
        assert err is not None
        assert "outside" in err

    def test_temp_dir_not_allowed_without_extra_dirs(self, temp_dir):
        """Without extra_dirs a random temp dir is not an allowed root."""
        f = temp_dir / "file.txt"
        f.touch()
        resolved, err = validate_and_resolve_path(str(f))
        assert resolved is None
        assert err is not None


class TestBaseDir:
    def test_relative_path_resolves_against_base_dir(self, temp_dir):
        f = temp_dir / "note.txt"
        f.touch()
        # base_dir changes where relative paths resolve; the dir must also be
        # an allowed root (extra_dirs) for the resolved file to be accepted.
        resolved, err = validate_and_resolve_path(
            "note.txt", base_dir=temp_dir, extra_dirs=[temp_dir]
        )
        assert err is None
        assert resolved == f.resolve()

    def test_traversal_still_blocked_with_base_dir(self, temp_dir):
        resolved, err = validate_and_resolve_path(
            "../escape.txt", base_dir=temp_dir, extra_dirs=[temp_dir]
        )
        assert resolved is None
        assert "traversal" in err.lower()

    def test_absolute_path_ignores_base_dir(self, temp_dir):
        f = temp_dir / "abs.txt"
        f.touch()
        resolved, err = validate_and_resolve_path(str(f), base_dir=temp_dir, extra_dirs=[temp_dir])
        assert err is None
        assert resolved == f.resolve()
