# Search 重排和召回耗时优化

日期：2026-09-08。以下为本机当前代码、已有 API Key 和本地持久化配置的实测，不是服务器部署验收。

## 改动

- 默认关闭 DuckDuckGo：YAML `search.web.enabled=false`，RuntimeConfig 和搜索工厂的缺省值也为 false；本地数据库同名配置已持久化为 false。仍可显式开启。
- `sources=web` 继续作为通用网页搜索别名。当前已配置的网页召回源为豆包、MiniMax 和 Bing。
- 重排保留原模型、10 条候选上限、标题/摘要/URL/召回上下文、判断标准和 0.5 过滤阈值，只将输出改成按候选顺序排列的 `scores` 数组。程序执行排序和筛选，模型不再逐条生成解释。
- 严格验证数组长度、数字类型、有限性和 [0,1] 范围；异常时退回本地排名。仍兼容旧版 index/score/reason 结构。
- Trace 保留分数、候选映射和模型用量，默认不再包含逐条自然语言理由。

## 固定候选重排 A/B

复用此前 5 个精选案例各自固定的 10 条候选，两个版本使用完全相同的原始问题上下文和候选输入；交替执行顺序以减少顺序偏差。均使用现有火山模型、temperature=0、thinking disabled，没有改候选内容来换速度。服务端缓存命中和网络波动仍会影响耗时。

| 查询 | 原重排 | 优化后 |
| --- | ---: | ---: |
| Dunlop 清洁保养剂 | 12.291 s | 3.887 s |
| 成人钢琴教材 | 12.834 s | 1.538 s |
| 欧洲卡车 DLC | 8.925 s | 2.991 s |
| 宠物行业报告 | 9.335 s | 2.608 s |
| Dify RAG 实践 | 10.716 s | 6.577 s |
| 平均 | 10.820 s | 3.520 s |

重排平均耗时下降约 67%，平均输出由 522.8 token 减少到 53 token。输入信息没有压缩，输出协议说明略有增加。

5 个案例逐项的 Precision@5、Recall@5、MRR 和反例命中数全部一致：两种版本均有 23/25 条结果匹配仓库相关性规则、命中 12/15 个期望项、反例命中 0。三个案例的 Top 5 URL 集合完全相同，另外两个各重合 4 条；排序有变化。这是小样本、基于关键词标注的回归检查，不能证明所有查询语义质量完全一致。

原始数据和复现脚本（本地忽略产物）：

- `artifacts/search-eval/rerank-compact-ab-20260908.json`
- `artifacts/search-eval/rerank_compact_ab.py`
- `artifacts/search-eval/service_before_rerank_optimization.py`

## 完整工具实测

优化前后分别顺序执行相同的三条查询，默认 limit=5、include_images=true、open_results=false。包括工具创建、改写、召回、重排和补图，不包括 Agent 的前置规划和最后回答生成；实时网页候选和网络状态可能发生变化。

| 查询 | 优化前完整 search | 优化后完整 search |
| --- | ---: | ---: |
| Dunlop 清洁保养剂 | 30.888 s | 11.491 s |
| 成人钢琴教材 | 30.288 s | 13.067 s |
| Dify RAG 实践 | 25.693 s | 8.826 s |
| 平均 | 28.956 s | 11.128 s |

平均下降约 62%。优化后的阶段范围为：改写 3.4–4.2 秒、召回 1.0–1.9 秒、本地排名 0.03–0.13 秒、重排 2.6–4.1 秒、补图 0.85–3.53 秒。三次均返回 5 条结果，改写和重排均正常完成，召回没有 DuckDuckGo 请求，也不再因它等待 10 秒超时；部分图片探测失败仍在 trace 中如实记录。

数据：`artifacts/search-eval/current-latency-20260908.json` 和 `artifacts/search-eval/optimized-latency-20260908.json`。线上耗时需部署后另外验证；本次操作时本地 Agent 和 Gateway 服务均未启动，没有重启或部署服务。

## 自动化验证

新增 `tests/test_search_rerank_compact.py` 共 19 个参数化测试实例，覆盖分数映射、排序与同分顺序、阈值、全部低相关、候选证据保留、异常数组回退、旧格式兼容，以及 DuckDuckGo 默认关闭、显式启用和通用 web 别名。

先验证新行为在修改前失败，再执行实现后的局部测试（184 项通过）；最后 `./scripts/test.sh` 通过：Python 868 项、JavaScript 253 项，Go vet/test/build 全通过。Android 因未配置 Java/SDK 跳过。
