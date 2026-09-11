# Spark 生图 Provider 与统一 AI 生图工具

2026-09-11：Spark 请求现使用 Provider 0.8 的公共模板 ID，工具参数保持兼容，详见 [模板接入](spark-template-provider.md)。

2026-09-10 扩展：新增 Spark 图生图附件选择和上传适配，详见 [图片输入接入](spark-image-inputs.md)。需要目标 Provider 开放 image_to_image 模式；此处代码更新不等于远端已部署。

共用 Spark 地址与密钥的文生视频工具见 [Spark 生视频工具](spark-video-provider.md)。

实现基于 Media Provider 接口协议 v1（2026-09-06，0.2.0）：固定 Z-Image Base、单张 PNG 文生图，默认 1024×1024。宽高单边 256–4096、16 的倍数，总像素 262144–4194304；支持 2048×2048、4096×1024、832×1216 等尺寸。后续协议参数扩展集中在 `agent/aigc/spark_client.py`，HTTP API、Agent workflow 和 tool 共用 `agent/aigc/image_service.py`。

## 配置

Python Agent 支持下列环境变量，也可放入项目根目录未纳入版本控制的 `.env`：

```dotenv
IMAGE_PROVIDER=spark
MEDIA_BASE_URL=https://your-provider.example.com
MEDIA_API_KEY=your-provider-api-key
```

`MEDIA_BASE_URL` 是 origin，不包含 `/v1`。公网联调使用 Provider 当前公布的 Tunnel 地址；服务端部署时配置固定域名。Key 只保存在后端环境或密钥配置中。

对应运行期设置为 `aigc.image_provider`、`aigc.spark.base_url`、`aigc.spark.api_key`。支持现有配置同步接口；本次未增加管理页面表单。YAML 可使用 `aigc.image_provider` 和 `aigc.spark.base_url` 层级配置，密钥使用环境变量。环境配置变更需重启 Agent，运行期配置更新立即生效。

未配置 `IMAGE_PROVIDER` 时仍默认 MiniMax，兼容已有行为。可以在单次生图 API/tool 请求中传 `provider: "spark"` 或 `provider: "minimax"` 覆盖默认值；MiniMax 原有配置继续有效。Spark 不复用 DGX LLM 或 MiniMax 的 Key。生图 Provider 与聊天模型的 `llm.default_provider` 相互独立：聊天可使用 Claude、DGX 等，生图按 `aigc.image_provider` 或请求内 `provider` 单独选择。`spark` 调用 `/v1/tasks`；`minimax` 调用 MiniMax `/v1/image_generation`，并保留既有 512–2048、8 对齐的尺寸规则。

## 工具与 API

对外仅保留 `image_generation_v1`（AI 生图）一个工具，负责直接生图、研究、上下文整理和提示词修饰。原 `generate_image` 封装作为内部适配器保留，不自动注册、不出现在工具列表或模型工具目录中；最终图片调用与 HTTP API 共用 Provider 服务层。统一入口沿用原有工具权限，禁用 AI 生图时没有另一个直接生图工具可绕过。

AI 生图是 Super Chat 的常驻工具，每轮都会提供 schema，不再依赖关键词匹配才让模型看到。模型按语义判断是否调用；系统提示要求使用真实工具输出，不能编造图片 URL 或用占位图冒充结果。对“帮我生成一只小猫”“给我画一幅小猫图片”这样的明确指令，如果模型未调用任何工具便结束，执行层会补充一次受权限治理的生图调用。闲聊、否定指令、提示词编写和显式 ASCII/字符画请求不触发该执行兜底。工具被禁用时不会绕过禁用配置。 最终回复从本轮成功的生图工具结果保留图片原始 URL：修复模型改写的 `attachment://` 地址，补回模型遗漏的图片，避免生成成功却无法展示。

`image_generation_v1` 工具参数示例：

```json
{
  "task": "生成清晨阳光下的橙色机器人，三维插画，无文字",
  "reason": "用户明确要求生成图片",
  "provider": "spark",
  "negative_prompt": "模糊，畸形",
  "width": 2048,
  "height": 2048,
  "seed": 42
}
```

工具可用参数：`task`、`reason`、可选的 `context`、`provider`、`negative_prompt`、`width`、`height`、`aspect_ratio`、`seed`、`idempotency_key`。尺寸同时提供或同时省略，显式宽高优先于 `aspect_ratio`；不提供宽高时，按比例选取符合协议的预设尺寸。Spark 提示词最多 4000 字符，seed 为 0–4294967295 整数，省略则随机。Spark 的宽高必须 16 对齐，1920×1080 会报错，1920×1088 合法；4096×4096 因总像素超限报错，不会自动缩小。模型选择、批量出图仍不支持。图生图通过 mode=image_to_image、image_asset_id / image_data_url 或工具的 image_attachment_index 接入，不复用 MiniMax 的 subject_reference 格式。Provider 不执行 MiniMax 的 `prompt_optimizer`；需要修饰时使用上层 AI 生图工作流。

