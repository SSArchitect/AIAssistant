# 火山引擎 Provider

管理页中显示为“火山引擎 / Volcengine”，内部沿用 `doubao` 和 `llm.doubao.*` 配置键。
默认接入 Agent Plan：`https://ark.cn-beijing.volces.com/api/plan/v3`，
默认模型 `doubao-seed-2.1-turbo`。环境变量为 `DOUBAO_API_KEY`、
`DOUBAO_BASE_URL`、`DOUBAO_MODEL`；运行时管理页配置优先于环境变量。
密钥只应放入被 Git 忽略的 `.env` 或管理页配置，不要写入 YAML、代码或测试。

聊天与模型发现使用相同 Base URL。已有按量接口用户可在管理页明确设置
`https://ark.cn-beijing.volces.com/api/v3` 并保留原模型 ID；系统不会自动切换计费接口。
`doubao:<model>` 可覆盖单次使用的模型，例如 `doubao:glm-5.3`。

Agent Plan 没有 OpenAI `/models` 接口（2026-09-08 实测返回 404）。
因此“刷新模型”加载 `agent/llm/doubao_provider.py` 中按
[官方套餐清单](https://docs.volcengine.com/docs/82379/2366394)维护的 11 个文本模型，
不将图片、视频、语音和向量模型混入聊天选择器。Kimi K3 需要 Medium 或更高套餐；
清单不代表当前账号的实际权限，后续模型变化需更新该常量，也可在管理页手动添加。

“验证配置”对 Plan 返回待检测，避免把静态清单误认为密钥验证结果。
选择模型发送真实消息来验证当前模型，或调用管理 API `/api/admin/test-provider`
（会消耗少量套餐额度）。
普通按量或自定义地址仍请求其 `/models`，鉴权及网络错误直接返回，不使用静态清单掩盖错误。

测试：`python3 -m pytest tests/test_doubao_provider.py` 和
`node --test tests/test_admin_model_refresh_web.js`，完成后运行 `./scripts/test.sh`。

专业数据集通过独立工具 `professional_search` 接入，复用火山引擎 Key 或使用
`DATAPRO_API_KEY` / `search.datapro.api_key` 专属 Key。覆盖企业、金融、宏观经济、
汽车和学术数据，保留完整结构化结果。配置、权限要求及测试见
[专业检索接入说明](volcengine-professional-search.md)。
