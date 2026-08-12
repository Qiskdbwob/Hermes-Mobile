"""File tools must honor the active project workspace.

Regression coverage for the fix: project_switch/artifacts set
agent._workspace but no file tool used it, so project files were rejected
as "outside allowed directories" and relative paths resolved against cwd.
"""

from hermes_mobile.core.agent import MobileAgent


class TestWorkspaceFileScope:
    async def test_read_file_resolves_relative_to_workspace(self, tmp_path):
        agent = MobileAgent()
        agent._workspace = tmp_path
        (tmp_path / "note.txt").write_text("hello workspace")

        result = await agent._tool_read_file("note.txt")

        assert result == "hello workspace"

    async def test_read_file_blocks_path_outside_workspace(self, tmp_path):
        agent = MobileAgent()
        agent._workspace = tmp_path
        outside = tmp_path.parent / "secret.txt"
        outside.write_text("secret")

        result = await agent._tool_read_file(str(outside))

        assert "Error" in result
        assert "outside" in result

    async def test_write_file_lands_in_workspace(self, tmp_path):
        agent = MobileAgent()
        agent._workspace = tmp_path

        result = await agent._tool_write_file("new.txt", "content")

        assert "Error" not in result
        assert (tmp_path / "new.txt").read_text() == "content"

    async def test_list_files_uses_workspace_for_dot(self, tmp_path):
        agent = MobileAgent()
        agent._workspace = tmp_path
        (tmp_path / "a.txt").write_text("a")

        result = await agent._tool_list_files(".")

        assert any("a.txt" in p for p in result)

    async def test_search_files_scoped_to_workspace(self, tmp_path):
        agent = MobileAgent()
        agent._workspace = tmp_path
        (tmp_path / "target.txt").write_text("needle inside")

        result = await agent._tool_search_files("needle", path=".")

        assert result["count"] >= 1

    async def test_patch_scoped_to_workspace(self, tmp_path):
        agent = MobileAgent()
        agent._workspace = tmp_path
        (tmp_path / "p.txt").write_text("hello world")

        result = await agent._tool_patch("p.txt", "hello", "goodbye")

        assert "error" not in result
        assert (tmp_path / "p.txt").read_text() == "goodbye world"
