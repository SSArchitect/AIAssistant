# 搜索本地翻译替代评估

日期：2026-09-08。

结论：当前跨语言 query 由远程 LLM 改写节点生成，但搜索本身并不强依赖这个节点；关闭或失败时会退回词法 query。技术上可以改用本地翻译。此次实测的轻量 Argos/OPUS-MT 1.9 模型速度足够，但会漏掉查询主题、产品名称和人名，因此本次没有替换默认链路，也没有改线上配置。

## 当前链路

- `agent/search/service.py` 的 `_search_query_rewriter_from_runtime_config` 创建 LLM 改写器，默认使用 `llm.default_provider`。
- `search.rewrite.enabled=false` 关闭整个 LLM 改写节点，保留词法处理，不再产生跨语言翻译。
- 默认 `search.recall.max_queries=2`；合并时优先保留词法首条和互补语言 query，因此同语言的语义扩展常没有进入实际召回。
- Doubao、MiniMax 等 provider 当前只使用第一条 query；第二条翻译主要给支持两条 query 的 Web/Bing provider 使用。
- LLM rerank 是独立的后续节点。替换翻译不会消除重排或搜索源的耗时；前次实测改写平均约 4 秒，不能把整个四十多秒归因于翻译。

## 实验设置

使用本机 macOS ARM64、Python 3.9.6、`ctranslate2==4.6.3` 和 `sentencepiece==0.2.1`，CPU int8、2 个计算线程、beam size 4、length penalty 0.2、replace_unknowns=true。直接运行短查询翻译，不安装 Argos 的完整分句和 PyTorch 依赖。解码按 Argos tokenizer 处理残留 SentencePiece 空格标记。

来源为 [Argos 官方模型索引](https://github.com/argosopentech/argospm-index/blob/main/index.json)，两个模型下载共约 138.5 MiB：

| 模型 | 包 SHA-256 |
| --- | --- |
| [zh→en 1.9](https://argos-net.com/v1/translate-zh_en-1_9.argosmodel) | `62e7af5a3a48b530e47b7b3e5c78c2de79073ecd815750d2bf3ab35b4a67da2d` |
| [en→zh 1.9](https://argos-net.com/v1/translate-en_zh-1_9.argosmodel) | `433e7c4f034d87fbe2353161e05f18646d7999452f801a4e1f0378522b9850ab` |

推理参数参照 [Argos 翻译实现](https://github.com/argosopentech/argos-translate/blob/master/argostranslate/translate.py) 和 [tokenizer 实现](https://github.com/argosopentech/argos-translate/blob/master/argostranslate/tokenizer.py)。CTranslate2 的 [CPU 支持说明](https://opennmt.net/CTranslate2/hardware_support.html) 包含 ARM64。

复用仓库 5 个搜索评测问题，各跑 5 次，比较翻译文本的忠实程度；LLM 对照来自当天先前实验。没有重新测最终搜索相关性，这些数据不能视为最终召回率或答案质量的 A/B 结果。

## 结果

| 查询 | 本地直接翻译 | 单条耗时中位数 | 观察 |
| --- | --- | ---: | --- |
| Dunlop65 01 02 三瓶 清洁 保养剂 电吉他 分别作用 | Dunlop 65 01 02 3 bottles Cleaning, maintenance, electric guitars. | 91 ms | 保留品牌、编号，弱化“分别作用” |
| 成人钢琴入门 教材 拜厄 车尔尼 哈农 | The adult piano. | 47 ms | 漏掉教材和全部三个人名 |
| Euro Truck Simulator 2 DLC list latest | 最新DLC列表 | 70 ms | 丢失游戏名和版本号 |
| 宠物用品 行业市场报告 2026 渠道规模 | 2026 Channel size | 46 ms | 丢失宠物用品和市场报告主题 |
| Dify RAG Agent 工程实践 评测 benchmark | Diffy RAG Agent Engineering Practice Evaluation benchmark | 77 ms | 品牌拼写改变 |

5 条查询的中位耗时平均约 66 ms，不包含首次导入和模型载入。首次试跑导入加中译英模型加载约 721 ms；后续进程受文件缓存影响，导入约 59 ms、两个模型加载分别约 72/59 ms。耗时仅代表这台开发机。

5 次重复输出一致。人工检查发现 4/5 查询有关键实体丢失或改名；这只是小样本翻译缺陷计数，不是通用准确率。之前 LLM 生成的翻译能保留 Beyer/Czerny/Hanon、游戏名称、宠物主题以及 Dify。此前“LLM 语义扩展没有测到额外召回收益”，并不意味着任意便宜翻译器都能达到它的翻译质量。

进一步试验：

- 按空格分段翻译能减少漏词，但仍产生 `Bayer / Chelney / Hanon`、`Petty supplies`、`Diffy` 等错误。
- 去掉空格会把 Dunlop 的多个编号粘在一起，其他查询仍有漏译或错误转写。
- float32 复测钢琴、宠物和 Dify 查询，核心遗漏或拼写错误仍存在，不是切换非量化就能解决。

因此不建议直接启用此次模型。后续若继续替换，应先对更强的专用翻译模型做同样测试，加入品牌/型号保护，并保留原始 query；不要用针对这 5 条的硬编码词表掩盖泛化问题。本次没有评估其他本地模型，不能据此判定所有本地翻译都不可用。

## 留存和验证

本地实验脚本：`artifacts/search-eval/local_translation_probe.py`；数据：`artifacts/search-eval/local-translation-20260908.json`。模型解压在临时目录 `/tmp/search-translation-prototype`，未放入运行链路。重跑命令：

```bash
python3 artifacts/search-eval/local_translation_probe.py --models /tmp/search-translation-prototype
```

本次仅新增评估文档和被 Git 忽略的实验产物，没有新增产品 feature，也未增加主依赖文件中的强制依赖。两个实验依赖安装在本机 Python 用户环境。

验证：搜索局部测试 41 项通过；`./scripts/test.sh` 通过，Python 849 项、JavaScript 253 项，以及 Go vet/test/build 均通过。Android 检查因缺少 Java/SDK 跳过。没有新增产品单元测试，因为本次未修改产品运行行为。
