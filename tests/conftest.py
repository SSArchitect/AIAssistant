import pytest
from httpx import ASGITransport, AsyncClient

from agent.main import app, skill_registry, lifespan
from agent.orchestrator.engine import AgentEngine


@pytest.fixture(scope="session", autouse=True)
def setup_skills():
    """Initialize skill registry once for all tests."""
    skill_registry.auto_discover(
        "agent.skills.builtin",
        "agent.skills.custom",
    )


@pytest.fixture
def engine():
    """Create a fresh AgentEngine for testing."""
    return AgentEngine(skill_registry)


@pytest.fixture
async def client():
    """Create an async test client for the FastAPI app."""
    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
