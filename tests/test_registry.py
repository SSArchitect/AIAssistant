"""Unit tests for skill registry."""
import pytest
from agent.skills.registry import SkillRegistry
from agent.skills.base import Skill, SkillMetadata, SkillResult


class DummySkill(Skill):
    def metadata(self) -> SkillMetadata:
        return SkillMetadata(name="dummy", description="A test skill")

    async def execute(self, **kwargs) -> SkillResult:
        return SkillResult(success=True, data="dummy result")


class AnotherSkill(Skill):
    def metadata(self) -> SkillMetadata:
        return SkillMetadata(name="another", description="Another test skill")

    async def execute(self, **kwargs) -> SkillResult:
        return SkillResult(success=True)


class DisabledSkill(Skill):
    def metadata(self) -> SkillMetadata:
        return SkillMetadata(name="disabled", description="Disabled", enabled=False)

    async def execute(self, **kwargs) -> SkillResult:
        return SkillResult(success=True)


class TestSkillRegistry:
    def test_register_and_get(self):
        registry = SkillRegistry()
        skill = DummySkill()
        registry.register(skill)

        retrieved = registry.get("dummy")
        assert retrieved is skill

    def test_get_nonexistent(self):
        registry = SkillRegistry()
        assert registry.get("nonexistent") is None

    def test_list_skills(self):
        registry = SkillRegistry()
        registry.register(DummySkill())
        registry.register(AnotherSkill())

        skills = registry.list_skills()
        assert len(skills) == 2
        names = {s.metadata().name for s in skills}
        assert names == {"dummy", "another"}

    def test_get_tool_definitions(self):
        registry = SkillRegistry()
        registry.register(DummySkill())

        defs = registry.get_tool_definitions()
        assert len(defs) == 1
        assert defs[0].name == "dummy"
        assert defs[0].description == "A test skill"

    def test_get_tool_definitions_skips_disabled_skills(self):
        registry = SkillRegistry()
        registry.register(DummySkill())
        registry.register(DisabledSkill())

        defs = registry.get_tool_definitions()

        assert [item.name for item in defs] == ["dummy"]

    def test_auto_discover_builtin(self):
        registry = SkillRegistry()
        registry.auto_discover("agent.skills.builtin")

        skills = registry.list_skills()
        names = {s.metadata().name for s in skills}
        assert "echo" in names
        assert "datetime" in names
        assert "calculator" in names
        assert "create_todo" in names
        assert "list_todos" in names
        assert "update_todo" in names
        assert "image_generation_v1" in names
        assert "deep_research_v1" not in names
        assert "weight_loss_v1" in names

    def test_auto_discover_invalid_package(self):
        """Should not crash on invalid package name."""
        registry = SkillRegistry()
        registry.auto_discover("nonexistent.package")
        assert len(registry.list_skills()) == 0

    def test_duplicate_register_overwrites(self):
        registry = SkillRegistry()
        skill1 = DummySkill()
        skill2 = DummySkill()
        registry.register(skill1)
        registry.register(skill2)

        assert registry.get("dummy") is skill2
        assert len(registry.list_skills()) == 1
