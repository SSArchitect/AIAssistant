from agent.skills.base import Skill, SkillMetadata, SkillParameter, SkillResult


class EchoSkill(Skill):
    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            name="echo",
            description="原样返回给定文本，主要用于测试技能系统。",
            parameters=[
                SkillParameter(
                    name="text",
                    type="string",
                    description="要原样返回的文本。",
                    required=True,
                ),
            ],
            tags=["utility", "test"],
            domains=["utility"],
            routing_keywords=["echo", "回显", "测试工具", "use a tool", "tool test"],
            idempotent=True,
        )

    async def execute(self, **kwargs) -> SkillResult:
        text = kwargs.get("text", "")
        return SkillResult(
            success=True,
            data={"echoed": text},
            display_text=f"Echo: {text}",
        )
