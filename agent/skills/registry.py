from __future__ import annotations
import importlib
import inspect
import logging
import pkgutil
from pathlib import Path

from .base import Skill
from agent.llm.base import ToolDefinition

logger = logging.getLogger(__name__)


class SkillRegistry:
    def __init__(self):
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        meta = skill.metadata()
        self._skills[meta.name] = skill
        logger.info(f"Registered skill: {meta.name}")

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def list_skills(self) -> list[Skill]:
        return list(self._skills.values())

    def get_tool_definitions(self) -> list[ToolDefinition]:
        """Convert all skills to LLM tool definitions."""
        definitions = []
        for skill in self._skills.values():
            if not skill.metadata().enabled:
                continue
            td = skill.to_tool_definition()
            definitions.append(
                ToolDefinition(
                    name=td["name"],
                    description=td["description"],
                    parameters=td["parameters"],
                )
            )
        return definitions

    def auto_discover(self, *packages: str) -> None:
        """Auto-discover and register skills from packages."""
        for package_name in packages:
            try:
                package = importlib.import_module(package_name)
            except ImportError as e:
                logger.warning(f"Could not import package {package_name}: {e}")
                continue

            package_path = Path(package.__file__).parent

            for _, module_name, _ in pkgutil.iter_modules([str(package_path)]):
                full_name = f"{package_name}.{module_name}"
                try:
                    module = importlib.import_module(full_name)
                except ImportError as e:
                    logger.warning(f"Could not import module {full_name}: {e}")
                    continue

                for _, obj in inspect.getmembers(module, inspect.isclass):
                    if (
                        issubclass(obj, Skill)
                        and obj is not Skill
                        and not inspect.isabstract(obj)
                    ):
                        try:
                            instance = obj()
                            self.register(instance)
                        except Exception as e:
                            logger.warning(f"Could not instantiate {obj.__name__}: {e}")
