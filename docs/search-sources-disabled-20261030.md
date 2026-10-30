# 搜索来源关闭与耗时验证

2026-10-30 已在生产持久化并热更新以下设置：

```json
{
  "search.minimax.enabled": "false",
  "search.bailian.enabled": "false"
}
```

可复用的配置快照位于 `ops/config/search-sources-20261030.json`。该文件用于记录和显式应用配置，
应用不会自动读取它。现有生产值已经写入 Gateway 的 settings 表，并通过 `/agent/config`
同步到正在运行的 Agent；后续 Gateway 配置同步和服务重启会继续使用持久化值。

## 生效范围

- 默认搜索和 `sources=web` 仅使用现有豆包搜索与 Bing。
- 仅关闭搜索召回来源；聊天默认模型及创作模型没有改变。
- 搜索改写、重排继续使用线上既有的 `bailian:qwen3.8-flash` 创作模型。
- 补图保持原行为，默认开启。本次没有修改补图实现或开关。
- 没有发布应用源码、重启服务或更新客户端版本，无需安装或 OTA。

本次检查了变更前后的其他持久化设置与内存配置摘要，确认范围外设置未变。
生产源码以 HEAD `82680b1523a23e39b10225fbe0d17e118717f2e1` 及其已部署补丁为基线。
当时远端 Git 尚未包含部分已部署的百炼适配与搜索模型继承代码；本次提交仅记录配置及其
回归检查，不把未归档的其他部署内容一并提交，也不使用 Git 整仓覆盖生产工作树。

## 实际耗时

从生产 Agent 的 loopback API 顺序执行三个公开查询。均为 `sources=web`、`limit=5`、
`include_images=true`、`open_results=false`，保留改写与重排。全部返回有效文字结果，
仅调用豆包和 Bing，搜索 provider error 均为零。

| 查询 | 召回 | 改写 | 重排 | 补图 | 完整搜索 | 返回条数 / 图片数 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Python asyncio TaskGroup 官方文档 | 0.452 s | 3.072 s | 2.514 s | 10.532 s | 16.746 s | 4 / 1 |
| 国家博物馆 参观 预约 官方 | 0.442 s | 1.839 s | 2.526 s | 1.782 s | 6.773 s | 5 / 0 |
| 问界 M6 220V 电源插座 官方说明 | 1.487 s | 1.717 s | 1.751 s | 0.462 s | 5.527 s | 2 / 0 |

完整搜索还包含本地排序与调用开销；不包含聊天主模型、Gateway 和客户端网络/展示。
这些是三个不同查询的单次验收样本，不是固定查询前后 A/B，也不能据此保证长期延迟。
关闭故障来源后召回已达到约 0.5–1.5 秒，完整搜索仍取决于改写、重排和补图。
补图节点 `completed` 表示处理正常结束，不表示一定找到了图片。

## 验证与回退

新增 `tests/test_search_provider_selection.py`，覆盖有密钥但来源关闭、默认/web 来源、
显式指定禁用来源、保留辅助模型调用、单一健康来源及全部关闭时的行为。
测试隔离 runtime config，并模拟 provider，不调用真实搜索或修改数据库。

配置上线前的工作区局部测试 87 项通过；生产实际源码上的新增回归测试 9 项通过。
工作区 `./scripts/test.sh` 在项目虚拟环境下通过：Python 2084 项、JavaScript 990 项、
Go vet/test/build、Mac 60 项原生测试及桌面更新测试；Android 因 Java/SDK 未配置跳过。
公网健康接口返回 `status=ok`、`agent=ok`。

本次 Git 提交基于远端 HEAD 单独建立隔离候选。该候选的局部测试 193 项通过，
`./scripts/test.sh` 全量通过：Python 1625 项、JavaScript 345 项、Go vet/test/build；
Android 因 Java/SDK 未配置跳过。同一份新增测试加载本地较新的实现也有 9 项通过。

生产范围备份及回执：`/home/ubuntu/releases/search-sources-20261030/`。
回退只恢复这两个设置，先检查当前值是否已被后续修改：

```bash
python3 /home/ubuntu/releases/search-sources-20261030/update_search_sources.py rollback
```

该命令在生产主机执行。若已经发生后续配置调整，应先核对备份和当前值，避免恢复过时设置。
