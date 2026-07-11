# Agent Assistant 开发与运行规范

最后更新：2026-06-18

这份文档记录当前代码落地后的服务启动方式、开发流程、测试要求和已知限制。架构方向见 [agent-workbench-architecture.md](./agent-workbench-architecture.md)。

生产服务器部署、Git bundle 兜底、systemd/Nginx 检查和线上配置同步流程见 [server-deployment-runbook.md](./server-deployment-runbook.md)。

## 1. 当前服务边界

项目保持 Go Gateway + Python Agent Service 分离：

```text
Web UI / Browser
  -> Go Gateway :8080
      -> 会话、消息、配置、静态资源、API 聚合
      -> Python Agent Service :9090
          -> Agent registry、LLM provider、skills、memory、trace
```

职责约定：

- Go Gateway 是前端和外部调用的统一入口。Web UI 应优先访问 `/api/*`，不要直接依赖 Python 服务地址。
- Python Agent Service 负责 AI runtime 相关能力，包括 agent 执行、模型调用、工具调用、memory 和 trace。
- 新增 agent 时，不要先抽象一个覆盖所有框架的厚 `AgentSpec/ToolSpec/MemorySpec`。平台只稳定薄协议：agent manifest、chat request/response、run、run event。
- Memory 是平台长期资产，优先自研和可迁移；工具可以按 agent/runtime 独立适配，但工具调用必须进入 trace。

## 2. 端口与入口

默认端口：

```text
Go Gateway / Web UI: http://localhost:8080
Python Agent:        http://localhost:9090
```

常用健康检查：

```bash
curl -sS http://localhost:9090/agent/health
curl -sS http://localhost:8080/api/health
curl -sS http://localhost:8080/api/agents
curl -sS http://localhost:8080/api/runs
```

核心目录：

```text
agent/      Python Agent Service
gateway/    Go Gateway
web/        Static Web UI
config/     config.yaml
data/       SQLite data
logs/       service logs
.pids/      background service pid files
docs/       architecture and development docs
```

## 3. 安装与配置

Python 依赖：

```bash
pip3 install -r agent/requirements.txt
```

Go 依赖由 Go module 管理：

```bash
cd gateway
go mod download
```

主要配置文件：

```text
config/config.yaml
```

运行期模型配置也可以通过 Web UI 的 Settings 写入后同步到 Python Agent Service。Gateway 启动时会尝试把已有配置同步到 Python 服务；同步失败不应阻断 Gateway 启动，但需要查看 `logs/gateway.log`。

## 4. 服务启动方式

### 4.1 后台启动

适合日常本地使用：

```bash
./scripts/start.sh start
```

等价 Makefile 命令：

```bash
make start
```

脚本行为：

- 创建 `.pids/`、`logs/`、`data/`。
- 启动 Python Agent Service，等待 `/agent/health`。
- 编译并启动 Go Gateway。
- Web UI 地址为 `http://localhost:8080`。
- 日志写入 `logs/agent.log` 和 `logs/gateway.log`。

停止、重启、状态和日志：

```bash
./scripts/start.sh stop
./scripts/start.sh restart
./scripts/start.sh status
./scripts/start.sh logs

make stop
make restart
make status
make logs
```

### 4.2 前台开发模式

适合边改边看日志：

```bash
./scripts/dev.sh
```

等价 Makefile 命令：

```bash
make dev
```

该模式会：

- 前台启动 Python Agent Service，开启 uvicorn reload。
- 等待 agent health。
- 前台启动 Go Gateway。
- `Ctrl+C` 后清理两个进程。

### 4.3 单服务开发

只启动 Python Agent：

```bash
make dev-agent
```

只启动 Go Gateway：

```bash
make dev-gateway
```

单独启动 Gateway 时必须保证 Python Agent 已在 `:9090` 可访问；否则 `/api/chat`、`/api/agents`、`/api/runs` 等代理接口会失败。

## 5. 当前 API 契约

### 5.1 Gateway API

前端和外部调用优先使用这些接口：

```text
POST /api/chat
GET  /api/agents
GET  /api/runs
GET  /api/runs/:id
GET  /api/conversations
POST /api/conversations
GET  /api/conversations/:id
GET  /api/admin/settings
PUT  /api/admin/settings
```

`POST /api/chat` 会透传 Python Agent 返回的 debug 字段：

