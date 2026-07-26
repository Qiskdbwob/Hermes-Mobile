"""Tests for the skills manager module."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from hermes_mobile.skills.manager import MobileSkill, MobileSkillManager


def _create_skill_file(skills_dir: Path, name: str, code: str) -> Path:
    path = skills_dir / f"{name}.py"
    path.write_text(code)
    return path


def _create_skill_package(skills_dir: Path, name: str, code: str = "") -> Path:
    pkg_dir = skills_dir / name
    pkg_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "name": name,
        "description": f"Test skill {name}",
        "schema": {
            "type": "object",
            "properties": {"input": {"type": "string", "description": "Input value"}},
            "required": ["input"],
        },
    }
    (pkg_dir / "skill.yaml").write_text(yaml.dump(manifest))

    if code:
        (pkg_dir / "main.py").write_text(code)
    else:
        (pkg_dir / "main.py").write_text(
            f'async def execute(input: str) -> str:\n    return f"Executed {name}: {input}"\n'
        )

    return pkg_dir


class TestMobileSkill:
    def test_creates_with_required_fields(self):
        skill = MobileSkill(name="test", description="A test skill", schema={"type": "object"})
        assert skill.name == "test"
        assert skill.description == "A test skill"
        assert skill.schema == {"type": "object"}
        assert skill.enabled is True
        assert skill.source == "local"

    def test_get_schema(self):
        schema = {"type": "object", "properties": {"q": {"type": "string"}}}
        skill = MobileSkill(name="my_skill", description="Does stuff", schema=schema)
        result = skill.get_schema()
        assert result["type"] == "function"
        assert result["function"]["name"] == "my_skill"
        assert result["function"]["parameters"] == schema

    def test_to_dict(self):
        skill = MobileSkill(name="test", description="desc", schema={}, enabled=False)
        d = skill.to_dict()
        assert d["name"] == "test"
        assert d["description"] == "desc"
        assert d["enabled"] is False
        assert "id" in d

    def test_from_dict(self):
        d = {
            "name": "restored",
            "description": "restored desc",
            "schema": {"type": "object"},
            "enabled": False,
            "path": "/tmp/test_skill.py",
        }
        skill = MobileSkill.from_dict(d)
        assert skill.name == "restored"
        assert skill.enabled is False
        assert skill.path == Path("/tmp/test_skill.py")

    def test_from_dict_minimal(self):
        d = {"name": "minimal", "description": "min", "schema": {}}
        skill = MobileSkill.from_dict(d)
        assert skill.name == "minimal"
        assert skill.enabled is True

    async def test_execute_python_skill_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            skills_dir = Path(tmp)
            skill_path = _create_skill_file(
                skills_dir,
                "greeter",
                "async def execute(name: str) -> str:\n    return f'Hello {name}!'",
            )
            skill = MobileSkill(
                name="greeter",
                description="Greets",
                schema={"type": "object"},
                path=skill_path,
            )
            result = await skill.execute(name="World")
            assert result == "Hello World!"

    async def test_execute_sync_skill_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            skills_dir = Path(tmp)
            skill_path = _create_skill_file(
                skills_dir,
                "calculator",
                "def execute(x: int, y: int) -> int:\n    return x + y",
            )
            skill = MobileSkill(
                name="calculator",
                description="Adds",
                schema={"type": "object"},
                path=skill_path,
            )
            result = await skill.execute(x=1, y=2)
            assert result == 3

    async def test_execute_class_based_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            skills_dir = Path(tmp)
            code = """
class MySkill:
    async def execute(self, msg: str) -> str:
        return f"Echo: {msg}"
