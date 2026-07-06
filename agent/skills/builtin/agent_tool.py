from __future__ import annotations

from agent.runtime.registry import get_agent
from agent.schemas.agent import AgentInfo
from agent.skills.base import Skill, SkillMetadata, SkillParameter, SkillResult


class AgentToolSkill(Skill):
    """Tool wrapper around a specialized agent workflow."""

    auto_discover = False

    def __init__(self, agent: AgentInfo):
        self.agent = agent

    def _routing_guidance(self) -> str:
        if self.agent.id == "weight_loss_v1":
            return (
                "Use this agent only for explicit calorie estimation, meal/exercise logging, weight-loss goals, "
                "nutrition stats, or calorie deficit questions; do not call it merely because the user mentions "
                "meals, takeout, breakfast, lunch, or dinner in a life recap."
            )
        if self.agent.id == "image_generation_v1":
            return "Use this agent for image generation, prompt refinement, visual design, posters, covers, and visual deliverables."
        return "Use this only when the current user request clearly requires this specialized agent."

    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            name=self.agent.id,
            description=(
                f"Run the {self.agent.name} agent as a specialized tool workflow. "
                f"{self.agent.description} "
                f"{self._routing_guidance()} "
                "Arguments should preserve the user's concrete task and any context the target agent needs. "
                "The tool returns JSON that the main agent should use before composing the final answer."
            ),
            parameters=[
                SkillParameter(
                    name="task",
                    type="string",
                    description="The full user-facing task for this agent, preserving concrete details.",
                    required=True,
                ),
                SkillParameter(
                    name="reason",
                    type="string",
                    description="Brief reason why this agent tool is required.",
                    required=True,
                ),
                SkillParameter(
                    name="context",
                    type="string",
                    description="Relevant context this agent needs, including the original request when useful.",
                    required=False,
                ),
            ],
            tags=["agent", "workflow", self.agent.id],
            source="system",
        )

    async def execute(self, **kwargs) -> SkillResult:
        return SkillResult(
            success=False,
            error=f"{self.agent.id} is an agent workflow tool and must be handled by the agent engine.",
            data={"agent_workflow": True, "agent_id": self.agent.id, "arguments": kwargs},
            display_text=f"{self.agent.id} must be handled by the agent engine.",
        )


def _required_agent(agent_id: str) -> AgentInfo:
    agent = get_agent(agent_id)
    if agent is None:
        raise ValueError(f"Unknown agent: {agent_id}")
    return agent


class ImageGenerationAgentTool(AgentToolSkill):
    auto_discover = True

    def __init__(self):
        super().__init__(_required_agent("image_generation_v1"))


class WeightLossAgentTool(AgentToolSkill):
    auto_discover = True

    def __init__(self):
        super().__init__(_required_agent("weight_loss_v1"))
