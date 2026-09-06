# Connect 实现与接入说明

日期：2026-09-06。当前交付为 `connect.v1` 文字私聊基础版。

## 当前能力

- 工作台 **Connect**：支持目录、我的连接、连接详情、连接检测、断开、重新连接、删除连接、备注、来源会话入口，以及失败或结果不明消息的人工重发。
- 飞书：自建应用凭据、官方 SDK 长连接接收私聊、通过一次性配对码绑定发送者、发送最终文本。
- 微信：基于腾讯 iLink 公开实现的独立适配器，扫码授权、文字私聊长轮询、回复上下文隔离、游标恢复。未依赖 OpenClaw 运行时。
- 两端都由现有 `super_chat` 执行，复用人设、长期记忆、工具策略、上下文构建、Trace 和消息/Token 用量记录；Connect 不提供模型或专业 Agent 选择。
- 表格通过 Markdown AST 按「列名：值」输出，保留数值、单位和链接；最终回答按 UTF-8 字节预算分段并编号。正文默认不随模型 token 流逐条外发。超过 10 秒的运行最多发送一条处理中提示；需要工具授权时额外提示用户到工作台的来源会话处理。
- 仅支持文字私聊。图片、文件、音视频消息会得到明确的文字提示，不作为伪造用户请求交给模型；群聊和其他机器人消息忽略。

Slack、Telegram、设备执行、飞书卡片、流式预览、图片/文件发送、微信额外验证码授权和主动推送尚未实现，不出现在可连接目录中。微信扫码若要求额外验证码，会显示授权未完成，需要后续扩展该授权分支。

## 接入步骤

同时更新并启动 Gateway 和 Python Agent，登录工作台账号，在 **Connect → 可连接的端** 选择平台。

### 飞书

1. 在飞书开放平台创建自建应用并开启机器人。
2. 启用接收用户私聊消息和发送机器人消息所需权限，订阅 `im.message.receive_v1`；事件接收方式选择长连接。应用发布和可用范围按平台要求配置。
3. 在 Connect 填写连接名称、App ID、App Secret，并选择人设。
4. 页面显示配对码后，由实际使用者向机器人私聊发送 `/connect <配对码>`。配对码有效期 10 分钟，过期可重新连接生成新码。
5. 页面显示已连接后，发送普通文字开始使用。连接检测会读取令牌可用性，不发送测试消息；权限与端到端收发以实际联调结果为准。