原有 `POST /api/aigc/image`（Gateway）和 `POST /agent/aigc/image`（内部 Agent）均支持新增的 `provider`、`negative_prompt`、`idempotency_key` 字段。API 保留 `response_format: "url" | "base64"`，tool 返回可展示 URL。

工具返回包含实际图片 Markdown 的工作流结果；HTTP 生图 API 仍以 `prompt` 接收提示词，成功响应沿用 `ImageGenerationResponse`，例如：

```json
{
  "id": "provider-task-id",
  "provider": "spark",
  "model": "z-image-base",
  "prompt": "清晨阳光下的橙色机器人，三维插画，无文字",
  "aspect_ratio": "1:1",
  "response_format": "url",
  "images": [{"index": 0, "url": "/static/generated/aigc/spark-uuid.png", "mime_type": "image/png"}],
  "metadata": {"seed": 42, "idempotency_key": "original-key", "width": 2048, "height": 2048}
}
```

Provider 下载地址需要鉴权，所以 Agent 先下载到 `web/static/generated/aigc/`，再返回 Gateway 的静态图片 URL。生成目录不纳入 Git；Agent 和 Gateway 需要共享该目录（当前部署使用同一项目路径），并在部署时保留结果文件。生成文件目前没有自动清理策略。

## 提示词修饰规则（2026-09-10）

统一 `image_generation_v1` 的提示词审查已适配 [OpenAI 图像提示指南](https://developers.openai.com/api/docs/guides/image-prompting) 的通用规则，适用于 Spark 和 MiniMax：

- 普通审查保留用途、主体数量、相对位置、比例、留白与禁用内容；只整理已明确的意图，不擅自添加道具或改变视觉风格。
- 专业修饰进一步明确光线、材质、视线和接触关系，避免堆砌镜头参数或给动物设计拟人抓握动作。
- 简短文案保留原文、位置与出现次数；密集中文、表格和小字号标签仍优先使用原有文字保护策略。

规则保存在 `agent/aigc/prompt_policy.py`，由生图审查注入。图片 Provider、模型、尺寸、seed、负向提示词和幂等行为不变，不引入 GPT Image 专有参数。首轮 Spark 对比显示部分构图改善，但不能保证容量、接触位置等细节准确；单元测试验证规则注入和既有行为兼容，不替代实际图片质量评测。

## 重试和错误

- 创建请求生成一次幂等键，所有网络/429/502/503/504 重试都复用原键及原始请求，最多 3 次。401/409/422 不自动重试。
- 接到任务后每 2 秒查询；`submitting`、`queued`、`running`、`recovering` 都继续等待。`failed` 为终态，不新建任务。
- 总等待期限为 240 秒，涵盖提交、重试、轮询和下载；超时只结束客户端等待，不取消服务端任务。
- 超时或 Provider 错误返回 `code`、`task_id`（如已知）、`idempotency_key`。tool 将其放在结果 `data`，内部 HTTP API 返回 502 的 `detail`，AI 生图 workflow 写入失败 trace 的 `provider_context`。
- 重试必须带返回的幂等键和原始输入；随机 seed 省略的请求继续省略，不把响应 seed 写回请求。业务明确要求重新生成时才换新键。跨进程重试的 API 调用方应在调用前持久保存自己的幂等键；统一 tool 在委派阶段生成键并随调用参数和 trace 保留；直接进入 AI 生图 workflow 时使用 run ID。
- 下载只接受当前 origin、当前任务的 artifact 路径，不跟随重定向。流式读取最多 32 MiB，检查 PNG 标识、尺寸和文件结束标记，完成后原子写入结果路径；中断可从头重试，失败不留下半张图片。

## 验证

局部测试：

```bash
python3 -m pytest tests/test_spark_image.py tests/test_minimax_provider.py tests/test_api.py tests/test_orchestrator.py tests/test_tool_router.py tests/test_tool_governance.py -q
(cd gateway && go test ./internal/bridge -run 'TestAgentClientGenerate' -count=1)
```

测试通过 MockTransport 验证真实 HTTP 请求构造与状态流转，不依赖公网 Key；包含成功路径、幂等重试、recovering、超时、鉴权/参数错误、下载校验、工具注册和 API/workflow/Go 代理兼容。
