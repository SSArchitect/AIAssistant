# 火山引擎专业检索

依据[专业数据集官方文档](https://docs.volcengine.com/docs/82379/2479086?lang=zh)，
工具层按领域拆分，底层共用同一个 HTTP MCP 客户端；服务端仍根据生成的自然语言 query 选择数据集。

| 工具 | 查询范围 | 参数 |
| --- | --- | --- |
| `finance_search` | 证券财报、行情、估值 | `securities`（1–3只）、`indicators`、`period` |
| `company_search` | 工商、股东、企业风险 | `companies`（1–5家）、`dataset`（business/risk）、`query` |
| `macro_search` | 宏观经济、地区和产业指标 | `query`（明确指标、地区、时间） |
| `vehicle_search` | 汽车配置、销量 | `dataset`（configuration/sales）、`query` |
| `academic_search` | 科研论文、期刊、文献 | `query` |

旧 `professional_search` 仅保留兼容入口，不参与初始路由或 `tool_search` 发现。

## 接口与配置

- 固定使用 `https://datapro.hqd.cn-beijing.volces.com/mcp`，HTTP MCP 接口，
  通过 `X-Agent-Plan-Key` 鉴权；与 Ark 聊天和豆包通用搜索接口独立。
- 默认 `search.datapro.enabled=true`；没有 Key 时不向模型暴露工具。
- Key 优先使用运行时 `search.datapro.api_key`（初始值来自 `DATAPRO_API_KEY`），
  否则复用 `llm.doubao.api_key`（初始值来自 `DOUBAO_API_KEY`）。
  不复用 `search.doubao.api_key`，它可能是普通搜索的独立凭据。
- 官方要求 Agent Plan 专业数据集专属 Key，并在控制台开通专业数据集抵扣。
  已有聊天 Key 是否可复用以实际鉴权结果为准；失败时可配置专属 Key。
  不自动开通服务、更改数据集开关或切换计费方式。密钥不写入 YAML。
- `search.datapro.timeout` 默认 60 秒，覆盖初始化、工具发现和查询全流程；
  有效配置范围为大于 0 且不超过 120 秒，无效值回退到 60 秒。

`finance_search` 示例参数：

```json
{"securities": ["中际旭创", "新易盛", "天孚通信"], "indicators": "市值 市盈率", "period": "2026年9月8日", "limit": 3}
```

`limit` 为本地返回条数上限（1–49），不会改变服务端检索或费用。
金融、汽车、企业等数据集各自的查询限制以官方文档为准，query 应明确实体、时间、
地区和指标；例如企业查询使用完整公司名称或统一信用代码。
金融数据库按具体证券查询，一次最多 3 只；不能用“CPO 龙头股”等板块筛选条件替代证券名称。
如需板块对比，应先用 `search` 确定标的，再提供具体证券名称或代码查询财务/估值指标。

## 结果与错误

客户端先初始化 MCP 会话，读取 `tools/list` 验证 `dataPro_search` 的 query 参数，
再执行一次 `tools/call`，支持 JSON 和 SSE 返回，结束后释放服务端会话。
查询不做自动重试，避免失败后不确定的重复计费。

结果保留 `items` 中完整的表格、数值、单位、报告期、作者和摘要，以及服务返回的
`dataset_type`、`trace_id`、`total`、`hint` 等字段。额外返回
`source=volcengine-datapro`、`returned_count`、`truncated`。
没有 URL 的结构化数据仍然有效，不进入普通网页去重、摘要截断或正文打开流程。
回答应引用真实 URL 或数据来源/数据集标识，不能编造链接。

工具按专业查询关键词动态加入模型可见工具，也可通过 `tool_search` 发现。
路由使用关键词、同义表达和文本片段评分，不是 embedding 或模型语义匹配。
“有没有官司”“去年赚了多少钱”“新能源车卖得怎么样”“研究资料”“国内生产总值”
等表达可直接带入工具；`tool_search` 使用同一评分规则，发现后引擎在下一轮加入真实参数定义。
带入只是让模型可以选择调用，并不强制发起检索；无领域线索的任意表达不保证命中。
执行走现有 Tool Governance 和 Trace，支持 `auto` / `confirm` / `deny` 及每次 run 调用上限。
普通搜索继续使用 `search`；专业搜索不加入每个普通网页查询的默认召回源。
旧 `professional_search` 的 deny/confirm 策略由新工具继承；若为某个新工具显式配置策略，则该工具使用新策略。
禁用旧入口时会同时从可用目录中排除全部领域工具；单独禁用领域工具只影响自身。

鉴权失败、超时、HTTP/MCP/数据集错误返回失败状态，错误不转发上游原文或密钥。
`stock_finance` 返回业务码 `4003` 时，工具返回
`professional_search_entity_not_found` 和明确的查询修正提示，保留安全的业务码及数据集类型。
这表示证券实体未匹配，不是权限错误；模型可按已有证券名称/代码重新查询，
未确定标的时先使用普通搜索。不会原样自动重试，也不会把失败伪装为成功。
返回空 `items` 表示成功但无匹配数据；不会伪造网页结果或静默切换数据服务。

## 验证

```bash
python3 -m pytest tests/test_datapro_search.py tests/test_dataset_tools.py tests/test_skills.py tests/test_tool_router.py tests/test_tool_governance.py
./scripts/test.sh
```

单元测试使用 `httpx.MockTransport` 验证协议、数据保留、错误、限制、配置、发现和路由。
2026-09-08 经用户授权，使用现有火山引擎 Key 验证了真实鉴权、MCP 初始化、
`tools/list` 和 `tools/call`。服务端工具名为 `dataPro_search`，必填参数只有字符串 `query`。
用受控的模型工具调用序列验证了 `tool_search` → schema 扩展 → Tool Governance →
真实专业检索 → 模型上下文的完整链路（未测试模型自主选工具的准确率）。
“五粮液季度业绩季报数据”在约 18.7 秒内返回 `stock_finance`、1 个证券实体和
74 条 records，数值、单位、期间和统计口径完整保留。
宏观示例曾返回 `code=0` 但 `items=[]`，服务端提示超出支持范围；
接口连通不等于每个数据集或每条 query 都有数据，回答需保留该限制。

此前版本已在线上确认专业数据集已启用。针对 run_c8298fa20f44424f94f4cd647bfff5e3，
复现板块描述查询返回 `4003`；将同一查询改为具体三家证券后，约17.4秒返回三家数据。
拆分后的回归测试覆盖各领域请求、金融参数边界、4003分类、查询恢复、工具发现和策略继承。