```json
{
  "conversation_id": "conv-id",
  "response": "...",
  "skills_used": [],
  "model_used": "model-name",
  "tokens_used": {},
  "agent_id": "general_assistant",
  "runtime": "self",
  "run_id": "run_xxx",
  "events": []
}
```

### 5.2 Python Agent API

Python 服务提供内部 agent 能力：

```text
GET  /agent/health
GET  /agent/skills
GET  /agent/agents
GET  /agent/roles
POST /agent/roles
PUT  /agent/roles/{role_id}
DELETE /agent/roles/{role_id}
GET  /agent/roles/{role_id}/memories
POST /agent/roles/{role_id}/memories
POST /agent/chat
GET  /agent/runs
GET  /agent/runs/{run_id}
GET  /agent/config
POST /agent/config
POST /agent/test-provider
POST /agent/list-models
```

Web UI 不应直接依赖 Python API，除非是在调试 Python 服务本身。

## 6. Agent 与 Trace 规范

### 6.1 Agent manifest

Agent 列表由 `agent/runtime/registry.py` 提供。当前有：

```text
general_assistant   self runtime，可用
langgraph_research  LangGraph 实验槽位，依赖未安装时 enabled=false
```

新增 agent 时至少要补：

- `id`：稳定唯一标识。
- `name`、`description`：用于 UI 展示。
- `runtime`、`framework`：用于调试和后续筛选。
- `enabled`：依赖缺失或功能未接好时必须为 `false`。
- `capabilities`：例如 `chat`、`tool_use`、`tracing`、`state_graph`。
- `metadata.default_role_id`：可选，控制该 Agent 默认注入哪个角色记忆域。
- 对应测试，确认 `/agent/agents` 和 Gateway `/api/agents` 能看到它。

### 6.2 Role 与 Memory

Memory 是平台长期资产，当前分三层：

- 会话记忆：`ConversationMemory` 保存单个 `conversation_id` 的短期上下文窗口，并支持 AI 压缩摘要。历史过长时，压缩器判断是否需要压缩，生成短期摘要并保留少量关键原文消息。
- 长期记忆：`RoleMemoryStore` 按 `role_id + user_id` 隔离 `long_term`，用于保存跨会话稳定的用户事实、偏好、持续项目和长期目标。
- 角色记忆：角色预设由 `RoleProfile` 的 `base_persona` / `instructions` 提供；用户显式调整助手角色、语气或工作方式时，可写入 `role` 记忆。旧的 `persona` kind 仍兼容读取，并按角色记忆渲染。
- 记忆更新：FastAPI 运行时默认启用 AI memory reviewer，在每轮回复后判断是否需要写入长期/角色记忆；如果 reviewer 失败，本轮跳过长期记忆写入，避免异常兜底产生低质量记忆。测试和裸 `AgentEngine` 默认仍可使用启发式 hook，避免额外模型调用。

账号隔离规则：

- Gateway 登录态中的 `X-Account-Session` / `account_session` 是权威用户来源；存在有效 session 时，请求 body/query/header 中的 `user_id` 不能覆盖账号 ID。
- Python Agent 的会话记忆 key 固定为 `user:{user_id}:conversation:{conversation_id}`，因此不同账号即使使用相同 `conversation_id` 也不会共享短期摘要或原始历史。
- `RoleMemoryStore` 的长期记忆和用户更新的角色记忆都按 `user_id` 过滤；角色预设本身仍是全局模板，用户个性化改动应写入 user-scoped `role` memory，而不是直接改全局预设。

Python Agent Service 默认把角色记忆持久化到 `data/agent_memory.json`。开发或测试时可以通过 `AGENT_MEMORY_STORAGE_PATH=/tmp/agent_memory.json` 指定其他路径。

`/agent/chat` 支持：

```json
{
  "conversation_id": "conv-id",
  "message": "请记住：我喜欢简洁回答",
  "agent_id": "general_assistant",
  "role_id": "default",
  "memory_enabled": true
}
```

Prompt 拼接顺序固定为：系统级配置（当前 Agent、工具调用说明、时间上下文） -> 记忆系统（角色记忆、长期记忆、短期摘要） -> 本轮模式指令和上下文块。响应会返回 `role_id` 和本轮注入的 `memory_context`；长期/角色记忆检测与会话压缩在答复完成后后台执行，新增记忆通过 trace 事件和 `RoleMemoryStore` 查询确认。普通业务 UI 不应把隐藏记忆直接展示为 assistant 回复内容。

