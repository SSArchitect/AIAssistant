# Spark 生视频工具

按 Provider 0.5.0 的 `VIDEO_API_PROTOCOL.md`（2026-09-06）接入文生视频。Super Chat 自动发现并常驻提供 `generate_video` 工具，复用现有工具权限、调用次数限制和 Trace。

## 配置与使用

视频复用生图的 `aigc.spark.base_url`、`aigc.spark.api_key`，对应环境变量 `MEDIA_BASE_URL`、`MEDIA_API_KEY`；地址为 origin，不带 `/v1`。无需新增配置，视频始终调用 Spark，不受 `IMAGE_PROVIDER` 或聊天模型选择影响。Provider 必须开放视频接单；未开放时工具返回 `unsupported_task_type`。

重启 Agent 或使用自动 reload 的开发模式后，可在 Super Chat 输入“生成一个纸鹤在雨天窗边随风飘动的视频，镜头缓慢推进，有自然雨声”。工具参数示例：

```json
{
  "prompt": "雨天窗边的木桌上，红色纸鹤随微风轻轻摆动，镜头缓慢推进，自然雨声，无对白，无文字。",
  "width": 480,
  "height": 864,
  "duration_seconds": 5,
  "fps": 29.97,
  "seed": "18446744073709551615"
}
```

- `prompt` 必填，1–4000 字符，拒绝全空白，原文透传。
- `width` / `height` 各 32–4096，必须为 32 的倍数，总面积不超过 1,032,192；默认 864×480。支持竖屏、方形及其他符合约束的尺寸。
- `num_frames` 为原生 24 FPS 时间轴上的帧数，接受整数 5–3592，向上对齐到 `17k+5`；例如 120 → 124。
- `duration_seconds` 接受大于 0、最多 3592/24 秒的有限 JSON 数字，先 `ceil(时长 × 24)` 再对齐。与 `num_frames` 二选一；都省略时使用 124 帧，仅传 null 或同时传两个有效值报错。
- 宽 × 高 × 对齐后的原生帧数不得超过 373,653,504。1344×768 最多 362 帧，864×480 最多 889 帧，320×320 可到 3592 帧。建议先用 124–362 帧，长片段属于实验范围。
- `fps` 接受 1–120、最多三位小数的有限 JSON 数字，默认 24。通过重复/丢弃画面帧保持运动速度和音频时间轴，不增加运动细节，不是光流插帧。
- `seed` 为 0–18446744073709551615 的整数或十进制字符串；省略、null 或整数 -1 时随机。工具将显式种子规范化为十进制字符串，保留完整 64 位精度。不要在 JavaScript 中将大 seed 先转 Number。
- `idempotency_key` 可选，用于重放原请求。工具在参数准备阶段生成一次，并纳入调用参数和 Trace。
- 不支持图生视频、参考视频、负向提示词、模型选择或音频开关。宽高/帧数仅接受整数，FPS/时长接受数字；除 seed 外不接受数字字符串，数值字段均拒绝布尔值，未知字段报错。

每次成功返回一个带音频的 MP4。Agent 将文件保存到 `web/static/generated/aigc/spark-video-*.mp4`，最终回答提供 `/static/generated/aigc/…` 链接，可打开播放或下载；即使模型漏写结果链接，执行层也会从成功的工具结果补回。

聊天界面按视频 URL 识别媒体，不要求链接标题必须是“视频”；已有聊天中的 `[纸鹤视频（…）](…mp4)` 也会显示播放器、下载视频按钮和打开视频链接。播放器支持内联播放，加载后显示从实际 MP4 读取的宽高与时长。Android 播放与下载使用配置的 API origin，下载复用原生文件保存能力；浏览器下载使用 Blob 文件保存。视频下载直接读取产物，不经过仅支持图片的下载代理，失败会显示重试提示。

成功结果透传 Provider 的 `seed_text` 和 `video`，包括请求帧数/时长、实际原生帧数、原生时长、输出帧率、输出帧数和时长。`metadata` 也使用 Provider 的执行参数，并保留幂等键和 seed。旧任务缺少新字段时，`video` / `seed_text` 可为 null，兼容原有下载；此时 `metadata` 的尺寸、帧率和原生帧数仅作请求估算。完整 64 位 seed 请读取字符串字段 `seed_text`。

输出帧数为 `ceil(实际原生帧数 × fps / 24)`，时长为输出帧数 / fps。示例的 5 秒、29.97 FPS 实际为 124 原生帧、155 输出帧、约 5.17184 秒。这些是 Provider 持久化的执行参数，不是 Agent 对 MP4 的媒体探测结果；编码容器还可能有毫秒级舍入。

工具列表可以禁用或设置 `generate_video` 的 `auto` / `confirm` / `deny` 策略。此入口是普通 Skill，不新增独立视频 Agent 或 HTTP 生视频路由；Provider 服务封装位于 `agent/aigc/video_service.py`。

## 生命周期与重试

图片和视频共用 `SparkTaskClient` 的提交、鉴权、重试、轮询和错误上下文逻辑。视频每 5 秒查询一次，`submitting`、`queued`、`running`、`recovering` 均继续等待，`failed` 和 `expired` 终止等待并返回错误。视频客户端总等待期限为 540 秒，包含下载；工具治理超时为 570 秒，留出返回错误信息的余量。

网络错误以及 429/502/503/504 最多尝试 3 次，始终复用同一幂等键及请求体；401/409/422 不自动重试。超时只结束客户端等待，不取消服务端任务。失败结果保留 `code`、`task_id`、`idempotency_key`，会话压缩也保留这些字段。

继续等待或恢复下载时，用原 `idempotency_key` 和原始 `prompt`、尺寸、帧数或时长、FPS、seed 等参数再次调用工具。不得将时长替换成换算后的帧数，也不能将 120 帧改成对齐后的 124 帧；它们是不同的调参请求。原请求省略 seed 时继续省略，不能改用响应中的随机 seed。数字种子和对应十进制字符串等价，-1/null/省略等价，兼容 0.4 请求的幂等重放。仅在明确重新生成时使用新键。重放直接走幂等 POST，不用“当前是否允许新任务”的能力开关拦截已有任务恢复。

下载只接受当前任务、当前 artifact ID 对应的相对地址，不跟随重定向。文件按 64 KiB 分块写入 `.part`，最多 512 MiB，检查 Content-Type、Content-Length（如有）及 MP4 顶层容器完整性后原子改名。中断后从头下载，不拼接 Range；失败或取消时清理临时文件。编码、音频及实际尺寸验证由 Provider 负责。

Provider 结果保留 24 小时，Agent 在返回成功前下载到本地业务目录。与现有生图一致，Agent 和 Gateway 需共享生成目录并在部署时保留文件；本地文件目前没有自动清理策略。

## 测试

```bash
python3 -m pytest tests/test_spark_video.py tests/test_spark_image.py tests/test_tool_router.py tests/test_orchestrator.py tests/test_tool_governance.py tests/test_api.py -q
./scripts/test.sh
```

视频测试使用 HTTP MockTransport，覆盖尺寸/时长/FPS/seed 参数约束、帧网格与资源边界、64 位精度、请求类型与幂等重试、执行元数据和旧任务兼容，以及过期、下载中断与清理、工具路由和权限、真实结果链接及重试上下文保留，不消耗 GPU。真实视频生成需使用已配置的 Provider 联调。
