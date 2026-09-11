# Spark Provider 0.8 模板接入

2026-09-11，依据 Provider `TEMPLATE_API_PROTOCOL.md` 适配。Provider 0.8 继续接受旧的
`type + mode + input.character_style` 请求，因此升级 Provider 本身不会破坏原 Agent 调用。
本次 Agent 在 Spark 请求中显式加入顶层 `template`，锁定版本化的生成效果契约；部署此版
Agent 时，目标 Spark Provider 需为 0.8.0 或兼容新版模板协议的版本。

Agent API、`image_generation_v1` 和 `generate_video` 的调用参数保持原有形式，由客户端
按已校验的模式选择公共模板，不把内部 workflow 文件名或任意模板字符串交给模型选择。

| Agent 请求 | Provider 顶层 template |
| --- | --- |
| 默认文生图 / `mode=text_to_image` | `image.text.v1` |
| `mode=image_to_image`（也可由源图自动推断） | `image.edit.v1` |
| `character_style=anime` + 源图 | `image.character.anime.v1` |
| `character_style=chibi` + 源图 | `image.character.chibi.v1` |
| 默认文生视频 / `mode=text_to_video` | `video.text.v1` |
| `mode=image_to_video`（也可由首帧自动推断） | `video.image.v1` |

发给 Provider 的 `type`、图像输入模式 `mode`、角色 `character_style` 继续携带，并与
模板保持一致；协议明确允许这种组合。生成参数仍放在 `input`。角色模板不传 denoise，
保留 1048576 总像素上限；视频仍不传 negative_prompt，大 seed 使用十进制字符串。

成功结果的 `metadata.template` 优先保留 Provider 最终任务响应中的公共模板 ID；
兼容缺少该字段或值为 null 的历史响应时，按原请求的模板补齐。

部署时可带 Bearer Key 检查 `GET /v1/templates`，确认需要的模板 `enabled=true`。
该目录还提供 `input_schema` 和模板专属资源上限；当前 Agent 固定支持上表 6 个模板，
尚未提供动态模板目录工具。任务提交沿用直接幂等 POST，不在恢复旧任务前用当前模板开关
拦截；Provider 会先处理幂等重放，再检查是否接受新任务。新任务被拒绝时透传
`unsupported_mode` / `unsupported_task_type`，不自动换模板或换 Key。

按照 Provider 协议，新旧写法会规范化到同一请求计算幂等哈希，因此升级前未完成的请求
仍使用原参数和原 Key 恢复。重试保留提示词、seed、尺寸、原始帧数或时长，不能把时长
替换成对齐后的帧数；修改风格或参数属于新请求。

此改动不变更 Provider 地址与密钥。Provider 的 2026-09-11 协议注明原临时公网 Tunnel
已失效；云端联调需要可达的 origin。模板适配本身不修复公网入口，也不代表云端 Agent 已部署。

验证使用 HTTP MockTransport，不消耗 GPU：

```bash
python3 -m pytest tests/test_spark_templates.py tests/test_spark_image.py tests/test_spark_video.py tests/test_spark_image_inputs.py tests/test_character_stylization.py -q
./scripts/test.sh
```

新增测试覆盖 6 个模板、附件上传、稳定幂等重试、轮询下载、模板结果元数据、历史响应，
以及未启用模式和幂等冲突时不回退模板。既有图片/视频的完整请求断言同步增加模板字段。
