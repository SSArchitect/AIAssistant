# AIAssistant

Personal AI Assistant。

当前知识边界：Drive 保存问答、报告和资料；Memory 只保存会话摘要、用户偏好与长期事实。聊天回答可直接保存为 `/知识库` 下的 Markdown，并通过 Drive 搜索与读取复用。

工具层支持风险等级、读写类型、`auto / confirm / deny` 用户策略、单次运行调用上限、超时和 Trace 审计。永久删除 Drive/Todo 和公开分享 Drive 文件默认要求本轮明确指令；网页归档属于可撤销的普通写入，默认自动执行。
