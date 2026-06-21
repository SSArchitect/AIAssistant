from __future__ import annotations
import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent.aigc import MiniMaxAIGCClient
from agent.config import settings, runtime_config
from agent.memory import RoleMemoryStore
from agent.orchestrator.engine import AgentEngine
from agent.runtime.registry import list_agents
from agent.search import SearchResult, SearchService
from agent.schemas.agent import AgentListResponse
from agent.schemas.aigc import ImageGenerationRequest, ImageGenerationResponse
from agent.schemas.chat import ChatRequest, ChatResponse, SkillInfo, SkillListResponse
from agent.schemas.memory import (
    MemoryCreateRequest,
    MemoryKind,
    MemoryListResponse,
    MemoryRecord,
    RoleCreateRequest,
    RoleListResponse,
    RoleProfile,
    RoleUpdateRequest,
)
from agent.schemas.trace import RunListResponse, RunRecord
from agent.skills.registry import SkillRegistry
from agent.trace import TraceStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# Global instances
skill_registry = SkillRegistry()
trace_store = TraceStore()
engine: AgentEngine | None = None


class SearchRequest(BaseModel):
    query: str
    sources: list[str] | None = None
    limit: int = 5


class SearchResponse(BaseModel):
    query: str
    sources: list[str] = []
    provider_errors: list[str] = []
    results: list[SearchResult] = []


def _memory_storage_path() -> Path:
    configured = os.environ.get("AGENT_MEMORY_STORAGE_PATH")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parent.parent / "data" / "agent_memory.json"


@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine
    # Startup: discover and register skills
    skill_registry.auto_discover(
        "agent.skills.builtin",
        "agent.skills.custom",
    )
    engine = AgentEngine(
        skill_registry,
        trace_store=trace_store,
        role_memory=RoleMemoryStore(storage_path=_memory_storage_path()),
    )
    logger.info(
        f"Agent engine started with {len(skill_registry.list_skills())} skills"
    )
    yield
    # Shutdown
    logger.info("Agent engine shutting down")


