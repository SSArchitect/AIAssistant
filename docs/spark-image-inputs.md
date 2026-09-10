# Spark 图片输入：图生图与图生视频

2026-09-10。Agent 已接入 Provider 0.6.0 的两个新模式；远端 Provider 必须先部署并在 `/v1/capabilities` 声明相应模式。原文生链路保持兼容。

## 使用入口

图生图继续使用 `image_generation_v1`，图生视频继续使用 `generate_video`。无需新增 Agent，也不绕过现有工具权限和 Trace。

上传图片后可请求“把第二个附件里的图片重绘成水彩”或“让这张图片动起来”。工具通过 `image_attachment_index` 选择本轮附件，从 **全部附件列表的 1** 开始计数。后端提取实际图片 data URL，并将二进制上传 Spark；模型不复制 base64。多个图片必须明确选择，不能静默使用第一张。

```json
{
  "task": "把上传图片重绘成水彩",
  "reason": "用户要求基于原图重绘",
  "provider": "spark",
  "mode": "image_to_image",
  "image_attachment_index": 1,
  "denoise": 0.45,
  "width": 1024,
  "height": 1024
}
```

```json
{
  "prompt": "人物轻轻转头，镜头缓慢推进",
  "mode": "image_to_video",
  "image_attachment_index": 1,
  "width": 864,
  "height": 480,
  "duration_seconds": 5
}
```

图生模式只有一个图片附件时可省略 index；无图或多图未选择时明确失败。Spark 图片工作流在存在参考图片且未显式设置 text_to_image 时会使用该图片；显式文生模式可只使用文字。

## HTTP 与客户端

`POST /api/aigc/image` 和 `/agent/aigc/image` 新增：

- `mode`: text_to_image / image_to_image。
- `image_asset_id` 或 `image_data_url`，二选一。data URL 只接受 PNG/JPEG/WebP 的严格 base64、原始字节最多 16 MiB。
- `denoise`: `0 < value <= 1`，默认 0.45，越大重绘通常越明显。
- `image_fit`: center_crop（默认，居中裁剪）或 stretch（拉伸）。

直接 HTTP 请求无聊天附件上下文，应使用 asset ID 或 data URL，不能使用附件序号。视频仍由 tool/service 提供，不新增 HTTP 视频路由。视频请求模型接受 `first_frame_asset_id` 或内部 `first_frame_data_url`，对应单首帧。

传入实际图片来源时，Agent 自动推断图生模式；显式文生模式与图片输入冲突时报错。MiniMax 的 subject_reference 保持独立语义，Spark 不接受该字段。

尺寸沿用原图片/视频规则，不随原图自动改变。画幅不同时，默认居中裁剪可能裁掉边缘；stretch 会改变物体比例。

## 上传和重试

上传调用 `POST /v1/assets`，正文为原始字节，带图片 Content-Type 和鉴权。上传 Key 为 `input-` 加任务幂等键的 SHA-256，保证跨重连、跨进程重试仍得到相同资产。相同 Key 改变图片字节或 MIME 返回冲突。任务创建请求仅携带 asset_id，不携带 base64。

已到期上传记录可被重放以恢复已有任务；Provider 在任务层先执行幂等查询，再检查图片 TTL 和接单开关。随机 seed、时长/帧数、提示词等重试规则见原 Spark 文档。错误继续包含 code、task_id（已知时）、idempotency_key。

图片/视频输出仍下载到 `web/static/generated/aigc`，保留实际结果 URL；新增 metadata.mode/source 便于检查输入来源和重绘参数。工具权限拒绝时不会上传图片；工具 Trace 中的图片 data URL 脱敏。

## 本版范围

图生图使用现有 Z-Image Base 的潜空间重绘，不等同于专门的指令编辑模型，不保证脸、文字或其他细节精确不变。图生视频只开放 H3 单首帧条件；不支持尾帧、多参考图、mask、参考视频。已生成的图片可作为新附件重新上传，或由业务后端上传后引用返回的资产 ID。

## 验证

新增 `tests/test_spark_image_inputs.py` 覆盖：图片二进制上传、重试一致性、到期重放、上传失败上下文、附件选择、模式冲突、工具治理与图片脱敏，以及完整图片工作流向 Provider 传递实际附件。

Go bridge 新增图生图字段转发测试。完整回归执行 `./scripts/test.sh`；测试使用 mock HTTP，不消耗 GPU。真实 GPU 测试由 Spark Provider 工程的 `tools/verify_image_inputs_live.py` 执行。

### 2026-09-10 Agent 本地联调

通过本项目客户端调用正式 Provider，两条新链路均完成上传、生成、下载和跨客户端幂等重放；修改提示词但复用任务 Key 均返回 `idempotency_conflict`。使用 Provider 验收目录中的非个人 512×512 样图，不代表最大尺寸或并发性能。

- 图生图：512×512、denoise=0.45、seed=42，约 20 秒完成；构图保留并出现水彩重绘变化。
- 图生视频：512×512、请求 5 秒、24 FPS、seed=42，约 180 秒完成。完整解码 124 个视频帧及音轨，实际时长约 5.167 秒。
- Gateway `/api/aigc/image` 对原请求的重放返回相同任务，生成图片可通过本地静态资源地址下载。
- 修复附件序号与显式图片来源同时传入时静默忽略序号的问题；现在明确拒绝冲突来源。
- 兼容历史任务 `mode: null`，返回元数据使用原请求模式。
- 修复 Gateway 将图片输入校验错误统一转换为 500 的问题：保留 Agent 的 400/422 等 HTTP 状态，上游不可达返回 502。

新增 Python 回归用例覆盖来源冲突和空模式兼容；`gateway/internal/handlers/chat_aigc_test.go` 覆盖输入校验、上游失败状态转发及服务不可达。局部 Python 测试 224 项通过；全量 Python 889 项、前端 253 项通过，Go vet/test/build 通过。Android 因未配置 Java/SDK 跳过。

本地联调脚本、JSON 报告、完整测试日志和部署前 Gateway 备份保存在 `tmp/spark-validation-20260910/`（不纳入 Git）；生成文件保存在 `web/static/generated/aigc/`。一次直接资产查询未通过，随后使用客户端标准重试查询得到 200/ready；生成任务和幂等重放均正常。

最终部署已完成：Agent `:9090` 与 Gateway `:8080` 健康检查正常，沿用本机现有 launchd 服务。部署后实测非法 base64 返回 400、非法资产 UUID 返回 422；视频完整下载返回 200、Range 下载返回 206。浏览器读取到 512×512、5.167 秒，`readyState=4` 且无媒体错误；工作台首页无浏览器脚本错误。最终 `./scripts/test.sh` 再次全部通过。