"""
            _create_skill_file(skills_dir, "echo_skill", code)
            skill_path = skills_dir / "echo_skill.py"
            skill = MobileSkill(
                name="echo_skill",
                description="Echoes",
                schema={"type": "object"},
                path=skill_path,
            )
            result = await skill.execute(msg="hello")
            assert result == "Echo: hello"

    async def test_execute_raises_on_unknown_type(self):
        skill = MobileSkill(
            name="bad",
            description="bad",
            schema={},
            path=Path("/nonexistent"),
        )
        with pytest.raises(ValueError, match="Unknown skill type"):
            await skill.execute()

    async def test_execute_raises_on_no_execute_function(self):
        with tempfile.TemporaryDirectory() as tmp:
            skills_dir = Path(tmp)
            skill_path = _create_skill_file(skills_dir, "empty", "# no execute function")
            skill = MobileSkill(
                name="empty",
                description="empty",
                schema={},
                path=skill_path,
            )
            with pytest.raises(ValueError, match="No execute function"):
                await skill.execute()

    async def test_execute_does_not_raise_on_missing_loader(self, monkeypatch):
        with tempfile.TemporaryDirectory() as tmp:
            skills_dir = Path(tmp)
            skill_path = _create_skill_file(skills_dir, "ok", "async def execute(): return 42")

            import importlib.util

            original = importlib.util.spec_from_file_location

            def broken_spec(*args, **kwargs):
                return None

            monkeypatch.setattr(importlib.util, "spec_from_file_location", broken_spec)

            skill = MobileSkill(name="ok", description="ok", schema={}, path=skill_path)
            with pytest.raises(ValueError, match="Could not load"):
                await skill.execute()

    async def test_execute_package_skill(self, temp_dir: Path):
        pkg_dir = _create_skill_package(
            temp_dir,
            "pkg_skill",
            "async def execute(input: str) -> str:\n    return f'Pkg: {input}'",
        )
        skill = MobileSkill(
            name="pkg_skill",
            description="Package skill",
            schema={"type": "object"},
            path=pkg_dir,
        )
        result = await skill.execute(input="test")
        assert result == "Pkg: test"

    async def test_execute_sync_class_based_skill(self, temp_dir: Path):
        code = """
class MySkill:
    def execute(self, msg: str) -> str:
        return f"Sync: {msg}"
