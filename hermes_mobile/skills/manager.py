"""Mobile Skills Manager - Handles skill discovery, installation, and execution"""

import logging
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)


class MobileSkill:
    """Represents a mobile skill"""

    def __init__(
        self,
        name: str,
        description: str,
        schema: Dict[str, Any],
        source: str = "local",
        enabled: bool = True,
        path: Optional[Path] = None,
    ):
        self.id = str(uuid.uuid4())
        self.name = name
        self.description = description
        self.schema = schema
        self.source = source
        self.enabled = enabled
        self.path = path
        self._module = None

    def get_schema(self) -> Dict[str, Any]:
        """Get the tool schema for this skill"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.schema,
            },
        }

    async def execute(self, **kwargs) -> Any:
        """Execute the skill"""
        if self.path and self.path.suffix == ".py":
            return await self._execute_python_skill(**kwargs)
        elif self.path and (self.path / "main.py").exists():
            return await self._execute_package_skill(**kwargs)
        else:
            raise ValueError(f"Unknown skill type for {self.name}")

    async def _execute_python_skill(self, **kwargs) -> Any:
        """Execute a Python skill file"""
        import importlib.util

        spec = importlib.util.spec_from_file_location(self.name, self.path)
        if spec is None or spec.loader is None:
            raise ValueError(f"Could not load skill from {self.path}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Look for execute function
        if hasattr(module, "execute"):
            if asyncio.iscoroutinefunction(module.execute):
                return await module.execute(**kwargs)
            else:
                return module.execute(**kwargs)

        # Look for class with execute method
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if isinstance(attr, type) and hasattr(attr, "execute"):
                instance = attr()
                if asyncio.iscoroutinefunction(instance.execute):
                    return await instance.execute(**kwargs)
                else:
                    return instance.execute(**kwargs)

        raise ValueError(f"No execute function found in skill {self.name}")

    async def _execute_package_skill(self, **kwargs) -> Any:
        """Execute a package skill"""
        main_path = self.path / "main.py"
        return await self._execute_python_skill(path=main_path, **kwargs)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "schema": self.schema,
            "source": self.source,
            "enabled": self.enabled,
            "path": str(self.path) if self.path else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MobileSkill":
        skill = cls(
            name=data["name"],
            description=data["description"],
            schema=data["schema"],
            source=data.get("source", "local"),
            enabled=data.get("enabled", True),
            path=Path(data["path"]) if data.get("path") else None,
        )
        skill.id = data.get("id", str(uuid.uuid4()))
        return skill


class MobileSkillManager:
    """Manages skills for the mobile agent"""

    def __init__(self, skills_dir: Path):
        self.skills_dir = Path(skills_dir)
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self._skills: Dict[str, MobileSkill] = {}
        self._load_skills()

    def _load_skills(self):
        """Load skills from the skills directory"""
        # Load from skill packages (directories with skill.yaml)
        for skill_dir in self.skills_dir.iterdir():
            if skill_dir.is_dir() and (skill_dir / "skill.yaml").exists():
                self._load_skill_package(skill_dir)

        # Load from individual Python files
        for skill_file in self.skills_dir.glob("*.py"):
            if skill_file.name not in ("__init__.py", "skill_manager.py"):
                self._load_skill_file(skill_file)

    def _load_skill_package(self, skill_dir: Path):
        """Load a skill from a package directory"""
        try:
            with open(skill_dir / "skill.yaml") as f:
                skill_data = yaml.safe_load(f)

            skill = MobileSkill(
                name=skill_data["name"],
                description=skill_data.get("description", ""),
                schema=skill_data.get("schema", {}),
                source="package",
                enabled=skill_data.get("enabled", True),
                path=skill_dir,
            )
            self._skills[skill.name] = skill
            logger.info(f"Loaded skill package: {skill.name}")
        except Exception as e:
            logger.error(f"Failed to load skill package {skill_dir}: {e}")

    def _load_skill_file(self, skill_file: Path):
        """Load a skill from a Python file"""
        try:
            content = skill_file.read_text()

            # Parse the file for skill metadata
            name = skill_file.stem
            description = ""
            schema = {}

            if '"""' in content:
                docstring = content.split('"""')[1]
                lines = docstring.strip().split("\n")
                if lines:
                    description = lines[0]
                    for line in lines:
                        if line.strip().startswith("schema:"):
                            try:
                                schema = yaml.safe_load(line.split("schema:", 1)[1])
                            except Exception:
                                pass

            skill = MobileSkill(
                name=name,
                description=description,
                schema=schema,
                source="file",
                enabled=True,
                path=skill_file,
            )
            self._skills[skill.name] = skill
            logger.info(f"Loaded skill file: {skill.name}")
        except Exception as e:
            logger.error(f"Failed to load skill file {skill_file}: {e}")

    def get_skill(self, name: str) -> Optional[MobileSkill]:
        """Get a skill by name"""
        return self._skills.get(name)

    def get_active_skills(self) -> List[MobileSkill]:
        """Get all enabled skills"""
        return [s for s in self._skills.values() if s.enabled]

    def get_all_skills(self) -> List[MobileSkill]:
        """Get all skills"""
        return list(self._skills.values())

    def enable_skill(self, name: str) -> bool:
        """Enable a skill"""
        if name in self._skills:
            self._skills[name].enabled = True
            return True
        return False

    def disable_skill(self, name: str) -> bool:
        """Disable a skill"""
        if name in self._skills:
            self._skills[name].enabled = False
            return True
        return False

    def remove_skill(self, name: str) -> bool:
        """Remove a skill"""
        if name in self._skills:
            skill = self._skills[name]
            if skill.path and skill.path.exists():
                if skill.path.is_dir():
                    shutil.rmtree(skill.path)
                else:
                    skill.path.unlink()
            del self._skills[name]
            return True
        return False

    async def install_skill_from_url(self, url: str) -> Optional[MobileSkill]:
        """Install a skill from a URL (GitHub, etc.)"""
        try:
            import tempfile

            with tempfile.TemporaryDirectory() as tmpdir:
                tmp_path = Path(tmpdir)

                if url.startswith("https://github.com/"):
                    # Clone GitHub repo
                    result = subprocess.run(
                        ["git", "clone", "--depth", "1", url, "skill"],
                        cwd=tmp_path,
                        capture_output=True,
                        text=True,
                    )
                    if result.returncode != 0:
                        raise Exception(f"Git clone failed: {result.stderr}")

                    skill_dir = tmp_path / "skill"
                else:
                    # Download single file
                    import urllib.request

                    skill_file = tmp_path / "skill.py"
                    urllib.request.urlretrieve(url, skill_file)
                    skill_dir = skill_file

                # Install to skills directory
                if skill_dir.is_dir():
                    dest = self.skills_dir / skill_dir.name
                    if dest.exists():
                        shutil.rmtree(dest)
                    shutil.copytree(skill_dir, dest)
                    self._load_skill_package(dest)
                    return self._skills.get(skill_dir.name)
                else:
                    dest = self.skills_dir / skill_dir.name
                    shutil.copy2(skill_dir, dest)
                    self._load_skill_file(dest)
                    return self._skills.get(skill_dir.stem)

        except Exception as e:
            logger.error(f"Failed to install skill from {url}: {e}")
            return None

    async def install_skill_from_path(self, path: Path) -> Optional[MobileSkill]:
        """Install a skill from a local path"""
        try:
            if path.is_dir():
                dest = self.skills_dir / path.name
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(path, dest)
                self._load_skill_package(dest)
                return self._skills.get(path.name)
            else:
                dest = self.skills_dir / path.name
                shutil.copy2(path, dest)
                self._load_skill_file(dest)
                return self._skills.get(path.stem)
        except Exception as e:
            logger.error(f"Failed to install skill from {path}: {e}")
            return None

    def create_skill_template(self, name: str, description: str = "") -> Path:
        """Create a new skill template"""
        skill_dir = self.skills_dir / name
        skill_dir.mkdir(parents=True, exist_ok=True)

        # Create skill.yaml
        skill_yaml = {
            "name": name,
            "description": description,
            "version": "1.0.0",
            "author": "Hermes Mobile User",
            "schema": {
                "type": "object",
                "properties": {
                    "input": {"type": "string", "description": "Input parameter"},
                },
                "required": ["input"],
            },
            "enabled": True,
            "tags": [],
        }

        with open(skill_dir / "skill.yaml", "w") as f:
            yaml.dump(skill_yaml, f, default_flow_style=False)

        # Create main.py
        main_py = f'''"""
{name} - {description}
"""

async def execute(input: str) -> str:
    """Execute the skill"""
    # TODO: Implement skill logic
    return f"Skill {name} executed with input: {{input}}"
'''

        with open(skill_dir / "main.py", "w") as f:
            f.write(main_py)

        # Create README
        readme = f"""# {name}

{description}

## Usage

This skill can be invoked by the Hermes Mobile agent.

## Parameters

- `input` (string): Input parameter

## Returns

String result
"""

        with open(skill_dir / "README.md", "w") as f:
            f.write(readme)

        self._load_skill_package(skill_dir)
        return skill_dir

    def export_skill(self, name: str, export_path: Path) -> bool:
        """Export a skill to a directory"""
        skill = self._skills.get(name)
        if not skill or not skill.path:
            return False

        if skill.path.is_dir():
            shutil.copytree(skill.path, export_path / name, dirs_exist_ok=True)
        else:
            export_path.mkdir(parents=True, exist_ok=True)
            shutil.copy2(skill.path, export_path / skill.path.name)

        return True

    def get_skill_info(self, name: str) -> Optional[Dict[str, Any]]:
        """Get detailed skill information"""
        skill = self._skills.get(name)
        if not skill:
            return None

        info = skill.to_dict()
        if skill.path and skill.path.is_dir():
            readme = skill.path / "README.md"
            if readme.exists():
                info["readme"] = readme.read_text()

            main_py = skill.path / "main.py"
            if main_py.exists():
                info["source"] = main_py.read_text()

        return info