### 6.3 Tool Sources

当前工具路径：

- Python 启动时从 `agent.skills.builtin` 和 `agent.skills.custom` 自动发现 `Skill`。
- `AgentEngine` 在每轮 self runtime chat 中调用 `skill_registry.get_tool_definitions()`，并把结果传给 provider 的 tool/function calling 参数。
- 因此 `super_chat`、`general_assistant`、`knowledge_qa_self_v1` 这类 `runtime="self"` 且启用的 Agent 都能看到 enabled skills。
- `runtime="langgraph"` 的实验 Agent 当前还没有接入 chat，因此也还没有接入这套 tool registry。

Tool UI 当前展示 `/api/tools` 返回的 skill 元数据，包括 `source` 和 `enabled`。后续 MCP / HTTP / plugin 工具应注册成同一层 ToolDefinition，并在执行时写入 trace。

Search 已作为一个内置 skill 接入：

- `search.local.documents`：JSON 数组，本地关键词检索源。
- `search.http.base_url`：后台统一 search 服务地址，默认以 `q` 和 `limit` 查询参数请求。
- `search.http.api_key`：可选 Bearer token。
- `search.http.query_param`：可选查询参数名，默认 `q`。
- `search.minimax.enabled`：启用 MiniMax Token Plan MCP 网络搜索，默认 `true`。需要可用的 `llm.minimax.api_key` 或 `search.minimax.api_key`。
- `search.minimax.command`：MCP 启动命令，默认 `uvx`。
- `search.minimax.args`：MCP 启动参数 JSON，默认 `["minimax-coding-plan-mcp","-y"]`。
- `search.minimax.api_host`：MiniMax API Host，默认 `https://api.minimaxi.com`。
- `search.minimax.timeout`：单次 MCP 请求超时时间，默认 `60` 秒。
- `search.min_provider_coverage`：通用 web 检索至少等待多少个 provider 完成后才允许提前收敛，默认 `2`；设为 `1` 可恢复更偏速度的首个相关结果策略。
- `search.provider_limit_multiplier`：每个 provider 的候选召回倍数，默认 `2`，最终仍按调用方 `limit` 截断。
- `search.recall.max_queries`：单个 provider 最多使用多少个 query variant 做召回，默认 `2`；HTTP/本地/MiniMax 源默认只请求一次，DuckDuckGo/Bing fallback 会使用原 query 加一个降噪关键词 query。
- `search.rewrite.enabled`：启用 LLM query rewrite，默认 `true`；失败会退回词法 rewrite。
- `search.rewrite.provider`：rewrite 使用的 LLM provider，默认使用 `llm.default_provider`。
- `search.rewrite.max_queries`：LLM rewrite 最多生成多少条候选 query，默认 `4`；实际召回仍受 `search.recall.max_queries` 和 provider 的 `recall_query_limit` 限制。
- `search.rewrite.timeout_seconds`：LLM rewrite 超时时间，默认 `12` 秒。
- `search.rerank.enabled`：启用 LLM rerank，默认 `true`；失败会退回 BM25 ranking。
- `search.rerank.provider`：rerank 使用的 LLM provider，默认使用 `llm.default_provider`。
- `search.rerank.max_candidates`：送入 LLM rerank 的最大候选数，默认 `10`。
- `search.rerank.timeout_seconds`：LLM rerank 超时时间，默认 `20` 秒。
- `search.rerank.min_score`：LLM rerank 保留候选的最低分，默认 `0.5`。
- `search.web.enabled`：是否启用 DuckDuckGo HTML fallback，默认 `true`。

SearchService 会先生成词法 query variants；启用 LLM rewrite 时，会在保留词法兜底的基础上使用模型通用知识生成同义词、别名、缩写/全称、跨语言和型号拆分等多 query 扩召。LLM rewrite 会尽量同时覆盖中文和英文 query，并在 query 数有限时优先保留互补语种，避免中文搜索引擎只拿英文 query 召回。之后汇总多个 provider 的候选，通过 `agent.search.ranking` 做 BM25 相关性排序、低相关过滤和来源多样性重排，再由 LLM rerank 按原始 query 的实体、限定词、任务意图和文档形态做最终筛选；结果仍按调用方 `limit` 截断。