"""
        skill_path = _create_skill_file(temp_dir, "sync_class", code)
        skill = MobileSkill(
            name="sync_class",
            description="Sync class skill",
            schema={"type": "object"},
            path=skill_path,
        )
        result = await skill.execute(msg="hello")
        assert result == "Sync: hello"


class TestMobileSkillManager:
    def test_creates_skills_dir(self, temp_dir: Path):
        skills_dir = temp_dir / "my_skills"
        manager = MobileSkillManager(skills_dir)
        assert skills_dir.exists()

    def test_loads_nothing_from_empty_dir(self, temp_dir: Path):
        manager = MobileSkillManager(temp_dir)
        assert len(manager.get_all_skills()) == 0

    def test_loads_skill_file(self, temp_dir: Path):
        _create_skill_file(
            temp_dir,
            "hello",
            "async def execute(input: str) -> str:\n    return f'Hi {input}'",
        )
        manager = MobileSkillManager(temp_dir)
        skills = manager.get_all_skills()
        assert len(skills) == 1
        assert skills[0].name == "hello"

    def test_loads_skill_package(self, temp_dir: Path):
        _create_skill_package(temp_dir, "my_pkg_skill")
        manager = MobileSkillManager(temp_dir)
        skills = manager.get_all_skills()
        assert len(skills) >= 1
        names = [s.name for s in skills]
        assert "my_pkg_skill" in names

    def test_ignores_init_and_manager_files(self, temp_dir: Path):
        _create_skill_file(temp_dir, "__init__", "")
        _create_skill_file(temp_dir, "skill_manager", "")
        manager = MobileSkillManager(temp_dir)
        assert len(manager.get_all_skills()) == 0

    def test_get_skill(self, temp_dir: Path):
        _create_skill_file(
            temp_dir,
            "finder",
            "async def execute(q: str) -> str:\n    return q",
        )
        manager = MobileSkillManager(temp_dir)
        skill = manager.get_skill("finder")
        assert skill is not None
        assert skill.name == "finder"

    def test_get_skill_nonexistent(self, temp_dir: Path):
        manager = MobileSkillManager(temp_dir)
        assert manager.get_skill("nope") is None

    def test_get_active_skills(self, temp_dir: Path):
        _create_skill_file(temp_dir, "a", "async def execute(): return 1")
        _create_skill_file(temp_dir, "b", "async def execute(): return 2")
        manager = MobileSkillManager(temp_dir)
        skills = manager.get_active_skills()
        assert len(skills) == 2
        manager.disable_skill("a")
        active = manager.get_active_skills()
        assert len(active) == 1
        assert active[0].name == "b"

    def test_enable_disable_skill(self, temp_dir: Path):
        _create_skill_file(temp_dir, "tog", "async def execute(): return 1")
        manager = MobileSkillManager(temp_dir)
        skill = manager.get_skill("tog")
        assert skill is not None
        assert skill.enabled is True

        manager.disable_skill("tog")
        assert skill.enabled is False

        manager.enable_skill("tog")
        assert skill.enabled is True

    def test_enable_nonexistent_skill(self, temp_dir: Path):
        manager = MobileSkillManager(temp_dir)
        assert manager.enable_skill("ghost") is False

    def test_disable_nonexistent_skill(self, temp_dir: Path):
        manager = MobileSkillManager(temp_dir)
        assert manager.disable_skill("ghost") is False

    async def test_execute_skill_via_skill_obj(self, temp_dir: Path):
        _create_skill_file(
            temp_dir,
            "reverse",
            "async def execute(text: str) -> str:\n    return text[::-1]",
        )
        manager = MobileSkillManager(temp_dir)
        skill = manager.get_skill("reverse")
        assert skill is not None
        result = await skill.execute(text="hello")
        assert result == "olleh"

    def test_remove_skill(self, temp_dir: Path):
        _create_skill_file(temp_dir, "delete_me", "async def execute(): return 1")
        manager = MobileSkillManager(temp_dir)
        assert manager.remove_skill("delete_me") is True
        assert manager.get_skill("delete_me") is None

    def test_remove_nonexistent_skill(self, temp_dir: Path):
        manager = MobileSkillManager(temp_dir)
        assert manager.remove_skill("ghost") is False

    def test_get_skill_info(self, temp_dir: Path):
        _create_skill_file(
            temp_dir,
            "info_test",
            "async def execute(): return 1",
        )
        manager = MobileSkillManager(temp_dir)
        info = manager.get_skill_info("info_test")
        assert info is not None
        assert info["name"] == "info_test"

    def test_get_skill_info_nonexistent(self, temp_dir: Path):
        manager = MobileSkillManager(temp_dir)
        assert manager.get_skill_info("ghost") is None

    def test_export_skill(self, temp_dir: Path):
        _create_skill_file(temp_dir, "export_me", "async def execute(): return 1")
        manager = MobileSkillManager(temp_dir)
        export_path = temp_dir / "exported"
        assert manager.export_skill("export_me", export_path) is True

    def test_export_nonexistent_skill(self, temp_dir: Path):
        manager = MobileSkillManager(temp_dir)
        assert manager.export_skill("ghost", temp_dir) is False

    def test_export_file_skill(self, temp_dir: Path):
        skills_dir = temp_dir / "skills"
        skills_dir.mkdir()
        skill_path = _create_skill_file(skills_dir, "file_skill", "async def execute(): return 1")
        manager = MobileSkillManager(skills_dir)
        export_path = temp_dir / "exported"
        assert manager.export_skill("file_skill", export_path) is True

    def test_get_skill_info_package(self, temp_dir: Path):
        pkg_dir = _create_skill_package(temp_dir, "info_pkg")
        (pkg_dir / "README.md").write_text("# Info Pkg\nDocs here")
        manager = MobileSkillManager(temp_dir)
        info = manager.get_skill_info("info_pkg")
        assert info is not None
        assert info["name"] == "info_pkg"
        assert "readme" in info
        assert "source" in info

    def test_load_skill_package_error(self, temp_dir: Path):
        bad_dir = temp_dir / "bad_pkg"
        bad_dir.mkdir()
        (bad_dir / "skill.yaml").write_text("invalid: yaml: : broken")
        manager = MobileSkillManager(temp_dir)
        assert manager.get_skill("bad_pkg") is None

    def test_load_skill_file_with_schema(self, temp_dir: Path):
        code = '''"""
