# Spark 角色风格化

新增 `mode=character_stylization` 和 `character_style=anime|chibi`，配合一张源图调用 Spark Provider 0.7.0 的独立 Qwen-Image-Edit-2511 workflow。原文生图与图生图语义保持不变。

工具 `image_generation_v1` 可使用：

```json
{
  "task": "把附件人物变成 Q 版，保留黄色外套和眼镜",
  "provider": "spark",
  "mode": "character_stylization",
  "character_style": "chibi",
  "image_attachment_index": 1
}
```

源图可选已有 `image_asset_id`，附件序号按本轮全部附件从 1 开始。不可混用来源。`denoise` 不适用于角色风格化。显式输出总像素最多 1048576；省略尺寸按画幅选择合法预设。实际生成仍异步接单、轮询及下载，超时后复用原幂等 Key 获取同一任务。

图片结果 `model=qwen-image-edit-2511`，metadata.stylization 记录实际风格、模型和预设版本。该功能只支持 Spark，其他 Provider 会明确拒绝，避免静默丢失风格意图。

调用前确认目标 capabilities 包含 character_stylization。大模型首次加载可能较慢；会话流式后台任务沿用现有长任务机制，直接 API 的超时不等于后端取消。

本轮仅修改 Agent 本地源码；云服务器 Agent 未部署。