`search` Skill 可通过 `open_results=true` 打开前几条搜索结果并把网页正文写入 `metadata.page`；已知 URL 也可直接调用 `open_url` Skill 读取公开 HTTP/HTTPS 页面正文。

Search 质量评测使用 `evals/search/cases.json`。默认离线评测使用固定 fixture，适合在每次改 query rewrite、召回、ranking 或 rerank 阈值后做回归检查：

```bash
make eval-search
python3 scripts/eval_search.py --mode offline --json
python3 scripts/eval_search.py --mode offline --compare-original
```

也可以从本地 SQLite 和服务器 conversation trace 里收集更大规模的 trace-derived 评测数据：

```bash
make collect-search-evals
make eval-search-trace
python3 scripts/eval_search.py --cases evals/search/trace_cases.json --mode offline --compare-original
```

`evals/search/trace_cases.json` 的期望/反例来自历史 `search.llm_rerank` 分数，适合作为量级回归和分布观察；`evals/search/query_bank.json` 收集未标注 query 分布，方便后续人工挑坏例补进精选集。严格语义金标仍优先维护 `evals/search/cases.json`。

需要观察真实 provider 表现时运行 live 评测：

```bash
make eval-search-live
python3 scripts/eval_search.py --mode live --endpoint http://127.0.0.1:9090/agent/search --output /tmp/search-eval.json
```

评测输出包含 `recall@k`、`precision@k`、`MRR`、`bad@k`、耗时和 trace 节点。线上 trace 发现新的坏例后，优先把 query、期望结果、污染结果和 fixture 补进 `evals/search/cases.json`，再调参数或 prompt。

Conversation Eval 是更通用的用例准备 workflow：从真实 conversation/message/trace 里挖掘候选场景、意图、任务链、边界情况和失败模式，再审核进可回归的 `evals/conversation/cases.json`。

```bash
make collect-conversation-evals
make eval-conversation
python3 scripts/eval_conversation.py --mode agent --endpoint http://127.0.0.1:9090/agent/chat
```

Conversation Eval 有两种运行模式：

- historical：只检查 case 内保存的 `historical_response`，不会调用模型或工具，适合快速验证规则和已批准用例。
- agent：用隔离身份 `__eval__` 直接调用 Python Agent `/agent/chat` 重放，不经过 Gateway conversation 写入，不污染真实用户帐号；但它会实际消耗模型/工具调用额度。

每个 case 分三层：

- `taxonomy`：场景、意图、任务链、边界情况、失败模式和 tags，只用于归类与切片。
- `expected.include`：用例应包含的可编辑要求，拆为 `tool_calls`、`answer_result`、`citations` 三类；工具与答案结果会同步到确定性评分字段。
- `rubric`：维度评分规则，默认包含 `tool_use`、`accuracy`、`completeness`、`constraints`；每个维度记录标准、标准要求和 1-5 通过分，不再使用人工权重；运行后生成 `scorecard`，报告按维度和 tag slice 聚合。

相关文件：

- `evals/conversation/candidates.json`：自动挖掘的候选用例，默认不是金标。
- `evals/conversation/cases.json`：人工批准后的回归用例集。
- `evals/conversation/latest_report.json`：最近一次 eval 报告。
- `evals/conversation/run_history.json`：最近多次回归的轻量历史记录。
- `evals/conversation/runs/<run_id>.json`：每次回归的完整报告快照。

Web 工作台里可以在 Developer -> Eval 中一键采集候选、编辑候选、批准用例、运行 Historical Check 和 Isolated Replay，并查看总分、历史记录、每个用例的分数和运行详情。候选挖掘默认会尝试用当前 LLM 补全场景、意图、期望项和 1-5 分维度标准；如果 LLM 不可用，会保留确定性规则兜底，候选 metadata 会记录 enrichment 状态。

`mcp.servers` 目前只是通用配置入口，尚未实现通用 MCP server 启动、tool discovery、权限审批和动态注册。MiniMax Token Plan MCP 已作为 search provider 的专项集成接入。

### 6.4 Trace 事件

每次 chat 必须创建 run，并返回 `run_id` 与 `events`。基础事件约定：

```text
run.started
memory.loaded
memory.review.started
memory.review.completed
memory.review.failed
memory.compaction.started
memory.compaction.completed
memory.compaction.skipped
memory.compaction.failed
model.started
model.completed
model.failed
tool.started
tool.completed
tool.failed
memory.extracted
run.completed
run.failed
```