长连接使用 `github.com/larksuite/oapi-sdk-go/v3 v3.11.0`；对应实现见 [飞书官方 SDK](https://github.com/larksuite/oapi-sdk-go/tree/v3.11.0)。需要 Gateway 能访问飞书的 HTTPS 和 WebSocket 服务，不要求公网 webhook。

### 微信

1. 选择微信，填写连接名称、选择人设并点击「新增连接」。
2. 用微信扫描页面二维码并确认，身份由平台授权响应返回。二维码仅在本地转换为 PNG 展示，不向外部二维码服务发送授权内容。
3. 在微信发送文字，页面会出现对应独立来源会话。

适配协议参考固定到腾讯 [`2f4dcbf57bedf0e17e266fdedcf0cd2dd141b7d3`](https://github.com/Tencent/openclaw-weixin/tree/2f4dcbf57bedf0e17e266fdedcf0cd2dd141b7d3)，对应包版本 2.4.8。[授权流程](https://github.com/Tencent/openclaw-weixin/blob/2f4dcbf57bedf0e17e266fdedcf0cd2dd141b7d3/src/auth/login-qr.ts)和[收发 API](https://github.com/Tencent/openclaw-weixin/blob/2f4dcbf57bedf0e17e266fdedcf0cd2dd141b7d3/src/api/api.ts)为兼容参考。当前完成的是协议样例测试，账号可接入性、实际发送配额和 `context_token` 的延迟回复期限仍需真实账号验证。

## 连接管理

「新增连接」为每个账号/用途创建独立记录；恢复已存在的连接应使用卡片上的「重新连接」。反复点击同一新增入口会保留当前表单与创建请求 ID，提交过程中也不会重复创建。

新建时可以填写备注，已有连接点击「备注」编辑。备注最多 500 个 Unicode 字符，支持多行，去掉首尾空白；保存空文本即可清空。备注仅为连接管理信息，不传给模型，也不改变人设、来源会话或连接状态。人设服务不可用时仍可修改备注和删除连接。

「删除连接」需要确认，会停止监听和运行中的任务，清除本地保存的授权、配对信息、来源路由、运行队列、投递和检测记录，并从列表移除连接。已有 Conversation/Message 和人设记忆保留；Python 已持久化的运行记录仍按现有账号数据生命周期保存。已开始的网络发送可能已经到达平台，不能撤回。服务端保留清除敏感字段的删除标记以占用原创建请求 ID，旧创建请求重试返回冲突，重启也不会恢复已删除连接。删除后可用新的创建请求重新绑定同一平台账号，建立新的来源会话。

## 会话和重投规则

每条连接独立保存 `role_id`。创建表单默认选择 Web 当前人设；已有连接点击「人设」保存修改，不需要重新扫码或授权。可选项为当前账号可用且启用的人设，服务端再次验证；旧连接迁移为 `default`。Web 此后切换人设不会自动改变已有连接。

接收普通消息时把人设 ID 快照到 turn，运行时传给 Super Chat；切换只影响之后接收的新消息，队列中的旧消息、重投和已冻结运行请求保持原 ID。快照固定的是人设 ID，而非人设内容的版本。已选人设后来被删除或停用时，运行会明确失败，不静默替换成其他人设。切换人设不会清空当前会话，如需重新开始，应在原平台发送 `/new`。

`source_id` 由项目账号、平台、连接实例、远端机器人身份、对端会话、平台线程、发送者共同确定。跨平台、实例或对端不会共享 Conversation。连接实例只绑定一个发送者；不是任何知道机器人地址的人都能使用该项目账号。

- 新消息 ID → 新 `turn_id` 和 `run_id`，在该来源当前 Conversation 中排队。
- 同来源 + 相同消息 ID + 相同内容 → 返回原 turn，不重复执行或生成新的投递；相同消息 ID 携带不同内容返回冲突。
- `/new` → 切换本来源话题，并向原平台回复「已为你开启新话题。想聊点什么？」及记忆保留提示，无需等待下一条消息或模型运行；下条普通消息建立新 Conversation。保留连接的人设及该人设下当前账号的长期记忆，旧会话原文和短期摘要不进入新会话。旧任务仍会完成，需要取消时另发 `/stop`。晚到的旧消息重投仍指向原 turn，确认回复也不会因此重复投递。
- `/status`、`/stop` → 控制面查询/取消，不交给模型。`/stop` 撤销该来源尚未开始投递的消息；已开始的网络发送可能已到达平台。
- `/help` → 返回指令和人设设置入口说明。控制指令本身不建立聊天会话，不写入模型的对话历史。
- 来源会话可在工作台查看和审批。Web 不允许追加聊天或重新生成，继续提问需回原平台，或在 Web 新建独立话题。

同一来源串行运行，全局最多 4 个运行。用户消息在出队时持久化，使后面排队的输入不会提前混入前一轮的模型上下文。首次提交前冻结完整运行请求，后续恢复不会因历史或策略变化构建不同的重投内容。

## 模型实际读取的上下文

不是把数据库里所有 Message 都交给大模型。Connect 沿用 Web 的上下文机制：

- 正常运行读取 Python `ConversationMemory` 的当前消息窗口，按 `user_id + conversation_id` 隔离；另注入人设、检索命中的长期记忆、短期摘要、本轮消息和必要工具上下文。同账号、同人设跨端共享长期记忆，跨来源不共享短期历史。
- 窗口超过 **40 条消息** 后，在回复完成后的后台阶段尝试 AI 压缩，生成摘要并选留最多 **12 条原文消息**。AI 可以判断暂不压缩，后台也有执行时差，所以并非每次请求固定带 12 条；窗口有 **80 条**硬上限。这里的「条」含用户、助手以及运行产生的工具消息，不等于对话轮数。
- 单次压缩摘要最多 1,200 字符；按日期维护最多 8 个摘要块，注入时总摘要裁剪到约 2,400 字符。这些是历史窗口限制，不代表包含工具说明、本轮消息的整个模型请求拥有统一 token 预算。
- 若进程里尚无该会话历史，Gateway 提供数据库最近最多 **30 条**用户/助手消息作为文本兜底；每条最多 1,800 字符，历史块总预算 24,000 字节。Connect 仅取本轮用户消息之前的内容。Python 已有窗口时丢弃此兜底块，避免重复注入。

当前短期原文窗口和摘要只在 Python 进程内，尚未持久化；服务重启后不能恢复完整短期摘要。数据库兜底块也不会自动回填窗口，不能视为完整记忆恢复。长期/角色记忆另由 `RoleMemoryStore` 持久化到 `data/agent_memory.json`。后续完善恢复应持久化会话摘要和窗口版本，并在首次加载时显式恢复窗口。

## 状态与恢复

`desired_state` 表示用户意图，`status` 表示观测状态。Disconnect 持久化 `disconnected` 并增加 `generation`，取消旧监听器和运行，撤销未发出的交付。检测只返回诊断，不改变连接意图；过期授权或检测结果不能覆盖新 generation。历史不会因 Disconnect 删除。

后端重启会暂时中断网络监听，但不修改连接意图、generation、人设或来源会话。启动后，`desired_state=enabled` 的已连接或网络异常连接会使用持久化凭据和游标恢复监听，不要求重新扫码；正在扫码授权的请求若被退出或请求取消打断，保留待授权状态供后续继续，不误记为永久错误。已经主动 Disconnect 的连接保持断开；真正失效的授权或已过期的二维码仍需重新授权。恢复依赖原数据库及 `connect.key`，部署时不能替换或删除它们。

重新连接会先断开旧 generation，再授权。必须保持原机器人及原发送者身份，否则进入错误状态；不会把旧来源历史转交给另一个平台账号。同一个平台机器人身份不能被另一条连接重复绑定。

接收、执行与投递分开持久化：

- Gateway SQLite：`connect_connections`、`connect_sources`、`connect_turns`、`connect_deliveries`、`connect_checks`；普通历史仍写现有 Conversation/Message。
- 微信一批消息逐条事务落库，只有整批处理完成后才持久化新游标。崩溃可以导致旧批次重读，依靠消息唯一键去重；不会先推进游标再处理消息。这是基础版的恢复方式，尚未实现设计稿里的整批原子事务与分布式租约。
- Python SQLite：`connect_runs` 按稳定 `run_id` 和不可变请求哈希受理，结果持久化。Gateway 重启仅恢复同一个 run 的查询；Python 重启时将未完成 run 标为 interrupted，不重新执行潜在副作用。完成结果仍可重新查询。
- 最终结果、助手消息、用量和 Outbox 在同一个 Gateway 事务中写入；重新执行收尾不会重复保存。
- 发送的稳定 ID 为 `turn_id:part`。明确限流拒绝可退避重试，发送超时、5xx 或发送后进程退出等无法确认结果的情况标为 `unknown`。不会自动重发不明结果；用户可在详情中确认重发，可能产生重复消息。
- `unknown` 不等于失败，平台是否已接收可能无法证明。微信的 `client_id` 不视为服务端 exactly-once 保证。

连接检测采用只读请求，12 秒超时；同 generation 的并发检测合并，5 秒内复用近期结果。没有做端到端收发验证的项保持「未验证」，不会伪装成全链路通过。

## 服务接口与扩展点

所有管理接口要求 `X-Account-Session`，不接受 URL 的 `user_id` 或 `account_session` 作为 Connect 授权凭据。前端沿用工作台统一请求封装与登录 session；服务端对每条资源验证归属。响应设置 `Cache-Control: no-store`，不包含凭据和回复 token。

```text
GET  /api/connect/v1/catalog
GET  /api/connect/v1/roles
GET  /api/connect/v1/connections
POST /api/connect/v1/connections
GET  /api/connect/v1/connections/:id
PUT  /api/connect/v1/connections/:id/role
PUT  /api/connect/v1/connections/:id/note
DELETE /api/connect/v1/connections/:id
POST /api/connect/v1/connections/:id/check
GET  /api/connect/v1/connections/:id/checks/:check_id
POST /api/connect/v1/connections/:id/disconnect
POST /api/connect/v1/connections/:id/reconnect
POST /api/connect/v1/connections/:id/deliveries/:delivery_id/retry
```

创建必须带 `request_id`，可带 `note` 和 `role_id`（省略为 `default`）；修改人设使用 `PUT /connections/:id/role`，body 为 `{ "role_id": "..." }`。修改备注使用 `PUT /connections/:id/note`，body 为 `{ "note": "..." }`，空字符串清空，遗漏/null 拒绝；删除使用 `DELETE /connections/:id`，同一账号重复删除返回成功，跨账号访问返回 404。人设读取有 10 秒超时。检测为有界同步响应；不是设计稿中的独立异步检测任务。内部 Python 端点为 `POST /agent/connect/runs` 与 `GET /agent/connect/runs/:id?user_id=...`，只供受信任 Gateway 调用，不应公网暴露 Python 服务。

新增消息平台实现 `gateway/internal/connect.Adapter`：能力描述、授权、只读检测、入站监听、最终投递。Core 的 `Accept` 统一负责身份、来源、幂等和排队；`Runner` 抽象运行边界。目录来自注册的适配器，前端不硬编码未实现平台。未来设备需要单独的能力授权、指令和结果协议，不能通过聊天 Adapter 的 Send 方法直接执行设备命令。

## 部署与验证

基础版部署要求：**一个 Gateway 进程 + 一个 Python Agent 进程**，使用各自持久化本地目录。当前没有分布式租约，不支持多个实例同时消费同一 SQLite。Python 与 Gateway 应处于受保护网络或本机。

- Gateway 自动在业务 DB 同目录创建 `connect.key`，32 字节 AES-GCM 密钥，文件权限 `0600`。凭据、游标和来源回复上下文分别加密并绑定记录 ID。备份或迁移须同时保存数据库和密钥；丢失密钥后旧凭据无法解密。
- Python 运行记录默认在 `data/connect_runs.db`；可通过 `AGENT_CONNECT_RUNS_PATH` 指定持久化文件。测试自动使用临时文件。
- 项目账号删除会先断开该账号连接，再删除对应 Connect 数据与 Python 运行记录；其他账号不受影响。
- 尚未提供自动历史清理、凭据轮换管理和多进程接管；不要把此版本作为分布式消息平台运行。

自动化测试覆盖来源/epoch/重投、跨账号拒绝、凭据过滤与配对、断开和重连的 generation、并发检测合并、运行串行与 200 个流式事件只产生最终交付、发送不明后的人工重发、结果与用量事务、平台协议样例、Python 重启/取消/数据删除、Web 目录和账号切换隔离。发布前执行 `./scripts/test.sh`；真实平台授权、私聊收发和较长任务延迟回复仍需账号验收。