app = FastAPI(title="Agent Engine", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/agent/health")
async def health():
    return {
        "status": "ok",
        "skills_count": len(skill_registry.list_skills()),
        "agents_count": len(list_agents()),
        "roles_count": len(engine.role_memory.list_roles()) if engine else 0,
    }


@app.get("/agent/agents", response_model=AgentListResponse)
async def agents():
    return AgentListResponse(agents=list_agents())


@app.get("/agent/roles", response_model=RoleListResponse)
async def roles():
    if engine is None:
        raise HTTPException(status_code=503, detail="Agent engine not ready")
    return RoleListResponse(roles=engine.role_memory.list_roles())


@app.post("/agent/roles", response_model=RoleProfile)
async def create_role(request: RoleCreateRequest):
    if engine is None:
        raise HTTPException(status_code=503, detail="Agent engine not ready")
    try:
        return engine.role_memory.create_role(request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.put("/agent/roles/{role_id}", response_model=RoleProfile)
async def update_role(role_id: str, request: RoleUpdateRequest):
    if engine is None:
        raise HTTPException(status_code=503, detail="Agent engine not ready")
    try:
        return engine.role_memory.update_role(role_id, request)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.delete("/agent/roles/{role_id}")
async def delete_role(role_id: str):
    if engine is None:
        raise HTTPException(status_code=503, detail="Agent engine not ready")
    try:
        engine.role_memory.delete_role(role_id)
    except ValueError as e:
        message = str(e)
        status = 400 if "cannot delete" in message else 404
        raise HTTPException(status_code=status, detail=message) from e
    return {"status": "ok"}


@app.get("/agent/roles/{role_id}/memories", response_model=MemoryListResponse)
async def list_role_memories(
    role_id: str,
    kind: Optional[MemoryKind] = None,
    agent_id: Optional[str] = None,
):
    if engine is None:
        raise HTTPException(status_code=503, detail="Agent engine not ready")
    if engine.role_memory.get_role(role_id) is None:
        raise HTTPException(status_code=404, detail="role not found")
    return MemoryListResponse(
        memories=engine.role_memory.list_memories(
            role_id=role_id,
            kind=kind,
            agent_id=agent_id,
        )
    )


@app.post("/agent/roles/{role_id}/memories", response_model=MemoryRecord)
async def create_role_memory(role_id: str, request: MemoryCreateRequest):
    if engine is None:
        raise HTTPException(status_code=503, detail="Agent engine not ready")
    if engine.role_memory.get_role(role_id) is None:
        raise HTTPException(status_code=404, detail="role not found")
    memory = engine.role_memory.add_memory(
        role_id=role_id,
        kind=request.kind,
        content=request.content,
        source=request.source,
        agent_id=request.agent_id,
        confidence=request.confidence,
        tags=request.tags,
        metadata=request.metadata,
    )
    return memory


@app.delete("/agent/roles/{role_id}/memories/{memory_id}")
async def delete_role_memory(role_id: str, memory_id: str):
    if engine is None:
        raise HTTPException(status_code=503, detail="Agent engine not ready")
    try:
        engine.role_memory.delete_memory(role_id=role_id, memory_id=memory_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"status": "ok"}


@app.get("/agent/skills", response_model=SkillListResponse)
async def list_skills():
    skills = []
    for s in skill_registry.list_skills():
        meta = s.metadata()
        skills.append(
            SkillInfo(
                name=meta.name,
                description=meta.description,
                parameters=[
                    {"name": p.name, "type": p.type, "description": p.description, "required": p.required}
                    for p in meta.parameters
                ],
                version=meta.version,
                tags=meta.tags,
                source=meta.source,
                enabled=meta.enabled,
            )
        )
    return SkillListResponse(skills=skills)


@app.post("/agent/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    if engine is None:
        raise HTTPException(status_code=503, detail="Agent engine not ready")
    return await engine.process(request)


@app.post("/agent/search", response_model=SearchResponse)
async def search(request: SearchRequest):
    query = (request.query or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="query is required")

    limit = max(1, min(int(request.limit or 5), 10))
    sources = [item.strip() for item in (request.sources or []) if item.strip()] or None
    service = SearchService.from_runtime_config()
    if not service.provider_names:
        raise HTTPException(status_code=503, detail="no search providers configured")

    try:
        results = await service.search(query, sources=sources, limit=limit)
    except Exception as e:
        logger.exception("Search failed")
        raise HTTPException(status_code=502, detail=f"search failed: {e}") from e

    return SearchResponse(
        query=query,
        sources=service.provider_names,
        provider_errors=service.last_provider_errors,
        results=results,
    )


@app.post("/agent/aigc/image", response_model=ImageGenerationResponse)
async def generate_image(request: ImageGenerationRequest):
    client = MiniMaxAIGCClient.from_runtime_config()
    try:
        raw = await client.generate_image(
            request.prompt,
            model=request.model,
            aspect_ratio=request.aspect_ratio,
            response_format=request.response_format,
            n=request.n,
            prompt_optimizer=request.prompt_optimizer,
            extra=request.minimax_extra(),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("Image generation failed")
        raise HTTPException(status_code=502, detail=f"image generation failed: {e}") from e

    return ImageGenerationResponse.from_minimax(
        raw,
        request,
        model=request.model or client.image_model,
    )


def _sse(event: str, payload: dict) -> str:
    data = json.dumps(payload, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {data}\n\n"


def _jsonable_model(model: BaseModel) -> dict:
    return json.loads(model.model_dump_json())


def _chunk_text(text: str, size: int = 24) -> list[str]:
    if not text:
        return []
    return [text[i : i + size] for i in range(0, len(text), size)]


@app.post("/agent/chat/stream")
async def chat_stream(request: ChatRequest):
    """Stream run events and the final response over Server-Sent Events.

    This endpoint currently streams trace events as they are produced and sends
    the final answer in small chunks after the self-runtime tool loop completes.
    Provider-level token streaming can be added later without changing the
    gateway/frontend SSE contract.
    """
    if engine is None:
        raise HTTPException(status_code=503, detail="Agent engine not ready")

    run_id = request.run_id or f"run_{uuid4().hex}"
    stream_request = request.model_copy(update={"stream": True, "run_id": run_id})

    async def generate():
        yielded_events = 0
        streamed_text = ""
        token_queue: asyncio.Queue[str] = asyncio.Queue()

        async def on_token(token: str) -> None:
            await token_queue.put(token)

        yield _sse("meta", {"run_id": run_id})

        task = asyncio.create_task(engine.process(stream_request, on_token=on_token))
        try:
            while not task.done():
                run = trace_store.get_run(run_id)
                if run is not None:
                    events = run.events[yielded_events:]
                    yielded_events += len(events)
                    for event in events:
                        yield _sse("trace", _jsonable_model(event))
                while not token_queue.empty():
                    token = token_queue.get_nowait()
                    streamed_text += token
                    yield _sse("token", {"text": token})
                await asyncio.sleep(0.08)

            response = await task
            run = trace_store.get_run(run_id)
            if run is not None:
                events = run.events[yielded_events:]
                yielded_events += len(events)
                for event in events:
                    yield _sse("trace", _jsonable_model(event))

            while not token_queue.empty():
                token = token_queue.get_nowait()
                streamed_text += token
                yield _sse("token", {"text": token})

            if not streamed_text:
                for chunk in _chunk_text(response.response):
                    yield _sse("token", {"text": chunk})
                    await asyncio.sleep(0.01)

            yield _sse("response", _jsonable_model(response))
            yield _sse("done", {"run_id": run_id})
        except Exception as e:
            logger.exception("Streaming chat failed")
            yield _sse(
                "error",
                {
                    "run_id": run_id,
                    "error": str(e),
                },
            )

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/agent/runs", response_model=RunListResponse)
async def list_runs(conversation_id: Optional[str] = None, limit: int = 50):
    bounded_limit = max(1, min(limit, 200))
    return RunListResponse(
        runs=trace_store.list_runs(
            conversation_id=conversation_id,
            limit=bounded_limit,
        )
    )


@app.get("/agent/runs/{run_id}", response_model=RunRecord)
async def get_run(run_id: str):
    run = trace_store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return run


# ==================== Config Management ====================

class ConfigUpdateRequest(BaseModel):
    settings: dict[str, str]


class ConfigResponse(BaseModel):
    settings: dict[str, str]


@app.get("/agent/config")
async def get_config():
    return {"settings": runtime_config.get_all()}


@app.post("/agent/config")
async def update_config(request: ConfigUpdateRequest):
    runtime_config.update(request.settings)
    # Clear cached providers so they recreate with new config
    if engine is not None:
        engine.clear_providers()
    return {"status": "ok"}


class TestProviderRequest(BaseModel):
    provider: str


class ValidateProviderRequest(BaseModel):
    provider: str


@app.post("/agent/test-provider")
async def test_provider(request: TestProviderRequest):
    """Test a provider by sending a simple message."""
    if engine is None:
        raise HTTPException(status_code=503, detail="Agent engine not ready")

    provider_name = request.provider
    try:
        from agent.llm.factory import create_provider
        from agent.llm.base import LLMMessage

        provider = create_provider(provider_name)
        messages = [
            LLMMessage(role="user", content="Say 'hello' in one word."),
        ]
        response = await provider.chat(messages)
        return {
            "success": True,
            "message": f"Provider '{provider_name}' is working. Response: {response.content[:100]}",
            "model": response.model,
        }
    except Exception as e:
        logger.exception(f"Provider test failed for {provider_name}")
        return {
            "success": False,
            "message": f"Provider '{provider_name}' test failed: {str(e)}",
            "model": "",
        }


@app.post("/agent/validate-provider")
async def validate_provider(request: ValidateProviderRequest):
    """Validate provider credentials without sending a chat completion."""
    provider_name = request.provider
    checked_at = datetime.now(timezone.utc).isoformat()

    try:
        if provider_name != "ollama" and not _provider_api_key(provider_name):
            return {
                "success": False,
                "status": "missing",
                "provider": provider_name,
                "message": f"{provider_name} API key is not configured",
                "model_count": 0,
                "validated_at": checked_at,
            }

        models = await _fetch_models(provider_name)
        return {
            "success": True,
            "status": "verified",
            "provider": provider_name,
            "message": f"Credentials verified. {len(models)} models are available.",
            "model_count": len(models),
            "validated_at": checked_at,
        }
    except Exception as e:
        logger.exception(f"Provider validation failed for {provider_name}")
        return {
            "success": False,
            "status": "error",
            "provider": provider_name,
            "message": str(e),
            "model_count": 0,
            "validated_at": checked_at,
        }


class ListModelsRequest(BaseModel):
    provider: str


@app.post("/agent/list-models")
async def list_models(request: ListModelsRequest):
    """List available models for a given provider by calling its API."""
    provider_name = request.provider
    try:
        models = await _fetch_models(provider_name)
        return {"success": True, "models": models}
    except Exception as e:
        logger.exception(f"Failed to list models for {provider_name}")
        return {"success": False, "models": [], "error": str(e)}


def _provider_api_key(provider_name: str) -> str:
    keys = {
        "claude": runtime_config.claude_api_key,
        "openai": runtime_config.openai_api_key,
        "gemini": runtime_config.gemini_api_key,
        "deepseek": runtime_config.deepseek_api_key,
        "doubao": runtime_config.doubao_api_key,
        "minimax": runtime_config.minimax_api_key,
    }
    return keys.get(provider_name, "")


async def _fetch_models(provider_name: str) -> list[dict]:
    """Fetch available models from a provider's API."""

    if provider_name == "claude":
        import anthropic
        api_key = runtime_config.claude_api_key
        if not api_key:
            raise ValueError("Claude API key not configured")
        client = anthropic.AsyncAnthropic(api_key=api_key)
        resp = await client.models.list(limit=100)
        models = []
        for m in resp.data:
            models.append({"id": m.id, "name": m.display_name or m.id})
        # Sort: newest first (by id alphabetically descending is a decent heuristic)
        models.sort(key=lambda x: x["id"], reverse=True)
        return models

    elif provider_name == "openai":
        import openai
        api_key = runtime_config.openai_api_key
        if not api_key:
            raise ValueError("OpenAI API key not configured")
        kwargs = {"api_key": api_key}
        base_url = runtime_config.openai_base_url
        if base_url:
            kwargs["base_url"] = base_url
        client = openai.AsyncOpenAI(**kwargs)
        resp = await client.models.list()
        models = []
        for m in resp.data:
            models.append({"id": m.id, "name": m.id})
        models.sort(key=lambda x: x["id"])
        return models

    elif provider_name == "gemini":
        from google import genai
        api_key = runtime_config.gemini_api_key
        if not api_key:
            raise ValueError("Gemini API key not configured")
        client = genai.Client(api_key=api_key)
        models = []
        async for m in await client.aio.models.list():
            model_id = m.name.replace("models/", "") if m.name else ""
            if model_id and "gemini" in model_id:
                models.append({
                    "id": model_id,
                    "name": m.display_name or model_id,
                })
        models.sort(key=lambda x: x["id"], reverse=True)
        return models

    elif provider_name == "deepseek":
        import openai
        api_key = runtime_config.deepseek_api_key
        if not api_key:
            raise ValueError("DeepSeek API key not configured")
        client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com/v1",
        )
        resp = await client.models.list()
        models = []
        for m in resp.data:
            models.append({"id": m.id, "name": m.id})
        models.sort(key=lambda x: x["id"])
        return models

    elif provider_name == "doubao":
        import openai
        api_key = runtime_config.doubao_api_key
        if not api_key:
            raise ValueError("Doubao API key not configured")
        client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url="https://ark.cn-beijing.volces.com/api/v3",
        )
        resp = await client.models.list()
        models = []
        for m in resp.data:
            models.append({"id": m.id, "name": m.id})
        models.sort(key=lambda x: x["id"])
        return models

    elif provider_name == "minimax":
        import openai
        api_key = runtime_config.minimax_api_key
        if not api_key:
            raise ValueError("MiniMax API key not configured")
        client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url=runtime_config.minimax_base_url,
        )
        resp = await client.models.list()
        models = []
        for m in resp.data:
            models.append({"id": m.id, "name": m.id})
        models.sort(key=lambda x: x["id"])
        return models

    elif provider_name == "ollama":
        import ollama as ollama_lib
        base_url = runtime_config.ollama_base_url or "http://localhost:11434"
        client = ollama_lib.AsyncClient(host=base_url)
        resp = await client.list()
        models = []
        for m in resp.models:
            name = m.model if hasattr(m, "model") else str(m.get("model", ""))
            models.append({"id": name, "name": name})
        models.sort(key=lambda x: x["id"])
        return models

    else:
        raise ValueError(f"Unknown provider: {provider_name}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "agent.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
