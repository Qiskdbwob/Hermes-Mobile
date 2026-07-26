"""Tests for the toolsets system."""

from hermes_mobile.toolsets import (
    HERMES_CORE_TOOLS,
    HERMES_WEBHOOK_SAFE_TOOLS,
    TOOLSETS,
    TOOL_SCHEMAS,
    DISTRIBUTIONS,
    ToolCategory,
    get_all_toolsets,
    get_distribution,
    get_tool_schema,
    get_tool_schemas,
    get_toolset,
    get_toolset_info,
    list_distributions,
    list_toolsets_by_category,
    resolve_toolset,
    validate_toolset,
)


class TestToolCategory:
    def test_enum_values(self):
        assert ToolCategory.WEB.value == "web"
        assert ToolCategory.TERMINAL.value == "terminal"
        assert ToolCategory.FILE.value == "file"
        assert ToolCategory.VISION.value == "vision"
        assert ToolCategory.BROWSER.value == "browser"
        assert ToolCategory.CODE.value == "code"
        assert ToolCategory.SKILLS.value == "skills"
        assert ToolCategory.PLANNING.value == "planning"
        assert ToolCategory.SPEECH.value == "speech"
        assert ToolCategory.CRON.value == "cron"
        assert ToolCategory.SMART_HOME.value == "smart_home"
        assert ToolCategory.KANBAN.value == "kanban"
        assert ToolCategory.COMPUTER_USE.value == "computer_use"
        assert ToolCategory.SESSION.value == "session"
        assert ToolCategory.CLARIFY.value == "clarify"
        assert ToolCategory.IMAGE_GEN.value == "image_gen"
        assert ToolCategory.VIDEO.value == "video"

    def test_unique_values(self):
        values = [cat.value for cat in ToolCategory]
        assert len(values) == len(set(values))


class TestHermesCoreTools:
    def test_contains_web_tools(self):
        assert "web_search" in HERMES_CORE_TOOLS
        assert "web_extract" in HERMES_CORE_TOOLS

    def test_contains_terminal_tools(self):
        assert "terminal" in HERMES_CORE_TOOLS
        assert "process" in HERMES_CORE_TOOLS

    def test_contains_file_tools(self):
        assert "read_file" in HERMES_CORE_TOOLS
        assert "write_file" in HERMES_CORE_TOOLS
        assert "patch" in HERMES_CORE_TOOLS
        assert "search_files" in HERMES_CORE_TOOLS

    def test_contains_browser_tools(self):
        assert "browser_navigate" in HERMES_CORE_TOOLS
        assert "browser_snapshot" in HERMES_CORE_TOOLS
        assert "browser_cdp" in HERMES_CORE_TOOLS
        assert "browser_dialog" in HERMES_CORE_TOOLS

    def test_contains_kanban_tools(self):
        assert "kanban_show" in HERMES_CORE_TOOLS
        assert "kanban_create" in HERMES_CORE_TOOLS
        assert "kanban_complete" in HERMES_CORE_TOOLS

    def test_no_duplicates(self):
        assert len(HERMES_CORE_TOOLS) == len(set(HERMES_CORE_TOOLS))

    def test_core_tools_count(self):
        assert len(HERMES_CORE_TOOLS) >= 30  # At least 30 core tools


class TestHermesWebhookSafeTools:
    def test_all_are_core_tools(self):
        for tool in HERMES_WEBHOOK_SAFE_TOOLS:
            assert tool in HERMES_CORE_TOOLS

    def test_no_duplicates(self):
        assert len(HERMES_WEBHOOK_SAFE_TOOLS) == len(set(HERMES_WEBHOOK_SAFE_TOOLS))


class TestToolsets:
    def test_toolset_structure(self):
        for name, toolset in TOOLSETS.items():
            assert "description" in toolset, f"Toolset {name!r} missing description"
            assert "tools" in toolset, f"Toolset {name!r} missing tools"
            assert "includes" in toolset, f"Toolset {name!r} missing includes"
            assert "category" in toolset, f"Toolset {name!r} missing category"
            assert isinstance(toolset["description"], str)
            assert isinstance(toolset["tools"], list)
            assert isinstance(toolset["includes"], list)
            assert isinstance(toolset["category"], ToolCategory)

    def test_all_tool_references_valid(self):
        all_known = set(HERMES_CORE_TOOLS) | set(TOOLSETS.keys())
        for name, toolset in TOOLSETS.items():
            for tool in toolset["tools"]:
                assert tool in HERMES_CORE_TOOLS, (
                    f"Toolset {name!r} references unknown tool {tool!r}"
                )
            for inc in toolset["includes"]:
                assert inc in TOOLSETS, (
                    f"Toolset {name!r} references unknown included toolset {inc!r}"
                )

    def test_resolve_toolset_web(self):
        tools = resolve_toolset("web")
        assert "web_search" in tools
        assert "web_extract" in tools
        assert len(tools) == 2

    def test_resolve_toolset_research(self):
        tools = resolve_toolset("research")
        assert "web_search" in tools
        assert "browser_navigate" in tools
        assert "vision_analyze" in tools
        assert "todo" in tools

    def test_resolve_toolset_development(self):
        tools = resolve_toolset("development")
        assert "terminal" in tools
        assert "read_file" in tools
        assert "execute_code" in tools
        assert "web_search" in tools
        assert "browser_navigate" in tools

    def test_resolve_toolset_minimal(self):
        tools = resolve_toolset("minimal")
        assert "web_search" in tools
        assert "web_extract" not in tools
        assert len(tools) == 1

    def test_resolve_toolset_safe(self):
        tools = resolve_toolset("safe")
        assert "web_search" in tools
        assert "terminal" not in tools
        assert "process" not in tools

    def test_resolve_toolset_full_stack(self):
        tools = resolve_toolset("full_stack")
        assert "web_search" in tools
        assert "terminal" in tools
        assert "browser_navigate" in tools
        assert "kanban_create" in tools
        assert "computer_use" in tools
        assert "x_search" in tools

    def test_resolve_nonexistent_toolset(self):
        tools = resolve_toolset("nonexistent_toolset_xyz")
        assert tools == set()

    def test_resolve_core_tool_as_name(self):
        tools = resolve_toolset("web_search")
        assert tools == {"web_search"}

    def test_resolve_unknown_string(self):
        tools = resolve_toolset("__definitely_not_a_tool__")
        assert tools == set()

    def test_circular_reference_protection(self):
        tools = resolve_toolset("web")
        assert isinstance(tools, set)
        # Should not infinite-loop
        resolve_toolset("full_stack")

    def test_automation_toolset(self):
        tools = resolve_toolset("automation")
        assert "terminal" in tools
        assert "browser_navigate" in tools
        assert "cronjob" in tools
        assert "ha_list_entities" in tools

    def test_creative_toolset(self):
        tools = resolve_toolset("creative")
        assert "image_generate" in tools
        assert "vision_analyze" in tools
        assert "web_search" in tools