事件字段：

```json
{
  "id": "evt_xxx",
  "run_id": "run_xxx",
  "type": "model.completed",
  "status": "completed",
  "title": "Model call 1 completed",
  "step_id": null,
  "payload": {},
  "duration_ms": 123,
  "created_at": "..."
}
```

规范：

- 正常完成必须有 `run.started` 和 `run.completed`。
- 失败必须有 `run.started` 和 `run.failed`，并写入 `error_type`、`error_message`。
- 模型调用、工具调用、检索、handoff、人工确认等步骤都应写事件。
- `payload` 可以保留调试信息，但不要写入明文密钥。
- 前端 trace panel 默认折叠，避免影响正常聊天阅读。

## 7. 测试要求

一键测试：

```bash
./scripts/test.sh
```

等价：

```bash
make test
```

当前测试脚本覆盖：

```text
go vet ./...
go test ./...
go build -o /dev/null ./cmd/server/
python3 -m pytest tests/ -v --tb=short
node --check web/static/js/app.js  # 如果本机安装了 node
config/config.yaml YAML 校验
Python 核心 import 校验
builtin skill discovery 校验
```

局部测试：

```bash
python3 -m pytest
python3 -m pytest tests/test_api.py tests/test_trace.py

cd gateway
go test ./...
```

新增能力时的测试规范：

- 改 `/agent/chat` 响应字段时，必须更新 `tests/test_api.py` 的 chat contract 测试。
- 改 trace 存储或事件结构时，必须更新 `tests/test_trace.py`。
- 改 Go bridge 的 Python API 代理时，必须更新 `gateway/internal/bridge/agent_client_test.go`。
- 改 Web JS 时，至少跑 `node --check web/static/js/app.js`。
- 最终提交前跑 `./scripts/test.sh`。

当前基线结果：

```text
Python: 69 passed
Go: go vet / go test / go build passed
Web: app.js syntax passed when node is available
```

## 8. 开发限制与注意事项

当前已知限制：

- TraceStore 还是内存实现，服务重启后 run history 会丢失。后续需要落 SQLite/Postgres。
- `/agent/chat` 当前是非 streaming；`stream` 字段保留但还没有端到端 SSE。
- `langgraph_research` 只是实验槽位；未安装 `langgraph` 时会显示 `enabled=false`。
- Tool adapter 还没有统一权限层；高风险工具后续必须接 approval/permission。
- Knowledge/RAG 还未落库和向量化；相关 agent 不能假装具备引用能力。
- Gateway 当前主要面向本地个人工作台，没有认证、租户隔离、限流和生产审计。
- `data/assistant.db` 是本地 SQLite，生产化前需要迁移策略。
- `logs/`、`.pids/`、`data/` 是运行产物，不应作为业务代码提交。
- macOS 系统 Python 3.9 会出现 EOL 和 LibreSSL 相关 warning，当前不影响测试，但建议后续切项目虚拟环境。
- 在受限沙盒或某些 Codex 工具环境里，后台服务可能无法稳定绑定端口或保持常驻；这属于运行环境限制。真实本机开发建议用终端直接执行 `./scripts/dev.sh` 或 `./scripts/start.sh start`。

## 9. 推荐开发流程

日常开发：

```text
1. 修改代码
2. 跑局部测试
3. 跑 ./scripts/test.sh
4. 用 ./scripts/dev.sh 前台验证关键流程
5. 确认 trace panel 能看到 run/model/tool 事件
```

新增 LangGraph agent 建议流程：

```text
1. 安装并锁定 langgraph 依赖
2. 在 agent/runtime/registry.py 增加或启用 manifest
3. 独立实现 LangGraph agent runner，不强行改造 general_assistant
4. 将 graph node 开始/结束/失败映射成 RunEvent
5. 补 Python API contract 测试和 Go bridge 测试
6. 在 Web UI 中允许选择该 agent
7. 跑 ./scripts/test.sh
```

不要做的事：

- 不要为了接一个新框架，把所有 agent 都改成同一个厚 `AgentSpec`。
- 不要让前端直接依赖 Python 内部 API。
- 不要在 trace payload 中记录密钥、完整凭证或不可控的大对象。
- 不要跳过 Gateway bridge 测试；Go/Python 边界最容易因为 JSON 字段变化出问题。