My docstring
schema: {type: object, properties: {q: {type: string}}}
"""
async def execute(q: str) -> str:
    return q
'''
        _create_skill_file(temp_dir, "schema_skill", code)
        manager = MobileSkillManager(temp_dir)
        skill = manager.get_skill("schema_skill")
        assert skill is not None
        assert "schema" in skill.description or skill.schema != {}

    def test_load_skill_file_error(self, temp_dir: Path, monkeypatch):
        manager = MobileSkillManager(temp_dir)
        bad_file = temp_dir / "broken.py"
        bad_file.write_text("# some content")

        def broken_read_text(*args, **kwargs):
            raise OSError("Permission denied")

        monkeypatch.setattr(Path, "read_text", broken_read_text)
        manager._load_skill_file(bad_file)
        assert manager.get_skill("broken") is None

    def test_remove_directory_skill(self, temp_dir: Path):
        pkg_dir = _create_skill_package(temp_dir, "del_pkg")
        assert pkg_dir.exists()
        manager = MobileSkillManager(temp_dir)
        assert manager.remove_skill("del_pkg") is True
        assert manager.get_skill("del_pkg") is None
        assert not pkg_dir.exists()

    def test_remove_file_skill_removes_file(self, temp_dir: Path):
        skill_path = _create_skill_file(temp_dir, "del_file", "async def execute(): return 1")
        assert skill_path.exists()
        manager = MobileSkillManager(temp_dir)
        assert manager.remove_skill("del_file") is True
        assert not skill_path.exists()

    def test_create_skill_template(self, temp_dir: Path):
        manager = MobileSkillManager(temp_dir)
        result = manager.create_skill_template("my_new_skill", "A custom skill")
        assert result.exists()
        assert (result / "skill.yaml").exists()
        assert (result / "main.py").exists()
        assert (result / "README.md").exists()
        skill = manager.get_skill("my_new_skill")
        assert skill is not None
        assert skill.description == "A custom skill"

    async def test_install_skill_from_path_dir(self, temp_dir: Path):
        src_dir = temp_dir / "imported_pkg"
        src_dir.mkdir()
        manifest = {
            "name": "imported_pkg",
            "description": "Imported package",
            "schema": {"type": "object", "properties": {}},
        }
        (src_dir / "skill.yaml").write_text(yaml.dump(manifest))
        (src_dir / "main.py").write_text("async def execute(): return 'imported'")

        manager = MobileSkillManager(temp_dir / "skills_dest")
        result = await manager.install_skill_from_path(src_dir)
        assert result is not None
        assert result.name == "imported_pkg"

    async def test_install_skill_from_path_file(self, temp_dir: Path):
        src_file = _create_skill_file(
            temp_dir, "standalone", "async def execute(): return 'standalone'"
        )
        manager = MobileSkillManager(temp_dir / "skills_dest")
        result = await manager.install_skill_from_path(src_file)
        assert result is not None
        assert result.name == "standalone"

    async def test_install_skill_from_path_overwrite(self, temp_dir: Path):
        pkg_dir = _create_skill_package(temp_dir, "overwrite_me")
        manager = MobileSkillManager(temp_dir / "skills_dest")
        result1 = await manager.install_skill_from_path(pkg_dir)
        assert result1 is not None
        result2 = await manager.install_skill_from_path(pkg_dir)
        assert result2 is not None
        assert result2.name == "overwrite_me"

    async def test_install_skill_from_path_error(self, temp_dir: Path):
        manager = MobileSkillManager(temp_dir)
        fake = Path("/nonexistent/path")
        result = await manager.install_skill_from_path(fake)
        assert result is None

    async def test_install_skill_from_url_generic_fail(self, temp_dir: Path):
        manager = MobileSkillManager(temp_dir)
        result = await manager.install_skill_from_url("https://invalid.url/skill.py")
        assert result is None

    def test_export_package_skill(self, temp_dir: Path):
        pkg_dir = _create_skill_package(temp_dir, "pkg_export")
        manager = MobileSkillManager(temp_dir)
        export_path = temp_dir / "exported"
        assert manager.export_skill("pkg_export", export_path) is True
        assert (export_path / "pkg_export").exists()

    def test_load_skill_file_schema_error(self, temp_dir: Path):
        code = '''"""
My skill
schema: !!invalid [tag
"""
async def execute(): return 1
'''
        _create_skill_file(temp_dir, "bad_schema", code)
        manager = MobileSkillManager(temp_dir)
        skill = manager.get_skill("bad_schema")
        assert skill is not None
        assert skill.name == "bad_schema"