class TestGetToolset:
    def test_get_toolset_returns_sorted(self):
        tools = get_toolset("web")
        assert tools == sorted(tools)
        assert tools == ["web_extract", "web_search"]

    def test_get_toolset_research(self):
        tools = get_toolset("research")
        assert "browser_snapshot" in tools
        assert "memory" in tools


class TestGetAllToolsets:
    def test_returns_copy(self):
        all_sets = get_all_toolsets()
        assert all_sets == TOOLSETS
        assert all_sets is not TOOLSETS  # Should be a copy

    def test_contains_expected_keys(self):
        all_sets = get_all_toolsets()
        assert "web" in all_sets
        assert "browser" in all_sets
        assert "terminal" in all_sets
        assert "full_stack" in all_sets


class TestValidateToolset:
    def test_valid_toolset(self):
        assert validate_toolset("web") is True
        assert validate_toolset("research") is True
        assert validate_toolset("full_stack") is True

    def test_valid_core_tool(self):
        assert validate_toolset("web_search") is True

    def test_invalid_toolset(self):
        assert validate_toolset("nonexistent") is False


class TestGetToolsetInfo:
    def test_info_structure(self):
        info = get_toolset_info("web")
        assert info is not None
        assert info["name"] == "web"
        assert info["description"] == "Web research and content extraction tools"
        assert isinstance(info["tools"], list)
        assert isinstance(info["includes"], list)
        assert info["category"] == "web"
        assert isinstance(info["resolved_tools"], list)

    def test_info_nonexistent(self):
        assert get_toolset_info("nonexistent") is None


class TestListToolsetsByCategory:
    def test_returns_dict(self):
        by_cat = list_toolsets_by_category()
        assert isinstance(by_cat, dict)
        assert "web" in by_cat
        assert "file" in by_cat
        assert "browser" in by_cat

    def test_all_toolsets_accounted(self):
        by_cat = list_toolsets_by_category()
        all_listed = {name for names in by_cat.values() for name in names}
        assert all_listed == set(TOOLSETS.keys())

    def test_no_duplicate_names(self):
        by_cat = list_toolsets_by_category()
        all_listed = [name for names in by_cat.values() for name in names]
        assert len(all_listed) == len(set(all_listed))


class TestGetToolSchema:
    def test_existing_schema(self):
        schema = get_tool_schema("web_search")
        assert schema is not None
        assert "function" in schema
        assert schema["function"]["name"] == "web_search"

    def test_nonexistent_schema(self):
        assert get_tool_schema("nonexistent") is None

    def test_get_tool_schemas_multiple(self):
        schemas = get_tool_schemas(["web_search", "web_extract", "nonexistent"])
        assert len(schemas) == 2
        assert all(s["function"]["name"].startswith("web_") for s in schemas)

    def test_get_tool_schemas_empty(self):
        assert get_tool_schemas([]) == []


class TestDistributions:
    def test_get_existing_distribution(self):
        dist = get_distribution("default")
        assert dist is not None
        assert "description" in dist
        assert "toolsets" in dist

    def test_get_nonexistent_distribution(self):
        assert get_distribution("nonexistent") is None

    def test_list_distributions(self):
        names = list_distributions()
        assert "default" in names
        assert len(names) == len(set(names))


class TestResolveToolsetEdgeCases:
    def test_circular_reference_detected(self):
        """Trigger circular reference protection by passing visited set directly."""
        tools = resolve_toolset("web", visited={"web"})
        assert tools == set()

    def test_circular_via_includes(self):
        """Verify no crash when no actual cycle exists (sanity check)."""
        tools = resolve_toolset("full_stack")
        assert isinstance(tools, set)
        assert len(tools) > 0
