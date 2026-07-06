const API_BASE = '';
const LANGUAGE_KEY = 'agent_assistant_language';
const MODE_STORAGE_KEY = 'super_chat_mode_ids';
const SUPER_CHAT_AGENT_ID = 'super_chat';
const DEEP_RESEARCH_MODE_ID = 'deep_research';
const DEEP_RESEARCH_AGENT_ID = 'deep_research_v1';
const CURRENT_CONVERSATION_STORAGE_KEY = 'agent_assistant_current_conversation_id';
const CURRENT_ROLE_ID_STORAGE_KEY = 'agent_assistant_current_role_id';
const CURRENT_PROJECT_STORAGE_KEY = 'agent_assistant_current_project_id';
const CHAT_DRIVE_PATH_STORAGE_KEY = 'agent_assistant_chat_drive_path_id';
const PROJECT_CHAT_CONVERSATION_STORAGE_KEY = 'agent_assistant_project_conversation_id';
const DRIVE_COLLAPSED_FOLDERS_STORAGE_KEY = 'agent_assistant_drive_collapsed_folder_ids';
const DRIVE_RECENT_PATHS_STORAGE_KEY = 'agent_assistant_drive_recent_path_ids';
const SIDEBAR_COLLAPSE_STORAGE_KEY = 'agent_assistant_sidebar_collapsed_sections';
const CURRENT_USER_ID_STORAGE_KEY = 'agent_assistant_current_user_id';
const ACCOUNT_SESSION_STORAGE_KEY = 'agent_assistant_account_session';
const GUEST_ACCOUNT_ID = '0';
const MOBILE_BREAKPOINT_QUERY = '(max-width: 720px)';
const PROJECT_MAX_DOCUMENT_CHARS = 180000;
const PROJECT_SEARCH_DEBOUNCE_MS = 260;
const DRIVE_PROMPT_CONTEXT_ITEM_LIMIT = 16;

const VIEW_COPY = {
    chat: ['views.chat.title', 'views.chat.subtitle'],
    pulse: ['views.pulse.title', 'views.pulse.subtitle'],
    projects: ['views.projects.title', 'views.projects.subtitle'],
    agents: ['views.agents.title', 'views.agents.subtitle'],
    tools: ['views.tools.title', 'views.tools.subtitle'],
    trace: ['views.trace.title', 'views.trace.subtitle'],
    developer: ['views.developer.title', 'views.developer.subtitle'],
};

const I18N = {
    zh: {
        app: { name: '阿安的工作台' },
        nav: { chat: 'Super Chat', pulse: 'Pulse', projects: '网盘', agents: 'Agents', tools: 'Tools', trace: 'Trace', runs: 'Runs', developer: 'Developer', memory: 'Memory' },
        sidebar: {
            navigation: '导航',
            pinned: '固定 Agent',
            projects: '网盘',
            recent: '最近会话',
            fullConfig: '完整配置',
            modelSelect: '模型选择',
            defaultModel: '默认模型',
            emptyConversations: '暂无会话',
            emptyPinned: '在 Agents 中固定常用功能',
            emptyProjects: '网盘为空',
        },
        topbar: { agent: 'Agent', role: '角色' },
        account: {
            label: '帐号',
            add: '新帐号',
            switch: '切换/注册帐号',
            loginTitle: '选择帐号',
            existing: '已有帐号',
            enter: '进入',
            newName: '新帐号',
            password: '密码',
            close: '关闭帐号面板',
            namePlaceholder: '输入帐号名',
            passwordPlaceholder: '输入密码',
            create: '创建并进入',
            guestEnter: '访客进入默认帐号',
            guestLoading: '正在进入访客帐号...',
            guestFailed: '访客进入失败：{message}',
            createFailed: '创建帐号失败：{message}',
            loginFailed: '登录失败：{message}',
            loadFailed: '加载帐号失败：{message}',
            emptyName: '请输入帐号名',
            emptyPassword: '请输入至少 4 位密码',
        },
        actions: {
            newChat: '新话题',
            toggleSidebar: '切换侧边栏',
            refresh: '刷新数据',
            send: '发送',
            back: '返回',
            save: '保存',
            cancel: '取消',
            cancelTask: '取消任务',
            usePath: '使用此路径',
            delete: '删除',
            createProject: '新建文件夹',
            uploadKnowledge: '上传文件',
            saveAsDocument: '保存到网盘',
            saveToDrive: '生成报告',
            chatWithPath: '去 Super Chat 问答',
            chatThisPath: '问答',
            previewDocument: '预览',
            createFromSelection: '清空选择',
            clearSelection: '清空选择',
            moveUp: '上移',
            moveDown: '下移',
            attach: '上传附件',
            removeAttachment: '移除附件',
            startTask: '开始任务',
            pin: '固定到左侧',
            unpin: '取消固定',
            test: 'Test',
            testing: 'Testing...',
            openConfig: '打开完整配置',
            generate: '生成图片',
            generating: '生成中...',
            regenerateAnswer: '重新回答',
            copyAnswer: '复制回答',
            copyMessage: '复制消息',
            copyCode: '复制代码',
            copied: '已复制',
            copyFailed: '复制失败',
            confirmDeleteConversation: '确定删除这个会话及其全部消息吗？',
            confirmDeleteTopic: '确定删除 Topic「{name}」吗？',
            confirmDeleteProject: '确定删除「{name}」及其中全部内容吗？',
            confirmDeleteDocument: '确定删除「{name}」吗？',
        },
        media: {
            preview: '图片预览',
            zoomIn: '放大',
            zoomOut: '缩小',
            rotate: '旋转',
            download: '下载图片',
            downloading: '正在下载...',
            downloaded: '已开始下载。',
            downloadFailed: '下载失败：图片地址已失效或当前服务无法保存这张图片。',
            close: '关闭',
        },
        views: {
            chat: { title: 'Super Chat', subtitle: '意图识别、Agent 调用与汇总回答入口' },
            pulse: { title: 'Pulse', subtitle: 'Topic 推荐、信息簇阅读与下一跳学习入口' },
            projects: { title: '网盘', subtitle: '每个帐号独立的文件树、上传下载与 Super Chat 上下文' },
            agents: { title: 'Agents', subtitle: 'Agent 功能入口、实现版本和能力状态' },
            tools: { title: 'Tools', subtitle: '内置工具、参数和调用状态' },
            runs: { title: 'Runs', subtitle: '执行轨迹、事件和调试信息' },
            trace: { title: 'Trace', subtitle: '层级事件、节点详情与调试定位' },
            developer: { title: 'Memory', subtitle: 'Memory 系统、持久化记录和最近一轮注入信息' },
        },
        projects: {
            emptyTitle: '网盘还没有内容',
            emptyDetail: '上传文件，或把 Super Chat 的输出保存进来。',
            createTitle: '文件夹名称',
            createPlaceholder: '例如：产品资料',
            sourceLibrary: '网盘内容',
            knowledgeMap: '当前文件夹',
            contextChat: '网盘问答',
            search: '检索网盘文件',
            documents: '{count} 个项目',
            links: '{count} 个文件夹',
            selected: '已选 {count}',
            noDocuments: '暂无文件',
            noSearchResults: '没有匹配文件',
            activeDocument: '当前文件',
            uploadFailed: '上传失败：{message}',
            uploadDone: '已上传 {count} 个文件',
            uploadBinaryNote: '已保存原文件，可下载；暂不参与正文问答。',
            askPlaceholder: '基于选中的网盘内容提问；未选择时会检索全网盘',
            ask: '提问',
            asking: '生成中...',
            expandMap: '整理知识',
            answer: '回答',
            answerEmpty: '等待网盘问答',
            saveDialogTitle: '保存到网盘',
            saveNameLabel: '文件名',
            pathLabel: '路径',
            pathDialogTitle: '选择路径',
            pathCurrent: '当前：{path}',
            pathJump: '路径',
            frequentPaths: '常用路径',
            allPaths: '全部路径',
            pathEmpty: '暂无文件夹',
            pathRequired: '请选择路径',
            saveNameRequired: '请输入文件名',
            saving: '保存中...',
            canceling: '正在取消...',
            saveTitle: '文件名',
            saveDone: '已保存到网盘',
            saveFailed: '保存失败：{message}',
            saveCancelled: '已取消生成报告。',
            saveTaskStarted: '正在生成并保存「{title}」',
            previewLoading: '正在加载文档...',
            previewFailed: '加载文档失败：{message}',
            previewBinary: '此文件已保存到网盘，可下载原文件；当前格式暂不提取为问答正文。',
            createSelectionTitle: '新文件夹名称',
            createSelectionDone: '已处理选择',
            createSelectionFailed: '创建失败：{message}',
            loadFailed: '加载网盘失败：{message}',
            deleteFailed: '删除失败：{message}',
            moveDone: '已移动 {count} 个项目',
            moveFailed: '移动失败：{message}',
            contextSources: '上下文来源',
            generatedDocDefaultTitle: 'Super Chat 报告.md',
            rootName: '我的网盘',
            chatPathChip: '网盘路径',
            chatPathTitle: 'Super Chat 网盘路径：{path}',
            folderContents: '{folders} 个文件夹 · {files} 个文件',
            download: '下载',
            expandPrompt: '请基于当前网盘上下文，帮我整理可以沉淀的新知识：\n1. 提炼关键结论。\n2. 标出缺失或薄弱的资料。\n3. 生成一篇可以直接保存到网盘的新知识文档草稿。',
            type: {
                folder: '文件夹',
                file: '文件',
                source: '资料',
                note: '笔记',
                generated: '生成',
                summary: '总结',
            },
        },
        aigc: {
            formTitle: 'AI 生图',
            formSubtitle: 'MiniMax image-01 文生图',
            prompt: '提示词',
            promptPlaceholder: '描述你想生成的画面、风格、主体、构图和细节',
            aspectRatio: '比例',
            count: '数量',
            format: '格式',
            model: '模型',
            seed: 'Seed',
            promptOptimizer: '提示词优化',
            resultsTitle: '生成结果',
            resultsSubtitle: '结果会保留在当前浏览器会话中',
            emptyTitle: '还没有图片',
            emptyDetail: '输入提示词后开始生成。',
            ready: '准备生成',
            generated: '已生成 {count} 张图片',
            noImages: 'MiniMax 返回成功，但没有图片数据。',
            openImage: '打开图片',
            download: '下载',
            resultTitle: '图片 {index}',
            urlExpires: 'URL 通常会在 24 小时后失效。',
        },
        chat: {
            placeholder: '输入任务，Enter 发送；Shift/Cmd + Enter 换行',
            currentConversation: '当前会话',
            loadConversationFailed: '加载会话失败：{message}',
            createConversationFailed: '创建会话失败：{message}',
            resumePending: 'AI 仍在生成，完成后会自动恢复到当前会话',
            citations: '引用来源',
            followUpAria: '推荐追问',
        },
        chatNav: {
            previousUser: '上一条用户消息',
            historyOpen: '展开对话历史',
            historyClose: '收起对话历史',
            historyTitle: '对话历史',
            count: '{count} 条用户消息',
            empty: '暂无用户消息',
            emptyQuery: '空消息',
            jumpToQuery: '跳转到第 {index} 条用户消息',
            current: '当前位置',
        },
        roleMemory: {
            title: '角色记忆',
            defaultRole: '默认助手',
            empty: '暂无角色记忆',
            placeholder: '写下这个角色需要长期遵守的语气、偏好或工作方式',
            save: '保存',
            saved: '已保存',
            loadFailed: '加载角色记忆失败：{message}',
            saveFailed: '保存失败：{message}',
            deleteFailed: '删除失败：{message}',
            manual: '手动',
            ai: '对话',
        },
        developer: {
            refresh: '刷新 Memory',
            refreshing: '刷新中...',
            storageTitle: '持久化边界',
            storageDetail: '长期记忆和角色记忆由 RoleMemoryStore 持久化，默认写入 data/agent_memory.json；会话记忆是 ConversationMemory 的短期窗口/摘要。',
            account: '帐号',
            currentRole: '当前角色',
            roles: '角色域',
            records: '记录',
            longTerm: '长期记忆',
            rolePersona: '角色记忆',
            shortTerm: '短期记忆',
            shortTermDetail: '按 user_id + conversation_id 隔离，作为当前会话上下文窗口和摘要，不在本页的长期存量列表中展示。',
            injectionOrder: '注入顺序',
            injectionOrderDetail: '系统级配置 -> 记忆系统（长期记忆、角色记忆、短期摘要）-> 本轮模式与上下文块。',
            inventoryTitle: '当前持久化 Memory',
            lastRunTitle: '最近一轮 Memory 调试',
            contextTitle: '本轮注入',
            updatesTitle: '本轮新增',
            empty: '暂无记录',
            neverLoaded: '等待加载',
            loadFailed: '加载 Memory 失败：{message}',
            partialFailed: '部分角色读取失败：{message}',
            noLastRun: '还没有捕获到本轮 memory_context 或 memory_updates。',
            kindLongTerm: 'long_term · 长期',
            kindRole: 'role · 角色',
            kindPersona: 'persona · 人设兼容',
            sourceManual: '手动',
            sourceChat: '对话',
            sourceUnknown: '未知来源',
            confidence: '置信度',
            metadata: 'Metadata',
            currentScope: '当前角色域',
            allScopes: '全部角色域',
            persistentYes: '持久化',
            persistentNo: '短期',
            agentScope: 'Agent',
            updatedAt: '更新',
            createdAt: '创建',
            lastUsed: '上次注入',
            status: '状态',
            reviewState: 'Review',
            scope: 'Scope',
            version: '版本',
            sourceTrace: '来源 Trace',
            edit: '编辑',
            archive: '归档',
            activate: '激活',
            delete: '删除',
            editPrompt: '编辑记忆内容',
            deleteConfirm: '确定删除这条记忆？这个操作会从持久化存储移除它。',
            updateFailed: '更新失败：{message}',
            deleteFailed: '删除失败：{message}',
            statusActive: 'active · 注入',
            statusPending: 'pending_review · 待审',
            statusArchived: 'archived · 不注入',
            sourceHook: '自动抽取',
            searchPlaceholder: '搜索内容、角色、标签或 ID',
            kindFilter: '类型',
            statusFilter: '状态',
            sortLabel: '排序',
            allKinds: '全部类型',
            allStatuses: '全部状态',
            filterOther: '其他类型',
            sortUpdatedDesc: '最近更新',
            sortUpdatedAsc: '最早更新',
            sortLastUsedDesc: '最近注入',
            sortConfidenceDesc: '置信度优先',
            showingCount: '显示 {visible} / {total}',
            resetFilters: '重置',
            selectedCount: '已选 {count}',
            selectVisible: '选中可见长期',
            clearSelection: '清空选择',
            deleteSelected: '删除选中',
            selectMemory: '选择这条长期记忆',
            deleteSelectedConfirm: '确定删除选中的 {count} 条长期记忆？这个操作会从持久化存储移除它们。',
            deleteSelectedFailed: '{count} 条删除失败：{message}',
            expandAll: '展开当前',
            collapseAll: '收起全部',
            details: '详情',
            expand: '展开',
            collapse: '收起',
            noMatches: '没有符合筛选的记录',
            fullContent: '完整内容',
        },
        pulse: {
            topicsTitle: 'Topic 订阅',
            topicsSubtitle: '选择一个方向，生成可持续阅读的信息簇',
            topicName: 'Topic',
            topicPlaceholder: '例如：AI 应用开发',
            keywords: '关键词',
            keywordsPlaceholder: 'Agent, RAG, 多模态',
            subscribe: '订阅',
            subscribing: '订阅中...',
            refresh: '刷新 Pulse',
            todayTitle: '今日 Pulse',
            generatedAt: '已预计算：{time}',
            neverGenerated: '等待生成',
            refreshing: '正在生成新的 Pulse...',
            loading: '正在加载 Pulse...',
            emptyTitle: '还没有信息簇',
            emptyDetail: '添加一个 Topic 或刷新 Pulse。',
            emptyComputingTitle: 'Pulse 还在计算中',
            emptyComputingDetail: '先不展示失败兜底卡；拿到可核验来源后会自动更新。',
            emptyUnavailableTitle: '暂无有效信息簇',
            emptyUnavailableDetail: '本次搜索或总结没有拿到可核验来源，先隐藏推荐卡。',
            emptyTopics: '还没有订阅 Topic',
            emptyModule: '这个模块暂时没有推荐',
            emptyFiltered: '这个 Topic 暂时没有信息簇',
            emptySuggestedTopics: '暂无可推荐 Topic',
            subscribed: '订阅',
            suggestedTopics: '推荐 Topic',
            topicFilterAll: '全部信息簇',
            addSuggestedTopic: '订阅',
            hot: '热度',
            heat: '热度 {score}',
            featureScore: '排序 {score}',
            expand: '展开',
            collapse: '收起',
            ask: '继续聊',
            openPost: '打开帖子',
            closePost: '关闭帖子',
            like: 'Like',
            liked: 'Liked',
            upvote: '赞',
            downvote: '踩',
            reason: '推荐理由',
            signals: '依据线索',
            quickContext: '背景',
            keyPoints: '关键点',
            newsSources: '新闻来源',
            suggestedQuestions: '可以追问',
            relatedClusters: '相关信息簇',
            openCluster: '打开',
            sourceTopic: '关注 Topic',
            sourceMemory: '近日 Memory',
            sourceHot: '可能兴趣',
            modules: {
                topicHot: ['关注 Topic 热门话题推荐', '来自你主动订阅的主题，优先给出今天值得展开的角度。'],
                memory: ['基于近日 Memory 推荐', '从最近本地对话里提取信号，帮你延续未完成的思路。'],
                interestHot: ['可能感兴趣的近日热门话题推荐', '把订阅和 memory 信号叠加到高关注候选池，展示可解释的兴趣推荐。'],
            },
            loadFailed: '加载 Pulse 失败：{message}',
            createFailed: '订阅失败：{message}',
            deleteFailed: '删除失败：{message}',
            topicRequired: '请先填写 Topic',
        },
        attachments: {
            reading: '解析中',
            ready: '已解析',
            unsupported: '暂不支持解析此格式',
            tooLarge: '文件超过 {size} 限制',
            empty: '没有可读取文本',
            readFailed: '解析失败：{message}',
            mediaReady: '已添加',
            defaultPrompt: '请阅读附件内容，给出要点总结和下一步建议。',
            imageDefaultPrompt: '请根据本轮描述和参考素材生成图片。',
            weightLossDefaultPrompt: '请估算这餐热量并记录到减脂数据库。',
            contextTitle: '附件上下文',
            contextIntro: '用户在本轮消息上传了附件。请把这些内容作为当前问题的上下文；如果答案使用了附件内容，请明确指出来自哪个附件。',
            truncated: '内容已截断',
        },
        health: { checking: '检查中', online: 'Agent 在线', unavailable: 'Agent 不可用' },
        modes: {
            toggle: '功能',
            title: 'Super Chat 功能',
            imageTitle: 'AI 生图功能',
            active: '已启用：{names}',
            items: {
                deep_research: ['深度研究', '先确认计划，再多轮检索出报告'],
                research: ['研究', '需要资料时先整理和检索来源'],
                plan: ['规划', '先规划执行步骤再处理'],
                image_generation: ['AI 生图', '强制交给 AI 生图 Agent 执行'],
                image_prompt_refine: ['专业修饰', '先审查并补全画面提示词，再生图'],
            },
        },
        agents: {
            emptyTitle: '还没有可展示的 Agent',
            emptyDetail: '确认 Python Agent Service 已启动。',
            available: '可用',
            unavailable: '未接入',
            experimental: '实验',
            pinned: '已固定',
            fit: '适合',
            implementation: '实现',
            entry: '入口',
            canStart: '可开始任务',
            waiting: '等待接入',
            capabilityMissing: '能力待补充',
            dependencyHint: '能力还在规划或依赖未安装',
            groups: {
                entry: ['入口 Agent', '日常任务、意图识别和后续总控入口'],
                creative: ['内容生成', 'AIGC、生图、长文创作等专业工作区'],
                research: ['研究 Agent', '深度研究、资料整理与实验性框架'],
                general: ['通用能力', '基础助手和工具调用能力'],
            },
            type: { entry: '入口', creative: '创作', research: '研究', general: '通用' },
            useCase: {
                super: '不知道该找谁时，从这里开始',
                image: '对话生图、参考素材和专业提示词修饰',
                weightLoss: '食物图片估热量、饮食记录和热量缺口统计',
                research: '长任务研究、资料整理',
                default: '日常问答、计算和工具调用',
            },
            implementationSelf: '自研 self loop',
        },
        tools: {
            unavailableTitle: 'Tools 接口不可用',
            emptyTitle: '还没有注册工具',
            emptyDetail: 'SkillRegistry 当前没有返回内置工具。',
            unnamed: 'Unnamed Tool',
            noParams: '无参数',
            title: '工具管理',
            detail: '按来源查看、筛选和关闭当前帐号可用的工具。',
            search: '搜索工具、来源或标签',
            all: '全部',
            enabled: '启用',
            disabled: '关闭',
            total: '{enabled} / {total} 可用',
            baseDisabled: '系统关闭',
            userDisabled: '当前帐号关闭',
            userEnabled: '当前帐号启用',
            sourceGroup: '{source} · {count}',
            parameters: '{count} 个参数',
            required: '必填',
            optional: '可选',
            noMatches: '没有符合筛选的工具',
            mcpTitle: 'MCP 配置',
            mcpDetail: '保存当前帐号自己的 MCP server JSON；通用 MCP discovery 接入后会从这里读取。',
            mcpEnabled: '启用 MCP',
            mcpServers: 'MCP Servers JSON',
            mcpPlaceholder: '[{"name":"filesystem","command":"npx","args":["..."]}]',
            saveMcp: '保存 MCP',
            saving: '保存中...',
            saved: '已保存',
            saveFailed: '保存失败：{message}',
            invalidJson: '请输入合法 JSON',
        },
        runs: {
            unavailableTitle: 'Trace 接口不可用',
            emptyTitle: '暂无运行记录',
            emptyDetail: '完成一次 Chat 后会生成 run 和事件。',
            noEvents: '无事件',
            noQuery: '无 query',
            scenario: '功能场景',
            runId: 'Run',
        },
        trace: {
            open: '打开 Trace',
            backToChat: '回到对话',
            copyTraceId: '复制 Trace ID',
            events: '{count} 个事件',
            waiting: '等待 run id',
            hierarchy: '层级',
            details: '节点详情',
            runOverview: 'Run 概览',
            stage: '阶段',
            plan: '执行计划',
            planStep: '计划步骤',
            modelCall: '模型调用',
            toolCall: '工具调用',
            expand: '展开',
            collapse: '折叠',
            event: '事件',
            childNodes: '子节点',
            timeline: '事件时间线',
            payload: 'Payload',
            input: 'Input',
            output: 'Output',
            result: 'Result',
            error: 'Error',
            emptyPayload: '无 payload',
            noSelection: '选择左侧节点查看详情',
        },
        settings: {
            configured: '已配置',
            missing: '缺失',
            verified: '已验证',
            pending: '待检测',
            error: '检测失败',
            default: '默认',
            noModels: '未配置模型列表',
            serviceTitle: 'Python Agent Service',
            serviceChecking: '检查中',
            modelKeys: '模型与密钥',
            noDefaultProvider: '未设置默认模型服务',
            connected: '已连接',
            failed: '失败',
        },
        welcome: {
            prompt: '把问题或任务发给我就好。',
            imageCreate: '直接生图',
            imagePolish: '专业修饰生图',
            imageReference: '参考素材生图',
        },
        capabilities: {
            chat: '对话',
            tool_use: '工具调用',
            intent_routing_planned: '意图识别规划',
            summary_planned: '汇总规划',
            tracing: 'Trace',
            conversation_memory: '会话记忆',
            state_graph: '状态图',
            checkpoint_ready: 'Checkpoint',
            ab_test: 'A/B 对比',
            deep_research: '深度研究',
            research_planning: '研究计划',
            multi_round_search: '多轮检索',
            source_synthesis: '来源综合',
            report_generation: '报告生成',
            aigc: 'AIGC',
            image_generation: '生图',
            image_generation_planned: '生图规划',
            prompt_refine: '提示词修饰',
            prompt_refine_planned: '提示词优化',
            conversation_image_generation: '对话生图',
            multimodal_input: '多模态输入',
            food_image_calorie_estimation: '食物图估热量',
            nutrition_log: '饮食记录',
            calorie_deficit_tracking: '热量缺口',
            database_persistence: '数据库持久化',
        },
        errors: { rateLimit: '请求频率超限', error: '错误', requestFailed: '请求失败', streamFailed: '流式输出失败' },
    },
    en: {
        app: { name: '阿安的工作台' },
        nav: { chat: 'Super Chat', pulse: 'Pulse', projects: 'Drive', agents: 'Agents', tools: 'Tools', trace: 'Trace', runs: 'Runs', developer: 'Developer', memory: 'Memory' },
        sidebar: {
            navigation: 'Navigation',
            pinned: 'Pinned Agents',
            projects: 'Drive',
            recent: 'Recent Chats',
            fullConfig: 'Full Settings',
            modelSelect: 'Model selection',
            defaultModel: 'Default Model',
            emptyConversations: 'No conversations',
            emptyPinned: 'Pin frequent agents from Agents',
            emptyProjects: 'Empty drive',
        },
        topbar: { agent: 'Agent', role: 'Role' },
        account: {
            label: 'Account',
            add: 'New account',
            switch: 'Switch or create account',
            loginTitle: 'Choose Account',
            existing: 'Existing account',
            enter: 'Enter',
            newName: 'New account',
            password: 'Password',
            close: 'Close account panel',
            namePlaceholder: 'Account name',
            passwordPlaceholder: 'Password',
            create: 'Create and enter',
            guestEnter: 'Enter as guest',
            guestLoading: 'Entering as guest...',
            guestFailed: 'Failed to enter as guest: {message}',
            createFailed: 'Failed to create account: {message}',
            loginFailed: 'Failed to log in: {message}',
            loadFailed: 'Failed to load accounts: {message}',
            emptyName: 'Enter an account name',
            emptyPassword: 'Enter a password with at least 4 characters',
        },
        actions: {
            newChat: 'New Topic',
            toggleSidebar: 'Toggle sidebar',
            refresh: 'Refresh data',
            send: 'Send',
            back: 'Back',
            save: 'Save',
            cancel: 'Cancel',
            cancelTask: 'Cancel task',
            usePath: 'Use Path',
            delete: 'Delete',
            createProject: 'New Folder',
            uploadKnowledge: 'Upload Files',
            saveAsDocument: 'Save to Drive',
            saveToDrive: 'Generate Report',
            chatWithPath: 'Ask in Super Chat',
            chatThisPath: 'Ask',
            previewDocument: 'Preview',
            createFromSelection: 'New From Selection',
            clearSelection: 'Clear selection',
            moveUp: 'Move up',
            moveDown: 'Move down',
            attach: 'Upload attachment',
            removeAttachment: 'Remove attachment',
            startTask: 'Start Task',
            pin: 'Pin to sidebar',
            unpin: 'Unpin',
            test: 'Test',
            testing: 'Testing...',
            openConfig: 'Open Full Settings',
            generate: 'Generate Image',
            generating: 'Generating...',
            regenerateAnswer: 'Regenerate Answer',
            copyAnswer: 'Copy Answer',
            copyMessage: 'Copy Message',
            copyCode: 'Copy Code',
            copied: 'Copied',
            copyFailed: 'Copy Failed',
            confirmDeleteConversation: 'Delete this conversation and all of its messages?',
            confirmDeleteTopic: 'Delete topic "{name}"?',
            confirmDeleteProject: 'Delete "{name}" and all nested contents?',
            confirmDeleteDocument: 'Delete "{name}"?',
        },
        media: {
            preview: 'Image Preview',
            zoomIn: 'Zoom In',
            zoomOut: 'Zoom Out',
            rotate: 'Rotate',
            download: 'Download Image',
            downloading: 'Downloading...',
            downloaded: 'Download started.',
            downloadFailed: 'Download failed: the image URL expired or this service could not save it.',
            close: 'Close',
        },
        views: {
            chat: { title: 'Super Chat', subtitle: 'Intent routing, agent calls, and final answers' },
            pulse: { title: 'Pulse', subtitle: 'Topic seeds, information clusters, and next-step reading' },
            projects: { title: 'Drive', subtitle: 'Per-account file tree, uploads, downloads, and Super Chat context' },
            agents: { title: 'Agents', subtitle: 'Agent entry points, runtimes, and capability status' },
            tools: { title: 'Tools', subtitle: 'Built-in tools, parameters, and execution status' },
            runs: { title: 'Runs', subtitle: 'Execution traces, events, and debugging details' },
            trace: { title: 'Trace', subtitle: 'Hierarchical events, node details, and debugging context' },
            developer: { title: 'Memory', subtitle: 'Memory system, persisted records, and latest run injection' },
        },
        projects: {
            emptyTitle: 'Your drive is empty',
            emptyDetail: 'Upload files or save Super Chat outputs here.',
            createTitle: 'Folder name',
            createPlaceholder: 'e.g. Product notes',
            sourceLibrary: 'Drive Contents',
            knowledgeMap: 'Current Folder',
            contextChat: 'Drive Q&A',
            search: 'Search drive files',
            documents: '{count} items',
            links: '{count} folders',
            selected: '{count} selected',
            noDocuments: 'No files',
            noSearchResults: 'No matching files',
            activeDocument: 'Active file',
            uploadFailed: 'Upload failed: {message}',
            uploadDone: 'Uploaded {count} files',
            uploadBinaryNote: 'Original file saved and downloadable; not used as text context yet.',
            askPlaceholder: 'Ask with selected drive context; if nothing is selected, the drive will be searched',
            ask: 'Ask',
            asking: 'Generating...',
            expandMap: 'Organize',
            answer: 'Answer',
            answerEmpty: 'Waiting for Drive Q&A',
            saveDialogTitle: 'Save to Drive',
            saveNameLabel: 'File name',
            pathLabel: 'Path',
            pathDialogTitle: 'Choose Path',
            pathCurrent: 'Current: {path}',
            pathJump: 'Path',
            frequentPaths: 'Frequent Paths',
            allPaths: 'All Paths',
            pathEmpty: 'No folders',
            pathRequired: 'Choose a path',
            saveNameRequired: 'Enter a file name',
            saving: 'Saving...',
            canceling: 'Canceling...',
            saveTitle: 'File name',
            saveDone: 'Saved to Drive',
            saveFailed: 'Save failed: {message}',
            saveCancelled: 'Report generation was canceled.',
            saveTaskStarted: 'Generating and saving "{title}"',
            previewLoading: 'Loading document...',
            previewFailed: 'Failed to load document: {message}',
            previewBinary: 'This file is saved in Drive and can be downloaded; this format is not extracted as text context yet.',
            createSelectionTitle: 'New folder name',
            createSelectionDone: 'Selection handled',
            createSelectionFailed: 'Create failed: {message}',
            loadFailed: 'Failed to load Drive: {message}',
            deleteFailed: 'Delete failed: {message}',
            moveDone: 'Moved {count} items',
            moveFailed: 'Move failed: {message}',
            contextSources: 'Context sources',
            generatedDocDefaultTitle: 'Super Chat Report.md',
            rootName: 'My Drive',
            chatPathChip: 'Drive path',
            chatPathTitle: 'Super Chat drive path: {path}',
            folderContents: '{folders} folders · {files} files',
            download: 'Download',
            expandPrompt: 'Use the current drive context to organize durable knowledge:\n1. Extract the key conclusions.\n2. Identify missing or weak source material.\n3. Draft a new knowledge document that can be saved directly.',
            type: {
                folder: 'Folder',
                file: 'File',
                source: 'Source',
                note: 'Note',
                generated: 'Generated',
                summary: 'Summary',
            },
        },
        aigc: {
            formTitle: 'AI Image',
            formSubtitle: 'MiniMax image-01 text-to-image',
            prompt: 'Prompt',
            promptPlaceholder: 'Describe the scene, style, subject, composition, and details',
            aspectRatio: 'Aspect Ratio',
            count: 'Count',
            format: 'Format',
            model: 'Model',
            seed: 'Seed',
            promptOptimizer: 'Prompt Optimizer',
            resultsTitle: 'Results',
            resultsSubtitle: 'Results stay in this browser session',
            emptyTitle: 'No images yet',
            emptyDetail: 'Enter a prompt to generate the first image.',
            ready: 'Ready',
            generated: 'Generated {count} image(s)',
            noImages: 'MiniMax succeeded but returned no image data.',
            openImage: 'Open Image',
            download: 'Download',
            resultTitle: 'Image {index}',
            urlExpires: 'URL results usually expire after 24 hours.',
        },
        chat: {
            placeholder: 'Type a task. Enter to send, Shift/Cmd+Enter for newline',
            currentConversation: 'Current conversation',
            loadConversationFailed: 'Failed to load conversation: {message}',
            createConversationFailed: 'Failed to create conversation: {message}',
            resumePending: 'AI is still generating. The answer will reappear here when it finishes.',
            citations: 'Sources',
            followUpAria: 'Suggested follow-up questions',
        },
        chatNav: {
            previousUser: 'Previous user message',
            historyOpen: 'Open conversation history',
            historyClose: 'Close conversation history',
            historyTitle: 'Conversation History',
            count: '{count} user messages',
            empty: 'No user messages yet',
            emptyQuery: 'Empty message',
            jumpToQuery: 'Jump to user message {index}',
            current: 'Current position',
        },
        roleMemory: {
            title: 'Role Memory',
            defaultRole: 'Default Assistant',
            empty: 'No role memories yet',
            placeholder: 'Write the tone, preference, or working style this role should keep',
            save: 'Save',
            saved: 'Saved',
            loadFailed: 'Failed to load role memory: {message}',
            saveFailed: 'Failed to save: {message}',
            deleteFailed: 'Failed to delete: {message}',
            manual: 'Manual',
            ai: 'Chat',
        },
        developer: {
            refresh: 'Refresh Memory',
            refreshing: 'Refreshing...',
            storageTitle: 'Persistence Boundary',
            storageDetail: 'Long-term and role memories are persisted by RoleMemoryStore, defaulting to data/agent_memory.json. Conversation memory is a short-term window / summary in ConversationMemory.',
            account: 'Account',
            currentRole: 'Current Role',
            roles: 'Role scopes',
            records: 'Records',
            longTerm: 'Long-term Memory',
            rolePersona: 'Role Memory',
            shortTerm: 'Short-term Memory',
            shortTermDetail: 'Scoped by user_id + conversation_id as the active conversation window and summary; it is not listed in this persisted inventory.',
            injectionOrder: 'Injection Order',
            injectionOrderDetail: 'System config -> memory system (long-term, role memory, short-term summary) -> turn modes and context blocks.',
            inventoryTitle: 'Current Persisted Memory',
            lastRunTitle: 'Latest Run Memory Debug',
            contextTitle: 'Injected This Turn',
            updatesTitle: 'Stored This Turn',
            empty: 'No records',
            neverLoaded: 'Waiting to load',
            loadFailed: 'Failed to load memory: {message}',
            partialFailed: 'Some role scopes failed: {message}',
            noLastRun: 'No memory_context or memory_updates captured yet.',
            kindLongTerm: 'long_term · long-term',
            kindRole: 'role · role',
            kindPersona: 'persona · persona compat',
            sourceManual: 'Manual',
            sourceChat: 'Chat',
            sourceUnknown: 'Unknown source',
            confidence: 'Confidence',
            metadata: 'Metadata',
            currentScope: 'Current role scope',
            allScopes: 'All role scopes',
            persistentYes: 'Persisted',
            persistentNo: 'Short-term',
            agentScope: 'Agent',
            updatedAt: 'Updated',
            createdAt: 'Created',
            lastUsed: 'Last injected',
            status: 'Status',
            reviewState: 'Review',
            scope: 'Scope',
            version: 'Version',
            sourceTrace: 'Source Trace',
            edit: 'Edit',
            archive: 'Archive',
            activate: 'Activate',
            delete: 'Delete',
            editPrompt: 'Edit memory content',
            deleteConfirm: 'Delete this memory from persistent storage?',
            updateFailed: 'Update failed: {message}',
            deleteFailed: 'Delete failed: {message}',
            statusActive: 'active · injected',
            statusPending: 'pending_review · review',
            statusArchived: 'archived · not injected',
            sourceHook: 'Auto extracted',
            searchPlaceholder: 'Search content, role, tags, or ID',
            kindFilter: 'Type',
            statusFilter: 'Status',
            sortLabel: 'Sort',
            allKinds: 'All types',
            allStatuses: 'All statuses',
            filterOther: 'Other types',
            sortUpdatedDesc: 'Recently updated',
            sortUpdatedAsc: 'Oldest updated',
            sortLastUsedDesc: 'Recently injected',
            sortConfidenceDesc: 'Confidence first',
            showingCount: 'Showing {visible} / {total}',
            resetFilters: 'Reset',
            selectedCount: '{count} selected',
            selectVisible: 'Select visible long-term',
            clearSelection: 'Clear selection',
            deleteSelected: 'Delete selected',
            selectMemory: 'Select this long-term memory',
            deleteSelectedConfirm: 'Delete {count} selected long-term memories from persistent storage?',
            deleteSelectedFailed: '{count} deletions failed: {message}',
            expandAll: 'Expand current',
            collapseAll: 'Collapse all',
            details: 'Details',
            expand: 'Expand',
            collapse: 'Collapse',
            noMatches: 'No records match the filters',
            fullContent: 'Full content',
        },
        pulse: {
            topicsTitle: 'Topic Subscriptions',
            topicsSubtitle: 'Pick a direction and generate ongoing information clusters',
            topicName: 'Topic',
            topicPlaceholder: 'Example: AI app development',
            keywords: 'Keywords',
            keywordsPlaceholder: 'Agents, RAG, multimodal',
            subscribe: 'Subscribe',
            subscribing: 'Subscribing...',
            refresh: 'Refresh Pulse',
            todayTitle: "Today's Pulse",
            generatedAt: 'Precomputed: {time}',
            neverGenerated: 'Waiting to generate',
            refreshing: 'Generating a fresh Pulse...',
            loading: 'Loading Pulse...',
            emptyTitle: 'No clusters yet',
            emptyDetail: 'Add a topic or refresh Pulse.',
            emptyComputingTitle: 'Pulse is still computing',
            emptyComputingDetail: 'Failed fallback cards are hidden; clusters will appear after verifiable sources are available.',
            emptyUnavailableTitle: 'No valid clusters',
            emptyUnavailableDetail: 'This run did not find verifiable sources, so recommendation cards are hidden for now.',
            emptyTopics: 'No topic subscriptions yet',
            emptyModule: 'No recommendations in this module yet',
            emptyFiltered: 'No clusters for this topic yet',
            emptySuggestedTopics: 'No suggested topics',
            subscribed: 'Topic',
            suggestedTopics: 'Suggested Topics',
            topicFilterAll: 'All clusters',
            addSuggestedTopic: 'Subscribe',
            hot: 'Hot',
            heat: 'Heat {score}',
            featureScore: 'Rank {score}',
            expand: 'Expand',
            collapse: 'Collapse',
            ask: 'Ask',
            openPost: 'Open post',
            closePost: 'Close post',
            like: 'Like',
            liked: 'Liked',
            upvote: 'Up',
            downvote: 'Down',
            reason: 'Why this',
            signals: 'Signals',
            quickContext: 'Context',
            keyPoints: 'Key Points',
            newsSources: 'News Sources',
            suggestedQuestions: 'Suggested Questions',
            relatedClusters: 'Related Clusters',
            openCluster: 'Open',
            sourceTopic: 'Followed Topic',
            sourceMemory: 'Recent Memory',
            sourceHot: 'Likely Interest',
            modules: {
                topicHot: ['Hot Topics From Followed Topics', 'Recommendations generated from topics you explicitly follow.'],
                memory: ['Recommended From Recent Memory', 'Signals extracted from recent local conversations to continue unfinished threads.'],
                interestHot: ['Likely Interesting Recent Hot Topics', 'A transparent match between your topics, memory signals, and a hot-topic candidate pool.'],
            },
            loadFailed: 'Failed to load Pulse: {message}',
            createFailed: 'Failed to subscribe: {message}',
            deleteFailed: 'Failed to delete: {message}',
            topicRequired: 'Enter a topic first',
        },
        attachments: {
            reading: 'Parsing',
            ready: 'Parsed',
            unsupported: 'This format is not supported yet',
            tooLarge: 'File exceeds the {size} limit',
            empty: 'No readable text found',
            readFailed: 'Parse failed: {message}',
            mediaReady: 'Added',
            defaultPrompt: 'Please read the attachment content, then summarize the key points and next steps.',
            imageDefaultPrompt: 'Generate an image from this turn and the uploaded references.',
            weightLossDefaultPrompt: 'Estimate this meal calories and save it to the weight-loss database.',
            contextTitle: 'Attachment Context',
            contextIntro: 'The user uploaded attachments for this turn. Treat the following content as context for the current question; if you use it, identify which attachment it came from.',
            truncated: 'Content truncated',
        },
        health: { checking: 'Checking', online: 'Agent online', unavailable: 'Agent unavailable' },
        modes: {
            toggle: 'Modes',
            title: 'Super Chat Modes',
            imageTitle: 'AI Image Modes',
            active: 'Enabled: {names}',
            items: {
                deep_research: ['Deep Research', 'Confirm a plan, then search and report'],
                research: ['Research', 'Organize and retrieve sources when needed'],
                plan: ['Plan', 'Plan execution steps before handling'],
                image_generation: ['AI Image', 'Force this turn through the AI image agent'],
                image_prompt_refine: ['Prompt Polish', 'Review and enrich the visual prompt before generation'],
            },
        },
        agents: {
            emptyTitle: 'No agents to show yet',
            emptyDetail: 'Make sure the Python Agent Service is running.',
            available: 'Available',
            unavailable: 'Not wired',
            experimental: 'Experimental',
            pinned: 'Pinned',
            fit: 'Best for',
            implementation: 'Implementation',
            entry: 'Entry',
            canStart: 'Can start tasks',
            waiting: 'Waiting',
            capabilityMissing: 'Capabilities pending',
            dependencyHint: 'This capability is planned or has missing dependencies',
            groups: {
                entry: ['Entry Agents', 'Daily tasks, intent routing, and orchestration'],
                creative: ['Content Generation', 'AIGC, image prompts, and long-form creation'],
                research: ['Research Agents', 'Deep research, source organization, and runtime trials'],
                general: ['General Capability', 'Basic assistant and tool use'],
            },
            type: { entry: 'Entry', creative: 'Creative', research: 'Research', general: 'General' },
            useCase: {
                super: 'Start here when you are not sure which agent to use',
                image: 'Conversational image generation with references and prompt polish',
                weightLoss: 'Food-photo calorie estimates, meal logs, and deficit tracking',
                research: 'Long research and source organization',
                default: 'Daily chat, calculation, and tool use',
            },
            implementationSelf: 'Native self loop',
        },
        tools: {
            unavailableTitle: 'Tools API unavailable',
            emptyTitle: 'No tools registered',
            emptyDetail: 'SkillRegistry did not return built-in tools.',
            unnamed: 'Unnamed Tool',
            noParams: 'No parameters',
            title: 'Tool Management',
            detail: 'Browse, filter, and disable tools for the current account.',
            search: 'Search tools, sources, or tags',
            all: 'All',
            enabled: 'Enabled',
            disabled: 'Disabled',
            total: '{enabled} / {total} available',
            baseDisabled: 'System off',
            userDisabled: 'Off for this account',
            userEnabled: 'On for this account',
            sourceGroup: '{source} · {count}',
            parameters: '{count} parameters',
            required: 'Required',
            optional: 'Optional',
            noMatches: 'No tools match this filter',
            mcpTitle: 'MCP Config',
            mcpDetail: 'Save MCP server JSON for this account; generic MCP discovery can read it later.',
            mcpEnabled: 'Enable MCP',
            mcpServers: 'MCP Servers JSON',
            mcpPlaceholder: '[{"name":"filesystem","command":"npx","args":["..."]}]',
            saveMcp: 'Save MCP',
            saving: 'Saving...',
            saved: 'Saved',
            saveFailed: 'Save failed: {message}',
            invalidJson: 'Enter valid JSON',
        },
        runs: {
            unavailableTitle: 'Trace API unavailable',
            emptyTitle: 'No runs yet',
            emptyDetail: 'A run and events will appear after a chat completes.',
            noEvents: 'No events',
            noQuery: 'No query',
            scenario: 'Scenario',
            runId: 'Run',
        },
        trace: {
            open: 'Open Trace',
            backToChat: 'Back to chat',
            copyTraceId: 'Copy Trace ID',
            events: '{count} events',
            waiting: 'Waiting for run id',
            hierarchy: 'Hierarchy',
            details: 'Node Details',
            runOverview: 'Run Overview',
            stage: 'Stage',
            plan: 'Execution Plan',
            planStep: 'Plan Step',
            modelCall: 'Model Call',
            toolCall: 'Tool Call',
            expand: 'Expand',
            collapse: 'Collapse',
            event: 'Event',
            childNodes: 'Child nodes',
            timeline: 'Event timeline',
            payload: 'Payload',
            input: 'Input',
            output: 'Output',
            result: 'Result',
            error: 'Error',
            emptyPayload: 'No payload',
            noSelection: 'Select a node on the left to inspect it',
        },
        settings: {
            configured: 'configured',
            missing: 'missing',
            verified: 'verified',
            pending: 'needs check',
            error: 'failed',
            default: 'default',
            noModels: 'No model list configured',
            serviceTitle: 'Python Agent Service',
            serviceChecking: 'Checking',
            modelKeys: 'Models & Keys',
            noDefaultProvider: 'No default provider set',
            connected: 'Connected',
            failed: 'Failed',
        },
        welcome: {
            prompt: 'Send me a question or task to get started.',
            imageCreate: 'Generate Image',
            imagePolish: 'Polished Prompt',
            imageReference: 'Use References',
        },
        capabilities: {
            chat: 'Chat',
            tool_use: 'Tool use',
            intent_routing_planned: 'Intent routing planned',
            summary_planned: 'Summary planned',
            tracing: 'Trace',
            conversation_memory: 'Conversation memory',
            state_graph: 'State graph',
            checkpoint_ready: 'Checkpoint',
            ab_test: 'A/B test',
            deep_research: 'Deep research',
            research_planning: 'Research planning',
            multi_round_search: 'Multi-round search',
            source_synthesis: 'Source synthesis',
            report_generation: 'Report generation',
            aigc: 'AIGC',
            image_generation: 'Image generation',
            image_generation_planned: 'Image generation planned',
            prompt_refine: 'Prompt polish',
            prompt_refine_planned: 'Prompt refinement planned',
            conversation_image_generation: 'Chat image generation',
            multimodal_input: 'Multimodal input',
            food_image_calorie_estimation: 'Food-photo calories',
            nutrition_log: 'Nutrition log',
            calorie_deficit_tracking: 'Calorie deficit',
            database_persistence: 'Database persistence',
        },
        errors: { rateLimit: 'Rate Limit Exceeded', error: 'Error', requestFailed: 'Request failed', streamFailed: 'Streaming failed' },
    },
};

const PROVIDERS = [
    { key: 'claude', label: 'Claude', checkKey: 'llm.claude.api_key' },
    { key: 'openai', label: 'OpenAI', checkKey: 'llm.openai.api_key' },
    { key: 'gemini', label: 'Gemini', checkKey: 'llm.gemini.api_key' },
    { key: 'deepseek', label: 'DeepSeek', checkKey: 'llm.deepseek.api_key' },
    { key: 'doubao', label: 'Doubao', checkKey: 'llm.doubao.api_key' },
    { key: 'minimax', label: 'MiniMax', checkKey: 'llm.minimax.api_key' },
    { key: 'ollama', label: 'Ollama', checkKey: 'llm.ollama.base_url' },
];

const SUPER_CHAT_MODES = [
    {
        id: DEEP_RESEARCH_MODE_ID,
        prompts: {
            zh: '【深度研究】本轮交给 Deep Research Agent。必须先输出研究计划大纲给用户确认；用户确认后再按计划进行多轮外网检索、分步总结，并汇总为研究报告。',
            en: '[Deep Research] Route this turn to the Deep Research Agent. First produce a research plan for user confirmation; after approval, run multi-round web research, summarize step by step, and produce a research report.',
        },
    },
];

const IMAGE_CHAT_MODES = [
    {
        id: 'image_prompt_refine',
        prompts: {
            zh: '【专业修饰】本轮先像专业视觉创意总监一样审查用户意图和参考素材，补全主体、构图、镜头、光线、材质、风格、色彩、负面约束，再把修饰后的提示词用作生图输入。信息不足时先问一个关键问题；足够时直接生成。',
            en: '[Prompt Polish] For this turn, review the user intent and references like a professional visual creative director, enriching subject, composition, camera, lighting, materials, style, color, and negative constraints before using the refined prompt for image generation. Ask one key question if information is insufficient; generate directly when enough.',
        },
    },
];

function availableModes() {
    if (currentAgentId !== SUPER_CHAT_AGENT_ID) return [];
    return SUPER_CHAT_MODES;
}

function allModes() {
    return [...SUPER_CHAT_MODES, ...IMAGE_CHAT_MODES];
}

const MAX_TEXT_ATTACHMENT_BYTES = 1024 * 1024;
const MAX_MEDIA_ATTACHMENT_BYTES = 8 * 1024 * 1024;
const MAX_DRIVE_BINARY_BYTES = 2 * 1024 * 1024;
const MAX_ATTACHMENT_CHARS = 12000;
const MAX_TOTAL_ATTACHMENT_CHARS = 24000;
const ACTIVE_RUN_POLL_MS = 1500;
const ACTIVE_RUN_MAX_POLLS = 240;
const CONVERSATION_RENDER_CACHE_LIMIT = 20;
const FOLLOW_UP_QUESTION_COUNT = 3;
const FOLLOW_UP_POLL_DELAYS_MS = [500, 1000, 1500, 2000, 3000, 4000];
const TEXT_ATTACHMENT_EXTENSIONS = new Set([
    'txt', 'md', 'markdown', 'csv', 'tsv', 'json', 'jsonl', 'yaml', 'yml',
    'xml', 'html', 'htm', 'log', 'ini', 'toml', 'env', 'conf', 'cfg', 'properties',
    'rst', 'adoc', 'tex', 'srt', 'vtt', 'ics', 'lock',
    'js', 'jsx', 'ts', 'tsx', 'css', 'scss', 'less', 'vue', 'svelte',
    'py', 'go', 'java', 'c', 'h', 'cpp', 'hpp', 'cs', 'rs', 'rb', 'php',
    'sh', 'bash', 'zsh', 'fish', 'sql', 'swift', 'scala', 'kt', 'kts', 'lua',
    'r', 'pl', 'dart', 'dockerfile', 'gitignore',
]);
const IMAGE_ATTACHMENT_EXTENSIONS = new Set(['png', 'jpg', 'jpeg', 'webp', 'gif', 'avif', 'bmp', 'heic', 'heif', 'svg']);
const AUDIO_ATTACHMENT_EXTENSIONS = new Set(['mp3', 'wav', 'm4a', 'aac', 'ogg', 'flac', 'webm']);
const VIDEO_ATTACHMENT_EXTENSIONS = new Set(['mp4', 'mov', 'webm', 'm4v', 'avi', 'mkv', 'ogv']);
const DOCUMENT_ATTACHMENT_EXTENSIONS = new Set(['pdf', 'doc', 'docx', 'rtf', 'odt', 'xls', 'xlsx', 'ods', 'ppt', 'pptx', 'odp', 'key', 'numbers', 'pages']);
const ARCHIVE_ATTACHMENT_EXTENSIONS = new Set(['zip', 'rar', '7z', 'tar', 'gz', 'tgz', 'bz2']);
const DRIVE_BINARY_EXTENSIONS = new Set([
    ...IMAGE_ATTACHMENT_EXTENSIONS,
    ...AUDIO_ATTACHMENT_EXTENSIONS,
    ...VIDEO_ATTACHMENT_EXTENSIONS,
    ...DOCUMENT_ATTACHMENT_EXTENSIONS,
    ...ARCHIVE_ATTACHMENT_EXTENSIONS,
]);

let activeView = 'chat';
let currentConversationId = null;
let conversations = [];
let conversationRenderCache = new Map();
let agents = [];
let tools = [];
let toolUserSettings = {};
let toolMcpConfig = { enabled: false, servers: '' };
let toolFilter = 'all';
let toolSearchQuery = '';
let toolSettingsSaving = false;
let toolSettingsStatus = '';
let toolSettingsStatusType = 'muted';
let runs = [];
let settings = {};
let health = null;
let pulse = { date: '', generated_at: '', topics: [], suggested_topics: [], items: [] };
let currentLanguage = localStorage.getItem(LANGUAGE_KEY) || 'zh';
let currentUserId = loadCurrentUserId();
let currentAccountToken = '';
let accounts = [];
let currentAgentId = SUPER_CHAT_AGENT_ID;
let projects = [];
let currentProjectId = loadCurrentProjectId();
let chatDrivePathId = loadChatDrivePathId();
let projectDetail = null;
let activeProjectDocumentId = '';
let projectSearchQuery = '';
let projectSearchResults = [];
let projectSearchDebounceTimer = null;
let projectSearchComposing = false;
let projectSearchRequestSeq = 0;
let projectOpenClickTimer = null;
let projectInlineFileId = '';
let projectInlineFileDetail = { item: null, loading: false, error: '' };
let projectError = '';
let projectStatusText = '';
let projectStatusType = 'muted';
let projectUploadBusy = false;
let projectAskInput = '';
let projectAskAnswer = '';
let projectAskError = '';
let projectAskLoading = false;
let projectAskSources = [];
let selectedProjectDocumentIds = new Set();
let lastSelectedProjectDocumentId = '';
let driveDragState = createEmptyDriveDragState();
let driveSelectionBoxState = createEmptyDriveSelectionBoxState();
let pendingProjectDeletes = new Set();
let pendingProjectDocumentDeletes = new Set();
let collapsedDriveFolderIds = loadDriveCollapsedFolderIds();
let driveRecentPathIds = loadDriveRecentPathIds();
let roles = [];
let currentRoleId = loadCurrentRoleId();
let roleMemories = [];
let roleMemoryError = '';
let roleMemoryStatusText = '';
let roleMemorySaving = false;
let roleMemoryDeletingIds = new Set();
let developerMemoryState = {
    memories: [],
    loadedAt: '',
    loading: false,
    error: '',
    partialErrors: [],
};
const DEFAULT_DEVELOPER_MEMORY_VIEW_STATE = {
    query: '',
    kind: 'all',
    status: 'active',
    sort: 'updated_desc',
};
let developerMemoryViewState = { ...DEFAULT_DEVELOPER_MEMORY_VIEW_STATE };
let developerMemoryMutatingIds = new Set();
let expandedDeveloperMemoryIds = new Set();
let selectedDeveloperMemoryKeys = new Set();
let developerMemoryHoverCard = null;
let developerMemoryHoverHideTimer = null;
let lastMemoryDebug = null;
let selectedRunId = '';
let selectedTraceNodeId = '';
let selectedTraceRunId = '';
let collapsedTraceNodeIds = new Set();
let expandedTraceNodeIds = new Set();
let defaultModelText = '';
const activeConversationRequests = new Set();
const streamingTaskCancellers = new Map();
const pendingConversationDeletes = new Set();
const pendingPulseTopicDeletes = new Set();
let toolsError = '';
let runsError = '';
let pulseError = '';
let pulseErrorType = 'load';
let pulseTopicSubmitting = false;
let pulseRefreshPollTimer = null;
let pulseRefreshPollAttempts = 0;
let pinnedAgentIds = loadPinnedAgents();
let collapsedSidebarSections = loadCollapsedSidebarSections();
let selectedModeIds = loadSelectedModes();
let attachedContexts = [];
let attachmentSeq = 0;
let activeRunWatcher = null;
let mediaPreviewScale = 1;
let mediaPreviewRotation = 0;
let mediaPreviewReturnFocus = null;
let expandedPulseItemIds = new Set();
let selectedPulseTopicId = '';
let selectedPulsePostId = '';
let pulsePostReturnFocus = null;
let pulseExposureObserver = null;
let exposedPulseItemKeys = new Set();
let userQuestionHistory = [];
let questionHistoryIndex = -1;
let questionHistoryDraft = '';
let applyingQuestionHistory = false;
let guestLoginBusy = false;
let followUpRenderToken = 0;
let chatHistoryPanelOpen = false;
let chatNavigationUpdateScheduled = false;
let driveSaveDialogState = createEmptyDriveSaveDialogState();
let drivePathDialogState = createEmptyDrivePathDialogState();
let drivePreviewState = createEmptyDrivePreviewState();

const sidebar = document.getElementById('sidebar');
const sidebarBackdrop = document.getElementById('sidebar-backdrop');
const accountSelect = document.getElementById('account-select');
const btnAddAccount = document.getElementById('btn-add-account');
const accountLogin = document.getElementById('account-login');
const accountLoginClose = document.querySelector('[data-account-login-close]');
const loginAccountSelect = document.getElementById('login-account-select');
const loginPasswordInput = document.getElementById('login-password-input');
const btnAccountLogin = document.getElementById('btn-account-login');
const guestLoginLink = document.getElementById('guest-login-link');
const accountCreateForm = document.getElementById('account-create-form');
const accountCreateButton = accountCreateForm?.querySelector('button[type="submit"]');
const accountNameInput = document.getElementById('account-name-input');
const accountPasswordInput = document.getElementById('account-password-input');
const accountLoginError = document.getElementById('account-login-error');
const conversationList = document.getElementById('conversation-list');
const messagesContainer = document.getElementById('messages');
const inputArea = document.getElementById('input-area');
const chatHistoryTools = document.getElementById('chat-history-tools');
const btnChatPrevUser = document.getElementById('btn-chat-prev-user');
const btnChatHistory = document.getElementById('btn-chat-history');
const chatHistoryPanel = document.getElementById('chat-history-panel');
const chatHistoryList = document.getElementById('chat-history-list');
const chatHistoryCount = document.getElementById('chat-history-count');
const messageInput = document.getElementById('message-input');
const btnSend = document.getElementById('btn-send');
const btnNewChat = document.getElementById('btn-new-chat');
const btnToggleSidebar = document.getElementById('btn-toggle-sidebar');
const btnRefresh = document.getElementById('btn-refresh');
const modelSelect = document.getElementById('model-select');
const currentModelEl = document.getElementById('current-model');
const agentSelect = document.getElementById('agent-select');
const rolePicker = document.getElementById('role-picker');
const roleSelect = document.getElementById('role-select');
const btnRoleMemory = document.getElementById('btn-role-memory');
const roleMemoryPopover = document.getElementById('role-memory-popover');
const roleMemoryList = document.getElementById('role-memory-list');
const roleMemoryForm = document.getElementById('role-memory-form');
const roleMemoryInput = document.getElementById('role-memory-input');
const roleMemoryStatus = document.getElementById('role-memory-status');
const viewTitle = document.getElementById('view-title');
const viewSubtitle = document.getElementById('view-subtitle');
const systemStatus = document.getElementById('system-status');
const agentCount = document.getElementById('agent-count');
const projectCount = document.getElementById('project-count');
const toolCount = document.getElementById('tool-count');
const runCount = document.getElementById('run-count');
const pinnedAgentList = document.getElementById('pinned-agent-list');
const projectList = document.getElementById('project-list');
const navSectionCount = document.getElementById('nav-section-count');
const pinnedSectionCount = document.getElementById('pinned-section-count');
const projectSectionCount = document.getElementById('project-section-count');
const conversationSectionCount = document.getElementById('conversation-section-count');
const agentsGrid = document.getElementById('agents-grid');
const toolsGrid = document.getElementById('tools-grid');
const projectWorkbench = document.getElementById('project-workbench');
const projectUploadInput = document.getElementById('project-upload-input');
const driveSaveDialog = document.getElementById('drive-save-dialog');
const driveSaveForm = document.getElementById('drive-save-form');
const driveSaveNameInput = document.getElementById('drive-save-name-input');
const driveSaveTree = document.getElementById('drive-save-tree');
const driveSavePathCurrent = document.getElementById('drive-save-path-current');
const driveSaveError = document.getElementById('drive-save-error');
const btnDriveSaveConfirm = document.getElementById('btn-drive-save-confirm');
const drivePathDialog = document.getElementById('drive-path-dialog');
const drivePathForm = document.getElementById('drive-path-form');
const drivePathTree = document.getElementById('drive-path-tree');
const drivePathCurrent = document.getElementById('drive-path-current');
const drivePathError = document.getElementById('drive-path-error');
const btnDrivePathConfirm = document.getElementById('btn-drive-path-confirm');
const drivePreviewDialog = document.getElementById('drive-preview-dialog');
const drivePreviewTitle = document.getElementById('drive-preview-title');
const drivePreviewMeta = document.getElementById('drive-preview-meta');
const drivePreviewStatus = document.getElementById('drive-preview-status');
const drivePreviewContent = document.getElementById('drive-preview-content');
const drivePreviewDownload = document.querySelector('[data-drive-preview-download]');
const runList = document.getElementById('run-list');
const runDetail = document.getElementById('run-detail');
const developerWorkbench = document.getElementById('developer-workbench');
const settingsGrid = document.getElementById('settings-grid');
const pulseTopicForm = document.getElementById('pulse-topic-form');
const pulseTopicInput = document.getElementById('pulse-topic-input');
const pulseKeywordsInput = document.getElementById('pulse-keywords-input');
const pulseTopicList = document.getElementById('pulse-topic-list');
const pulseSuggestedTopics = document.getElementById('pulse-suggested-topics');
const pulseTopicFilter = document.getElementById('pulse-topic-filter');
const pulseItems = document.getElementById('pulse-items');
const pulseDateTitle = document.getElementById('pulse-date-title');
const pulseGeneratedAt = document.getElementById('pulse-generated-at');
const pulsePostWindow = document.getElementById('pulse-post-window');
const pulsePostTitle = document.getElementById('pulse-post-title');
const pulsePostNote = document.getElementById('pulse-post-note');
const pulsePostBody = document.getElementById('pulse-post-body');
const pulsePostFooter = document.getElementById('pulse-post-footer');
const languageToggle = document.getElementById('language-toggle');
const agentCommandBar = document.getElementById('agent-command-bar');
const modeMenu = document.getElementById('mode-menu');
const btnModeToggle = document.getElementById('btn-mode-toggle');
const btnAttach = document.getElementById('btn-attach');
const attachmentInput = document.getElementById('attachment-input');
const modePopover = document.getElementById('mode-popover');
const modeOptions = document.getElementById('mode-options');
const modeChips = document.getElementById('mode-chips');
const modeCount = document.getElementById('mode-count');
const mediaLightbox = document.getElementById('media-lightbox');
const mediaLightboxTitle = document.getElementById('media-lightbox-title');
const mediaLightboxStatus = document.getElementById('media-lightbox-status');
const mediaLightboxStage = document.getElementById('media-lightbox-stage');
const mediaLightboxImage = document.getElementById('media-lightbox-image');
const mediaLightboxClose = document.querySelector('[data-media-preview-close].media-tool-button');
const mobileLayoutQuery = window.matchMedia(MOBILE_BREAKPOINT_QUERY);
let wasMobileLayout = mobileLayoutQuery.matches;

if (mobileLayoutQuery.matches) {
    sidebar.classList.add('hidden');
}

function isMobileLayout() {
    return mobileLayoutQuery.matches;
}

function isSidebarOpen() {
    return !sidebar.classList.contains('hidden');
}

function isMobileSidebarOpen() {
    return isMobileLayout() && isSidebarOpen();
}

function syncMobileSidebarState() {
    const open = isMobileSidebarOpen();
    document.body.classList.toggle('mobile-sidebar-open', open);
    if (sidebarBackdrop) sidebarBackdrop.hidden = !open;
    if (btnToggleSidebar) btnToggleSidebar.setAttribute('aria-expanded', String(open));
    sidebar.setAttribute('aria-hidden', String(isMobileLayout() && !open));
}

function setSidebarOpen(open) {
    sidebar.classList.toggle('hidden', !open);
    syncMobileSidebarState();
}

function closeMobileSidebar() {
    if (isMobileLayout()) setSidebarOpen(false);
}

function handleMobileLayoutChange() {
    const mobile = isMobileLayout();
    if (mobile && !wasMobileLayout) {
        sidebar.classList.add('hidden');
    }
    if (!mobile && wasMobileLayout) {
        sidebar.classList.remove('hidden');
    }
    wasMobileLayout = mobile;
    syncMobileSidebarState();
}

if (mobileLayoutQuery.addEventListener) {
    mobileLayoutQuery.addEventListener('change', handleMobileLayoutChange);
} else if (mobileLayoutQuery.addListener) {
    mobileLayoutQuery.addListener(handleMobileLayoutChange);
}

syncMobileSidebarState();

function t(key, vars = {}) {
    const parts = key.split('.');
    let value = I18N[currentLanguage];
    for (const part of parts) value = value?.[part];
    if (typeof value !== 'string') return key;
    return value.replace(/\{(\w+)\}/g, (_, name) => vars[name] ?? '');
}

function applyI18n() {
    document.documentElement.lang = currentLanguage === 'zh' ? 'zh-CN' : 'en';
    document.querySelectorAll('[data-i18n]').forEach((el) => {
        el.textContent = t(el.dataset.i18n);
    });
    document.querySelectorAll('[data-i18n-placeholder]').forEach((el) => {
        el.placeholder = t(el.dataset.i18nPlaceholder);
    });
    document.querySelectorAll('[data-i18n-title]').forEach((el) => {
        el.title = t(el.dataset.i18nTitle);
    });
    document.querySelectorAll('[data-i18n-aria-label]').forEach((el) => {
        el.setAttribute('aria-label', t(el.dataset.i18nAriaLabel));
    });
    document.querySelectorAll('[data-copy-answer], [data-copy-code], [data-copy-trace-id]').forEach(resetCopyButtonFeedback);
    if (languageToggle) languageToggle.textContent = currentLanguage === 'zh' ? 'EN' : '中';
    setGuestLoginBusy(guestLoginBusy);
}

function setLanguage(language) {
    currentLanguage = language;
    localStorage.setItem(LANGUAGE_KEY, currentLanguage);
    conversationRenderCache.clear();
    applyI18n();
    renderHealth();
    renderConversationList();
    renderProjectList();
    renderAgentSelect();
    renderPinnedAgents();
    renderAgents();
    renderAgentCommandBar();
    renderModes();
    renderTools();
    renderRuns();
    renderSettings();
    renderProjects();
    renderDriveSaveDialog();
    renderDrivePathDialog();
    renderDriveDocumentPreview();
    renderPulse();
    renderAccountControls();
    renderRoleSelect();
    renderRoleMemoryList();
    renderDeveloperView();
    renderModelSelect();
    updateTopbar();
    updateChatHistoryControls();
    refreshWelcomeIfEmpty();
    refreshMediaPreviewLabels();
}

async function apiCall(method, path, body = null) {
    const opts = {
        method,
        headers: { 'Content-Type': 'application/json' },
    };
    if (currentAccountToken) opts.headers['X-Account-Session'] = currentAccountToken;
    if (currentUserId) opts.headers['X-User-ID'] = currentUserId;
    if (body) opts.body = JSON.stringify(body);

    const resp = await fetch(API_BASE + path, opts);
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({ error: resp.statusText }));
        throw new Error(err.error || err.detail || 'Request failed');
    }
    return resp.json();
}

function wait(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

function loadPinnedAgents() {
    try {
        const raw = localStorage.getItem('pinned_agent_ids');
        if (raw === null) return ['super_chat'];
        const parsed = JSON.parse(raw || '[]');
        return Array.isArray(parsed) ? parsed : [];
    } catch {
        return ['super_chat'];
    }
}

function savePinnedAgents() {
    localStorage.setItem('pinned_agent_ids', JSON.stringify(pinnedAgentIds));
}

function loadCollapsedSidebarSections() {
    try {
        const parsed = JSON.parse(localStorage.getItem(SIDEBAR_COLLAPSE_STORAGE_KEY) || '[]');
        return Array.isArray(parsed) ? parsed : [];
    } catch {
        return [];
    }
}

function saveCollapsedSidebarSections() {
    localStorage.setItem(SIDEBAR_COLLAPSE_STORAGE_KEY, JSON.stringify(collapsedSidebarSections));
}

function setSidebarSectionCollapsed(sectionId, collapsed) {
    const allowed = ['nav', 'pinned', 'projects', 'conversations'];
    if (!allowed.includes(sectionId)) return;

    if (collapsed) {
        collapsedSidebarSections = Array.from(new Set([...collapsedSidebarSections, sectionId]));
    } else {
        collapsedSidebarSections = collapsedSidebarSections.filter((id) => id !== sectionId);
    }
    saveCollapsedSidebarSections();
    applySidebarCollapseState();
}

function applySidebarCollapseState() {
    document.querySelectorAll('[data-sidebar-section]').forEach((section) => {
        const sectionId = section.dataset.sidebarSection;
        const collapsed = collapsedSidebarSections.includes(sectionId);
        section.classList.toggle('collapsed', collapsed);
        const toggle = section.querySelector('[data-toggle-sidebar-section]');
        if (toggle) toggle.setAttribute('aria-expanded', String(!collapsed));
    });
}

function canonicalModeId(modeId) {
    return String(modeId || '').trim();
}

function modeStorageKey(conversationId = currentConversationId) {
    const suffix = conversationId ? `conversation:${conversationId}` : 'draft';
    return accountStorageKey(`${MODE_STORAGE_KEY}:${suffix}`);
}

function normalizeModeIds(modeIds = []) {
    if (!Array.isArray(modeIds)) return [];
    const allowed = new Set(allModes().map((mode) => mode.id));
    const normalized = modeIds
        .map(canonicalModeId)
        .filter((id) => allowed.has(id));
    return Array.from(new Set(normalized));
}

function loadSelectedModes(conversationId = currentConversationId) {
    try {
        const raw = localStorage.getItem(modeStorageKey(conversationId));
        const parsed = JSON.parse(raw || '[]');
        return normalizeModeIds(parsed);
    } catch {
        return [];
    }
}

function saveSelectedModes(conversationId = currentConversationId) {
    localStorage.setItem(modeStorageKey(conversationId), JSON.stringify(normalizeModeIds(selectedModeIds)));
}

function setSelectedModesForConversation(conversationId = currentConversationId, modeIds = null, { persist = false } = {}) {
    selectedModeIds = normalizeModeIds(Array.isArray(modeIds) ? modeIds : loadSelectedModes(conversationId));
    if (persist) saveSelectedModes(conversationId);
    renderModes();
}

function loadCurrentConversationId() {
    if (!currentUserId) return null;
    const value = localStorage.getItem(accountStorageKey(CURRENT_CONVERSATION_STORAGE_KEY));
    return value || null;
}

function loadCurrentUserId() {
    const value = localStorage.getItem(CURRENT_USER_ID_STORAGE_KEY);
    if (value && String(value).trim()) return String(value).trim();
    return '';
}

function saveCurrentConversationId(id) {
    if (!currentUserId) return;
    localStorage.setItem(accountStorageKey(CURRENT_CONVERSATION_STORAGE_KEY), id || '');
}

function loadCurrentProjectId() {
    if (!currentUserId) return '';
    return localStorage.getItem(accountStorageKey(CURRENT_PROJECT_STORAGE_KEY)) || '';
}

function saveCurrentProjectId(id) {
    if (!currentUserId) return;
    localStorage.setItem(accountStorageKey(CURRENT_PROJECT_STORAGE_KEY), id || '');
}

function loadChatDrivePathId() {
    if (!currentUserId) return '';
    return localStorage.getItem(accountStorageKey(CHAT_DRIVE_PATH_STORAGE_KEY)) || '';
}

function saveChatDrivePathId(id) {
    if (!currentUserId) return;
    localStorage.setItem(accountStorageKey(CHAT_DRIVE_PATH_STORAGE_KEY), id || '');
}

function loadDriveCollapsedFolderIds() {
    if (!currentUserId) return new Set();
    try {
        const parsed = JSON.parse(localStorage.getItem(accountStorageKey(DRIVE_COLLAPSED_FOLDERS_STORAGE_KEY)) || '[]');
        return new Set(Array.isArray(parsed) ? parsed.map(String).filter(Boolean) : []);
    } catch {
        return new Set();
    }
}

function saveDriveCollapsedFolderIds() {
    if (!currentUserId) return;
    localStorage.setItem(accountStorageKey(DRIVE_COLLAPSED_FOLDERS_STORAGE_KEY), JSON.stringify(Array.from(collapsedDriveFolderIds)));
}

function loadDriveRecentPathIds() {
    if (!currentUserId) return [];
    try {
        const parsed = JSON.parse(localStorage.getItem(accountStorageKey(DRIVE_RECENT_PATHS_STORAGE_KEY)) || '[]');
        return Array.isArray(parsed) ? Array.from(new Set(parsed.map(String).filter(Boolean))).slice(0, 8) : [];
    } catch {
        return [];
    }
}

function saveDriveRecentPathIds() {
    if (!currentUserId) return;
    localStorage.setItem(accountStorageKey(DRIVE_RECENT_PATHS_STORAGE_KEY), JSON.stringify(driveRecentPathIds.slice(0, 8)));
}

function projectConversationStorageKey(projectId) {
    return accountStorageKey(`${PROJECT_CHAT_CONVERSATION_STORAGE_KEY}:${projectId || 'draft'}`);
}

function loadProjectConversationId(projectId) {
    if (!currentUserId || !projectId) return '';
    return localStorage.getItem(projectConversationStorageKey(projectId)) || '';
}

function saveProjectConversationId(projectId, conversationId) {
    if (!currentUserId || !projectId) return;
    localStorage.setItem(projectConversationStorageKey(projectId), conversationId || '');
}

function saveCurrentUserId(id) {
    if (id) {
        localStorage.setItem(CURRENT_USER_ID_STORAGE_KEY, id);
    } else {
        localStorage.removeItem(CURRENT_USER_ID_STORAGE_KEY);
    }
}

function loadAccountSessionToken(userId = currentUserId) {
    const id = String(userId || '').trim();
    if (!id) return '';
    return localStorage.getItem(`${ACCOUNT_SESSION_STORAGE_KEY}:${id}`) || '';
}

function saveAccountSessionToken(userId, token) {
    const id = String(userId || '').trim();
    if (!id) return;
    const key = `${ACCOUNT_SESSION_STORAGE_KEY}:${id}`;
    if (token) {
        localStorage.setItem(key, token);
    } else {
        localStorage.removeItem(key);
    }
}

function accountStorageKey(key) {
    return `${key}:${currentUserId || 'anonymous'}`;
}

function conversationAgentId(conversation = null) {
    return String(conversation?.agent_id || SUPER_CHAT_AGENT_ID).trim() || SUPER_CHAT_AGENT_ID;
}

function currentConversationRecord(id = currentConversationId) {
    return conversations.find((conv) => conv.id === id) || null;
}

function applyConversationAgent(conversation = null) {
    setCurrentAgent(conversationAgentId(conversation));
}

function loadCurrentRoleId() {
    if (!currentUserId) return 'default';
    return localStorage.getItem(accountStorageKey(CURRENT_ROLE_ID_STORAGE_KEY)) || 'default';
}

function saveCurrentRoleId() {
    if (!currentUserId) return;
    localStorage.setItem(accountStorageKey(CURRENT_ROLE_ID_STORAGE_KEY), currentRoleId || 'default');
}

async function loadAccounts() {
    const data = await publicApiCall('GET', '/api/accounts');
    accounts = Array.isArray(data.accounts) ? data.accounts : [];
    renderAccountControls();
    return accounts;
}

async function createAccount(name, password) {
    const data = await publicApiCall('POST', '/api/accounts', { name, password });
    const account = data.account;
    if (account && account.id) {
        accounts = [...accounts.filter((item) => item.id !== account.id), account];
        renderAccountControls();
    }
    return data;
}

async function loginAccount(userId, password) {
    return publicApiCall('POST', '/api/accounts/login', { id: userId, password });
}

function guestEntryRequested() {
    const path = window.location.pathname.replace(/\/+$/, '') || '/';
    if (path === '/guest') return true;

    const params = new URLSearchParams(window.location.search);
    if (!params.has('guest')) return false;
    const value = (params.get('guest') || '1').trim().toLowerCase();
    return value !== '0' && value !== 'false' && value !== 'no';
}

function setGuestLoginBusy(isBusy) {
    guestLoginBusy = Boolean(isBusy);
    if (!guestLoginLink) return;

    guestLoginLink.textContent = guestLoginBusy ? t('account.guestLoading') : t('account.guestEnter');
    if (guestLoginBusy) {
        guestLoginLink.setAttribute('aria-disabled', 'true');
        guestLoginLink.setAttribute('aria-busy', 'true');
    } else {
        guestLoginLink.removeAttribute('aria-disabled');
        guestLoginLink.removeAttribute('aria-busy');
    }
}

async function enterGuestAccount(options = {}) {
    const data = await publicApiCall('POST', '/api/accounts/guest');
    if (data.account) {
        accounts = [...accounts.filter((item) => item.id !== data.account.id), data.account];
    }
    await switchAccount(data.account?.id || GUEST_ACCOUNT_ID, {
        token: data.token,
        refresh: options.refresh,
        reload: options.reload,
    });
}

async function publicApiCall(method, path, body = null) {
    const opts = {
        method,
        headers: { 'Content-Type': 'application/json' },
    };
    if (body) opts.body = JSON.stringify(body);

    const resp = await fetch(API_BASE + path, opts);
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({ error: resp.statusText }));
        throw new Error(err.error || err.detail || 'Request failed');
    }
    return resp.json();
}

function renderAccountControls() {
    const options = accounts.length
        ? accounts.map((account) => `<option value="${escapeAttr(account.id)}">${escapeHtml(account.name || account.id)}</option>`).join('')
        : `<option value="">${escapeHtml(t('account.loginTitle'))}</option>`;

    if (accountSelect) {
        accountSelect.innerHTML = options;
        accountSelect.value = accounts.some((account) => account.id === currentUserId) ? currentUserId : '';
    }
    if (loginAccountSelect) {
        loginAccountSelect.innerHTML = options;
        loginAccountSelect.value = accounts.some((account) => account.id === currentUserId) ? currentUserId : (accounts[0]?.id || '');
        loginAccountSelect.disabled = accounts.length === 0;
    }
    if (btnAccountLogin) btnAccountLogin.disabled = accounts.length === 0;
}

function accountLoginIsOpen() {
    return Boolean(accountLogin && !accountLogin.classList.contains('hidden'));
}

function canDismissAccountLogin() {
    return Boolean(currentUserId && currentAccountToken);
}

function updateAccountLoginDismissState() {
    if (!accountLogin) return;
    accountLogin.classList.toggle('dismissible', canDismissAccountLogin());
}

function showAccountLogin(message = '', selectedUserId = '', options = {}) {
    if (!accountLogin) return;
    accountLogin.classList.remove('hidden');
    document.body.classList.add('account-login-open');
    updateAccountLoginDismissState();
    if (accountLoginError) accountLoginError.textContent = message || '';
    renderAccountControls();
    if (selectedUserId && loginAccountSelect && accounts.some((account) => account.id === selectedUserId)) {
        loginAccountSelect.value = selectedUserId;
    }
    if (loginPasswordInput) loginPasswordInput.value = '';
    requestAnimationFrame(() => {
        if (options.focus === 'select' && accounts.length && loginAccountSelect) {
            loginAccountSelect.focus({ preventScroll: true });
        } else if (accounts.length && loginPasswordInput) {
            loginPasswordInput.focus({ preventScroll: true });
        } else if (accounts.length && loginAccountSelect) {
            loginAccountSelect.focus({ preventScroll: true });
        } else {
            accountNameInput?.focus({ preventScroll: true });
        }
    });
}

function hideAccountLogin() {
    if (!accountLogin) return;
    accountLogin.classList.add('hidden');
    document.body.classList.remove('account-login-open');
    if (accountLoginError) accountLoginError.textContent = '';
}

function dismissAccountLogin() {
    if (!canDismissAccountLogin()) return false;
    hideAccountLogin();
    focusMessageInput({ allowMobile: false });
    return true;
}

async function switchAccount(userId, options = {}) {
    const nextUserId = String(userId || '').trim();
    if (!nextUserId) {
        showAccountLogin();
        return;
    }

    stopActiveRunWatcher();
    activeConversationRequests.clear();
    currentUserId = nextUserId;
    currentAccountToken = options.token || loadAccountSessionToken(nextUserId);
    if (options.token) saveAccountSessionToken(nextUserId, options.token);
    saveCurrentUserId(currentUserId);
    if (options.reload === true) {
        hideAccountLogin();
        window.location.reload();
        return;
    }
    currentConversationId = loadCurrentConversationId();
    currentProjectId = loadCurrentProjectId();
    chatDrivePathId = loadChatDrivePathId();
    selectedModeIds = loadSelectedModes(currentConversationId);
    currentRoleId = loadCurrentRoleId();
    roleMemories = [];
    roleMemoryError = '';
    roleMemoryStatusText = '';
    roleMemoryDeletingIds = new Set();
    conversations = [];
    tools = [];
    toolUserSettings = {};
    toolMcpConfig = { enabled: false, servers: '' };
    toolSettingsStatus = '';
    toolSettingsStatusType = 'muted';
    runs = [];
    pulse = { date: '', generated_at: '', topics: [], suggested_topics: [], items: [] };
    projects = [];
    projectDetail = null;
    activeProjectDocumentId = '';
    projectSearchQuery = '';
    projectSearchResults = [];
    projectInlineFileId = '';
    projectInlineFileDetail = { item: null, loading: false, error: '' };
    projectError = '';
    projectStatusText = '';
    projectStatusType = 'muted';
    projectUploadBusy = false;
    projectAskInput = '';
    projectAskAnswer = '';
    projectAskError = '';
    projectAskLoading = false;
    projectAskSources = [];
    selectedProjectDocumentIds = new Set();
    lastSelectedProjectDocumentId = '';
    driveDragState = createEmptyDriveDragState();
    driveSelectionBoxState = createEmptyDriveSelectionBoxState();
    pendingProjectDeletes = new Set();
    pendingProjectDocumentDeletes = new Set();
    collapsedDriveFolderIds = loadDriveCollapsedFolderIds();
    driveRecentPathIds = loadDriveRecentPathIds();
    runsError = '';
    pulseError = '';
    pulseErrorType = 'load';
    pulseTopicSubmitting = false;
    selectedRunId = '';
    selectedTraceNodeId = '';
    selectedTraceRunId = '';
    expandedPulseItemIds = new Set();
    selectedPulseTopicId = '';
    selectedPulsePostId = '';
    exposedPulseItemKeys = new Set();
    clearQuestionHistory();
    clearAttachments();
    messageInput.value = '';
    autoResizeInput();
    updateSendState();
    renderAccountControls();
    renderRoleSelect();
    renderRoleMemoryList();
    renderConversationList();
    renderProjectList();
    renderProjects();
    renderPulse();
    renderRuns();
    showWelcome();

    if (options.refresh !== false) {
        await refreshAll();
        await restoreInitialConversation();
    }
    hideAccountLogin();
}

function displayConversationTitle(conv) {
    const title = String(conv?.title || '').trim();
    if (!title || title === 'New Conversation') return t('actions.newChat');
    return title;
}

function getSelectedModes() {
    const modes = availableModes();
    return selectedModeIds
        .map((id) => modes.find((mode) => mode.id === id))
        .filter(Boolean);
}

function modeCopy(mode) {
    const id = canonicalModeId(mode.id);
    const fallback = I18N.en.modes.items[id] || [id, ''];
    const localized = I18N[currentLanguage].modes.items[id] || fallback;
    return {
        name: localized[0],
        detail: localized[1],
    };
}

function renderModes() {
    if (!modeOptions) return;

    const title = modePopover?.querySelector('.mode-popover-head strong');
    if (title) {
        title.textContent = currentAgentId === 'image_generation_v1'
            ? t('modes.imageTitle')
            : t('modes.title');
    }

    const modes = availableModes();
    const allowedModeIds = new Set(modes.map((mode) => mode.id));
    const previousModeCount = selectedModeIds.length;
    selectedModeIds = selectedModeIds.filter((id) => allowedModeIds.has(id));
    if (selectedModeIds.length !== previousModeCount) saveSelectedModes();
    if (modeMenu) modeMenu.hidden = modes.length === 0;
    if (!modes.length) closeModePopover();

    modeOptions.innerHTML = modes.map((mode) => {
        const copy = modeCopy(mode);
        const checked = selectedModeIds.includes(mode.id) ? 'checked' : '';
        return `
            <label class="mode-option">
                <input type="checkbox" data-mode-id="${escapeAttr(mode.id)}" ${checked}>
                <span class="mode-option-copy">
                    <strong>${escapeHtml(copy.name)}</strong>
                    <small>${escapeHtml(copy.detail)}</small>
                </span>
            </label>
        `;
    }).join('');

    const activeModes = getSelectedModes();
    const hasDrivePathChip = Boolean(chatDrivePathChipHtml());
    if (modeChips) {
        modeChips.innerHTML = renderInputContextChips(activeModes);
        modeChips.hidden = activeModes.length === 0 && attachedContexts.length === 0 && !hasDrivePathChip;
    }
    if (modeCount) {
        modeCount.textContent = activeModes.length ? String(activeModes.length) : '';
    }
    if (btnModeToggle) {
        const names = activeModes.map((mode) => modeCopy(mode).name).join(', ');
        btnModeToggle.classList.toggle('active', activeModes.length > 0);
        btnModeToggle.title = activeModes.length ? t('modes.active', { names }) : t('modes.toggle');
    }
    updateChatNavigationOffset();
}

function renderInputContextChips(activeModes = getSelectedModes()) {
    const modeItems = activeModes.map((mode) => {
        const copy = modeCopy(mode);
        return `<span class="mode-chip" title="${escapeAttr(copy.detail)}">${escapeHtml(copy.name)}</span>`;
    });
    const drivePathChip = chatDrivePathChipHtml();
    const attachmentItems = attachedContexts.map(renderAttachmentChip);
    return [...modeItems, drivePathChip, ...attachmentItems].filter(Boolean).join('');
}

function chatDrivePathChipHtml() {
    if (selectedModeAgentId() !== SUPER_CHAT_AGENT_ID) return '';
    const item = chatDrivePathItem();
    if (!item?.id) return '';
    const display = chatDrivePathDisplay();
    const title = t('projects.chatPathTitle', { path: display });
    return `
        <button class="mode-chip drive-path-chip" type="button"
                data-open-chat-drive-path
                title="${escapeAttr(title)}"
                aria-label="${escapeAttr(title)}">
            <span>${escapeHtml(t('projects.chatPathChip'))}</span>
            <small>${escapeHtml(display)}</small>
        </button>
    `;
}

function attachmentStatusText(item) {
    if (item.status === 'ready') {
        return item.kind === 'text' ? t('attachments.ready') : t('attachments.mediaReady');
    }
    return item.status === 'reading' ? t('attachments.reading') : (item.error || t('attachments.unsupported'));
}

function attachmentPreviewUrl(item) {
    if (item.kind !== 'image') return '';
    const url = item.dataUrl || '';
    return isSafeDataImageUrl(url) ? url : '';
}

function renderAttachmentChip(item) {
    const statusText = attachmentStatusText(item);
    const title = `${item.name} / ${item.kind || 'file'} / ${formatBytes(item.size)} / ${statusText}`;
    const previewUrl = attachmentPreviewUrl(item);
    const isImage = item.kind === 'image';
    const chipClass = [
        'mode-chip',
        'attachment-chip',
        isImage ? 'attachment-image-chip' : '',
        item.status,
    ].filter(Boolean).join(' ');
    const preview = isImage
        ? (
            previewUrl
                ? `
                    <button class="attachment-thumb-button" type="button"
                            data-media-preview-src="${escapeAttr(previewUrl)}"
                            data-media-preview-alt="${escapeAttr(item.name)}"
                            data-media-download-name="${escapeAttr(item.name)}"
                            aria-label="${escapeAttr(t('media.preview'))}: ${escapeAttr(item.name)}"
                            title="${escapeAttr(t('media.preview'))}">
                        <img class="attachment-thumb" src="${escapeAttr(previewUrl)}" alt="">
                    </button>
                `
                : `<span class="attachment-thumb-placeholder" aria-hidden="true"></span>`
        )
        : '';
    return `
        <span class="${escapeAttr(chipClass)}" title="${escapeAttr(title)}">
            ${preview}
            <span class="attachment-copy">
                <span class="attachment-name">${escapeHtml(item.name)}</span>
                <small>${escapeHtml(statusText)}</small>
            </span>
            <button class="attachment-remove" type="button"
                    data-remove-attachment="${escapeAttr(item.id)}"
                    aria-label="${escapeAttr(t('actions.removeAttachment'))}: ${escapeAttr(item.name)}"
                    title="${escapeAttr(t('actions.removeAttachment'))}">&times;</button>
        </span>
    `;
}

function setModeSelected(modeId, selected) {
    const normalizedModeId = canonicalModeId(modeId);
    const allowed = availableModes().some((mode) => mode.id === normalizedModeId);
    if (!allowed) return;
    if (selected) {
        selectedModeIds = Array.from(new Set([...selectedModeIds.map(canonicalModeId), normalizedModeId]));
    } else {
        selectedModeIds = selectedModeIds
            .map(canonicalModeId)
            .filter((id) => id !== normalizedModeId);
    }
    saveSelectedModes();
    renderModes();
}

function closeModePopover() {
    if (modePopover) modePopover.classList.add('hidden');
}

function toggleModePopover() {
    if (!modePopover) return;
    modePopover.classList.toggle('hidden');
}

function selectedModePayload() {
    const modes = getSelectedModes();
    const modeIds = modes.map((mode) => mode.id);
    const modePrompts = modes.map((mode) => mode.prompts[currentLanguage] || mode.prompts.en);
    return {
        mode_ids: modeIds,
        mode_prompts: modePrompts,
    };
}

function selectedModeAgentId(fallbackAgentId = currentAgentId) {
    return fallbackAgentId;
}

function hasReadyAttachments() {
    return attachedContexts.some((item) => item.status === 'ready' && (item.content || item.dataUrl));
}

function hasPendingAttachments() {
    return attachedContexts.some((item) => item.status === 'reading');
}

function isCurrentConversationLoading() {
    return Boolean(currentConversationId && activeConversationRequests.has(currentConversationId));
}

function updateSendState() {
    btnSend.disabled = isCurrentConversationLoading()
        || hasPendingAttachments()
        || (!messageInput.value.trim() && !hasReadyAttachments());
    if (btnAttach) {
        btnAttach.classList.toggle('active', attachedContexts.length > 0);
    }
    updateRegenerateButtonsState();
    updateFollowUpButtonsState();
}

function updateRegenerateButtonsState() {
    const loading = isCurrentConversationLoading();
    messagesContainer.querySelectorAll('[data-regenerate-answer]').forEach((button) => {
        const message = button.closest('.message.assistant');
        const enabled = !loading
            && Boolean(message?.dataset.regenerateQuery)
            && !message?.classList.contains('streaming');
        button.disabled = !enabled;
        if (enabled) {
            button.removeAttribute('aria-disabled');
        } else {
            button.setAttribute('aria-disabled', 'true');
        }
    });
}

function updateFollowUpButtonsState() {
    const disabled = isCurrentConversationLoading() || hasPendingAttachments() || !currentConversationId;
    messagesContainer.querySelectorAll('[data-follow-up-question]').forEach((button) => {
        button.disabled = disabled;
        if (disabled) {
            button.setAttribute('aria-disabled', 'true');
        } else {
            button.removeAttribute('aria-disabled');
        }
    });
}

function clearFollowUpMessagesOnly() {
    messagesContainer.querySelectorAll('[data-follow-up-container]').forEach((node) => {
        node.remove();
    });
}

function removeFollowUpMessages() {
    followUpRenderToken += 1;
    clearFollowUpMessagesOnly();
}

function resetQuestionHistoryBrowse() {
    questionHistoryIndex = -1;
    questionHistoryDraft = '';
}

function clearQuestionHistory() {
    userQuestionHistory = [];
    resetQuestionHistoryBrowse();
}

function syncQuestionHistoryFromMessages(messages = []) {
    userQuestionHistory = (messages || [])
        .filter((msg) => msg?.role === 'user')
        .map((msg) => String(msg.content || '').trim())
        .filter(Boolean);
    resetQuestionHistoryBrowse();
}

function appendQuestionHistory(question = '') {
    const text = String(question || '').trim();
    if (!text) return;
    userQuestionHistory.push(text);
    resetQuestionHistoryBrowse();
}

function cursorIsOnFirstLine() {
    const start = messageInput.selectionStart ?? 0;
    const end = messageInput.selectionEnd ?? start;
    if (start !== end) return false;
    return !messageInput.value.slice(0, start).includes('\n');
}

function shouldBrowseQuestionHistory(event) {
    if (!['ArrowUp', 'ArrowDown'].includes(event.key)) return false;
    if (event.isComposing) return false;
    if (event.shiftKey || event.altKey || event.metaKey || event.ctrlKey) return false;
    if (!userQuestionHistory.length) return false;
    if (questionHistoryIndex >= 0) return true;
    return event.key === 'ArrowUp' && (!messageInput.value || cursorIsOnFirstLine());
}

function setQuestionHistoryInputValue(value = '') {
    applyingQuestionHistory = true;
    messageInput.value = value;
    autoResizeInput();
    updateSendState();
    if (messageInput.setSelectionRange) {
        const end = messageInput.value.length;
        messageInput.setSelectionRange(end, end);
    }
    applyingQuestionHistory = false;
}

function browseQuestionHistory(direction) {
    if (!userQuestionHistory.length) return;

    if (direction === 'up') {
        if (questionHistoryIndex < 0) {
            questionHistoryDraft = messageInput.value;
            questionHistoryIndex = userQuestionHistory.length - 1;
        } else {
            questionHistoryIndex = Math.max(0, questionHistoryIndex - 1);
        }
        setQuestionHistoryInputValue(userQuestionHistory[questionHistoryIndex]);
        return;
    }

    if (questionHistoryIndex < 0) return;
    if (questionHistoryIndex >= userQuestionHistory.length - 1) {
        const draft = questionHistoryDraft;
        resetQuestionHistoryBrowse();
        setQuestionHistoryInputValue(draft);
        return;
    }

    questionHistoryIndex += 1;
    setQuestionHistoryInputValue(userQuestionHistory[questionHistoryIndex]);
}

async function handleAttachmentSelection(files) {
    const list = Array.from(files || []);
    if (!list.length) return;

    const pending = list.map((file) => {
        const item = {
            id: `att_${Date.now()}_${attachmentSeq += 1}`,
            name: file.name || `attachment-${attachmentSeq}`,
            size: file.size || 0,
            type: file.type || '',
            kind: attachmentKind(file),
            status: 'reading',
            content: '',
            dataUrl: '',
            error: '',
            truncated: false,
        };
        attachedContexts.push(item);
        return { file, item };
    });

    renderModes();
    updateSendState();

    await Promise.all(pending.map(async ({ file, item }) => {
        try {
            const parsed = await parseAttachmentFile(file, item);
            item.content = parsed.content || '';
            item.dataUrl = parsed.dataUrl || '';
            item.kind = parsed.kind || item.kind;
            item.status = 'ready';
        } catch (err) {
            item.status = 'error';
            item.error = err.message || t('attachments.unsupported');
        } finally {
            renderModes();
            updateSendState();
        }
    }));
}

function imageExtensionFromMime(type = '') {
    const normalized = String(type || '').toLowerCase();
    if (normalized === 'image/jpeg') return 'jpg';
    if (normalized === 'image/svg+xml') return 'svg';
    const match = normalized.match(/^image\/([a-z0-9.+-]+)$/);
    return match ? match[1].replace('+xml', '') : 'png';
}

function fileFromClipboardImage(file, index = 1) {
    const type = file.type || 'image/png';
    const extension = imageExtensionFromMime(type);
    const fallbackName = `pasted-image-${new Date().toISOString().replace(/[:.]/g, '-')}-${index}.${extension}`;
    const name = file.name && file.name !== 'image.png' ? file.name : fallbackName;
    try {
        return new File([file], name, { type, lastModified: Date.now() });
    } catch {
        file.name = name;
        return file;
    }
}

function clipboardImageFiles(event) {
    const clipboard = event.clipboardData;
    if (!clipboard) return [];

    const files = [];
    const seen = new Set();
    const addFile = (file) => {
        if (!file || !(file.type || '').toLowerCase().startsWith('image/')) return;
        const key = `${file.name || ''}:${file.type || ''}:${file.size || 0}:${file.lastModified || 0}`;
        if (seen.has(key)) return;
        seen.add(key);
        files.push(fileFromClipboardImage(file, files.length + 1));
    };

    Array.from(clipboard.items || []).forEach((item) => {
        if (item.kind !== 'file' || !(item.type || '').toLowerCase().startsWith('image/')) return;
        addFile(item.getAsFile());
    });
    if (!files.length) {
        Array.from(clipboard.files || []).forEach(addFile);
    }
    return files;
}

function shouldHandleImagePaste(event) {
    if (activeView !== 'chat') return false;
    const target = event.target;
    if (!target || target === messageInput) return true;
    if (target.closest?.('#input-area, #messages')) return true;
    if (target.closest?.('input, textarea, [contenteditable="true"]')) return false;
    return true;
}

async function handleImagePaste(event) {
    if (event.defaultPrevented || !shouldHandleImagePaste(event)) return;
    const files = clipboardImageFiles(event);
    if (!files.length) return;
    event.preventDefault();
    await handleAttachmentSelection(files);
    focusMessageInput();
}

async function parseAttachmentFile(file, item = null) {
    if (!file.size) throw new Error(t('attachments.empty'));

    const kind = attachmentKind(file);
    if (item) item.kind = kind;

    if (kind === 'image' || kind === 'audio' || kind === 'video') {
        if (file.size > MAX_MEDIA_ATTACHMENT_BYTES) {
            throw new Error(t('attachments.tooLarge', { size: formatBytes(MAX_MEDIA_ATTACHMENT_BYTES) }));
        }
        return {
            kind,
            content: mediaAttachmentSummary(file, kind),
            dataUrl: normalizeMediaDataUrl(await readFileAsDataURL(file), file, kind),
        };
    }

    if (file.size > MAX_TEXT_ATTACHMENT_BYTES) {
        throw new Error(t('attachments.tooLarge', { size: formatBytes(MAX_TEXT_ATTACHMENT_BYTES) }));
    }
    if (kind !== 'text' || !isReadableAttachment(file)) {
        throw new Error(t('attachments.unsupported'));
    }

    let text = '';
    try {
        text = await file.text();
    } catch (err) {
        throw new Error(t('attachments.readFailed', { message: err.message || String(err) }));
    }

    const cleaned = normalizeAttachmentText(text);
    if (!cleaned) throw new Error(t('attachments.empty'));
    if (cleaned.length > MAX_ATTACHMENT_CHARS) {
        if (item) item.truncated = true;
        return {
            kind: 'text',
            content: cleaned.slice(0, MAX_ATTACHMENT_CHARS),
            dataUrl: '',
        };
    }
    return {
        kind: 'text',
        content: cleaned,
        dataUrl: '',
    };
}

function attachmentKind(file) {
    const type = (file.type || '').toLowerCase();
    if (type.startsWith('image/')) return 'image';
    if (type.startsWith('audio/')) return 'audio';
    if (type.startsWith('video/')) return 'video';
    const ext = fileExtension(file.name);
    if (IMAGE_ATTACHMENT_EXTENSIONS.has(ext)) return 'image';
    if (AUDIO_ATTACHMENT_EXTENSIONS.has(ext)) return 'audio';
    if (VIDEO_ATTACHMENT_EXTENSIONS.has(ext)) return 'video';
    if (isReadableAttachment(file)) return 'text';
    return 'file';
}

function mediaAttachmentSummary(file, kind) {
    const type = file.type || mediaMimeTypeForFile(file, kind) || `${kind}/*`;
    return `${kind} attachment: ${file.name || 'untitled'}, mime=${type}, size=${formatBytes(file.size || 0)}`;
}

function normalizeMediaDataUrl(dataUrl, file, kind) {
    const mimeType = file.type || mediaMimeTypeForFile(file, kind);
    if (!mimeType || !String(dataUrl).startsWith('data:')) return dataUrl;
    return String(dataUrl).replace(/^data:[^;,]*(;base64,)/i, `data:${mimeType}$1`);
}

function mediaMimeTypeForFile(file, kind) {
    const ext = fileExtension(file.name);
    if (kind === 'image') {
        if (ext === 'jpg') return 'image/jpeg';
        if (IMAGE_ATTACHMENT_EXTENSIONS.has(ext)) return `image/${ext === 'svg' ? 'svg+xml' : ext}`;
    }
    if (kind === 'audio' && AUDIO_ATTACHMENT_EXTENSIONS.has(ext)) {
        return ext === 'm4a' ? 'audio/mp4' : `audio/${ext}`;
    }
    if (kind === 'video' && VIDEO_ATTACHMENT_EXTENSIONS.has(ext)) {
        if (ext === 'mov') return 'video/quicktime';
        if (ext === 'm4v') return 'video/mp4';
        return `video/${ext}`;
    }
    return '';
}

function readFileAsDataURL(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result || ''));
        reader.onerror = () => reject(new Error(t('attachments.readFailed', { message: reader.error?.message || 'FileReader error' })));
        reader.readAsDataURL(file);
    });
}

function dataUrlBase64Content(dataUrl = '') {
    const value = String(dataUrl || '');
    const commaIndex = value.indexOf(',');
    if (commaIndex < 0) return '';
    return value.slice(commaIndex + 1);
}

function isReadableAttachment(file) {
    const type = (file.type || '').toLowerCase();
    if (type.startsWith('text/')) return true;
    if (['application/json', 'application/xml', 'application/x-yaml', 'application/yaml'].includes(type)) {
        return true;
    }
    const ext = fileExtension(file.name);
    return TEXT_ATTACHMENT_EXTENSIONS.has(ext);
}

function isSupportedDriveBinaryFile(file) {
    const type = (file.type || '').toLowerCase();
    const ext = fileExtension(file.name);
    if (type.startsWith('image/') || type.startsWith('audio/') || type.startsWith('video/')) return true;
    if (['application/pdf', 'application/zip', 'application/x-zip-compressed'].includes(type)) return true;
    return DRIVE_BINARY_EXTENSIONS.has(ext);
}

function driveMimeTypeForFile(file) {
    if (file.type) return file.type;
    const ext = fileExtension(file.name);
    if (ext === 'pdf') return 'application/pdf';
    if (ext === 'doc') return 'application/msword';
    if (ext === 'docx') return 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
    if (ext === 'xls') return 'application/vnd.ms-excel';
    if (ext === 'xlsx') return 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
    if (ext === 'ppt') return 'application/vnd.ms-powerpoint';
    if (ext === 'pptx') return 'application/vnd.openxmlformats-officedocument.presentationml.presentation';
    if (ext === 'zip') return 'application/zip';
    return mediaMimeTypeForFile(file, attachmentKind(file)) || 'application/octet-stream';
}

function fileExtension(name = '') {
    const match = String(name).toLowerCase().match(/\.([^.]+)$/);
    return match ? match[1] : '';
}

function normalizeAttachmentText(text = '') {
    return String(text)
        .replace(/\r\n/g, '\n')
        .replace(/\r/g, '\n')
        .replace(/\u0000/g, '')
        .trim();
}

function removeAttachment(id) {
    attachedContexts = attachedContexts.filter((item) => item.id !== id);
    renderModes();
    updateSendState();
    updateChatNavigationOffset();
}

function clearAttachments() {
    attachedContexts = [];
    renderModes();
    updateSendState();
    updateChatNavigationOffset();
}

function buildAttachmentContext(items = attachedContexts) {
    const ready = items.filter((item) => item.status === 'ready' && (item.content || item.dataUrl));
    if (!ready.length) return '';

    let remaining = MAX_TOTAL_ATTACHMENT_CHARS;
    const sections = [];
    ready.forEach((item, index) => {
        if (remaining <= 0) return;
        const isText = item.kind === 'text';
        const content = isText ? item.content.slice(0, remaining) : (item.content || mediaAttachmentSummary(item, item.kind || 'file'));
        remaining -= isText ? content.length : 0;
        const truncated = item.truncated || (isText && item.content.length > content.length);
        sections.push([
            `### ${index + 1}. ${item.name}`,
            `类型：${item.kind || 'file'}`,
            `MIME/扩展名：${item.type || fileExtension(item.name) || '未知'}`,
            `大小：${formatBytes(item.size)}`,
            item.dataUrl ? '媒体数据：已随结构化聊天请求上传' : '',
            truncated ? `备注：${t('attachments.truncated')}` : '',
            isText ? '内容：' : '描述：',
            content,
        ].filter(Boolean).join('\n'));
    });

    if (!sections.length) return '';
    return `${t('attachments.contextTitle')}\n${t('attachments.contextIntro')}\n\n${sections.join('\n\n')}`;
}

function attachmentSummary(items = attachedContexts) {
    return items
        .filter((item) => item.status === 'ready' && (item.content || item.dataUrl))
        .map((item) => ({
            name: item.name,
            size: item.size,
            kind: item.kind || 'file',
            truncated: Boolean(item.truncated),
        }));
}

function defaultAttachmentPrompt() {
    if (currentAgentId === 'image_generation_v1') return t('attachments.imageDefaultPrompt');
    if (currentAgentId === 'weight_loss_v1') return t('attachments.weightLossDefaultPrompt');
    return t('attachments.defaultPrompt');
}

function chatAttachmentPayload(items = attachedContexts) {
    return items
        .filter((item) => item.status === 'ready' && (item.content || item.dataUrl))
        .map((item) => ({
            name: item.name,
            type: item.type || '',
            size: item.size || 0,
            kind: item.kind || 'file',
            content: item.content || '',
            data_url: item.dataUrl || '',
            truncated: Boolean(item.truncated),
        }));
}

function driveWriteToolsUsed(resp) {
    const skills = Array.isArray(resp?.skills_used) ? resp.skills_used : [];
    return skills.some((skill) => skill === 'save_drive' || skill === 'mkdir_drive');
}

function isAgentPinned(agentId) {
    return pinnedAgentIds.includes(agentId);
}

function togglePinnedAgent(agentId) {
    if (isAgentPinned(agentId)) {
        pinnedAgentIds = pinnedAgentIds.filter((id) => id !== agentId);
    } else {
        pinnedAgentIds = [...pinnedAgentIds, agentId];
    }
    savePinnedAgents();
    renderPinnedAgents();
    renderAgents();
}

async function loadConversations() {
    const data = await apiCall('GET', '/api/conversations');
    conversations = data.conversations || [];
    const current = currentConversationRecord();
    if (current) applyConversationAgent(current);
    renderConversationList();
    updateTopbar();
}

async function createConversation() {
    const conv = await apiCall('POST', '/api/conversations', {
        user_id: currentUserId,
        agent_id: currentAgentId || SUPER_CHAT_AGENT_ID,
    });
    conversations.unshift(conv);
    currentConversationId = conv.id;
    saveCurrentConversationId(currentConversationId);
    saveSelectedModes(currentConversationId);
    renderConversationList();
    updateTopbar();
    return conv;
}

async function loadConversation(id) {
    return apiCall('GET', `/api/conversations/${encodeURIComponent(id)}`);
}

async function deleteConversation(id) {
    if (!id || pendingConversationDeletes.has(id)) return;
    if (!window.confirm(t('actions.confirmDeleteConversation'))) return;

    pendingConversationDeletes.add(id);
    renderConversationList();
    try {
        await apiCall('DELETE', `/api/conversations/${encodeURIComponent(id)}`);
        forgetConversationRender(id);
        conversations = conversations.filter((c) => c.id !== id);
        if (currentConversationId === id) {
            currentConversationId = null;
            saveCurrentConversationId(null);
            clearQuestionHistory();
            showWelcome();
        }
        updateTopbar();
    } finally {
        pendingConversationDeletes.delete(id);
        renderConversationList();
    }
}

async function loadProjects() {
    projectError = '';
    try {
        const data = await apiCall('GET', '/api/drive/tree');
        projectDetail = {
            items: Array.isArray(data.items) ? data.items : [],
            flat_items: Array.isArray(data.flat_items) ? data.flat_items : [],
        };
        projects = projectDetail.flat_items;
        const root = driveRootItem();
        if (!currentProjectId || !driveItemIsFolder(currentProjectId)) {
            currentProjectId = root?.id || '';
            saveCurrentProjectId(currentProjectId);
        }
        if (!chatDrivePathId || !driveItemIsFolder(chatDrivePathId)) {
            chatDrivePathId = root?.id || '';
            saveChatDrivePathId(chatDrivePathId);
        }
        if (activeProjectDocumentId && !driveItemById(activeProjectDocumentId)) {
            activeProjectDocumentId = '';
        }
        if (projectInlineFileId && driveItemById(projectInlineFileId)?.type !== 'file') {
            projectInlineFileId = '';
            projectInlineFileDetail = { item: null, loading: false, error: '' };
        }
        collapsedDriveFolderIds = new Set(Array.from(collapsedDriveFolderIds).filter((id) => driveItemIsFolder(id)));
        saveDriveCollapsedFolderIds();
        driveRecentPathIds = driveRecentPathIds.filter((id) => driveItemIsFolder(id));
        if (root?.id) rememberDrivePath(root.id, { render: false });
        selectedProjectDocumentIds = new Set(Array.from(selectedProjectDocumentIds).filter((id) => driveSelectableItem(driveItemById(id))));
        if (lastSelectedProjectDocumentId && !selectedProjectDocumentIds.has(lastSelectedProjectDocumentId)) {
            lastSelectedProjectDocumentId = Array.from(selectedProjectDocumentIds).pop() || '';
        }
        renderProjectList();
        updateCounts();
        renderProjects();
        renderModes();
    } catch (err) {
        projects = [];
        projectDetail = { items: [], flat_items: [] };
        projectError = t('projects.loadFailed', { message: err.message });
        renderProjectList();
        renderProjects();
        updateCounts();
    }
}

async function loadProjectDetail(id = currentProjectId) {
    const item = id ? driveItemById(id) : null;
    if (!id || item?.type === 'folder') {
        currentProjectId = id || '';
        saveCurrentProjectId(currentProjectId);
        rememberDrivePath(currentProjectId, { render: false });
    } else if (item?.type === 'file') {
        currentProjectId = item.parent_id || '';
        activeProjectDocumentId = item.id;
        saveCurrentProjectId(currentProjectId);
        rememberDrivePath(currentProjectId, { render: false });
    }
    renderProjectList();
    renderProjects();
    return projectDetail;
}

function currentProjectRecord(id = currentProjectId) {
    if (!id) {
        return driveRootItem() || { id: '', name: t('projects.rootName'), type: 'folder', parent_id: '' };
    }
    return driveItemById(id);
}

function projectDocuments() {
    return driveChildren(currentProjectId);
}

function projectLinks() {
    return driveItems().filter((item) => item.type === 'folder');
}

async function createProject(name = '') {
    const requestedName = String(name || window.prompt(t('projects.createTitle'), t('projects.createPlaceholder')) || '').trim();
    if (!requestedName) return null;
    const data = await apiCall('POST', '/api/drive/folders', {
        parent_id: currentProjectId || '',
        name: requestedName,
    });
    const folder = data.item;
    if (folder?.id) {
        currentProjectId = folder.id;
        saveCurrentProjectId(folder.id);
        activeProjectDocumentId = '';
        projectInlineFileId = '';
        projectInlineFileDetail = { item: null, loading: false, error: '' };
        projectAskAnswer = '';
        projectAskSources = [];
        setView('projects', { skipLoad: true });
        await loadProjects();
        rememberDrivePath(folder.id, { render: false });
    }
    return folder || null;
}

async function deleteProject(id) {
    if (!id || pendingProjectDeletes.has(id)) return;
    const item = driveItemById(id);
    if (!window.confirm(t('actions.confirmDeleteProject', { name: driveDisplayName(item) || id }))) return;

    pendingProjectDeletes.add(id);
    renderProjectList();
    renderProjects();
    try {
        await apiCall('DELETE', `/api/drive/items/${encodeURIComponent(id)}`);
        selectedProjectDocumentIds.delete(id);
        if (lastSelectedProjectDocumentId === id) lastSelectedProjectDocumentId = '';
        if (activeProjectDocumentId === id) activeProjectDocumentId = '';
        if (projectInlineFileId === id || driveHasAncestor(projectInlineFileId, id)) {
            projectInlineFileId = '';
            projectInlineFileDetail = { item: null, loading: false, error: '' };
        }
        if (currentProjectId === id || driveHasAncestor(currentProjectId, id)) {
            currentProjectId = item?.parent_id || '';
            saveCurrentProjectId(currentProjectId);
            activeProjectDocumentId = '';
            projectAskAnswer = '';
            projectAskSources = [];
        }
        if (chatDrivePathId === id || driveHasAncestor(chatDrivePathId, id)) {
            chatDrivePathId = item?.parent_id || driveRootItem()?.id || '';
            saveChatDrivePathId(chatDrivePathId);
        }
        await loadProjects();
    } catch (err) {
        projectStatusText = t('projects.deleteFailed', { message: err.message });
        projectStatusType = 'error';
        renderProjects();
    } finally {
        pendingProjectDeletes.delete(id);
        renderProjectList();
    }
}

async function reorderProject(id, direction) {
    void id;
    void direction;
}

async function selectProject(id) {
    const item = id ? driveItemById(id) : driveRootItem();
    if (!id || item?.type === 'folder') {
        currentProjectId = item?.id || '';
        saveCurrentProjectId(currentProjectId);
        rememberDrivePath(currentProjectId, { render: false });
        activeProjectDocumentId = '';
    } else if (item?.type === 'file') {
        currentProjectId = item.parent_id || '';
        activeProjectDocumentId = item.id;
        saveCurrentProjectId(currentProjectId);
        rememberDrivePath(currentProjectId, { render: false });
    }
    setView('projects', { skipLoad: true });
    renderProjectList();
    renderProjects();
    closeMobileSidebar();
}

function setProjectStatus(text = '', type = 'muted') {
    projectStatusText = text;
    projectStatusType = type;
    renderProjects();
}

async function createProjectDocument(projectId, payload) {
    const name = payload.name || payload.title || payload.source_name || t('projects.generatedDocDefaultTitle');
    const data = await apiCall('POST', '/api/drive/files', {
        parent_id: projectId || '',
        name,
        mime_type: payload.mime_type || 'text/plain; charset=utf-8',
        encoding: payload.encoding || '',
        content: payload.content || '',
        summary: payload.summary || '',
        tags: Array.isArray(payload.tags) ? payload.tags : [],
    });
    await loadProjects();
    if (data.item?.id) {
        activeProjectDocumentId = data.item.id;
        currentProjectId = data.item.parent_id || currentProjectId || '';
        saveCurrentProjectId(currentProjectId);
        renderProjects();
    }
    return data.item;
}

async function deleteProjectDocument(projectId, documentId) {
    void projectId;
    if (!documentId || pendingProjectDocumentDeletes.has(documentId)) return;
    const item = driveItemById(documentId);
    if (!window.confirm(t('actions.confirmDeleteDocument', { name: driveDisplayName(item) || documentId }))) return;
    pendingProjectDocumentDeletes.add(documentId);
    renderProjects();
    try {
        await apiCall('DELETE', `/api/drive/items/${encodeURIComponent(documentId)}`);
        selectedProjectDocumentIds.delete(documentId);
        if (lastSelectedProjectDocumentId === documentId) lastSelectedProjectDocumentId = '';
        if (activeProjectDocumentId === documentId) activeProjectDocumentId = '';
        if (projectInlineFileId === documentId) {
            projectInlineFileId = '';
            projectInlineFileDetail = { item: null, loading: false, error: '' };
        }
        if (currentProjectId === documentId || driveHasAncestor(currentProjectId, documentId)) {
            currentProjectId = item?.parent_id || '';
            saveCurrentProjectId(currentProjectId);
        }
        await loadProjects();
    } catch (err) {
        setProjectStatus(t('projects.deleteFailed', { message: err.message }), 'error');
    } finally {
        pendingProjectDocumentDeletes.delete(documentId);
        renderProjects();
    }
}

async function searchProjectDocuments(query = projectSearchQuery, options = {}) {
    const { render = true } = options;
    projectSearchQuery = String(query || '');
    if (!projectSearchQuery.trim()) {
        projectSearchResults = [];
        if (render) renderProjects();
        return [];
    }
    const data = await apiCall('GET', `/api/drive/search?q=${encodeURIComponent(projectSearchQuery.trim())}`);
    projectSearchResults = Array.isArray(data.results) ? data.results : [];
    if (render) renderProjects();
    return projectSearchResults;
}

function scheduleProjectSearch(inputEl, delay = PROJECT_SEARCH_DEBOUNCE_MS) {
    if (!inputEl) return;
    projectSearchQuery = inputEl.value || '';
    if (projectSearchComposing) return;
    const cursor = inputEl.selectionStart;
    const query = projectSearchQuery;
    clearTimeout(projectSearchDebounceTimer);
    projectSearchDebounceTimer = setTimeout(() => {
        void runProjectSearch(query, cursor);
    }, delay);
}

async function runProjectSearch(query = projectSearchQuery, cursor = null) {
    const requestSeq = ++projectSearchRequestSeq;
    try {
        await searchProjectDocuments(query, { render: false });
        if (requestSeq !== projectSearchRequestSeq) return;
        renderProjects();
        const nextSearch = document.querySelector('[data-project-search]');
        if (nextSearch && document.activeElement !== nextSearch) {
            nextSearch.focus({ preventScroll: true });
        }
        if (nextSearch && typeof cursor === 'number' && nextSearch.setSelectionRange) {
            nextSearch.setSelectionRange(cursor, cursor);
        }
    } catch (err) {
        if (requestSeq !== projectSearchRequestSeq) return;
        projectStatusText = err.message;
        projectStatusType = 'error';
        renderProjects();
    }
}

async function handleProjectUpload(files) {
    if (projectUploadBusy) return;
    const list = Array.from(files || []);
    if (!list.length) return;
    projectUploadBusy = true;
    setProjectStatus('', 'muted');
    let uploaded = 0;
    try {
        for (const file of list) {
            if (isReadableAttachment(file)) {
                const rawText = await file.text();
                let content = normalizeAttachmentText(rawText);
                if (!content) throw new Error(`${file.name}: ${t('attachments.empty')}`);
                if (content.length > PROJECT_MAX_DOCUMENT_CHARS) {
                    content = content.slice(0, PROJECT_MAX_DOCUMENT_CHARS);
                }
                await createProjectDocument(currentProjectId, {
                    title: file.name || '',
                    source_name: file.name || '',
                    type: 'source',
                    mime_type: file.type || 'text/plain; charset=utf-8',
                    content,
                });
                uploaded += 1;
                continue;
            }
            if (!isSupportedDriveBinaryFile(file)) {
                throw new Error(`${file.name}: ${t('attachments.unsupported')}`);
            }
            if (file.size > MAX_DRIVE_BINARY_BYTES) {
                throw new Error(`${file.name}: ${t('attachments.tooLarge', { size: formatBytes(MAX_DRIVE_BINARY_BYTES) })}`);
            }
            const content = dataUrlBase64Content(await readFileAsDataURL(file));
            if (!content) throw new Error(`${file.name}: ${t('attachments.readFailed', { message: 'empty data' })}`);
            await createProjectDocument(currentProjectId, {
                title: file.name || '',
                source_name: file.name || '',
                type: 'source',
                mime_type: driveMimeTypeForFile(file),
                encoding: 'base64',
                content,
                summary: `${t('projects.uploadBinaryNote')} ${formatBytes(file.size || 0)}`,
            });
            uploaded += 1;
        }
        setProjectStatus(t('projects.uploadDone', { count: uploaded }), 'ok');
    } catch (err) {
        setProjectStatus(t('projects.uploadFailed', { message: err.message }), 'error');
    } finally {
        projectUploadBusy = false;
        if (projectUploadInput) projectUploadInput.value = '';
        renderProjects();
    }
}

async function ensureProjectConversation(projectId) {
    const storedId = loadProjectConversationId(projectId || 'root');
    if (storedId && conversations.some((conv) => conv.id === storedId)) {
        return conversations.find((conv) => conv.id === storedId);
    }
    if (storedId) {
        try {
            const existing = await loadConversation(storedId);
            if (existing?.conversation?.id) {
                if (!conversations.some((conv) => conv.id === existing.conversation.id)) {
                    conversations.unshift(existing.conversation);
                    renderConversationList();
                }
                return existing.conversation;
            }
        } catch {
            saveProjectConversationId(projectId, '');
        }
    }
    const conv = await apiCall('POST', '/api/conversations', {
        user_id: currentUserId,
        agent_id: SUPER_CHAT_AGENT_ID,
    });
    conversations.unshift(conv);
    saveProjectConversationId(projectId || 'root', conv.id);
    renderConversationList();
    return conv;
}

async function askProject(queryOverride = '') {
    if (projectAskLoading) return;
    const query = String(queryOverride || projectAskInput || '').trim();
    if (!query) return;
    projectAskLoading = true;
    projectAskError = '';
    projectAskInput = query;
    renderProjects();
    try {
        const contextData = await apiCall('POST', '/api/drive/context', {
            query,
            item_ids: Array.from(selectedProjectDocumentIds),
        });
        const conversation = await ensureProjectConversation(currentProjectId || 'root');
        const model = modelSelect.value || undefined;
        const resp = await apiCall('POST', '/api/chat', {
            conversation_id: conversation.id,
            user_id: currentUserId,
            query,
            stream: false,
            model_preference: model || undefined,
            agent_id: SUPER_CHAT_AGENT_ID,
            role_id: currentRoleId || undefined,
            context_blocks: Array.isArray(contextData.context_blocks) ? contextData.context_blocks : [],
        });
        projectAskAnswer = resp.response || '';
        projectAskSources = Array.isArray(contextData.items) ? contextData.items : [];
        captureMemoryDebug(resp, conversation.id);
        void Promise.allSettled([loadConversations(), loadRuns()]);
    } catch (err) {
        projectAskError = err.message;
    } finally {
        projectAskLoading = false;
        renderProjects();
    }
}

async function expandProjectMap() {
    projectAskInput = t('projects.expandPrompt');
    await askProject(projectAskInput);
}

async function saveProjectAnswerAsDocument() {
    if (!projectAskAnswer.trim()) return;
    const result = await openDriveSaveDialog({
        title: t('projects.generatedDocDefaultTitle'),
        content: projectAskAnswer,
        defaultFolderId: currentProjectId || driveRootItem()?.id || '',
        returnFocus: document.querySelector('[data-project-save-answer]'),
        onSave: ({ title, folderId, content }) => createProjectDocument(folderId, {
            title,
            type: 'generated',
            source_document_id: selectedProjectDocumentIds.size === 1 ? Array.from(selectedProjectDocumentIds)[0] : '',
            content,
        }),
    });
    if (result?.saved) {
        setProjectStatus(t('projects.saveDone'), 'ok');
    }
}

async function saveAssistantMessageToDrive(button) {
    const message = button.closest('[data-copy-text]');
    const text = message?.dataset.copyText || '';
    if (!text.trim()) return;
    if (!currentConversationId || activeConversationRequests.has(currentConversationId)) return;
    button.disabled = true;
    button.setAttribute('aria-disabled', 'true');
    try {
        const result = await openDriveSaveDialog({
            title: defaultDriveFileName(text),
            content: text,
            defaultFolderId: chatDrivePathItem()?.id || driveRootItem()?.id || '',
            returnFocus: button,
            closeOnSaveStart: true,
            onSave: ({ title, folderId, content }) => generateAssistantReportToDrive({
                title,
                folderId,
                content,
            }),
            onBackgroundSaveDone: () => {
                projectStatusText = t('projects.saveDone');
                projectStatusType = 'ok';
                renderProjectList();
                if (activeView === 'projects') renderProjects();
            },
            onBackgroundSaveError: (err) => {
                if (isCancelledError(err)) return;
                projectStatusText = t('projects.saveFailed', { message: err.message });
                projectStatusType = 'error';
                if (activeView === 'projects') renderProjects();
            },
        });
        if (!result?.saved) return;
        projectStatusText = t('projects.saveDone');
        projectStatusType = 'ok';
        renderProjectList();
        if (activeView === 'projects') renderProjects();
    } catch (err) {
        projectStatusText = t('projects.saveFailed', { message: err.message });
        projectStatusType = 'error';
        if (activeView === 'projects') renderProjects();
    } finally {
        button.disabled = false;
        button.removeAttribute('aria-disabled');
    }
}

async function generateAssistantReportToDrive({ title, folderId, content }) {
    const conversationId = currentConversationId;
    if (!conversationId) throw new Error(t('chat.createConversationFailed', { message: '' }));
    if (activeConversationRequests.has(conversationId)) throw new Error(t('errors.requestFailed'));

    const folder = driveItemById(folderId) || chatDrivePathItem() || driveRootItem();
    const safeTitle = String(title || defaultDriveFileName(content)).trim();
    const reportRunId = createClientRunId();
    const cancelTaskId = createClientTaskId('report-save');
    const controller = new AbortController();
    let cancelled = false;
    const query = currentLanguage === 'zh'
        ? `请基于上一条助手回答生成 Markdown 报告，并保存到网盘文件「${safeTitle}」。`
        : `Generate a Markdown report from the previous assistant answer and save it to Drive as "${safeTitle}".`;
    const contextBlock = [
        '【Report generation source】',
        'The following is the assistant answer that must be transformed into a clean, reusable Markdown report.',
        '',
        content,
    ].join('\n');
    const instruction = [
        `目标文件名：${safeTitle}`,
        `目标 folder_id：${folder?.id || folderId || ''}`,
        '必须调用 save_drive 工具保存报告。save_drive 参数使用：name=目标文件名，folder_id=目标 folder_id，mime_type=text/markdown; charset=utf-8，content=生成后的 Markdown 报告正文。',
        '保存成功后只简短说明已保存，不要在聊天里重复输出完整报告正文。',
    ].join('\n');
    const fullQuery = `${query}\n\n${instruction}`;

    activeConversationRequests.add(conversationId);
    forgetConversationRender(conversationId);
    removeFollowUpMessages();
    updateSendState();
    const streamView = appendStreamingAssistantMessage('', conversationId, {
        cancelTaskId,
        onCancel: () => {
            if (cancelled) return;
            cancelled = true;
            streamView.setPending(t('projects.canceling'));
            void requestRunCancellation(reportRunId);
            controller.abort();
        },
    });
    streamView.setPending(t('projects.saveTaskStarted', { title: safeTitle }));
    scrollToBottom();
    try {
        const resp = await sendMessageStream(conversationId, fullQuery, streamView, '', [], {
            agent_id: SUPER_CHAT_AGENT_ID,
            mode_ids: [],
            mode_prompts: [],
            context_blocks: [contextBlock],
            run_id: reportRunId,
            suppress_user_message: true,
            suppress_follow_ups: true,
            signal: controller.signal,
        });
        streamView.finalize(resp);
        captureMemoryDebug(resp, conversationId);
        if (driveWriteToolsUsed(resp)) await loadProjects();
        void Promise.allSettled([loadConversations(), loadRuns()]).then(() => {
            if (currentConversationId === conversationId) updateTopbar();
        });
        const artifact = normalizeArtifacts(resp.artifacts || []).find((item) => item.type === 'drive_file');
        if (!artifact) throw new Error(t('projects.saveFailed', { message: t('errors.requestFailed') }));
        return driveItemById(artifact.item_id) || driveArtifactAsItem(artifact);
    } catch (err) {
        if (cancelled || isCancelledError(err)) {
            streamView.showCancelled(t('projects.saveCancelled'));
            throw markCancelledError(err);
        }
        streamView.showError(`Error: ${err.message}`);
        throw err;
    } finally {
        activeConversationRequests.delete(conversationId);
        updateSendState();
        if (currentConversationId === conversationId) {
            scrollToBottom();
            focusMessageInput();
        }
    }
}

function defaultDriveFileName(content = '') {
    const text = String(content || '').replace(/\r/g, '\n');
    const lines = text.split('\n').map((line) => line.trim()).filter(Boolean);
    const candidates = [];
    const heading = lines.find((line) => /^#{1,3}\s+\S/.test(line));
    if (heading) candidates.push(heading);
    const boldTitle = lines.find((line) => /^\*\*[^*]{4,80}\*\*$/.test(line));
    if (boldTitle) candidates.push(boldTitle);
    candidates.push(...lines.slice(0, 8));

    const base = candidates
        .map(cleanDriveFileNameCandidate)
        .find((value) => value.length >= 4 && !looksLikeDriveFilenameNoise(value));
    const fallback = cleanDriveFileNameCandidate(t('projects.generatedDocDefaultTitle').replace(/\.md$/i, ''));
    const name = truncateText(base || fallback || 'Super Chat Report', 48).replace(/\.md$/i, '').trim();
    return `${name || 'Super Chat Report'}.md`;
}

function cleanDriveFileNameCandidate(value = '') {
    const withoutImages = String(value)
        .replace(/!\[[^\]]*]\([^)]+\)/g, '')
        .replace(/\[([^\]]+)]\([^)]+\)/g, '$1')
        .replace(/`([^`]+)`/g, '$1')
        .replace(/^#{1,6}\s+/, '')
        .replace(/^>\s*/, '')
        .replace(/^[-*+]\s+/, '')
        .replace(/^\d+[.)、]\s+/, '')
        .replace(/^\*\*(.*)\*\*$/, '$1')
        .replace(/^(当然|好的|可以|下面是|以下是|Sure|Here is|Absolutely)[，,\s]+/i, '')
        .replace(/[\\/:*?"<>|]/g, '')
        .replace(/[\u0000-\u001f]/g, '')
        .replace(/\s+/g, ' ')
        .trim();
    const firstSentence = withoutImages.split(/[。.!?！？；;]/).map((part) => part.trim()).find(Boolean) || withoutImages;
    return firstSentence.replace(/[.。]+$/g, '').trim();
}

function looksLikeDriveFilenameNoise(value = '') {
    const text = String(value).trim();
    if (!text) return true;
    if (/^https?:\/\//i.test(text)) return true;
    if (/^[-*_`~]+$/.test(text)) return true;
    if (/^(摘要|总结|结论|回答|执行摘要|Report|Summary)$/i.test(text)) return true;
    return false;
}

function createClientRunId() {
    const id = crypto?.randomUUID?.().replace(/-/g, '')
        || `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;
    return `run_${id}`;
}

function createClientTaskId(prefix = 'task') {
    return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 9)}`;
}

function isCancelledError(err) {
    return err?.cancelled === true || err?.name === 'AbortError' || err?.errorType === 'cancelled' || err?.message === 'cancelled';
}

function markCancelledError(err) {
    const error = err instanceof Error ? err : new Error(t('projects.saveCancelled'));
    error.cancelled = true;
    return error;
}

async function requestRunCancellation(runId) {
    if (!runId) return;
    for (let attempt = 0; attempt < 3; attempt += 1) {
        try {
            await apiCall('POST', `/api/runs/${encodeURIComponent(runId)}/cancel`, {});
            return;
        } catch (err) {
            if (attempt >= 2) {
                console.warn('Cancel run failed', err);
                return;
            }
            await wait(150);
        }
    }
}

function createEmptyDriveSaveDialogState() {
    return {
        open: false,
        saving: false,
        title: '',
        content: '',
        targetFolderId: '',
        error: '',
        returnFocus: null,
        onSave: null,
        onBackgroundSaveDone: null,
        onBackgroundSaveError: null,
        closeOnSaveStart: false,
        resolve: null,
    };
}

function driveSaveDialogIsOpen() {
    return Boolean(driveSaveDialogState.open);
}

async function openDriveSaveDialog(options = {}) {
    const content = String(options.content || '');
    if (!content.trim()) return { saved: false };
    if (driveSaveDialogState.open) closeDriveSaveDialog({ saved: false }, { force: true });

    const resultPromise = new Promise((resolve) => {
        driveSaveDialogState = {
            ...createEmptyDriveSaveDialogState(),
            open: true,
            title: String(options.title || defaultDriveFileName(content)),
            content,
            returnFocus: options.returnFocus || document.activeElement,
            onSave: typeof options.onSave === 'function' ? options.onSave : null,
            onBackgroundSaveDone: typeof options.onBackgroundSaveDone === 'function' ? options.onBackgroundSaveDone : null,
            onBackgroundSaveError: typeof options.onBackgroundSaveError === 'function' ? options.onBackgroundSaveError : null,
            closeOnSaveStart: Boolean(options.closeOnSaveStart),
            resolve,
        };
    });

    renderDriveSaveDialog();

    try {
        const root = await ensureDriveTreeForSave();
        if (!driveSaveDialogState.open) return resultPromise;
        driveSaveDialogState.targetFolderId = normalizeDriveSaveFolderId(options.defaultFolderId, root.id);
        renderDriveSaveDialog();
        requestAnimationFrame(() => {
            driveSaveNameInput?.focus({ preventScroll: true });
            driveSaveNameInput?.select?.();
        });
    } catch (err) {
        if (driveSaveDialogState.open) {
            driveSaveDialogState.error = err.message || t('projects.pathRequired');
            renderDriveSaveDialog();
        }
    }

    return resultPromise;
}

async function ensureDriveTreeForSave() {
    if (!currentUserId) {
        showAccountLogin();
        throw new Error(t('account.loginTitle'));
    }
    if (!driveRootItem() || projectError) {
        await loadProjects();
    }
    const root = driveRootItem();
    if (!root) throw new Error(projectError || t('projects.pathRequired'));
    return root;
}

function normalizeDriveSaveFolderId(folderId = '', fallbackId = '') {
    const candidate = driveItemById(folderId);
    if (candidate?.type === 'folder') return candidate.id;
    const fallback = driveItemById(fallbackId);
    if (fallback?.type === 'folder') return fallback.id;
    return driveRootItem()?.id || '';
}

function closeDriveSaveDialog(result = { saved: false }, options = {}) {
    if (!driveSaveDialogState.open) return;
    if (driveSaveDialogState.saving && !options.force) return;

    const resolve = driveSaveDialogState.resolve;
    const returnFocus = driveSaveDialogState.returnFocus;
    driveSaveDialogState = createEmptyDriveSaveDialogState();
    renderDriveSaveDialog();
    if (typeof resolve === 'function') resolve(result);
    requestAnimationFrame(() => {
        if (returnFocus && typeof returnFocus.focus === 'function') {
            returnFocus.focus({ preventScroll: true });
        }
    });
}

function renderDriveSaveDialog() {
    if (!driveSaveDialog) return;
    const isOpen = driveSaveDialogState.open;
    driveSaveDialog.classList.toggle('hidden', !isOpen);
    document.body.classList.toggle('drive-save-open', isOpen);
    if (!isOpen) {
        if (driveSaveNameInput) driveSaveNameInput.value = '';
        if (driveSaveTree) driveSaveTree.innerHTML = '';
        if (driveSavePathCurrent) driveSavePathCurrent.textContent = '';
        if (driveSaveError) driveSaveError.textContent = '';
        if (btnDriveSaveConfirm) btnDriveSaveConfirm.textContent = t('actions.save');
        return;
    }

    if (driveSaveNameInput && driveSaveNameInput.value !== driveSaveDialogState.title) {
        driveSaveNameInput.value = driveSaveDialogState.title;
    }
    if (driveSavePathCurrent) {
        const path = driveSaveDialogState.targetFolderId ? driveBreadcrumbText(driveSaveDialogState.targetFolderId) : '';
        driveSavePathCurrent.textContent = path ? t('projects.pathCurrent', { path }) : '';
    }
    if (driveSaveTree) {
        const roots = driveSaveFolderTreeRoots();
        driveSaveTree.innerHTML = roots.length
            ? roots.map((item) => renderDriveSaveFolderOption(item)).join('')
            : `<div class="drive-save-empty">${escapeHtml(t('projects.pathEmpty'))}</div>`;
    }
    if (driveSaveError) {
        driveSaveError.textContent = driveSaveDialogState.error || '';
        driveSaveError.classList.toggle('visible', Boolean(driveSaveDialogState.error));
    }
    if (btnDriveSaveConfirm) {
        btnDriveSaveConfirm.disabled = driveSaveDialogState.saving || !driveSaveDialogState.targetFolderId;
        btnDriveSaveConfirm.setAttribute('aria-busy', driveSaveDialogState.saving ? 'true' : 'false');
        btnDriveSaveConfirm.textContent = driveSaveDialogState.saving ? t('projects.saving') : t('actions.save');
    }
    driveSaveDialog.querySelectorAll('[data-drive-save-cancel]').forEach((button) => {
        button.disabled = driveSaveDialogState.saving;
    });
}

function createEmptyDrivePathDialogState() {
    return {
        open: false,
        targetFolderId: '',
        error: '',
        returnFocus: null,
    };
}

function drivePathDialogIsOpen() {
    return Boolean(drivePathDialogState.open);
}

async function openChatDrivePathDialog(returnFocus = null) {
    if (drivePathDialogState.open) closeDrivePathDialog();
    drivePathDialogState = {
        ...createEmptyDrivePathDialogState(),
        open: true,
        targetFolderId: chatDrivePathItem()?.id || driveRootItem()?.id || '',
        returnFocus: returnFocus || document.activeElement,
    };
    renderDrivePathDialog();
    try {
        const root = await ensureDriveTreeForSave();
        if (!drivePathDialogState.open) return;
        drivePathDialogState.targetFolderId = normalizeDriveSaveFolderId(drivePathDialogState.targetFolderId, root.id);
        renderDrivePathDialog();
    } catch (err) {
        if (drivePathDialogState.open) {
            drivePathDialogState.error = err.message || t('projects.pathRequired');
            renderDrivePathDialog();
        }
    }
}

function closeDrivePathDialog() {
    if (!drivePathDialogState.open) return;
    const returnFocus = drivePathDialogState.returnFocus;
    drivePathDialogState = createEmptyDrivePathDialogState();
    renderDrivePathDialog();
    requestAnimationFrame(() => {
        if (returnFocus && typeof returnFocus.focus === 'function') {
            returnFocus.focus({ preventScroll: true });
        }
    });
}

function renderDrivePathDialog() {
    if (!drivePathDialog) return;
    const isOpen = drivePathDialogState.open;
    drivePathDialog.classList.toggle('hidden', !isOpen);
    document.body.classList.toggle('drive-path-open', isOpen);
    if (!isOpen) {
        if (drivePathTree) drivePathTree.innerHTML = '';
        if (drivePathCurrent) drivePathCurrent.textContent = '';
        if (drivePathError) drivePathError.textContent = '';
        return;
    }

    if (drivePathCurrent) {
        const path = drivePathDialogState.targetFolderId ? driveBreadcrumbText(drivePathDialogState.targetFolderId) : '';
        drivePathCurrent.textContent = path ? t('projects.pathCurrent', { path }) : '';
    }
    if (drivePathTree) {
        const roots = driveSaveFolderTreeRoots();
        drivePathTree.innerHTML = roots.length
            ? roots.map((item) => renderDrivePathFolderOption(item)).join('')
            : `<div class="drive-save-empty">${escapeHtml(t('projects.pathEmpty'))}</div>`;
    }
    if (drivePathError) {
        drivePathError.textContent = drivePathDialogState.error || '';
        drivePathError.classList.toggle('visible', Boolean(drivePathDialogState.error));
    }
    if (btnDrivePathConfirm) {
        btnDrivePathConfirm.disabled = !drivePathDialogState.targetFolderId;
    }
}

function renderDrivePathFolderOption(item, depth = 0) {
    if (!item || item.type !== 'folder') return '';
    const selected = item.id === drivePathDialogState.targetFolderId;
    const childFolders = (Array.isArray(item.children) ? item.children : [])
        .filter((child) => child.type === 'folder');
    return `
        <button class="drive-save-folder ${selected ? 'active' : ''}" type="button"
                data-drive-path-folder="${escapeAttr(item.id)}"
                aria-pressed="${selected ? 'true' : 'false'}"
                style="--drive-depth:${Math.min(depth, 6)}">
            ${driveItemIconSvg(item)}
            <span>
                <strong>${escapeHtml(driveDisplayName(item))}</strong>
                <small>${escapeHtml(driveItemMeta(item))}</small>
            </span>
            ${selected ? '<svg class="drive-save-check" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.6"><path d="m5 12 4 4L19 6"/></svg>' : ''}
        </button>
        ${childFolders.map((child) => renderDrivePathFolderOption(child, depth + 1)).join('')}
    `;
}

function selectDrivePathFolder(folderId = '') {
    if (!drivePathDialogState.open) return;
    drivePathDialogState.targetFolderId = normalizeDriveSaveFolderId(folderId, drivePathDialogState.targetFolderId);
    drivePathDialogState.error = '';
    renderDrivePathDialog();
}

function submitDrivePathDialog() {
    if (!drivePathDialogState.open) return;
    drivePathDialogState.targetFolderId = normalizeDriveSaveFolderId(drivePathDialogState.targetFolderId);
    if (!drivePathDialogState.targetFolderId) {
        drivePathDialogState.error = t('projects.pathRequired');
        renderDrivePathDialog();
        return;
    }
    setChatDrivePath(drivePathDialogState.targetFolderId);
    rememberDrivePath(drivePathDialogState.targetFolderId, { render: false });
    closeDrivePathDialog();
}

function driveSaveFolderTreeRoots() {
    const roots = driveTreeItems().filter((item) => item.type === 'folder');
    if (roots.length) return roots;
    const root = driveRootItem();
    return root ? [root] : [];
}

function renderDriveSaveFolderOption(item, depth = 0) {
    if (!item || item.type !== 'folder') return '';
    const selected = item.id === driveSaveDialogState.targetFolderId;
    const childFolders = (Array.isArray(item.children) ? item.children : [])
        .filter((child) => child.type === 'folder');
    return `
        <button class="drive-save-folder ${selected ? 'active' : ''}" type="button"
                data-drive-save-folder="${escapeAttr(item.id)}"
                aria-pressed="${selected ? 'true' : 'false'}"
                style="--drive-depth:${Math.min(depth, 6)}">
            ${driveItemIconSvg(item)}
            <span>
                <strong>${escapeHtml(driveDisplayName(item))}</strong>
                <small>${escapeHtml(driveItemMeta(item))}</small>
            </span>
            ${selected ? '<svg class="drive-save-check" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.6"><path d="m5 12 4 4L19 6"/></svg>' : ''}
        </button>
        ${childFolders.map((child) => renderDriveSaveFolderOption(child, depth + 1)).join('')}
    `;
}

function selectDriveSaveFolder(folderId = '') {
    if (!driveSaveDialogState.open || driveSaveDialogState.saving) return;
    if (driveSaveNameInput) driveSaveDialogState.title = driveSaveNameInput.value;
    driveSaveDialogState.targetFolderId = normalizeDriveSaveFolderId(folderId, driveSaveDialogState.targetFolderId);
    driveSaveDialogState.error = '';
    renderDriveSaveDialog();
}

async function submitDriveSaveDialog() {
    if (!driveSaveDialogState.open || driveSaveDialogState.saving) return;
    driveSaveDialogState.title = String(driveSaveNameInput?.value || '').trim();
    driveSaveDialogState.targetFolderId = normalizeDriveSaveFolderId(driveSaveDialogState.targetFolderId);
    driveSaveDialogState.error = '';

    if (!driveSaveDialogState.title) {
        driveSaveDialogState.error = t('projects.saveNameRequired');
        renderDriveSaveDialog();
        driveSaveNameInput?.focus({ preventScroll: true });
        return;
    }
    if (!driveSaveDialogState.targetFolderId) {
        driveSaveDialogState.error = t('projects.pathRequired');
        renderDriveSaveDialog();
        return;
    }
    if (typeof driveSaveDialogState.onSave !== 'function') {
        driveSaveDialogState.error = t('projects.saveFailed', { message: t('errors.requestFailed') });
        renderDriveSaveDialog();
        return;
    }

    driveSaveDialogState.saving = true;
    renderDriveSaveDialog();
    const savePayload = {
        title: driveSaveDialogState.title,
        folderId: driveSaveDialogState.targetFolderId,
        content: driveSaveDialogState.content,
    };
    if (driveSaveDialogState.closeOnSaveStart) {
        const onSave = driveSaveDialogState.onSave;
        const onDone = driveSaveDialogState.onBackgroundSaveDone;
        const onError = driveSaveDialogState.onBackgroundSaveError;
        try {
            const savePromise = Promise.resolve(onSave(savePayload));
            rememberDrivePath(savePayload.folderId, { render: false });
            closeDriveSaveDialog({
                saved: false,
                submitted: true,
                title: savePayload.title,
                folderId: savePayload.folderId,
            }, { force: true });
            savePromise.then((savedItem) => {
                if (typeof onDone === 'function') {
                    onDone({
                        item: savedItem || null,
                        title: savePayload.title,
                        folderId: savePayload.folderId,
                    });
                }
            }).catch((err) => {
                if (typeof onError === 'function') {
                    onError(err);
                } else if (!isCancelledError(err)) {
                    console.warn('Background drive save failed', err);
                }
            });
        } catch (err) {
            driveSaveDialogState.saving = false;
            driveSaveDialogState.error = t('projects.saveFailed', { message: err.message });
            renderDriveSaveDialog();
        }
        return;
    }
    try {
        const savedItem = await driveSaveDialogState.onSave(savePayload);
        rememberDrivePath(savePayload.folderId, { render: false });
        closeDriveSaveDialog({
            saved: true,
            item: savedItem || null,
            title: savePayload.title,
            folderId: savePayload.folderId,
        }, { force: true });
    } catch (err) {
        driveSaveDialogState.saving = false;
        driveSaveDialogState.error = t('projects.saveFailed', { message: err.message });
        renderDriveSaveDialog();
    }
}

async function createProjectFromSelection() {
    selectedProjectDocumentIds = new Set();
    renderModes();
    renderProjects();
}

function toggleProjectDocumentSelection(documentId, selected) {
    if (!driveSelectableItemId(documentId)) return;
    const next = new Set(selectedProjectDocumentIds);
    if (selected) {
        next.add(documentId);
    } else {
        next.delete(documentId);
    }
    setDriveSelection(Array.from(next), { lastId: documentId });
}

function openProjectDocument(documentId, options = {}) {
    const item = driveItemById(documentId);
    if (item?.type === 'folder') {
        enterDriveFolder(item.id);
        return;
    }
    if (item?.type === 'file') {
        if (options.surface === 'detail') {
            activeProjectDocumentId = item.id;
            void openDriveDocumentPreview(item.id);
            renderProjectList();
            renderProjects();
            return;
        }
        void openDriveFileInline(item.id);
        return;
    }
    renderProjectList();
    renderProjects();
}

function clearProjectOpenClickTimer() {
    if (!projectOpenClickTimer) return;
    clearTimeout(projectOpenClickTimer);
    projectOpenClickTimer = null;
}

async function openDriveArtifact(itemId = '') {
    const id = String(itemId || '').trim();
    if (!id) return;
    if (!driveItemById(id)) {
        await loadProjects();
    }
    const item = driveItemById(id);
    if (!item) return;
    if (item.type === 'folder') {
        enterDriveFolder(item.id);
        setView('projects', { skipLoad: true });
        return;
    }
    if (item.type === 'file') {
        await openDriveDocumentPreview(item.id);
    }
}

async function openDriveFileInline(itemId = '') {
    const cached = driveItemById(itemId);
    if (!cached || cached.type !== 'file') return;
    currentProjectId = cached.parent_id || currentProjectId || '';
    activeProjectDocumentId = cached.id;
    projectInlineFileId = cached.id;
    projectInlineFileDetail = { item: cached, loading: true, error: '' };
    saveCurrentProjectId(currentProjectId);
    rememberDrivePath(currentProjectId, { render: false });
    renderProjectList();
    renderProjects();
    try {
        const data = await apiCall('GET', `/api/drive/items/${encodeURIComponent(itemId)}`);
        if (projectInlineFileId !== itemId) return;
        projectInlineFileDetail = { item: data.item || cached, loading: false, error: '' };
        renderProjects();
    } catch (err) {
        if (projectInlineFileId !== itemId) return;
        projectInlineFileDetail = { item: cached, loading: false, error: t('projects.previewFailed', { message: err.message }) };
        renderProjects();
    }
}

function clearDriveFileInlineDetail() {
    if (!projectInlineFileId) return;
    projectInlineFileId = '';
    projectInlineFileDetail = { item: null, loading: false, error: '' };
    renderProjectList();
    renderProjects();
}

async function loadAgents() {
    const data = await apiCall('GET', '/api/agents');
    agents = data.agents || [];
    const currentExists = agents.some((agent) => agent.id === currentAgentId);
    if (!currentExists) {
        const preferred = agents.find((agent) => agent.enabled) || agents[0];
        currentAgentId = preferred ? preferred.id : 'super_chat';
    }
    renderAgentSelect();
    renderPinnedAgents();
    renderAgents();
    renderAgentCommandBar();
    renderModes();
    updateCounts();
}

async function loadRoles() {
    roleMemoryError = '';
    try {
        const data = await apiCall('GET', '/api/roles');
        roles = Array.isArray(data.roles) ? data.roles : [];
        const selectable = selectableRoles();
        if (!selectable.some((role) => role.id === currentRoleId)) {
            currentRoleId = selectable[0]?.id || 'default';
            saveCurrentRoleId();
        }
        renderRoleSelect();
        await loadRoleMemories();
    } catch (err) {
        roles = [];
        roleMemories = [];
        roleMemoryError = t('roleMemory.loadFailed', { message: err.message });
        renderRoleSelect();
        renderRoleMemoryList();
        renderDeveloperView();
    }
}

function selectableRoles() {
    return roles.filter((role) => role && role.id && role.enabled !== false);
}

function localizedRoleText(role, field) {
    const localized = role?.metadata?.localized || {};
    const candidates = [
        localized[currentLanguage]?.[field],
        localized.zh?.[field],
        localized.en?.[field],
        role?.[field],
    ];
    const match = candidates.find((item) => typeof item === 'string' && item.trim());
    return match || '';
}

function roleDisplayName(role) {
    return localizedRoleText(role, 'name') || role?.id || t('roleMemory.defaultRole');
}

function renderRoleSelect() {
    if (!roleSelect) return;
    const selectable = selectableRoles();
    const displayRoles = selectable.length
        ? selectable
        : [{ id: currentRoleId || 'default', name: t('roleMemory.defaultRole'), enabled: true }];
    roleSelect.innerHTML = displayRoles.map((role) => (
        `<option value="${escapeAttr(role.id)}">${escapeHtml(roleDisplayName(role))}</option>`
    )).join('');
    roleSelect.value = displayRoles.some((role) => role.id === currentRoleId)
        ? currentRoleId
        : displayRoles[0]?.id || 'default';
    roleSelect.disabled = displayRoles.length === 0;
}

function setCurrentRole(roleId, { refreshMemory = true } = {}) {
    const selectable = selectableRoles();
    const nextRoleId = roleId || selectable[0]?.id || 'default';
    currentRoleId = selectable.some((role) => role.id === nextRoleId)
        ? nextRoleId
        : selectable[0]?.id || 'default';
    saveCurrentRoleId();
    renderRoleSelect();
    roleMemoryStatusText = '';
    renderDeveloperView();
    if (refreshMemory) {
        void loadRoleMemories();
    }
    if (activeView === 'developer') {
        void loadDeveloperMemory();
    }
}

async function loadRoleMemories() {
    if (!currentUserId || !currentRoleId) {
        roleMemories = [];
        renderRoleMemoryList();
        return;
    }
    roleMemoryError = '';
    try {
        const data = await apiCall('GET', `/api/roles/${encodeURIComponent(currentRoleId)}/memories?kind=role`);
        roleMemories = Array.isArray(data.memories) ? data.memories : [];
    } catch (err) {
        roleMemories = [];
        roleMemoryError = t('roleMemory.loadFailed', { message: err.message });
    }
    renderRoleMemoryList();
}

function renderRoleMemoryList() {
    if (btnRoleMemory) {
        btnRoleMemory.classList.toggle('active', roleMemories.length > 0);
    }
    if (roleMemoryStatus) {
        roleMemoryStatus.textContent = roleMemoryError || roleMemoryStatusText || '';
        roleMemoryStatus.classList.toggle('error', Boolean(roleMemoryError));
    }
    updateRoleMemoryFormState();
    if (!roleMemoryList) return;

    if (roleMemoryError) {
        roleMemoryList.innerHTML = `<div class="role-memory-empty">${escapeHtml(roleMemoryError)}</div>`;
        return;
    }
    if (!roleMemories.length) {
        roleMemoryList.innerHTML = `<div class="role-memory-empty">${escapeHtml(t('roleMemory.empty'))}</div>`;
        return;
    }

    roleMemoryList.innerHTML = roleMemories.map((memory) => {
        const deleting = roleMemoryDeletingIds.has(memory.id);
        const source = memory.source === 'manual' ? t('roleMemory.manual') : t('roleMemory.ai');
        const timeText = formatTime(memory.updated_at || memory.created_at || '');
        const meta = [source, timeText].filter(Boolean).join(' · ');
        return `
            <div class="role-memory-item">
                <div class="role-memory-copy">
                    <p>${escapeHtml(memory.content || '')}</p>
                    <small>${escapeHtml(meta)}</small>
                </div>
                <button class="role-memory-delete" type="button"
                        data-delete-role-memory="${escapeAttr(memory.id)}"
                        title="${escapeAttr(t('actions.delete'))}"
                        aria-label="${escapeAttr(t('actions.delete'))}"
                        ${deleting ? 'disabled aria-busy="true"' : ''}>
                    <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.2">
                        <path d="M3 6h18M8 6V4h8v2M10 11v6M14 11v6M6 6l1 15h10l1-15"/>
                    </svg>
                </button>
            </div>
        `;
    }).join('');
}

function updateRoleMemoryFormState() {
    const button = roleMemoryForm?.querySelector('[data-role-memory-save]');
    if (button) button.disabled = roleMemorySaving || !currentRoleId || !currentUserId;
}

function toggleRoleMemoryPopover() {
    if (!roleMemoryPopover) return;
    const willOpen = roleMemoryPopover.classList.contains('hidden');
    roleMemoryPopover.classList.toggle('hidden', !willOpen);
    if (willOpen) {
        roleMemoryStatusText = '';
        void loadRoleMemories();
        requestAnimationFrame(() => roleMemoryInput?.focus({ preventScroll: true }));
    }
}

function closeRoleMemoryPopover() {
    if (roleMemoryPopover) roleMemoryPopover.classList.add('hidden');
}

async function saveRoleMemory() {
    if (!currentRoleId || !roleMemoryInput || roleMemorySaving) return;
    const content = roleMemoryInput.value.trim();
    if (!content) {
        roleMemoryInput.focus();
        return;
    }

    roleMemorySaving = true;
    roleMemoryError = '';
    roleMemoryStatusText = '';
    updateRoleMemoryFormState();
    try {
        await apiCall('POST', `/api/roles/${encodeURIComponent(currentRoleId)}/memories`, {
            user_id: currentUserId,
            kind: 'role',
            content,
            source: 'manual',
            confidence: 1,
            tags: ['role_config'],
        });
        roleMemoryInput.value = '';
        roleMemoryStatusText = t('roleMemory.saved');
        await loadRoleMemories();
        if (activeView === 'developer') void loadDeveloperMemory();
    } catch (err) {
        roleMemoryError = t('roleMemory.saveFailed', { message: err.message });
        renderRoleMemoryList();
    } finally {
        roleMemorySaving = false;
        updateRoleMemoryFormState();
    }
}

async function deleteRoleMemory(memoryId) {
    if (!currentRoleId || !memoryId || roleMemoryDeletingIds.has(memoryId)) return;
    roleMemoryDeletingIds.add(memoryId);
    renderRoleMemoryList();
    try {
        await apiCall('DELETE', `/api/roles/${encodeURIComponent(currentRoleId)}/memories/${encodeURIComponent(memoryId)}`);
        roleMemoryStatusText = '';
        await loadRoleMemories();
        if (activeView === 'developer') void loadDeveloperMemory();
    } catch (err) {
        roleMemoryError = t('roleMemory.deleteFailed', { message: err.message });
        renderRoleMemoryList();
    } finally {
        roleMemoryDeletingIds.delete(memoryId);
        renderRoleMemoryList();
    }
}

function developerRoleScopes() {
    const selectable = selectableRoles();
    if (selectable.length) return selectable;
    return currentRoleId ? [{ id: currentRoleId, name: t('roleMemory.defaultRole'), enabled: true }] : [];
}

async function loadDeveloperMemory() {
    if (!developerWorkbench) return;
    if (!currentUserId) {
        selectedDeveloperMemoryKeys.clear();
        developerMemoryState = {
            memories: [],
            loadedAt: '',
            loading: false,
            error: '',
            partialErrors: [],
        };
        renderDeveloperView();
        return;
    }

    const scopes = developerRoleScopes();
    if (!scopes.length) {
        selectedDeveloperMemoryKeys.clear();
        developerMemoryState = {
            memories: [],
            loadedAt: new Date().toISOString(),
            loading: false,
            error: '',
            partialErrors: [],
        };
        renderDeveloperView();
        return;
    }

    developerMemoryState = {
        ...developerMemoryState,
        loading: true,
        error: '',
        partialErrors: [],
    };
    renderDeveloperView();

    const results = await Promise.allSettled(scopes.map(async (role) => {
        const data = await apiCall('GET', `/api/roles/${encodeURIComponent(role.id)}/memories?include_inactive=true`);
        const memories = Array.isArray(data.memories) ? data.memories : [];
        return memories.map((memory) => ({
            ...memory,
            role_id: memory.role_id || role.id,
        }));
    }));

    const memories = [];
    const partialErrors = [];
    results.forEach((result, index) => {
        if (result.status === 'fulfilled') {
            memories.push(...result.value);
            return;
        }
        const role = scopes[index];
        partialErrors.push(`${role?.id || 'role'}: ${result.reason?.message || result.reason || 'failed'}`);
    });

    memories.sort((a, b) => new Date(b.updated_at || b.created_at || 0) - new Date(a.updated_at || a.created_at || 0));
    const availableMemoryKeys = new Set(memories.map((memory) => developerMemoryKey(memory)));
    expandedDeveloperMemoryIds = new Set(
        [...expandedDeveloperMemoryIds].filter((key) => availableMemoryKeys.has(key)),
    );
    pruneSelectedDeveloperMemoryKeys(memories);
    developerMemoryState = {
        memories,
        loadedAt: new Date().toISOString(),
        loading: false,
        error: memories.length || partialErrors.length < scopes.length
            ? ''
            : t('developer.loadFailed', { message: partialErrors.join('; ') || 'unknown error' }),
        partialErrors: partialErrors.length < scopes.length ? partialErrors : [],
    };
    renderDeveloperView();
}

function captureMemoryDebug(resp = {}, conversationId = '') {
    const context = Array.isArray(resp.memory_context) ? resp.memory_context : [];
    const updates = Array.isArray(resp.memory_updates) ? resp.memory_updates : [];
    const events = (Array.isArray(resp.events) ? resp.events : [])
        .filter((event) => String(event?.type || '').startsWith('memory.'));

    if (!context.length && !updates.length && !events.length) return;
    lastMemoryDebug = {
        runId: resp.run_id || '',
        conversationId: resp.conversation_id || conversationId || currentConversationId || '',
        roleId: resp.role_id || currentRoleId || '',
        agentId: resp.agent_id || currentAgentId || '',
        modelUsed: resp.model_used || '',
        capturedAt: new Date().toISOString(),
        context,
        updates,
        events,
    };
    renderDeveloperView();
}

function renderDeveloperView() {
    if (!developerWorkbench) return;

    const memories = developerMemoryState.memories || [];
    const longTermCount = memories.filter((memory) => memory.kind === 'long_term').length;
    const roleMemoryCount = memories.filter((memory) => memory.kind === 'role' || memory.kind === 'persona').length;
    const scopes = developerRoleScopes();
    const currentRole = roles.find((role) => role.id === currentRoleId) || null;
    const currentRoleName = currentRole ? roleDisplayName(currentRole) : (currentRoleId || t('roleMemory.defaultRole'));
    const refreshLabel = developerMemoryState.loading ? t('developer.refreshing') : t('developer.refresh');
    const partialWarning = developerMemoryState.partialErrors?.length
        ? `<div class="developer-banner warn">${escapeHtml(t('developer.partialFailed', { message: developerMemoryState.partialErrors.join('; ') }))}</div>`
        : '';
    const errorBannerHtml = developerMemoryState.error
        ? `<div class="developer-banner error">${escapeHtml(developerMemoryState.error)}</div>`
        : '';

    developerWorkbench.innerHTML = `
        <div class="developer-toolbar">
            <div>
                <h2>${escapeHtml(t('developer.storageTitle'))}</h2>
                <p>${escapeHtml(t('developer.storageDetail'))}</p>
            </div>
            <button class="btn-secondary" type="button" data-developer-refresh ${developerMemoryState.loading ? 'disabled aria-busy="true"' : ''}>
                <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.3">
                    <path d="M21 12a9 9 0 0 1-9 9 9.8 9.8 0 0 1-6.7-2.7"/>
                    <path d="M3 12a9 9 0 0 1 9-9 9.8 9.8 0 0 1 6.7 2.7"/>
                    <path d="M3 20v-5h5M21 4v5h-5"/>
                </svg>
                <span>${escapeHtml(refreshLabel)}</span>
            </button>
        </div>
        <div class="developer-summary-grid">
            ${renderDeveloperSummaryCard(t('developer.account'), currentUserId || '-', t('developer.persistentYes'))}
            ${renderDeveloperSummaryCard(t('developer.currentRole'), currentRoleName, currentRoleId || '-')}
            ${renderDeveloperSummaryCard(t('developer.roles'), String(scopes.length), t('developer.allScopes'))}
            ${renderDeveloperSummaryCard(t('developer.records'), String(memories.length), `${t('developer.longTerm')} ${longTermCount} / ${t('developer.rolePersona')} ${roleMemoryCount}`)}
        </div>
        <section class="developer-panel developer-memory-model">
            <div class="developer-memory-type persistent">
                <span class="status-chip ok">${escapeHtml(t('developer.persistentYes'))}</span>
                <h3>${escapeHtml(t('developer.longTerm'))}</h3>
                <p>${escapeHtml(memoryKindExplanation('long_term'))}</p>
            </div>
            <div class="developer-memory-type persistent">
                <span class="status-chip neutral">${escapeHtml(t('developer.persistentYes'))}</span>
                <h3>${escapeHtml(t('developer.rolePersona'))}</h3>
                <p>${escapeHtml(memoryKindExplanation('role'))}</p>
            </div>
            <div class="developer-memory-type short-term">
                <span class="status-chip warn">${escapeHtml(t('developer.persistentNo'))}</span>
                <h3>${escapeHtml(t('developer.shortTerm'))}</h3>
                <p>${escapeHtml(t('developer.shortTermDetail'))}</p>
            </div>
            <div class="developer-memory-type">
                <span class="status-chip neutral">${escapeHtml(t('developer.injectionOrder'))}</span>
                <h3>${escapeHtml(t('developer.injectionOrder'))}</h3>
                <p>${escapeHtml(t('developer.injectionOrderDetail'))}</p>
            </div>
        </section>
        ${errorBannerHtml}
        ${partialWarning}
        ${renderDeveloperInventory(memories)}
        ${renderDeveloperLastRun()}
    `;
}

function renderDeveloperSummaryCard(label, value, detail) {
    return `
        <div class="developer-summary-card">
            <span>${escapeHtml(label)}</span>
            <strong>${escapeHtml(value)}</strong>
            <small>${escapeHtml(detail || '')}</small>
        </div>
    `;
}

function renderDeveloperInventory(memories = []) {
    const visibleMemories = filterDeveloperMemories(memories);
    const visibleSelectableCount = visibleMemories.filter(isSelectableDeveloperMemory).length;
    const selectedCount = selectedDeveloperMemories().length;
    const longTerm = visibleMemories.filter((memory) => memory.kind === 'long_term');
    const rolePersona = visibleMemories.filter((memory) => memory.kind === 'role' || memory.kind === 'persona');
    const other = visibleMemories.filter((memory) => memory.kind !== 'long_term' && memory.kind !== 'role' && memory.kind !== 'persona');
    const loadedText = developerMemoryState.loadedAt
        ? formatFullTime(developerMemoryState.loadedAt)
        : t('developer.neverLoaded');
    const groups = [
        { key: 'long_term', title: t('developer.longTerm'), memories: longTerm },
        { key: 'role', title: t('developer.rolePersona'), memories: rolePersona },
        { key: 'other', title: t('developer.filterOther'), memories: other },
    ].filter((group) => group.memories.length || developerMemoryViewState.kind === 'all');
    const memoryGroups = visibleMemories.length
        ? groups.map((group) => renderDeveloperMemoryGroup(group.title, group.memories, { groupKey: group.key })).join('')
        : `<div class="empty-inline developer-memory-no-results">${escapeHtml(memories.length ? t('developer.noMatches') : t('developer.empty'))}</div>`;

    return `
        <section class="developer-panel developer-inventory-panel">
            <div class="developer-panel-head">
                <div>
                    <h2>${escapeHtml(t('developer.inventoryTitle'))}</h2>
                    <p>${escapeHtml(`${t('developer.updatedAt')}: ${loadedText}`)}</p>
                </div>
                <span class="section-count">${visibleMemories.length}/${memories.length}</span>
            </div>
            ${renderDeveloperMemoryControls(memories.length, visibleMemories.length, selectedCount, visibleSelectableCount)}
            <div class="developer-memory-columns developer-memory-inventory">
                ${memoryGroups}
            </div>
        </section>
    `;
}

function renderDeveloperMemoryControls(totalCount = 0, visibleCount = 0, selectedCount = 0, visibleSelectableCount = 0) {
    const state = developerMemoryViewState;
    const hasSelection = selectedCount > 0;
    return `
        <div class="developer-memory-controls">
            <label class="developer-memory-control developer-memory-search">
                <span class="visually-hidden">${escapeHtml(t('developer.searchPlaceholder'))}</span>
                <input type="search"
                       data-developer-memory-search
                       placeholder="${escapeAttr(t('developer.searchPlaceholder'))}"
                       value="${escapeAttr(state.query || '')}">
            </label>
            <label class="developer-memory-control">
                <span>${escapeHtml(t('developer.kindFilter'))}</span>
                <select data-developer-memory-filter="kind">
                    ${renderDeveloperSelectOption('all', t('developer.allKinds'), state.kind)}
                    ${renderDeveloperSelectOption('long_term', t('developer.longTerm'), state.kind)}
                    ${renderDeveloperSelectOption('role', t('developer.rolePersona'), state.kind)}
                    ${renderDeveloperSelectOption('other', t('developer.filterOther'), state.kind)}
                </select>
            </label>
            <label class="developer-memory-control">
                <span>${escapeHtml(t('developer.statusFilter'))}</span>
                <select data-developer-memory-filter="status">
                    ${renderDeveloperSelectOption('all', t('developer.allStatuses'), state.status)}
                    ${renderDeveloperSelectOption('active', t('developer.statusActive'), state.status)}
                    ${renderDeveloperSelectOption('pending_review', t('developer.statusPending'), state.status)}
                    ${renderDeveloperSelectOption('archived', t('developer.statusArchived'), state.status)}
                </select>
            </label>
            <label class="developer-memory-control">
                <span>${escapeHtml(t('developer.sortLabel'))}</span>
                <select data-developer-memory-filter="sort">
                    ${renderDeveloperSelectOption('updated_desc', t('developer.sortUpdatedDesc'), state.sort)}
                    ${renderDeveloperSelectOption('updated_asc', t('developer.sortUpdatedAsc'), state.sort)}
                    ${renderDeveloperSelectOption('last_used_desc', t('developer.sortLastUsedDesc'), state.sort)}
                    ${renderDeveloperSelectOption('confidence_desc', t('developer.sortConfidenceDesc'), state.sort)}
                </select>
            </label>
            <div class="developer-memory-control developer-memory-count">
                <span>${escapeHtml(t('developer.showingCount', { visible: visibleCount, total: totalCount }))}</span>
                <button class="developer-memory-action" type="button" data-developer-memory-reset>
                    ${escapeHtml(t('developer.resetFilters'))}
                </button>
            </div>
            <div class="developer-memory-bulk-actions">
                <span class="developer-memory-selected-count">${escapeHtml(t('developer.selectedCount', { count: selectedCount }))}</span>
                <button class="developer-memory-action" type="button" data-developer-memory-selection="select-visible" ${visibleSelectableCount ? '' : 'disabled'}>
                    ${escapeHtml(t('developer.selectVisible'))}
                </button>
                <button class="developer-memory-action" type="button" data-developer-memory-selection="clear" ${hasSelection ? '' : 'disabled'}>
                    ${escapeHtml(t('developer.clearSelection'))}
                </button>
                <button class="developer-memory-action danger" type="button" data-developer-memory-delete-selected ${hasSelection ? '' : 'disabled'}>
                    ${escapeHtml(t('developer.deleteSelected'))}
                </button>
                <button class="developer-memory-action" type="button" data-developer-memory-bulk="expand">
                    ${escapeHtml(t('developer.expandAll'))}
                </button>
                <button class="developer-memory-action" type="button" data-developer-memory-bulk="collapse">
                    ${escapeHtml(t('developer.collapseAll'))}
                </button>
            </div>
        </div>
    `;
}

function renderDeveloperSelectOption(value, label, currentValue) {
    return `<option value="${escapeAttr(value)}" ${value === currentValue ? 'selected' : ''}>${escapeHtml(label)}</option>`;
}

function renderDeveloperMemoryGroup(title, memories = [], options = {}) {
    const compact = options.compact !== false;
    const groupKey = options.groupKey || 'memory';
    return `
        <div class="developer-memory-group developer-memory-group-${escapeAttr(groupKey)}">
            <div class="developer-memory-group-head">
                <h3>${escapeHtml(title)}</h3>
                <span>${memories.length}</span>
            </div>
            <div class="developer-memory-list" data-developer-memory-list="${escapeAttr(groupKey)}">
                ${memories.length
                    ? memories.map((memory) => renderDeveloperMemoryRecord(memory, { forceExpanded: !compact })).join('')
                    : `<div class="empty-inline">${escapeHtml(t('developer.empty'))}</div>`}
            </div>
        </div>
    `;
}

function renderDeveloperMemoryRecord(memory = {}, options = {}) {
    const key = developerMemoryKey(memory);
    const forceExpanded = options.forceExpanded === true;
    const isLongTerm = memory.kind === 'long_term';
    const selected = selectedDeveloperMemoryKeys.has(key);
    const expanded = !isLongTerm && (forceExpanded || expandedDeveloperMemoryIds.has(key));
    const roleName = memoryRoleLabel(memory.role_id);
    const kind = memoryKindLabel(memory.kind);
    const source = memorySourceLabel(memory.source);
    const updated = formatFullTime(memory.updated_at || memory.created_at || '');
    const created = formatFullTime(memory.created_at || '');
    const lastUsed = formatFullTime(memory.last_used_at || '');
    const status = memoryStatusLabel(memory.status || 'active');
    const confidence = Number.isFinite(Number(memory.confidence))
        ? `${t('developer.confidence')} ${Number(memory.confidence).toFixed(2)}`
        : '';
    const agent = memory.agent_id ? `${t('developer.agentScope')}: ${memory.agent_id}` : '';
    const tags = Array.isArray(memory.tags) ? memory.tags.filter(Boolean) : [];
    const busy = developerMemoryMutatingIds.has(memory.id);
    const selectControl = isLongTerm && isSelectableDeveloperMemory(memory)
        ? `<label class="developer-memory-select" title="${escapeAttr(t('developer.selectMemory'))}">
                <input type="checkbox"
                       data-developer-memory-select="${escapeAttr(key)}"
                       data-developer-memory-role="${escapeAttr(memory.role_id || currentRoleId || '')}"
                       data-developer-memory-id="${escapeAttr(memory.id || '')}"
                       aria-label="${escapeAttr(t('developer.selectMemory'))}"
                       ${selected ? 'checked' : ''}
                       ${busy ? 'disabled' : ''}>
           </label>`
        : '';
    const preview = isLongTerm
        ? String(memory.content || '').replace(/\s+/g, ' ').trim()
        : compactDeveloperMemoryContent(memory.content || '', 180);
    const metadata = memory.metadata && typeof memory.metadata === 'object' && Object.keys(memory.metadata).length
        ? `<details class="developer-memory-metadata">
                <summary>${escapeHtml(t('developer.metadata'))}</summary>
                <pre>${escapeHtml(JSON.stringify(memory.metadata, null, 2))}</pre>
           </details>`
        : '';
    const sourceTrace = memory.source_trace && typeof memory.source_trace === 'object' && Object.keys(memory.source_trace).length
        ? `<details class="developer-memory-metadata">
                <summary>${escapeHtml(t('developer.sourceTrace'))}</summary>
                <pre>${escapeHtml(JSON.stringify(memory.source_trace, null, 2))}</pre>
           </details>`
        : '';
    const archiveAction = memory.status === 'archived'
        ? `<button class="developer-memory-action" type="button" data-developer-memory-status="active" data-developer-memory-role="${escapeAttr(memory.role_id || currentRoleId || '')}" data-developer-memory-id="${escapeAttr(memory.id || '')}" ${busy ? 'disabled' : ''}>${escapeHtml(t('developer.activate'))}</button>`
        : `<button class="developer-memory-action" type="button" data-developer-memory-status="archived" data-developer-memory-role="${escapeAttr(memory.role_id || currentRoleId || '')}" data-developer-memory-id="${escapeAttr(memory.id || '')}" ${busy ? 'disabled' : ''}>${escapeHtml(t('developer.archive'))}</button>`;
    const compactMeta = [
        roleName,
        source,
        updated ? `${t('developer.updatedAt')}: ${updated}` : '',
        lastUsed ? `${t('developer.lastUsed')}: ${lastUsed}` : '',
        confidence,
    ].filter(Boolean);
    const detailMeta = `
        <div class="developer-memory-meta">
            <span>${escapeHtml(roleName)}</span>
            <span>${escapeHtml(source)}</span>
            <span>${escapeHtml(t('developer.scope'))}: ${escapeHtml(memory.scope || 'user')}</span>
            <span>${escapeHtml(t('developer.reviewState'))}: ${escapeHtml(memory.review_state || 'manual')}</span>
            ${updated ? `<span>${escapeHtml(t('developer.updatedAt'))}: ${escapeHtml(updated)}</span>` : ''}
            ${created ? `<span>${escapeHtml(t('developer.createdAt'))}: ${escapeHtml(created)}</span>` : ''}
            ${lastUsed ? `<span>${escapeHtml(t('developer.lastUsed'))}: ${escapeHtml(lastUsed)}</span>` : ''}
            ${confidence ? `<span>${escapeHtml(confidence)}</span>` : ''}
            ${agent ? `<span>${escapeHtml(agent)}</span>` : ''}
        </div>
    `;
    const toggleLabel = expanded ? t('developer.collapse') : t('developer.details');
    const toggleButton = forceExpanded || isLongTerm
        ? ''
        : `<button class="developer-memory-toggle" type="button"
                   data-developer-memory-toggle="${escapeAttr(key)}"
                   aria-expanded="${expanded ? 'true' : 'false'}"
                   title="${escapeAttr(expanded ? t('developer.collapse') : t('developer.expand'))}">
                <span class="developer-memory-toggle-icon" aria-hidden="true"></span>
                <span>${escapeHtml(toggleLabel)}</span>
           </button>`;
    const detailHtml = expanded && !isLongTerm
        ? `<div class="developer-memory-detail" data-developer-memory-record-detail="${escapeAttr(key)}">
                <div class="developer-memory-full">
                    <span>${escapeHtml(t('developer.fullContent'))}</span>
                    <p>${escapeHtml(memory.content || '')}</p>
                </div>
                ${detailMeta}
                ${tags.length ? `<div class="chip-row">${tags.map((tag) => `<span class="chip">${escapeHtml(tag)}</span>`).join('')}</div>` : ''}
                <div class="developer-memory-actions">
                    <button class="developer-memory-action" type="button" data-developer-memory-edit="${escapeAttr(memory.id || '')}" data-developer-memory-role="${escapeAttr(memory.role_id || currentRoleId || '')}" ${busy ? 'disabled' : ''}>${escapeHtml(t('developer.edit'))}</button>
                    ${archiveAction}
                    <button class="developer-memory-action danger" type="button" data-developer-memory-delete="${escapeAttr(memory.id || '')}" data-developer-memory-role="${escapeAttr(memory.role_id || currentRoleId || '')}" ${busy ? 'disabled' : ''}>${escapeHtml(t('developer.delete'))}</button>
                </div>
                ${sourceTrace}
                ${metadata}
           </div>`
        : '';
    const hoverContent = isLongTerm
        ? `data-memory-content="${escapeAttr(memory.content || '')}"`
        : '';

    return `
        <article class="developer-memory-record ${isLongTerm ? 'long-term' : ''} ${selected ? 'selected' : ''} ${expanded ? 'expanded' : 'compact'}"
                 data-developer-memory-record="${escapeAttr(key)}"
                 ${hoverContent}>
            <div class="developer-memory-record-head">
                ${selectControl || toggleButton}
                <div class="developer-memory-record-main">
                    <div class="developer-memory-record-line">
                        <p class="developer-memory-preview" ${isLongTerm ? '' : `title="${escapeAttr(memory.content || '')}"`}>${escapeHtml(preview || '-')}</p>
                        <div class="developer-memory-record-badges">
                            <span class="status-chip ${memoryStatusChipClass(memory.status || 'active')}">${escapeHtml(status)}</span>
                            <span class="status-chip neutral">${escapeHtml(kind)}</span>
                            <span class="status-chip neutral">${escapeHtml(`${t('developer.version')} ${String(memory.version || 1)}`)}</span>
                            ${memory.id ? `<code title="${escapeAttr(memory.id || '')}">${escapeHtml(shortDebugId(memory.id || ''))}</code>` : ''}
                        </div>
                    </div>
                    <div class="developer-memory-record-subhead">
                        ${compactMeta.map((item) => `<span>${escapeHtml(item)}</span>`).join('')}
                    </div>
                </div>
            </div>
            ${detailHtml}
        </article>
    `;
}

function filterDeveloperMemories(memories = []) {
    const query = normalizeDeveloperMemorySearch(developerMemoryViewState.query || '');
    const filtered = memories.filter((memory) => {
        const kindValue = developerMemoryKindFilterValue(memory.kind);
        if (developerMemoryViewState.kind !== 'all' && kindValue !== developerMemoryViewState.kind) return false;

        const statusValue = memory.status || 'active';
        if (developerMemoryViewState.status !== 'all' && statusValue !== developerMemoryViewState.status) return false;

        return !query || developerMemorySearchText(memory).includes(query);
    });
    return sortDeveloperMemories(filtered, developerMemoryViewState.sort);
}

function sortDeveloperMemories(memories = [], sortKey = 'updated_desc') {
    return memories
        .map((memory, index) => ({ memory, index }))
        .sort((left, right) => {
            let result = 0;
            if (sortKey === 'updated_asc') {
                result = developerMemoryTimestamp(left.memory, 'updated_at') - developerMemoryTimestamp(right.memory, 'updated_at');
            } else if (sortKey === 'last_used_desc') {
                result = developerMemoryLastUsedTimestamp(right.memory) - developerMemoryLastUsedTimestamp(left.memory);
            } else if (sortKey === 'confidence_desc') {
                result = developerMemoryConfidence(right.memory) - developerMemoryConfidence(left.memory);
            } else {
                result = developerMemoryTimestamp(right.memory, 'updated_at') - developerMemoryTimestamp(left.memory, 'updated_at');
            }
            return result || left.index - right.index;
        })
        .map((item) => item.memory);
}

function developerMemoryKindFilterValue(kind = '') {
    if (kind === 'long_term') return 'long_term';
    if (kind === 'role' || kind === 'persona') return 'role';
    return 'other';
}

function developerMemorySearchText(memory = {}) {
    const tags = Array.isArray(memory.tags) ? memory.tags.filter(Boolean) : [];
    return normalizeDeveloperMemorySearch([
        memory.id,
        memory.content,
        memory.kind,
        memory.status,
        memory.scope,
        memory.review_state,
        memory.role_id,
        memory.agent_id,
        memoryRoleLabel(memory.role_id),
        memoryKindLabel(memory.kind),
        memorySourceLabel(memory.source),
        ...tags,
    ].filter(Boolean).join(' '));
}

function normalizeDeveloperMemorySearch(text = '') {
    return String(text).replace(/\s+/g, ' ').trim().toLocaleLowerCase();
}

function developerMemoryTimestamp(memory = {}, primaryField = 'updated_at') {
    const value = memory[primaryField] || memory.updated_at || memory.created_at || '';
    const timestamp = new Date(value).getTime();
    return Number.isFinite(timestamp) ? timestamp : 0;
}

function developerMemoryLastUsedTimestamp(memory = {}) {
    return developerMemoryTimestamp(
        { ...memory, updated_at: memory.last_used_at || memory.updated_at || memory.created_at },
        'updated_at',
    );
}

function developerMemoryConfidence(memory = {}) {
    const value = Number(memory.confidence);
    return Number.isFinite(value) ? value : -1;
}

function compactDeveloperMemoryContent(content = '', limit = 180) {
    const text = String(content).replace(/\s+/g, ' ').trim();
    if (text.length <= limit) return text;
    return `${text.slice(0, limit).trim()}...`;
}

function developerMemoryKey(memory = {}) {
    const roleId = memory.role_id || currentRoleId || '';
    if (memory.id) return `${roleId}::${memory.id}`;
    const fallback = String(memory.content || '').replace(/\s+/g, ' ').slice(0, 64);
    return `${roleId}::${memory.kind || 'memory'}::${memory.created_at || ''}::${fallback}`;
}

function isSelectableDeveloperMemory(memory = {}) {
    return memory.kind === 'long_term' && !!memory.id && !!(memory.role_id || currentRoleId);
}

function pruneSelectedDeveloperMemoryKeys(memories = []) {
    const selectableKeys = new Set(
        memories
            .filter(isSelectableDeveloperMemory)
            .map((memory) => developerMemoryKey(memory)),
    );
    selectedDeveloperMemoryKeys = new Set(
        [...selectedDeveloperMemoryKeys].filter((key) => selectableKeys.has(key)),
    );
}

function selectedDeveloperMemories() {
    const memoryByKey = new Map(
        (developerMemoryState.memories || []).map((memory) => [developerMemoryKey(memory), memory]),
    );
    return [...selectedDeveloperMemoryKeys]
        .map((key) => memoryByKey.get(key))
        .filter(isSelectableDeveloperMemory);
}

function restoreDeveloperMemoryRecord(memoryKey = '', scrollTop = null) {
    if (!developerWorkbench || !memoryKey) return;
    requestAnimationFrame(() => {
        const records = developerWorkbench.querySelectorAll('[data-developer-memory-record]');
        const record = [...records].find((item) => item.dataset.developerMemoryRecord === memoryKey);
        const details = developerWorkbench.querySelectorAll('[data-developer-memory-record-detail]');
        const detail = [...details].find((item) => item.dataset.developerMemoryRecordDetail === memoryKey);
        const list = record?.closest('[data-developer-memory-list]');
        if (list && Number.isFinite(scrollTop)) {
            list.scrollTop = scrollTop;
        }
        const target = detail || record;
        if (target && typeof target.scrollIntoView === 'function') {
            target.scrollIntoView({ block: 'nearest', inline: 'nearest' });
        }
    });
}

function ensureDeveloperMemoryHoverCard() {
    if (developerMemoryHoverCard) return developerMemoryHoverCard;
    developerMemoryHoverCard = document.createElement('div');
    developerMemoryHoverCard.className = 'developer-memory-hover-card';
    developerMemoryHoverCard.hidden = true;
    developerMemoryHoverCard.addEventListener('mouseenter', cancelDeveloperMemoryHoverHide);
    developerMemoryHoverCard.addEventListener('mouseleave', () => hideDeveloperMemoryHoverCard());
    document.body.appendChild(developerMemoryHoverCard);
    return developerMemoryHoverCard;
}

function cancelDeveloperMemoryHoverHide() {
    if (!developerMemoryHoverHideTimer) return;
    clearTimeout(developerMemoryHoverHideTimer);
    developerMemoryHoverHideTimer = null;
}

function positionDeveloperMemoryHoverCard(event) {
    if (!developerMemoryHoverCard || developerMemoryHoverCard.hidden) return;
    const margin = 14;
    const offset = 16;
    const rect = developerMemoryHoverCard.getBoundingClientRect();
    let left = event.clientX + offset;
    let top = event.clientY + offset;
    if (left + rect.width > window.innerWidth - margin) {
        left = window.innerWidth - rect.width - margin;
    }
    if (top + rect.height > window.innerHeight - margin) {
        top = event.clientY - rect.height - offset;
    }
    developerMemoryHoverCard.style.left = `${Math.max(margin, left)}px`;
    developerMemoryHoverCard.style.top = `${Math.max(margin, top)}px`;
}

function showDeveloperMemoryHoverCard(record, event) {
    const content = record?.dataset.memoryContent || '';
    if (!content.trim()) return;
    cancelDeveloperMemoryHoverHide();
    const card = ensureDeveloperMemoryHoverCard();
    if (card.textContent !== content) {
        card.textContent = content;
        card.scrollTop = 0;
    }
    card.hidden = false;
    positionDeveloperMemoryHoverCard(event);
}

function hideDeveloperMemoryHoverCard(options = {}) {
    const delay = Number(options.delay || 0);
    cancelDeveloperMemoryHoverHide();
    if (delay > 0) {
        developerMemoryHoverHideTimer = window.setTimeout(() => {
            developerMemoryHoverHideTimer = null;
            if (developerMemoryHoverCard) {
                developerMemoryHoverCard.hidden = true;
            }
        }, delay);
        return;
    }
    if (developerMemoryHoverCard) {
        developerMemoryHoverCard.hidden = true;
    }
}

function renderDeveloperLastRun() {
    if (!lastMemoryDebug) {
        return `
            <section class="developer-panel">
                <div class="developer-panel-head">
                    <div>
                        <h2>${escapeHtml(t('developer.lastRunTitle'))}</h2>
                        <p>${escapeHtml(t('developer.noLastRun'))}</p>
                    </div>
                </div>
            </section>
        `;
    }

    const eventPayload = lastMemoryDebug.events?.length
        ? renderTraceJsonSection('Memory Events', lastMemoryDebug.events.map((event) => ({
            type: event.type,
            status: event.status,
            title: event.title,
            payload: event.payload || {},
        })))
        : '';

    return `
        <section class="developer-panel">
            <div class="developer-panel-head">
                <div>
                    <h2>${escapeHtml(t('developer.lastRunTitle'))}</h2>
                    <p>${escapeHtml(formatFullTime(lastMemoryDebug.capturedAt))}</p>
                </div>
                <span class="section-count">${(lastMemoryDebug.context || []).length + (lastMemoryDebug.updates || []).length}</span>
            </div>
            <div class="meta-row developer-run-meta">
                ${lastMemoryDebug.runId ? `<span>Run ${escapeHtml(shortRunId(lastMemoryDebug.runId))}</span>` : ''}
                ${lastMemoryDebug.conversationId ? `<span>${escapeHtml(lastMemoryDebug.conversationId)}</span>` : ''}
                ${lastMemoryDebug.roleId ? `<span>${escapeHtml(t('developer.currentRole'))}: ${escapeHtml(lastMemoryDebug.roleId)}</span>` : ''}
                ${lastMemoryDebug.agentId ? `<span>${escapeHtml(t('developer.agentScope'))}: ${escapeHtml(lastMemoryDebug.agentId)}</span>` : ''}
                ${lastMemoryDebug.modelUsed ? `<span>${escapeHtml(lastMemoryDebug.modelUsed)}</span>` : ''}
            </div>
            <div class="developer-memory-columns">
                ${renderDeveloperMemoryGroup(t('developer.contextTitle'), lastMemoryDebug.context || [])}
                ${renderDeveloperMemoryGroup(t('developer.updatesTitle'), lastMemoryDebug.updates || [])}
            </div>
            ${eventPayload}
        </section>
    `;
}

function memoryKindLabel(kind = '') {
    if (kind === 'long_term') return t('developer.kindLongTerm');
    if (kind === 'persona') return t('developer.kindPersona');
    if (kind === 'role') return t('developer.kindRole');
    return kind || 'memory';
}

function memoryKindExplanation(kind = '') {
    if (kind === 'long_term') {
        return currentLanguage === 'zh'
            ? '跨会话稳定事实、偏好、持续项目和长期目标；这是当前系统里的长期记忆。'
            : 'Stable cross-conversation facts, preferences, ongoing projects, and long-term goals. This is the long-term memory layer.';
    }
    return currentLanguage === 'zh'
        ? '用户对助手角色、语气和工作方式的长期调整；persona 是兼容旧 kind 的角色记忆。'
        : 'Durable user adjustments to assistant role, tone, and working style. persona is the compatibility kind for role memory.';
}

function memorySourceLabel(source = '') {
    if (source === 'manual') return t('developer.sourceManual');
    if (source === 'hook') return t('developer.sourceHook');
    if (source === 'ai' || source === 'chat') return t('developer.sourceChat');
    return source || t('developer.sourceUnknown');
}

function memoryStatusLabel(status = '') {
    if (status === 'active') return t('developer.statusActive');
    if (status === 'pending_review') return t('developer.statusPending');
    if (status === 'archived') return t('developer.statusArchived');
    return status || t('developer.statusActive');
}

function memoryStatusChipClass(status = '') {
    if (status === 'active') return 'ok';
    if (status === 'archived') return 'neutral';
    if (status === 'pending_review') return 'warn';
    return 'neutral';
}

function memoryRoleLabel(roleId = '') {
    if (!roleId) return t('roleMemory.defaultRole');
    const role = roles.find((item) => item.id === roleId);
    const name = role ? roleDisplayName(role) : roleId;
    return roleId === currentRoleId
        ? `${name} · ${t('developer.currentScope')}`
        : name;
}

async function updateDeveloperMemory(roleId, memoryId, patch = {}) {
    if (!roleId || !memoryId || developerMemoryMutatingIds.has(memoryId)) return;
    developerMemoryMutatingIds.add(memoryId);
    renderDeveloperView();
    try {
        await apiCall('PUT', `/api/roles/${encodeURIComponent(roleId)}/memories/${encodeURIComponent(memoryId)}`, patch);
        await loadDeveloperMemory();
        if (roleId === currentRoleId) await loadRoleMemories();
    } catch (err) {
        developerMemoryState = {
            ...developerMemoryState,
            error: t('developer.updateFailed', { message: err.message }),
        };
        renderDeveloperView();
    } finally {
        developerMemoryMutatingIds.delete(memoryId);
        renderDeveloperView();
    }
}

async function editDeveloperMemory(roleId, memoryId) {
    const memory = (developerMemoryState.memories || []).find((item) => item.id === memoryId);
    if (!memory) return;
    const nextContent = window.prompt(t('developer.editPrompt'), memory.content || '');
    if (nextContent === null) return;
    const content = nextContent.trim();
    if (!content || content === (memory.content || '').trim()) return;
    await updateDeveloperMemory(roleId, memoryId, {
        content,
        review_state: 'reviewed',
        review_notes: 'Edited from Developer view',
    });
}

async function deleteDeveloperMemory(roleId, memoryId) {
    if (!roleId || !memoryId || developerMemoryMutatingIds.has(memoryId)) return;
    if (!window.confirm(t('developer.deleteConfirm'))) return;
    developerMemoryMutatingIds.add(memoryId);
    renderDeveloperView();
    try {
        await apiCall('DELETE', `/api/roles/${encodeURIComponent(roleId)}/memories/${encodeURIComponent(memoryId)}`);
        await loadDeveloperMemory();
        if (roleId === currentRoleId) await loadRoleMemories();
    } catch (err) {
        developerMemoryState = {
            ...developerMemoryState,
            error: t('developer.deleteFailed', { message: err.message }),
        };
        renderDeveloperView();
    } finally {
        developerMemoryMutatingIds.delete(memoryId);
        renderDeveloperView();
    }
}

async function deleteSelectedDeveloperMemories() {
    const memories = selectedDeveloperMemories();
    if (!memories.length) {
        selectedDeveloperMemoryKeys.clear();
        renderDeveloperView();
        return;
    }
    if (!window.confirm(t('developer.deleteSelectedConfirm', { count: memories.length }))) return;

    const mutatingIds = new Set(memories.map((memory) => memory.id).filter(Boolean));
    mutatingIds.forEach((id) => developerMemoryMutatingIds.add(id));
    renderDeveloperView();

    const results = await Promise.allSettled(memories.map((memory) => (
        apiCall(
            'DELETE',
            `/api/roles/${encodeURIComponent(memory.role_id || currentRoleId || '')}/memories/${encodeURIComponent(memory.id)}`,
        )
    )));
    const failedKeys = new Set();
    const failedMessages = [];
    results.forEach((result, index) => {
        if (result.status === 'fulfilled') return;
        failedKeys.add(developerMemoryKey(memories[index]));
        failedMessages.push(result.reason?.message || String(result.reason || 'failed'));
    });
    selectedDeveloperMemoryKeys = new Set(
        [...selectedDeveloperMemoryKeys].filter((key) => failedKeys.has(key)),
    );

    try {
        await loadDeveloperMemory();
        const touchedCurrentRole = memories.some((memory) => (memory.role_id || currentRoleId || '') === currentRoleId);
        if (touchedCurrentRole) await loadRoleMemories();
    } catch (err) {
        failedMessages.push(err.message || String(err));
    } finally {
        mutatingIds.forEach((id) => developerMemoryMutatingIds.delete(id));
    }

    if (failedMessages.length) {
        developerMemoryState = {
            ...developerMemoryState,
            error: t('developer.deleteSelectedFailed', {
                count: failedMessages.length,
                message: failedMessages.slice(0, 3).join('; '),
            }),
        };
    }
    renderDeveloperView();
}

async function loadTools() {
    toolsError = '';
    try {
        const data = await apiCall('GET', '/api/tools');
        tools = data.skills || data.tools || [];
        toolUserSettings = data.user_settings || {};
        toolMcpConfig = data.mcp || {
            enabled: parseBooleanSetting(toolUserSettings['mcp.enabled'], false),
            servers: toolUserSettings['mcp.servers'] || '',
        };
    } catch (err) {
        tools = [];
        toolUserSettings = {};
        toolMcpConfig = { enabled: false, servers: '' };
        toolsError = err.message;
    }
    renderTools();
    updateCounts();
}

async function loadRuns() {
    runsError = '';
    try {
        const data = await apiCall('GET', '/api/runs?limit=50');
        runs = data.runs || [];
        if (!selectedRunId && runs.length > 0) selectedRunId = runs[0].run_id;
    } catch (err) {
        runs = [];
        selectedRunId = '';
        runsError = err.message;
    }
    renderRuns();
    updateCounts();
}

async function loadPulse() {
    pulseError = '';
    pulseErrorType = 'load';
    try {
        pulse = await apiCall('GET', '/api/pulse');
    } catch (err) {
        pulseError = err.message;
        pulseErrorType = 'load';
    }
    renderPulse();
    syncPulseRefreshPolling(false);
}

async function refreshPulse() {
    pulseError = '';
    pulseErrorType = 'load';
    try {
        pulse = await apiCall('POST', '/api/pulse/refresh', { date: pulse.date || undefined });
    } catch (err) {
        pulseError = err.message;
        pulseErrorType = 'load';
    }
    renderPulse();
    syncPulseRefreshPolling(true);
}

function syncPulseRefreshPolling(resetAttempts = false) {
    if (resetAttempts) {
        pulseRefreshPollAttempts = 0;
    }
    if (!pulse?.refreshing) {
        if (pulseRefreshPollTimer) {
            clearTimeout(pulseRefreshPollTimer);
            pulseRefreshPollTimer = null;
        }
        pulseRefreshPollAttempts = 0;
        return;
    }
    if (pulseRefreshPollTimer || pulseRefreshPollAttempts >= 24) {
        return;
    }
    pulseRefreshPollTimer = setTimeout(async () => {
        pulseRefreshPollTimer = null;
        pulseRefreshPollAttempts += 1;
        await loadPulse();
    }, 5000);
}

async function createPulseTopic(seed = null) {
    if (!pulseTopicInput || pulseTopicSubmitting) return;
    const seeded = seed && typeof seed === 'object';
    const name = seeded ? String(seed.name || '').trim() : pulseTopicInput.value.trim();
    if (!name) {
        pulseError = t('pulse.topicRequired');
        pulseErrorType = 'create';
        renderPulse();
        if (!seeded) pulseTopicInput.focus();
        return;
    }

    const keywords = seeded
        ? normalizePulseKeywordList(seed.keywords || [])
        : parsePulseKeywords(pulseKeywordsInput?.value || '');
    pulseTopicSubmitting = true;
    updatePulseTopicSubmitState();
    try {
        const data = await apiCall('POST', '/api/pulse/topics', { name, keywords });
        upsertPulseTopic(data.topic);
        if (data.topic?.id) selectedPulseTopicId = data.topic.id;
        pulseError = '';
        pulseErrorType = 'load';
        if (!seeded) {
            pulseTopicInput.value = '';
            if (pulseKeywordsInput) pulseKeywordsInput.value = '';
        }
        renderPulse();
        refreshPulse();
    } catch (err) {
        pulseError = err.message;
        pulseErrorType = 'create';
        renderPulse();
    } finally {
        pulseTopicSubmitting = false;
        updatePulseTopicSubmitState();
    }
}

async function deletePulseTopic(id) {
    if (!id || pendingPulseTopicDeletes.has(id)) return;
    const topic = (Array.isArray(pulse.topics) ? pulse.topics : []).find((item) => item.id === id);
    if (!window.confirm(t('actions.confirmDeleteTopic', { name: topic?.name || '' }))) return;

    pendingPulseTopicDeletes.add(id);
    renderPulse();
    try {
        await apiCall('DELETE', `/api/pulse/topics/${encodeURIComponent(id)}`);
        if (selectedPulseTopicId === id) selectedPulseTopicId = '';
        await refreshPulse();
    } catch (err) {
        pulseError = err.message;
        pulseErrorType = 'delete';
        renderPulse();
    } finally {
        pendingPulseTopicDeletes.delete(id);
        renderPulse();
    }
}

function upsertPulseTopic(topic) {
    if (!topic || !topic.id) return;
    const topicName = String(topic.name || '').trim().toLowerCase();
    const topics = Array.isArray(pulse.topics) ? pulse.topics : [];
    const nextTopics = topics.filter((item) => {
        const itemName = String(item.name || '').trim().toLowerCase();
        return item.id !== topic.id && (!topicName || itemName !== topicName);
    });
    pulse = { ...pulse, topics: [...nextTopics, topic] };
}

function updatePulseTopicSubmitState() {
    const submitButton = pulseTopicForm?.querySelector('.pulse-submit');
    if (!submitButton) return;
    submitButton.disabled = pulseTopicSubmitting;
    const label = submitButton.querySelector('[data-i18n="pulse.subscribe"]');
    if (label) label.textContent = t(pulseTopicSubmitting ? 'pulse.subscribing' : 'pulse.subscribe');
}

function parsePulseKeywords(value = '') {
    return normalizePulseKeywordList(String(value)
        .split(/[,\n，;；]/)
        .map((item) => item.trim()));
}

function normalizePulseKeywordList(values = []) {
    const seen = new Set();
    const keywords = [];
    (Array.isArray(values) ? values : []).forEach((value) => {
        const cleaned = String(value || '').trim();
        const key = cleaned.toLowerCase();
        if (!cleaned || seen.has(key)) return;
        seen.add(key);
        keywords.push(cleaned);
    });
    return keywords;
}

function mergeRuns(nextRuns = []) {
    (nextRuns || []).forEach((run) => {
        if (!run?.run_id) return;
        const index = runs.findIndex((item) => item.run_id === run.run_id);
        if (index >= 0) {
            runs[index] = { ...runs[index], ...run };
        } else {
            runs.unshift(run);
        }
    });
    runs.sort((a, b) => new Date(b.started_at || 0) - new Date(a.started_at || 0));
}

async function ensureRunLoaded(runId) {
    if (!runId) return null;
    const existing = runs.find((run) => run.run_id === runId);
    if (existing && Array.isArray(existing.events)) return existing;

    const run = await apiCall('GET', `/api/runs/${encodeURIComponent(runId)}`);
    mergeRuns([run]);
    return run;
}

async function openTraceRun(runId) {
    if (!runId) return;
    selectedRunId = runId;
    selectedTraceNodeId = '';
    runsError = '';
    setView('trace', { skipLoad: true });
    try {
        await ensureRunLoaded(runId);
        renderRuns();
        updateCounts();
    } catch (err) {
        runsError = err.message;
        renderRuns();
    }
}

async function loadSettings() {
    const data = await apiCall('GET', '/api/admin/settings');
    settings = data.settings || {};
    renderModelSelect();
    renderSettings();
}

async function loadHealth() {
    health = await apiCall('GET', '/api/health');
    renderHealth();
    renderSettings();
}

async function refreshAll() {
    if (!currentUserId) return;
    await Promise.allSettled([
        loadHealth(),
        loadConversations(),
        loadProjects(),
        loadAgents(),
        loadRoles(),
        loadTools(),
        loadRuns(),
        loadSettings(),
        loadPulse(),
    ]);
    if (activeView === 'developer') await loadDeveloperMemory();
    renderModes();
    updateTopbar();
}

async function bootApp() {
    try {
        await loadAccounts();
    } catch (err) {
        showAccountLogin(t('account.loadFailed', { message: err.message }));
        return;
    }

    if (guestEntryRequested()) {
        setGuestLoginBusy(true);
        try {
            await enterGuestAccount();
        } catch (err) {
            currentUserId = '';
            currentAccountToken = '';
            currentConversationId = null;
            renderAccountControls();
            showAccountLogin(t('account.guestFailed', { message: err.message }), GUEST_ACCOUNT_ID);
        } finally {
            setGuestLoginBusy(false);
        }
        return;
    }

    const storedUserId = loadCurrentUserId();
    const selectedAccount = accounts.find((account) => account.id === storedUserId) || null;
    const storedToken = selectedAccount ? loadAccountSessionToken(selectedAccount.id) : '';
    if (!selectedAccount || !storedToken) {
        currentUserId = '';
        currentAccountToken = '';
        currentConversationId = null;
        if (!selectedAccount) saveCurrentUserId('');
        renderAccountControls();
        showAccountLogin('', selectedAccount?.id || '');
        return;
    }

    currentUserId = selectedAccount.id;
    currentAccountToken = storedToken;
    currentConversationId = loadCurrentConversationId();
    currentRoleId = loadCurrentRoleId();
    renderAccountControls();
    await refreshAll();
    await restoreInitialConversation();
    focusMessageInput({ allowMobile: false });
}

function setView(view, options = {}) {
    if (!VIEW_COPY[view]) return;
    activeView = view;

    document.querySelectorAll('.nav-item').forEach((item) => {
        item.classList.toggle('active', item.dataset.view === view);
    });
    document.querySelectorAll('[data-nav-group]').forEach((group) => {
        const active = Array.from(group.querySelectorAll('.nav-item[data-view]')).some((item) => item.dataset.view === view);
        group.classList.toggle('active', active);
        if (active) {
            group.classList.remove('collapsed');
            const toggle = group.querySelector('[data-toggle-nav-group]');
            if (toggle) toggle.setAttribute('aria-expanded', 'true');
        }
    });
    document.querySelectorAll('[data-view-panel]').forEach((panel) => {
        panel.classList.toggle('active', panel.dataset.viewPanel === view);
    });

    updateTopbar();
    if (view === 'trace' && !options.skipLoad) loadRuns();
    if (view === 'tools') renderTools();
    if (view === 'agents') renderAgents();
    if (view === 'projects') {
        renderProjects();
        if (!options.skipLoad) {
            if (!projects.length) {
                loadProjects();
            } else if (currentProjectId) {
                loadProjectDetail(currentProjectId);
            }
        }
    }
    if (view === 'developer') {
        renderDeveloperView();
        if (!options.skipLoad) loadDeveloperMemory();
    }
    if (view === 'pulse') {
        renderPulse();
        if (!pulse.items.length && !pulseError) loadPulse();
    }
    if (view === 'chat' && options.restore !== false) ensureCurrentConversationVisible();
    if (options.closeSidebar !== false) closeMobileSidebar();
    updateChatHistoryControls();
}

function updateTopbar() {
    const copy = VIEW_COPY[activeView] || VIEW_COPY.chat;
    if (rolePicker) {
        rolePicker.hidden = activeView !== 'chat';
        if (rolePicker.hidden) closeRoleMemoryPopover();
    }

    if (activeView === 'chat') {
        viewTitle.textContent = getCurrentAgentName();
        const current = conversations.find((c) => c.id === currentConversationId);
        viewSubtitle.textContent = current ? displayConversationTitle(current) : t(copy[1]);
    } else {
        viewTitle.textContent = t(copy[0]);
        viewSubtitle.textContent = t(copy[1]);
    }

    if (btnNewChat) btnNewChat.hidden = activeView !== 'chat';
}

function updateCounts() {
    agentCount.textContent = agents.length ? String(agents.length) : '';
    if (projectCount) {
        const driveCount = driveContentItems().length;
        projectCount.textContent = driveCount ? String(driveCount) : '';
    }
    if (tools.length) {
        const enabledTools = tools.filter(toolEffectiveEnabled).length;
        toolCount.textContent = enabledTools === tools.length ? String(tools.length) : `${enabledTools}/${tools.length}`;
    } else {
        toolCount.textContent = '';
    }
    runCount.textContent = runs.length ? String(runs.length) : '';
    if (navSectionCount) {
        const navItems = document.querySelectorAll('#sidebar-nav > .nav-item, #sidebar-nav > .nav-group').length;
        navSectionCount.textContent = navItems ? String(navItems) : '';
    }
    if (pinnedSectionCount) pinnedSectionCount.textContent = pinnedAgentIds.length ? String(pinnedAgentIds.length) : '';
    if (projectSectionCount) {
        const driveCount = driveContentItems().length;
        projectSectionCount.textContent = driveCount ? String(driveCount) : '';
    }
    if (conversationSectionCount) conversationSectionCount.textContent = conversations.length ? String(conversations.length) : '';
}

function renderHealth() {
    if (!systemStatus) return;

    if (!health) {
        systemStatus.textContent = t('health.checking');
        systemStatus.classList.remove('ok');
        systemStatus.classList.add('warn');
        return;
    }
    const agentOk = health?.agent === 'ok';
    systemStatus.textContent = agentOk ? t('health.online') : t('health.unavailable');
    systemStatus.classList.toggle('ok', agentOk);
    systemStatus.classList.toggle('warn', !agentOk);
}

function renderConversationList() {
    if (conversationSectionCount) {
        conversationSectionCount.textContent = conversations.length ? String(conversations.length) : '';
    }
    if (!conversations.length) {
        conversationList.innerHTML = `<div class="empty-inline">${escapeHtml(t('sidebar.emptyConversations'))}</div>`;
        return;
    }

    conversationList.innerHTML = conversations.map((conv) => {
        const isActive = conv.id === currentConversationId;
        const deleting = pendingConversationDeletes.has(conv.id);
        return `
            <div class="conversation-item ${isActive ? 'active' : ''}" data-conversation-id="${escapeAttr(conv.id)}">
                <span class="title">${escapeHtml(displayConversationTitle(conv))}</span>
                <button class="delete-btn" type="button" data-delete-conversation="${escapeAttr(conv.id)}" title="${escapeAttr(t('actions.delete') || 'Delete')}" ${deleting ? 'disabled aria-busy="true"' : ''}>&times;</button>
            </div>
        `;
    }).join('');
}

function renderProjectList() {
    if (projectSectionCount) {
        projectSectionCount.textContent = projects.length ? String(projects.length) : '';
    }
    if (!projectList) return;
    if (!projects.length) {
        projectList.innerHTML = `<div class="empty-inline">${escapeHtml(t('sidebar.emptyProjects'))}</div>`;
        return;
    }

    projectList.innerHTML = projects.map((project, index) => {
        const active = project.id === currentProjectId && activeView === 'projects';
        const deleting = pendingProjectDeletes.has(project.id);
        return `
            <div class="project-item ${active ? 'active' : ''}">
                <button class="project-item-main" type="button" data-select-project="${escapeAttr(project.id)}">
                    <strong>${escapeHtml(project.name || '')}</strong>
                    <small>${escapeHtml(t('projects.documents', { count: project.document_count || 0 }))}</small>
                </button>
                <span class="project-item-actions">
                    <button class="project-mini-button" type="button" data-project-move="${escapeAttr(project.id)}" data-project-move-direction="up" title="${escapeAttr(t('actions.moveUp'))}" ${index === 0 ? 'disabled' : ''}>
                        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.4"><path d="m18 15-6-6-6 6"/></svg>
                    </button>
                    <button class="project-mini-button" type="button" data-project-move="${escapeAttr(project.id)}" data-project-move-direction="down" title="${escapeAttr(t('actions.moveDown'))}" ${index === projects.length - 1 ? 'disabled' : ''}>
                        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.4"><path d="m6 9 6 6 6-6"/></svg>
                    </button>
                    <button class="project-mini-button danger" type="button" data-delete-project="${escapeAttr(project.id)}" title="${escapeAttr(t('actions.delete'))}" ${deleting ? 'disabled aria-busy="true"' : ''}>
                        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.4"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v5M14 11v5"/></svg>
                    </button>
                </span>
            </div>
        `;
    }).join('');
}

function renderProjects() {
    if (!projectWorkbench) return;
    if (projectError) {
        projectWorkbench.innerHTML = `<div class="project-panel">${emptyState(projectError, '')}</div>`;
        return;
    }
    if (!projects.length) {
        projectWorkbench.innerHTML = `
            <div class="project-panel">
                ${emptyState(t('projects.emptyTitle'), t('projects.emptyDetail'))}
                <div class="project-empty-actions">
                    <button class="btn-primary" type="button" data-create-project>
                        <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 5v14M5 12h14"/></svg>
                        <span>${escapeHtml(t('actions.createProject'))}</span>
                    </button>
                </div>
            </div>
        `;
        return;
    }
    const project = projectDetail?.project || currentProjectRecord();
    if (!project) {
        projectWorkbench.innerHTML = emptyState(t('projects.emptyTitle'), '');
        return;
    }
    const documents = projectDocuments();
    const links = projectLinks();
    const activeDoc = documents.find((doc) => doc.id === activeProjectDocumentId) || documents[0] || null;
    if (activeDoc && activeProjectDocumentId !== activeDoc.id) activeProjectDocumentId = activeDoc.id;

    projectWorkbench.innerHTML = `
        <aside class="project-panel project-library-panel">
            <div class="project-panel-head">
                <div>
                    <h2>${escapeHtml(t('projects.sourceLibrary'))}</h2>
                    <p>${escapeHtml(t('projects.documents', { count: documents.length }))}</p>
                </div>
                <div class="project-panel-actions">
                    <button class="btn-secondary" type="button" data-create-project title="${escapeAttr(t('actions.createProject'))}">
                        <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.4"><path d="M12 5v14M5 12h14"/></svg>
                    </button>
                    <button class="btn-secondary" type="button" data-project-upload-trigger ${projectUploadBusy ? 'disabled aria-busy="true"' : ''}>
                        <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.4"><path d="M12 3v12"/><path d="m7 8 5-5 5 5"/><path d="M5 21h14"/></svg>
                        <span>${escapeHtml(t('actions.uploadKnowledge'))}</span>
                    </button>
                </div>
            </div>
            <div class="project-panel-body">
                <div class="project-library-toolbar">
                    <input class="project-search" type="search" data-project-search
                           placeholder="${escapeAttr(t('projects.search'))}"
                           value="${escapeAttr(projectSearchQuery)}">
                    ${renderProjectDocumentList()}
                </div>
            </div>
        </aside>

        <section class="project-panel project-map-panel">
            <div class="project-panel-head">
                <div>
                    <h2>${escapeHtml(project.name || t('views.projects.title'))}</h2>
                    <p>${escapeHtml(`${t('projects.documents', { count: documents.length })} · ${t('projects.links', { count: links.length })}`)}</p>
                </div>
                <div class="project-panel-actions">
                    <button class="btn-secondary" type="button" data-project-refresh>
                        <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.3"><path d="M21 12a9 9 0 0 1-9 9 9.8 9.8 0 0 1-6.7-2.7"/><path d="M3 12a9 9 0 0 1 9-9 9.8 9.8 0 0 1 6.7 2.7"/><path d="M3 20v-5h5M21 4v5h-5"/></svg>
                    </button>
                </div>
            </div>
            ${renderProjectMap(documents, links, activeDoc)}
            <div class="project-detail-pane">
                ${renderProjectDocumentDetail(activeDoc)}
            </div>
        </section>

        <aside class="project-panel project-context-panel">
            <div class="project-panel-head">
                <div>
                    <h2>${escapeHtml(t('projects.contextChat'))}</h2>
                    <p>${escapeHtml(t('projects.selected', { count: selectedProjectDocumentIds.size }))}</p>
                </div>
            </div>
            <div class="project-panel-body">
                ${renderProjectSelectionBar()}
                <textarea data-project-ask-input placeholder="${escapeAttr(t('projects.askPlaceholder'))}">${escapeHtml(projectAskInput)}</textarea>
                <div class="project-context-actions">
                    <button class="btn-primary" type="button" data-project-ask ${projectAskLoading || !documents.length ? 'disabled' : ''}>
                        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.4"><path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4Z"/></svg>
                        <span>${escapeHtml(projectAskLoading ? t('projects.asking') : t('projects.ask'))}</span>
                    </button>
                    <button class="btn-secondary" type="button" data-project-expand ${projectAskLoading || !documents.length ? 'disabled' : ''}>
                        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.4"><path d="M4 12h16"/><path d="M12 4v16"/></svg>
                        <span>${escapeHtml(t('projects.expandMap'))}</span>
                    </button>
                </div>
                ${renderProjectStatus()}
                ${renderProjectAnswer()}
                ${renderProjectContextSources()}
            </div>
        </aside>
    `;
}

function renderDrivePathJumpSelect() {
    const root = driveRootItem();
    const selectedId = currentProjectId || root?.id || '';
    const folders = driveItems()
        .filter((item) => item.type === 'folder')
        .sort((a, b) => driveBreadcrumbText(a.id).localeCompare(driveBreadcrumbText(b.id), currentLanguage === 'zh' ? 'zh-CN' : 'en'));
    const recentFolders = driveRecentPathIds
        .map((id) => driveItemById(id))
        .filter((item) => item?.type === 'folder' && item.id !== root?.id);
    const recentIds = new Set(recentFolders.map((item) => item.id));
    const allFolders = folders.filter((item) => item.id !== root?.id && !recentIds.has(item.id));
    const option = (item) => `<option value="${escapeAttr(item.id)}" ${item.id === selectedId ? 'selected' : ''}>${escapeHtml(driveBreadcrumbText(item.id))}</option>`;
    return `
        <label class="project-path-jump">
            <span class="visually-hidden">${escapeHtml(t('projects.pathJump'))}</span>
            <select data-drive-path-jump aria-label="${escapeAttr(t('projects.pathJump'))}">
                ${root ? `<option value="${escapeAttr(root.id)}" ${root.id === selectedId ? 'selected' : ''}>${escapeHtml(t('projects.rootName'))}</option>` : ''}
                ${recentFolders.length ? `<optgroup label="${escapeAttr(t('projects.frequentPaths'))}">${recentFolders.map(option).join('')}</optgroup>` : ''}
                ${allFolders.length ? `<optgroup label="${escapeAttr(t('projects.allPaths'))}">${allFolders.map(option).join('')}</optgroup>` : ''}
            </select>
        </label>
    `;
}

function renderProjectDocumentList() {
    const documents = projectSearchQuery.trim()
        ? projectSearchResults.map((result) => ({ ...result.document, _score: result.score, _snippet: result.snippet }))
        : projectDocuments();
    if (!documents.length) {
        return `<div class="empty-inline">${escapeHtml(projectSearchQuery.trim() ? t('projects.noSearchResults') : t('projects.noDocuments'))}</div>`;
    }
    return `
        <div class="project-document-list">
            ${documents.map(renderProjectDocumentRow).join('')}
        </div>
    `;
}

function renderProjectDocumentRow(doc) {
    const active = doc.id === activeProjectDocumentId;
    const deleting = pendingProjectDocumentDeletes.has(doc.id);
    const tags = Array.isArray(doc.tags) ? doc.tags.slice(0, 3) : [];
    const score = doc._score ? `<span class="chip muted">${escapeHtml(String(doc._score))}</span>` : '';
    return `
        <div class="project-document-row ${active ? 'active' : ''}">
            <button class="project-document-main" type="button" data-project-open-document="${escapeAttr(doc.id)}">
                <strong>${escapeHtml(doc.title || '')}</strong>
                <p>${escapeHtml(truncateText(doc._snippet || doc.summary || doc.content || '', 150))}</p>
                <span class="project-document-meta">
                    <span class="status-chip neutral">${escapeHtml(projectTypeLabel(doc))}</span>
                    ${score}
                    ${tags.map((tag) => `<span class="chip">${escapeHtml(tag)}</span>`).join('')}
                </span>
            </button>
            <button class="project-mini-button danger" type="button" data-project-delete-document="${escapeAttr(doc.id)}" title="${escapeAttr(t('actions.delete'))}" ${deleting ? 'disabled aria-busy="true"' : ''}>
                <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.4"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v5M14 11v5"/></svg>
            </button>
        </div>
    `;
}

function renderProjectMap(documents = [], links = [], activeDoc = null) {
    if (!documents.length) {
        return `<div class="project-map-wrap">${emptyState(t('projects.noDocuments'), '')}</div>`;
    }
    const nodes = documents.slice(0, 24);
    const positions = projectMapPositions(nodes.length);
    const positionById = new Map(nodes.map((doc, index) => [doc.id, positions[index]]));
    const edges = links.filter((link) => positionById.has(link.from_document_id) && positionById.has(link.to_document_id));
    return `
        <div class="project-map-wrap">
            <div class="project-map-stage">
                <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
                    ${edges.map((edge) => {
                        const from = positionById.get(edge.from_document_id);
                        const to = positionById.get(edge.to_document_id);
                        return `<line class="project-map-edge" x1="${from.x}" y1="${from.y}" x2="${to.x}" y2="${to.y}"><title>${escapeHtml(edge.relation || '')}</title></line>`;
                    }).join('')}
                </svg>
                ${nodes.map((doc, index) => {
                    const position = positions[index];
                    const active = activeDoc?.id === doc.id;
                    return `
                        <button class="project-map-node ${active ? 'active' : ''}" type="button"
                                style="left:${position.x}%;top:${position.y}%"
                                data-project-open-document="${escapeAttr(doc.id)}">
                            <strong>${escapeHtml(doc.title || '')}</strong>
                            <small>${escapeHtml(projectTypeLabel(doc))}</small>
                        </button>
                    `;
                }).join('')}
            </div>
        </div>
    `;
}

function projectMapPositions(count) {
    if (count <= 1) return [{ x: 50, y: 50 }];
    const positions = [];
    const radiusX = 36;
    const radiusY = 34;
    for (let index = 0; index < count; index += 1) {
        const angle = (Math.PI * 2 * index) / count - Math.PI / 2;
        positions.push({
            x: Math.round((50 + Math.cos(angle) * radiusX) * 10) / 10,
            y: Math.round((50 + Math.sin(angle) * radiusY) * 10) / 10,
        });
    }
    return positions;
}

function renderProjectDocumentDetail(doc) {
    if (!doc) return emptyState(t('projects.activeDocument'), t('projects.noDocuments'));
    const tags = Array.isArray(doc.tags) ? doc.tags : [];
    const related = projectLinks()
        .filter((link) => link.from_document_id === doc.id || link.to_document_id === doc.id)
        .slice(0, 8);
    return `
        <article class="project-detail-head">
            <div>
                <span class="status-chip neutral">${escapeHtml(projectTypeLabel(doc))}</span>
                <h2>${escapeHtml(doc.title || '')}</h2>
                <p>${escapeHtml(doc.summary || '')}</p>
            </div>
            ${tags.length ? `<div class="project-tag-row">${tags.map((tag) => `<span class="chip">${escapeHtml(tag)}</span>`).join('')}</div>` : ''}
            ${related.length ? `
                <div class="project-map-meta">
                    ${related.map((link) => `<span class="status-chip ok">${escapeHtml(link.relation || '')} · ${escapeHtml(String(link.confidence || 0))}</span>`).join('')}
                </div>
            ` : ''}
            <div class="project-doc-content">${escapeHtml(doc.content || '')}</div>
        </article>
    `;
}

function renderProjectSelectionBar() {
    const count = selectedProjectDocumentIds.size;
    return `
        <div class="project-selection-bar">
            <div class="project-selection-meta">
                <span class="status-chip neutral">${escapeHtml(t('projects.selected', { count }))}</span>
            </div>
            <div class="project-panel-actions">
                <button class="btn-secondary" type="button" data-project-create-from-selection ${count ? '' : 'disabled'}>
                    <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.4"><path d="M4 5h7l2 2h7v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2Z"/><path d="M12 11v6M9 14h6"/></svg>
                    <span>${escapeHtml(t('actions.createFromSelection'))}</span>
                </button>
                <button class="btn-secondary" type="button" data-project-clear-selection ${count ? '' : 'disabled'}>
                    <span>${escapeHtml(t('actions.clearSelection'))}</span>
                </button>
            </div>
        </div>
    `;
}

function renderProjectStatus() {
    const status = projectAskError || projectStatusText;
    if (!status) return '<div class="project-status"></div>';
    const type = projectAskError ? 'error' : projectStatusType;
    return `<div class="project-status ${escapeAttr(type)}">${escapeHtml(status)}</div>`;
}

function renderProjectAnswer() {
    const answer = projectAskAnswer || '';
    return `
        <section class="project-answer">
            <div class="project-answer-head">
                <strong>${escapeHtml(t('projects.answer'))}</strong>
                <button class="btn-secondary" type="button" data-project-save-answer ${answer.trim() && !projectAskLoading ? '' : 'disabled'}>
                    <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.4"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2Z"/><path d="M17 21v-8H7v8"/><path d="M7 3v5h8"/></svg>
                    <span>${escapeHtml(t('actions.saveAsDocument'))}</span>
                </button>
            </div>
            <div class="project-answer-body">${escapeHtml(answer || t('projects.answerEmpty'))}</div>
        </section>
    `;
}

function renderProjectContextSources() {
    const sources = Array.isArray(projectAskSources) ? projectAskSources : [];
    if (!sources.length) return '';
    return `
        <section class="project-answer">
            <div class="project-answer-head">
                <strong>${escapeHtml(t('projects.contextSources'))}</strong>
            </div>
            <div class="project-source-list">
                ${sources.map((doc) => `
                    <button class="project-source-item" type="button" data-project-open-document="${escapeAttr(doc.id)}">
                        <strong>${escapeHtml(doc.title || '')}</strong>
                        <small>${escapeHtml(doc.summary || '')}</small>
                    </button>
                `).join('')}
            </div>
        </section>
    `;
}

function projectTypeLabel(itemOrType = '') {
    const labels = I18N[currentLanguage].projects.type;
    if (itemOrType && typeof itemOrType === 'object') {
        const type = String(itemOrType.type || '');
        if (type === 'folder') return labels.folder;
        if (type === 'file') {
            const ext = driveFileExtension(itemOrType);
            if (ext) return currentLanguage === 'zh' ? `${ext}文件` : `${ext} file`;
            return labels.file;
        }
        return labels[type] || type || labels.source;
    }
    const type = String(itemOrType || '');
    return labels[type] || type || labels.source;
}

function driveItems() {
    return Array.isArray(projectDetail?.flat_items) ? projectDetail.flat_items : projects;
}

function driveContentItems() {
    return driveItems().filter((item) => !driveIsRootItem(item));
}

function driveTreeItems() {
    return Array.isArray(projectDetail?.items) ? projectDetail.items : [];
}

function driveRootItem() {
    return driveItems().find(driveIsRootItem) || driveTreeItems().find(driveIsRootItem) || null;
}

function driveIsRootItem(item) {
    return Boolean(item && item.type === 'folder' && !item.parent_id);
}

function driveDisplayName(item) {
    if (!item) return '';
    return driveIsRootItem(item) ? t('projects.rootName') : (item.name || '');
}

function driveItemById(id = '') {
    if (!id) return null;
    return driveItems().find((item) => item.id === id) || null;
}

function driveItemIsFolder(id = '') {
    return driveItemById(id)?.type === 'folder';
}

function chatDrivePathItem() {
    const item = driveItemById(chatDrivePathId);
    if (item?.type === 'folder') return item;
    return driveRootItem();
}

function chatDrivePathDisplay() {
    const item = chatDrivePathItem();
    return item?.id ? driveBreadcrumbText(item.id) : t('projects.rootName');
}

function setChatDrivePath(id = '') {
    const folderId = normalizeDriveSaveFolderId(id, driveRootItem()?.id || '');
    chatDrivePathId = folderId;
    saveChatDrivePathId(chatDrivePathId);
    rememberDrivePath(chatDrivePathId, { render: false });
    renderModes();
}

function rememberDrivePath(folderId = '', options = {}) {
    const folder = driveItemById(folderId);
    if (!folder || folder.type !== 'folder') return;
    driveRecentPathIds = [folder.id, ...driveRecentPathIds.filter((id) => id !== folder.id && driveItemIsFolder(id))].slice(0, 8);
    saveDriveRecentPathIds();
    if (options.render !== false) renderProjects();
}

function enterDriveFolder(folderId = '') {
    const folder = driveItemById(folderId) || driveRootItem();
    if (!folder || folder.type !== 'folder') return;
    currentProjectId = folder.id;
    activeProjectDocumentId = '';
    projectInlineFileId = '';
    projectInlineFileDetail = { item: null, loading: false, error: '' };
    saveCurrentProjectId(currentProjectId);
    rememberDrivePath(currentProjectId, { render: false });
    renderProjectList();
    renderProjects();
}

function goToDriveParentFolder() {
    const folder = currentProjectRecord();
    const parent = folder?.parent_id ? driveItemById(folder.parent_id) : null;
    enterDriveFolder(parent?.id || driveRootItem()?.id || '');
}

function toggleDriveFolderCollapsed(folderId = '') {
    if (!folderId || !driveItemIsFolder(folderId)) return;
    if (collapsedDriveFolderIds.has(folderId)) {
        collapsedDriveFolderIds.delete(folderId);
    } else {
        collapsedDriveFolderIds.add(folderId);
    }
    saveDriveCollapsedFolderIds();
    renderProjects();
}

function driveChildren(parentId = '') {
    const normalizedParent = parentId || '';
    return driveItems().filter((item) => (item.parent_id || '') === normalizedParent);
}

function driveChildCounts(parentId = '') {
    const children = driveChildren(parentId);
    return {
        folders: children.filter((item) => item.type === 'folder').length,
        files: children.filter((item) => item.type === 'file').length,
    };
}

function driveFolderHasFiles(folderId = '') {
    const children = driveChildren(folderId);
    return children.some((item) => item.type === 'file' || (item.type === 'folder' && driveFolderHasFiles(item.id)));
}

function driveSelectedItems() {
    return Array.from(selectedProjectDocumentIds).map((id) => driveItemById(id)).filter(Boolean);
}

function createEmptyDriveDragState() {
    return {
        sourceId: '',
        itemIds: [],
        dropFolderId: '',
    };
}

function createEmptyDriveSelectionBoxState() {
    return {
        active: false,
        pointerId: null,
        list: null,
        rectEl: null,
        startX: 0,
        startY: 0,
        currentX: 0,
        currentY: 0,
        additive: false,
        moved: false,
        selectedBefore: new Set(),
    };
}

function driveSelectableItem(item) {
    return Boolean(item?.id && !driveIsRootItem(item));
}

function driveSelectableItemId(itemId = '') {
    return driveSelectableItem(driveItemById(itemId));
}

function driveSelectableIdsInList(listEl) {
    if (!listEl) return [];
    return Array.from(listEl.querySelectorAll('[data-drive-selectable="true"][data-drive-item-id]'))
        .map((row) => row.dataset.driveItemId || '')
        .filter(driveSelectableItemId);
}

function normalizeDriveSelection(ids = []) {
    const normalized = [];
    const seen = new Set();
    ids.forEach((id) => {
        if (!id || seen.has(id) || !driveSelectableItemId(id)) return;
        seen.add(id);
        normalized.push(id);
    });
    return normalized;
}

function setDriveSelection(ids = [], options = {}) {
    const normalized = normalizeDriveSelection(ids);
    selectedProjectDocumentIds = new Set(normalized);
    const preferredLastId = options.lastId || lastSelectedProjectDocumentId;
    if (preferredLastId && selectedProjectDocumentIds.has(preferredLastId)) {
        lastSelectedProjectDocumentId = preferredLastId;
    } else {
        lastSelectedProjectDocumentId = normalized.length ? normalized[normalized.length - 1] : '';
    }
    if (options.render === false) {
        updateDriveSelectionDom(options.scope || document);
        return;
    }
    renderModes();
    renderProjects();
}

function updateDriveSelectionDom(scope = document) {
    scope.querySelectorAll?.('[data-drive-item-id]').forEach((row) => {
        row.classList.toggle('selected', selectedProjectDocumentIds.has(row.dataset.driveItemId || ''));
    });
}

function selectDriveDocumentRange(anchorId = '', targetId = '', listEl = null, selected = true) {
    if (!driveSelectableItemId(targetId)) return;
    const ids = driveSelectableIdsInList(listEl);
    const anchorIndex = ids.indexOf(anchorId);
    const targetIndex = ids.indexOf(targetId);
    if (anchorIndex === -1 || targetIndex === -1) {
        toggleProjectDocumentSelection(targetId, selected);
        return;
    }
    const [start, end] = anchorIndex < targetIndex ? [anchorIndex, targetIndex] : [targetIndex, anchorIndex];
    const next = new Set(selectedProjectDocumentIds);
    ids.slice(start, end + 1).forEach((id) => {
        if (selected) {
            next.add(id);
        } else {
            next.delete(id);
        }
    });
    setDriveSelection(Array.from(next), { lastId: targetId });
}

function handleProjectDocumentModifiedClick(button, event) {
    const documentId = button?.dataset.projectOpenDocument || '';
    if (!driveSelectableItemId(documentId)) return false;
    const isRange = event.shiftKey && lastSelectedProjectDocumentId;
    const isToggle = event.metaKey || event.ctrlKey;
    if (!isRange && !isToggle) return false;
    event.preventDefault();
    if (isRange) {
        selectDriveDocumentRange(lastSelectedProjectDocumentId, documentId, button.closest('.project-document-list'), true);
    } else {
        toggleProjectDocumentSelection(documentId, !selectedProjectDocumentIds.has(documentId));
    }
    return true;
}

function noteDrivePlainClick(documentId = '') {
    if (!driveSelectableItemId(documentId)) return;
    if (selectedProjectDocumentIds.size) {
        selectedProjectDocumentIds = new Set();
        updateDriveSelectionDom(document);
        renderModes();
    }
    lastSelectedProjectDocumentId = documentId;
}

function driveTopLevelItemIds(ids = []) {
    const normalized = normalizeDriveSelection(ids);
    const selected = new Set(normalized);
    return normalized.filter((id) => {
        let item = driveItemById(id);
        while (item?.parent_id) {
            if (selected.has(item.parent_id)) return false;
            item = driveItemById(item.parent_id);
        }
        return true;
    });
}

function driveDragItemIds(sourceId = '') {
    if (!driveSelectableItemId(sourceId)) return [];
    const candidates = selectedProjectDocumentIds.has(sourceId) && selectedProjectDocumentIds.size
        ? Array.from(selectedProjectDocumentIds)
        : [sourceId];
    return driveTopLevelItemIds(candidates);
}

function driveCanMoveItemToFolder(itemId = '', folderId = '') {
    const item = driveItemById(itemId);
    const folder = driveItemById(folderId);
    if (!driveSelectableItem(item) || !folder || folder.type !== 'folder') return false;
    if (item.id === folder.id || item.parent_id === folder.id) return false;
    if (item.type === 'folder' && driveHasAncestor(folder.id, item.id)) return false;
    return true;
}

function driveMovableItemIds(folderId = '', itemIds = driveDragState.itemIds) {
    return driveTopLevelItemIds(itemIds).filter((id) => driveCanMoveItemToFolder(id, folderId));
}

function driveDropTargetFromEvent(event) {
    if (!event?.target?.closest) return null;
    const row = event.target.closest('.project-document-row');
    if (row) {
        const folderId = row.dataset.driveDropFolderId || '';
        return folderId ? { element: row, folderId } : null;
    }
    const zone = event.target.closest('[data-drive-drop-folder-id]');
    const folderId = zone?.dataset.driveDropFolderId || '';
    return folderId ? { element: zone, folderId } : null;
}

function clearDriveDropTargets() {
    document.querySelectorAll('.drive-drop-target, .drive-drop-target-invalid').forEach((el) => {
        el.classList.remove('drive-drop-target', 'drive-drop-target-invalid');
    });
}

function markDriveDropTarget(target, valid) {
    clearDriveDropTargets();
    if (!target?.element) return;
    target.element.classList.add(valid ? 'drive-drop-target' : 'drive-drop-target-invalid');
}

function clearDriveDragState() {
    clearDriveDropTargets();
    document.body.classList.remove('drive-dragging');
    document.querySelectorAll('.project-document-row.dragging').forEach((row) => row.classList.remove('dragging'));
    driveDragState = createEmptyDriveDragState();
}

function shouldStartDriveSelectionBox(event) {
    if (activeView !== 'projects' || event.button !== 0 || event.pointerType === 'touch') return false;
    if (drivePreviewIsOpen() || driveSaveDialogIsOpen() || drivePathDialogIsOpen()) return false;
    if (event.target.closest?.('button, input, select, textarea, a, [contenteditable="true"], .project-document-row')) return false;
    const list = event.target.closest?.('.project-document-list');
    return Boolean(list?.querySelector('[data-drive-selectable="true"]'));
}

function startDriveSelectionBox(event) {
    if (!shouldStartDriveSelectionBox(event)) return;
    const list = event.target.closest('.project-document-list');
    const rectEl = document.createElement('div');
    rectEl.className = 'drive-selection-rect';
    document.body.appendChild(rectEl);
    driveSelectionBoxState = {
        ...createEmptyDriveSelectionBoxState(),
        active: true,
        pointerId: event.pointerId,
        list,
        rectEl,
        startX: event.clientX,
        startY: event.clientY,
        currentX: event.clientX,
        currentY: event.clientY,
        additive: event.metaKey || event.ctrlKey,
        selectedBefore: new Set(selectedProjectDocumentIds),
    };
    document.body.classList.add('drive-selecting');
    event.preventDefault();
}

function updateDriveSelectionBox(event) {
    if (!driveSelectionBoxState.active || event.pointerId !== driveSelectionBoxState.pointerId) return;
    driveSelectionBoxState.currentX = event.clientX;
    driveSelectionBoxState.currentY = event.clientY;
    const left = Math.min(driveSelectionBoxState.startX, driveSelectionBoxState.currentX);
    const top = Math.min(driveSelectionBoxState.startY, driveSelectionBoxState.currentY);
    const width = Math.abs(driveSelectionBoxState.currentX - driveSelectionBoxState.startX);
    const height = Math.abs(driveSelectionBoxState.currentY - driveSelectionBoxState.startY);
    if (width < 4 && height < 4) return;
    driveSelectionBoxState.moved = true;
    Object.assign(driveSelectionBoxState.rectEl.style, {
        left: `${left}px`,
        top: `${top}px`,
        width: `${width}px`,
        height: `${height}px`,
    });
    const selectionRect = { left, top, right: left + width, bottom: top + height };
    const hitIds = Array.from(driveSelectionBoxState.list.querySelectorAll('[data-drive-selectable="true"][data-drive-item-id]'))
        .filter((row) => rectsIntersect(selectionRect, row.getBoundingClientRect()))
        .map((row) => row.dataset.driveItemId || '')
        .filter(driveSelectableItemId);
    const next = new Set(driveSelectionBoxState.additive ? driveSelectionBoxState.selectedBefore : []);
    hitIds.forEach((id) => next.add(id));
    setDriveSelection(Array.from(next), { render: false, scope: driveSelectionBoxState.list });
    event.preventDefault();
}

function rectsIntersect(a, b) {
    return a.left <= b.right && a.right >= b.left && a.top <= b.bottom && a.bottom >= b.top;
}

function finishDriveSelectionBox(event) {
    if (!driveSelectionBoxState.active || event.pointerId !== driveSelectionBoxState.pointerId) return;
    const moved = driveSelectionBoxState.moved;
    cancelDriveSelectionBox();
    if (moved) {
        event.preventDefault();
        renderModes();
        renderProjects();
    }
}

function cancelDriveSelectionBox() {
    if (driveSelectionBoxState.rectEl) {
        driveSelectionBoxState.rectEl.remove();
    }
    document.body.classList.remove('drive-selecting');
    driveSelectionBoxState = createEmptyDriveSelectionBoxState();
}

async function moveDriveItemsToFolder(itemIds = [], folderId = '') {
    const movableIds = driveMovableItemIds(folderId, itemIds);
    if (!movableIds.length) return;
    try {
        await Promise.all(movableIds.map((id) => apiCall('PUT', `/api/drive/items/${encodeURIComponent(id)}`, {
            parent_id: folderId,
        })));
        projectStatusText = t('projects.moveDone', { count: movableIds.length });
        projectStatusType = 'ok';
        setDriveSelection(movableIds, { render: false });
        await loadProjects();
    } catch (err) {
        projectStatusText = t('projects.moveFailed', { message: err.message });
        projectStatusType = 'error';
        renderProjects();
    }
}

function handleDriveDragStart(event) {
    if (activeView !== 'projects') return;
    const row = event.target.closest?.('[data-drive-item-id][draggable="true"]');
    const sourceId = row?.dataset.driveItemId || '';
    const itemIds = driveDragItemIds(sourceId);
    if (!row || !itemIds.length) {
        event.preventDefault();
        return;
    }
    driveDragState = {
        ...createEmptyDriveDragState(),
        sourceId,
        itemIds,
    };
    if (!selectedProjectDocumentIds.has(sourceId)) {
        setDriveSelection([sourceId], { lastId: sourceId, render: false });
        renderModes();
    }
    row.classList.add('dragging');
    document.body.classList.add('drive-dragging');
    if (event.dataTransfer) {
        event.dataTransfer.effectAllowed = 'move';
        event.dataTransfer.setData('application/x-drive-item-ids', JSON.stringify(itemIds));
        event.dataTransfer.setData('text/plain', itemIds.join(','));
    }
}

function handleDriveDragOver(event) {
    if (!driveDragState.itemIds.length) return;
    const target = driveDropTargetFromEvent(event);
    if (!target) {
        clearDriveDropTargets();
        return;
    }
    const movableIds = driveMovableItemIds(target.folderId);
    const valid = movableIds.length > 0;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = valid ? 'move' : 'none';
    markDriveDropTarget(target, valid);
}

async function handleDriveDrop(event) {
    if (!driveDragState.itemIds.length) return;
    const target = driveDropTargetFromEvent(event);
    if (!target) {
        clearDriveDragState();
        return;
    }
    event.preventDefault();
    const itemIds = [...driveDragState.itemIds];
    const folderId = target.folderId;
    clearDriveDragState();
    await moveDriveItemsToFolder(itemIds, folderId);
}

function driveHasAncestor(itemId = '', ancestorId = '') {
    let item = driveItemById(itemId);
    while (item?.parent_id) {
        if (item.parent_id === ancestorId) return true;
        item = driveItemById(item.parent_id);
    }
    return false;
}

function driveBreadcrumbText(folderId = currentProjectId) {
    const stack = [];
    let item = driveItemById(folderId);
    const seen = new Set();
    while (item && !seen.has(item.id)) {
        seen.add(item.id);
        stack.unshift(driveDisplayName(item));
        item = driveItemById(item.parent_id);
    }
    return stack.filter(Boolean).join(' / ') || t('projects.rootName');
}

function driveItemSnippet(item) {
    if (item.type === 'folder') return driveItemMeta(item);
    return truncateText(item._snippet || item.summary || item.content || '', 150) || driveItemMeta(item);
}

function driveItemMeta(item) {
    if (item.type === 'folder') {
        return t('projects.folderContents', driveChildCounts(item.id));
    }
    const updated = item.updated_at ? formatFullTime(item.updated_at) : '';
    return [formatBytes(item.size || 0), updated].filter(Boolean).join(' · ');
}

function drivePromptContext(agentId = selectedModeAgentId()) {
    if (agentId !== SUPER_CHAT_AGENT_ID) return null;
    const folder = chatDrivePathItem() || driveRootItem();
    if (!folder?.id) return null;
    const children = driveChildren(folder.id).filter((item) => item && !driveIsRootItem(item));
    const visibleItems = children.slice(0, DRIVE_PROMPT_CONTEXT_ITEM_LIMIT);
    return {
        current_folder_id: folder.id,
        current_path: drivePromptPath(folder),
        items: visibleItems.map((item) => ({
            id: item.id || '',
            type: item.type || '',
            name: driveDisplayName(item),
            path: drivePromptPath(item),
            mime_type: item.mime_type || '',
            size: Number(item.size || 0),
            summary: truncateText(item.summary || driveItemMeta(item), 240),
            updated_at: item.updated_at || '',
        })),
        truncated: children.length > visibleItems.length,
    };
}

function drivePromptPath(item) {
    if (!item?.id) return '';
    if (driveIsRootItem(item)) return '/';
    const breadcrumb = driveBreadcrumbText(item.id);
    return breadcrumb ? `/${breadcrumb}` : '/';
}

function driveFileExtension(item) {
    const name = String(item?.name || item?.title || '').toLowerCase();
    const match = name.match(/\.([a-z0-9]+)$/);
    return match ? match[1] : '';
}

function driveItemIsMarkdown(item) {
    if (!item || item.type !== 'file') return false;
    const mime = String(item.mime_type || '').toLowerCase();
    const ext = driveFileExtension(item);
    return mime.includes('markdown') || ['md', 'mdx', 'markdown'].includes(ext);
}

function driveItemIconKind(item) {
    if (item?.type === 'folder') return 'folder';
    const mime = String(item?.mime_type || '').toLowerCase();
    const ext = driveFileExtension(item);
    if (mime.includes('pdf') || ext === 'pdf') return 'pdf';
    if (mime.startsWith('image/') || ['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp', 'heic'].includes(ext)) return 'image';
    if (mime.startsWith('audio/') || ['mp3', 'wav', 'm4a', 'aac', 'flac', 'ogg'].includes(ext)) return 'audio';
    if (mime.startsWith('video/') || ['mp4', 'mov', 'webm', 'mkv', 'avi'].includes(ext)) return 'video';
    if (mime.includes('spreadsheet') || mime.includes('excel') || ['xls', 'xlsx', 'csv', 'tsv', 'ods'].includes(ext)) return 'sheet';
    if (mime.includes('presentation') || mime.includes('powerpoint') || ['ppt', 'pptx', 'key', 'odp'].includes(ext)) return 'slide';
    if (mime.includes('word') || mime.includes('rtf') || ['doc', 'docx', 'rtf', 'odt'].includes(ext)) return 'document';
    if (mime.includes('markdown') || ['md', 'mdx', 'markdown'].includes(ext)) return 'markdown';
    if (mime.includes('zip') || mime.includes('compressed') || ['zip', 'rar', '7z', 'tar', 'gz'].includes(ext)) return 'archive';
    if (['json', 'yaml', 'yml', 'toml', 'xml'].includes(ext)) return 'data';
    if (mime.includes('javascript') || mime.includes('typescript') || ['js', 'jsx', 'ts', 'tsx', 'go', 'py', 'java', 'kt', 'rs', 'rb', 'php', 'c', 'cpp', 'h', 'css', 'scss', 'html', 'sh', 'sql'].includes(ext)) return 'code';
    if (mime.startsWith('text/') || ['txt', 'log'].includes(ext)) return 'text';
    return 'file';
}

function driveItemIconSvg(item) {
    const kind = driveItemIconKind(item);
    const className = `drive-inline-icon drive-inline-icon-${kind}`;
    if (kind === 'folder') {
        return `<svg class="${className}" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.3" aria-hidden="true" focusable="false"><path d="M4 5h7l2 2h7v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2Z" fill="currentColor" fill-opacity=".14"/><path d="M4 5h7l2 2h7v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2Z"/></svg>`;
    }
    if (kind === 'image') {
        return `<svg class="${className}" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.1" aria-hidden="true" focusable="false"><rect x="4" y="5" width="16" height="14" rx="2.5"/><path d="m7 16 3.5-4 3 3 2-2.2L18 16"/><circle cx="15.5" cy="9" r="1.2" fill="currentColor" stroke="none"/></svg>`;
    }
    if (kind === 'pdf') {
        return `<svg class="${className}" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true" focusable="false"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z"/><path d="M14 3v5h5"/><text x="6.2" y="17" fill="currentColor" stroke="none" font-size="6.2" font-weight="800">PDF</text></svg>`;
    }
    if (kind === 'sheet') {
        return `<svg class="${className}" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true" focusable="false"><rect x="5" y="4" width="14" height="16" rx="2"/><path d="M5 10h14M5 15h14M10 4v16M15 4v16"/></svg>`;
    }
    if (kind === 'slide') {
        return `<svg class="${className}" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.1" aria-hidden="true" focusable="false"><rect x="4" y="5" width="16" height="11" rx="2"/><path d="M12 16v4M8 20h8"/><path d="M9 12h5M9 9h6"/></svg>`;
    }
    if (kind === 'document' || kind === 'text' || kind === 'markdown') {
        const label = kind === 'markdown' ? '<text x="7" y="17" fill="currentColor" stroke="none" font-size="6.5" font-weight="800">MD</text>' : '<path d="M8 11h8M8 15h6"/>';
        return `<svg class="${className}" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true" focusable="false"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z"/><path d="M14 3v5h5"/>${label}</svg>`;
    }
    if (kind === 'code') {
        return `<svg class="${className}" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true" focusable="false"><path d="m9 9-3 3 3 3M15 9l3 3-3 3"/><path d="m13 7-2 10"/></svg>`;
    }
    if (kind === 'data') {
        return `<svg class="${className}" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true" focusable="false"><path d="M8 7c-2 0-2 2-2 3v1c0 1-1 1-2 1 1 0 2 0 2 1v1c0 1 0 3 2 3M16 7c2 0 2 2 2 3v1c0 1 1 1 2 1-1 0-2 0-2 1v1c0 1 0 3-2 3"/><path d="M11 9h2M11 15h2"/></svg>`;
    }
    if (kind === 'archive') {
        return `<svg class="${className}" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.1" aria-hidden="true" focusable="false"><path d="M6 4h12v16H6Z"/><path d="M10 4v4h4V4M10 12h4M10 16h4"/></svg>`;
    }
    if (kind === 'audio') {
        return `<svg class="${className}" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true" focusable="false"><path d="M9 18V6l9-2v12"/><circle cx="7" cy="18" r="2"/><circle cx="16" cy="16" r="2"/></svg>`;
    }
    if (kind === 'video') {
        return `<svg class="${className}" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true" focusable="false"><rect x="4" y="6" width="16" height="12" rx="2"/><path d="m11 10 4 2-4 2Z" fill="currentColor" stroke="none"/></svg>`;
    }
    return `<svg class="${className}" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.1" aria-hidden="true" focusable="false"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z"/><path d="M14 3v5h5"/></svg>`;
}

function downloadDriveItem(id = '') {
    const item = driveItemById(id);
    if (!item || item.type !== 'file') return;
    const params = new URLSearchParams();
    if (currentAccountToken) {
        params.set('account_session', currentAccountToken);
    } else if (currentUserId) {
        params.set('user_id', currentUserId);
    }
    const query = params.toString();
    const url = `${API_BASE}/api/drive/items/${encodeURIComponent(id)}/download${query ? `?${query}` : ''}`;
    window.open(url, '_blank', 'noopener');
}

function openChatWithDrivePath(folderId = currentProjectId) {
    const folder = driveItemById(folderId) || driveRootItem();
    if (!folder || folder.type !== 'folder') return;
    setChatDrivePath(folder.id);
    setView('chat');
    focusMessageInput();
}

function createEmptyDrivePreviewState() {
    return {
        open: false,
        loading: false,
        itemId: '',
        item: null,
        error: '',
        returnFocus: null,
    };
}

function drivePreviewIsOpen() {
    return Boolean(drivePreviewState.open);
}

async function openDriveDocumentPreview(itemId = '', returnFocus = null) {
    const cached = driveItemById(itemId);
    if (!cached || cached.type !== 'file') return;
    drivePreviewState = {
        ...createEmptyDrivePreviewState(),
        open: true,
        loading: true,
        itemId,
        item: cached,
        returnFocus: returnFocus || document.activeElement,
    };
    renderDriveDocumentPreview();
    try {
        const data = await apiCall('GET', `/api/drive/items/${encodeURIComponent(itemId)}`);
        if (!drivePreviewState.open || drivePreviewState.itemId !== itemId) return;
        drivePreviewState.item = data.item || cached;
        drivePreviewState.loading = false;
        drivePreviewState.error = '';
        renderDriveDocumentPreview();
    } catch (err) {
        if (!drivePreviewState.open || drivePreviewState.itemId !== itemId) return;
        drivePreviewState.loading = false;
        drivePreviewState.error = t('projects.previewFailed', { message: err.message });
        renderDriveDocumentPreview();
    }
}

function closeDriveDocumentPreview() {
    if (!drivePreviewState.open) return;
    const returnFocus = drivePreviewState.returnFocus;
    drivePreviewState = createEmptyDrivePreviewState();
    renderDriveDocumentPreview();
    requestAnimationFrame(() => {
        if (returnFocus && typeof returnFocus.focus === 'function') {
            returnFocus.focus({ preventScroll: true });
        }
    });
}

function renderDriveDocumentPreview() {
    if (!drivePreviewDialog) return;
    const isOpen = drivePreviewState.open;
    drivePreviewDialog.classList.toggle('hidden', !isOpen);
    document.body.classList.toggle('drive-preview-open', isOpen);
    const item = drivePreviewState.item;
    if (!isOpen) {
        if (drivePreviewTitle) drivePreviewTitle.textContent = '';
        if (drivePreviewMeta) drivePreviewMeta.textContent = '';
        if (drivePreviewStatus) drivePreviewStatus.textContent = '';
        if (drivePreviewContent) drivePreviewContent.textContent = '';
        if (drivePreviewDownload) drivePreviewDownload.disabled = true;
        return;
    }
    if (drivePreviewTitle) drivePreviewTitle.textContent = driveDisplayName(item) || t('projects.activeDocument');
    if (drivePreviewMeta) drivePreviewMeta.textContent = item ? [driveBreadcrumbText(item.parent_id), driveItemMeta(item)].filter(Boolean).join(' · ') : '';
    if (drivePreviewStatus) {
        drivePreviewStatus.textContent = drivePreviewState.loading ? t('projects.previewLoading') : (drivePreviewState.error || '');
        drivePreviewStatus.classList.toggle('error', Boolean(drivePreviewState.error));
        drivePreviewStatus.hidden = !drivePreviewState.loading && !drivePreviewState.error;
    }
    if (drivePreviewContent) {
        const isBinary = item?.encoding === 'base64';
        const isMarkdown = !isBinary && driveItemIsMarkdown(item);
        drivePreviewContent.classList.toggle('binary', isBinary);
        drivePreviewContent.classList.toggle('markdown', isMarkdown);
        drivePreviewContent.classList.toggle('drive-markdown-content', isMarkdown);
        if (isBinary) {
            drivePreviewContent.innerHTML = renderDriveBinaryPreview(item);
        } else if (isMarkdown) {
            drivePreviewContent.innerHTML = renderDriveMarkdownContent(item);
        } else {
            drivePreviewContent.textContent = item?.content || item?.summary || '';
        }
    }
    if (drivePreviewDownload) {
        drivePreviewDownload.disabled = !item?.id || drivePreviewState.loading;
        drivePreviewDownload.dataset.drivePreviewDownload = item?.id || '';
    }
}

function driveItemDataUrl(item) {
    if (!item || item.encoding !== 'base64' || !item.content) return '';
    const mime = item.mime_type || 'application/octet-stream';
    return `data:${mime};base64,${item.content}`;
}

function renderDriveBinaryPreview(item) {
    const dataUrl = driveItemDataUrl(item);
    const mime = String(item?.mime_type || '').toLowerCase();
    const message = escapeHtml(item?.summary || t('projects.previewBinary'));
    if (dataUrl && mime.startsWith('image/')) {
        return `<figure class="drive-preview-media"><img src="${escapeAttr(dataUrl)}" alt="${escapeAttr(driveDisplayName(item))}"><figcaption>${message}</figcaption></figure>`;
    }
    if (dataUrl && mime.startsWith('audio/')) {
        return `<div class="drive-preview-media"><audio controls src="${escapeAttr(dataUrl)}"></audio><p>${message}</p></div>`;
    }
    if (dataUrl && mime.startsWith('video/')) {
        return `<div class="drive-preview-media"><video controls src="${escapeAttr(dataUrl)}"></video><p>${message}</p></div>`;
    }
    if (dataUrl && mime === 'application/pdf') {
        return `<div class="drive-preview-media drive-preview-pdf"><iframe src="${escapeAttr(dataUrl)}" title="${escapeAttr(driveDisplayName(item))}"></iframe><p>${message}</p></div>`;
    }
    return `<div class="drive-preview-binary-message">${message}</div>`;
}

function renderDriveMarkdownContent(item) {
    return formatContent(item?.content || item?.summary || '');
}

function renderDriveSidebarItem(item, depth = 0) {
    const active = activeView === 'projects' && (item.id === currentProjectId || item.id === activeProjectDocumentId);
    const deleting = pendingProjectDeletes.has(item.id) || pendingProjectDocumentDeletes.has(item.id);
    const children = Array.isArray(item.children) ? item.children : [];
    const canDelete = !driveIsRootItem(item);
    return `
        <div class="project-item drive-tree-item ${active ? 'active' : ''}" style="--drive-depth:${Math.min(depth, 5)}">
            <button class="project-item-main" type="button" data-select-project="${escapeAttr(item.id)}">
                <strong>${driveItemIconSvg(item)}${escapeHtml(driveDisplayName(item))}</strong>
                <small>${escapeHtml(projectTypeLabel(item))}</small>
            </button>
            <span class="project-item-actions">
                ${canDelete ? `
                <button class="project-mini-button danger" type="button" data-delete-project="${escapeAttr(item.id)}" title="${escapeAttr(t('actions.delete'))}" ${deleting ? 'disabled aria-busy="true"' : ''}>
                    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.4"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/></svg>
                </button>
                ` : ''}
            </span>
        </div>
        ${children.map((child) => renderDriveSidebarItem(child, depth + 1)).join('')}
    `;
}

function renderProjectList() {
    const allItems = driveItems();
    const contentItems = driveContentItems();
    if (projectSectionCount) {
        projectSectionCount.textContent = contentItems.length ? String(contentItems.length) : '';
    }
    if (!projectList) return;
    const tree = driveTreeItems().map((item) => renderDriveSidebarItem(item, 0)).join('');
    projectList.innerHTML = tree || `<div class="empty-inline">${escapeHtml(t('sidebar.emptyProjects'))}</div>`;
}

function renderProjects() {
    if (!projectWorkbench) return;
    if (projectError) {
        projectWorkbench.innerHTML = `<div class="project-panel">${emptyState(projectError, '')}</div>`;
        return;
    }
    const allItems = driveItems();
    const contentItems = driveContentItems();
    const folder = currentProjectRecord();
    const documents = projectDocuments();
    const counts = driveChildCounts(currentProjectId);
    const isRootFolder = driveIsRootItem(folder);
    const inlineFile = projectInlineFileId
        ? (projectInlineFileDetail.item?.id === projectInlineFileId ? projectInlineFileDetail.item : driveItemById(projectInlineFileId))
        : null;

    projectWorkbench.innerHTML = `
        <aside class="project-panel project-library-panel">
            <div class="project-panel-head">
                <div>
                    <h2>${escapeHtml(t('projects.sourceLibrary'))}</h2>
                    <p>${escapeHtml(t('projects.documents', { count: contentItems.length }))}</p>
                </div>
                <div class="project-panel-actions">
                    <button class="btn-secondary" type="button" data-create-project title="${escapeAttr(t('actions.createProject'))}">
                        <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.4"><path d="M12 5v14M5 12h14"/></svg>
                    </button>
                    <button class="btn-secondary" type="button" data-project-upload-trigger ${projectUploadBusy ? 'disabled aria-busy="true"' : ''}>
                        <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.4"><path d="M12 3v12"/><path d="m7 8 5-5 5 5"/><path d="M5 21h14"/></svg>
                        <span>${escapeHtml(t('actions.uploadKnowledge'))}</span>
                    </button>
                </div>
            </div>
            <div class="project-panel-body">
                <div class="project-library-toolbar">
                    <input class="project-search" type="search" data-project-search
                           placeholder="${escapeAttr(t('projects.search'))}"
                           value="${escapeAttr(projectSearchQuery)}">
                    ${renderProjectDocumentList()}
                </div>
            </div>
        </aside>

        <section class="project-panel project-map-panel">
            ${inlineFile?.type === 'file'
                ? renderProjectInlineFilePanel(inlineFile)
                : renderProjectFolderPanel(folder, counts, documents, isRootFolder)}
        </section>
    `;
}

function renderProjectFolderPanel(folder, counts, documents, isRootFolder) {
    return `
        <div class="project-panel-head drive-detail-head">
            <div class="drive-detail-title">
                <h2>${escapeHtml(driveDisplayName(folder) || t('projects.rootName'))}</h2>
                <p>${escapeHtml(`${driveBreadcrumbText()} · ${t('projects.folderContents', counts)}`)}</p>
            </div>
            <div class="project-panel-actions">
                ${renderDrivePathJumpSelect()}
                <button class="btn-secondary" type="button" data-drive-go-parent title="${escapeAttr(t('actions.back'))}" ${isRootFolder ? 'disabled' : ''}>
                    <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.3"><path d="m12 19-7-7 7-7"/><path d="M19 12H5"/></svg>
                </button>
                <button class="btn-primary" type="button" data-project-chat-path="${escapeAttr(folder?.id || '')}">
                    <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.3"><path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4Z"/></svg>
                    <span>${escapeHtml(t('actions.chatWithPath'))}</span>
                </button>
                <button class="btn-secondary" type="button" data-project-refresh>
                    <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.3"><path d="M21 12a9 9 0 0 1-9 9 9.8 9.8 0 0 1-6.7-2.7"/><path d="M3 12a9 9 0 0 1 9-9 9.8 9.8 0 0 1 6.7 2.7"/><path d="M3 20v-5h5M21 4v5h-5"/></svg>
                </button>
            </div>
        </div>
        <div class="project-panel-body">
            ${renderProjectStatus()}
            ${renderCurrentFolderList(documents)}
        </div>
    `;
}

function renderProjectInlineFilePanel(item) {
    const parent = driveItemById(item.parent_id) || driveRootItem();
    return `
        <div class="project-panel-head drive-detail-head">
            <div class="drive-detail-title">
                <h2>${escapeHtml(driveDisplayName(item) || t('projects.activeDocument'))}</h2>
                <p>${escapeHtml([parent?.id ? driveBreadcrumbText(parent.id) : '', driveItemMeta(item)].filter(Boolean).join(' · '))}</p>
            </div>
            <div class="project-panel-actions">
                ${renderDrivePathJumpSelect()}
                <button class="btn-secondary" type="button" data-drive-back-to-folder title="${escapeAttr(t('actions.back'))}">
                    <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.3"><path d="m12 19-7-7 7-7"/><path d="M19 12H5"/></svg>
                </button>
                <button class="btn-secondary" type="button" data-project-download-document="${escapeAttr(item.id)}" title="${escapeAttr(t('projects.download'))}">
                    <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.3"><path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/></svg>
                </button>
            </div>
        </div>
        <div class="project-panel-body">
            ${renderProjectStatus()}
            ${renderInlineDriveFileContent(item)}
        </div>
    `;
}

function renderInlineDriveFileContent(item) {
    const detail = projectInlineFileDetail.item?.id === item.id ? projectInlineFileDetail.item : item;
    if (projectInlineFileDetail.loading && !detail.content) {
        return `<div class="project-map-wrap drive-folder-wrap">${emptyState(t('projects.previewLoading'), driveItemMeta(item))}</div>`;
    }
    if (projectInlineFileDetail.error) {
        return `<div class="project-map-wrap drive-folder-wrap">${emptyState(projectInlineFileDetail.error, driveItemMeta(item))}</div>`;
    }
    if (detail.encoding === 'base64') {
        return `<div class="project-file-detail-content binary">${renderDriveBinaryPreview(detail)}</div>`;
    }
    if (driveItemIsMarkdown(detail)) {
        return `<div class="project-file-detail-content markdown drive-markdown-content">${renderDriveMarkdownContent(detail)}</div>`;
    }
    return `<pre class="project-file-detail-content">${escapeHtml(detail.content || detail.summary || '')}</pre>`;
}

function renderProjectDocumentList() {
    const items = projectSearchQuery.trim()
        ? projectSearchResults.map((result) => ({ ...result.item, _score: result.score, _snippet: result.snippet }))
        : driveTreeItems();
    if (!items.length) {
        return `<div class="empty-inline">${escapeHtml(projectSearchQuery.trim() ? t('projects.noSearchResults') : t('projects.noDocuments'))}</div>`;
    }
    return `
        <div class="project-document-list" data-drive-list-surface="library">
            ${projectSearchQuery.trim()
                ? items.map((item) => renderProjectDocumentRow(item, 0, { surface: 'library' })).join('')
                : items.map((item) => renderDriveTreeDocumentRow(item, 0)).join('')}
        </div>
    `;
}

function renderDriveTreeDocumentRow(item, depth = 0) {
    const children = Array.isArray(item.children) ? item.children : [];
    const collapsed = item.type === 'folder' && collapsedDriveFolderIds.has(item.id);
    return `
        ${renderProjectDocumentRow(item, depth, {
            tree: true,
            hasChildren: children.length > 0,
            collapsed,
            surface: 'library',
        })}
        ${collapsed ? '' : children.map((child) => renderDriveTreeDocumentRow(child, depth + 1)).join('')}
    `;
}

function renderProjectDocumentRow(doc, depth = 0, options = {}) {
    const selected = selectedProjectDocumentIds.has(doc.id);
    const active = doc.id === activeProjectDocumentId || doc.id === currentProjectId;
    const deleting = pendingProjectDocumentDeletes.has(doc.id) || pendingProjectDeletes.has(doc.id);
    const score = doc._score ? `<span class="chip muted">${escapeHtml(String(doc._score))}</span>` : '';
    const canDelete = !driveIsRootItem(doc);
    const canSelect = driveSelectableItem(doc);
    const canDrag = canSelect && !deleting;
    const showToggle = options.tree && doc.type === 'folder';
    const toggleDisabled = !options.hasChildren;
    const surface = options.surface || (options.tree ? 'library' : 'detail');
    const dropAttr = doc.type === 'folder' ? `data-drive-drop-folder-id="${escapeAttr(doc.id)}"` : '';
    return `
        <div class="project-document-row drive-content-row ${active ? 'active' : ''} ${selected ? 'selected' : ''}"
             style="--drive-depth:${Math.min(depth, 8)}"
             data-drive-item-id="${escapeAttr(doc.id)}"
             data-drive-item-type="${escapeAttr(doc.type || '')}"
             data-drive-selectable="${canSelect ? 'true' : 'false'}"
             ${dropAttr}
             draggable="${canDrag ? 'true' : 'false'}">
            <span class="drive-row-leading">
                ${showToggle ? `
                    <button class="drive-tree-toggle" type="button"
                            data-drive-toggle-folder="${escapeAttr(doc.id)}"
                            aria-expanded="${options.collapsed ? 'false' : 'true'}"
                            title="${escapeAttr(options.collapsed ? t('actions.expand') : t('actions.collapse'))}"
                            ${toggleDisabled ? 'disabled' : ''}>
                        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5">
                            <path d="m9 6 6 6-6 6"/>
                        </svg>
                    </button>
                ` : '<span class="drive-tree-toggle-placeholder"></span>'}
            </span>
            <button class="project-document-main" type="button" data-project-open-document="${escapeAttr(doc.id)}" data-project-open-surface="${escapeAttr(surface)}">
                <strong>${driveItemIconSvg(doc)}${escapeHtml(driveDisplayName(doc))}</strong>
                <p>${escapeHtml(driveItemSnippet(doc))}</p>
                <span class="project-document-meta">
                    <span class="status-chip neutral">${escapeHtml(projectTypeLabel(doc))}</span>
                    ${score}
                    ${doc.type === 'file' ? `<span class="chip muted">${escapeHtml(formatBytes(doc.size || 0))}</span>` : ''}
                </span>
            </button>
            <span class="drive-row-actions">
                ${doc.type === 'folder' ? `
                    <button class="project-mini-button" type="button" data-project-chat-path="${escapeAttr(doc.id)}" title="${escapeAttr(t('actions.chatWithPath'))}">
                        <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.4"><path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4Z"/></svg>
                    </button>
                ` : ''}
                ${doc.type === 'file' ? `
                    <button class="project-mini-button" type="button" data-project-download-document="${escapeAttr(doc.id)}" title="${escapeAttr(t('projects.download'))}">
                        <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.4"><path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/></svg>
                    </button>
                ` : ''}
                ${canDelete ? `
                <button class="project-mini-button danger" type="button" data-project-delete-document="${escapeAttr(doc.id)}" title="${escapeAttr(t('actions.delete'))}" ${deleting ? 'disabled aria-busy="true"' : ''}>
                    <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.4"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v5M14 11v5"/></svg>
                </button>
                ` : ''}
            </span>
        </div>
    `;
}

function renderCurrentFolderList(items = projectDocuments()) {
    if (!items.length) {
        return `<div class="project-map-wrap drive-folder-wrap drive-drop-zone" data-drive-drop-folder-id="${escapeAttr(currentProjectId || driveRootItem()?.id || '')}">${emptyState(t('projects.noDocuments'), t('projects.emptyDetail'))}</div>`;
    }
    return `
        <div class="project-document-list current-folder-list drive-drop-zone" data-drive-list-surface="detail" data-drive-drop-folder-id="${escapeAttr(currentProjectId || driveRootItem()?.id || '')}">
            ${items.map((item) => renderProjectDocumentRow(item, 0, { surface: 'detail' })).join('')}
        </div>
    `;
}

function renderProjectSelectionBar() {
    const selectedItems = driveSelectedItems();
    const count = selectedItems.length;
    return `
        <div class="project-selection-bar">
            <div class="project-selection-meta">
                <span class="status-chip neutral">${escapeHtml(t('projects.selected', { count }))}</span>
                ${selectedItems.slice(0, 5).map((item) => `<span class="chip">${escapeHtml(driveDisplayName(item))}</span>`).join('')}
            </div>
            <div class="project-panel-actions">
                <button class="btn-secondary" type="button" data-project-clear-selection ${count ? '' : 'disabled'}>
                    <span>${escapeHtml(t('actions.clearSelection'))}</span>
                </button>
            </div>
        </div>
    `;
}

function renderProjectContextSources() {
    const sources = Array.isArray(projectAskSources) ? projectAskSources : [];
    if (!sources.length) return '';
    return `
        <section class="project-answer">
            <div class="project-answer-head">
                <strong>${escapeHtml(t('projects.contextSources'))}</strong>
            </div>
            <div class="project-source-list">
                ${sources.map((item) => `
                    <button class="project-source-item" type="button" data-project-open-document="${escapeAttr(item.id)}">
                        <strong>${driveItemIconSvg(item)}${escapeHtml(driveDisplayName(item))}</strong>
                        <small>${escapeHtml(item.summary || driveItemMeta(item))}</small>
                    </button>
                `).join('')}
            </div>
        </section>
    `;
}

function renderPinnedAgents() {
    if (!pinnedAgentList) return;
    const pinnedAgents = pinnedAgentIds
        .map((id) => agents.find((agent) => agent.id === id))
        .filter(Boolean);
    if (pinnedSectionCount) {
        pinnedSectionCount.textContent = pinnedAgents.length ? String(pinnedAgents.length) : '';
    }

    if (!pinnedAgents.length) {
        pinnedAgentList.innerHTML = `<div class="empty-inline">${escapeHtml(t('sidebar.emptyPinned'))}</div>`;
        return;
    }

    pinnedAgentList.innerHTML = pinnedAgents.map((agent) => `
        <button class="pinned-agent-item ${agent.id === currentAgentId ? 'active' : ''}"
                type="button"
                data-start-agent-id="${escapeAttr(agent.id)}"
                ${agent.enabled ? '' : 'disabled'}>
            <span class="pinned-agent-icon">${escapeHtml(agentIconText(agent))}</span>
            <span class="pinned-agent-body">
                <strong>${escapeHtml(agent.name || agent.id)}</strong>
                <small>${escapeHtml(agent.enabled ? agent.framework || agent.runtime || 'agent' : t('agents.unavailable'))}</small>
            </span>
        </button>
    `).join('');
}

function agentIconText(agent) {
    const id = agent?.id || '';
    if (id.includes('image') || id.includes('aigc')) return currentLanguage === 'zh' ? '图' : 'I';
    if (id.includes('weight') || id.includes('loss')) return currentLanguage === 'zh' ? '减' : 'W';
    if (id.includes('super')) return 'S';
    if (id.includes('research')) return currentLanguage === 'zh' ? '研' : 'R';
    return 'A';
}

function renderAgentSelect() {
    if (!agentSelect) return;

    if (!agents.length) {
        agentSelect.innerHTML = '<option value="super_chat">Super Chat</option>';
        return;
    }

    agentSelect.innerHTML = agents.map((agent) => {
        const disabled = agent.enabled ? '' : 'disabled';
        const suffix = agent.enabled ? '' : ` (${t('agents.unavailable')})`;
        return `<option value="${escapeAttr(agent.id)}" ${disabled}>${escapeHtml(agent.name || agent.id)}${suffix}</option>`;
    }).join('');
    agentSelect.value = currentAgentId;
}

function renderAgents() {
    if (!agents.length) {
        agentsGrid.innerHTML = emptyState(t('agents.emptyTitle'), t('agents.emptyDetail'));
        return;
    }

    const groups = [
        { key: 'entry', tone: 'blue' },
        { key: 'creative', tone: 'rose' },
        { key: 'research', tone: 'amber' },
        { key: 'general', tone: 'slate' },
    ];

    agentsGrid.innerHTML = groups.map((group) => {
        const items = agents.filter((agent) => getAgentGroup(agent) === group.key);
        if (!items.length) return '';
        const [title, detail] = I18N[currentLanguage].agents.groups[group.key];
        return `
            <section class="agent-section tone-${group.tone}">
                <div class="agent-section-head">
                    <div>
                        <h2>${escapeHtml(title)}</h2>
                        <p>${escapeHtml(detail)}</p>
                    </div>
                    <span class="section-count">${items.length}</span>
                </div>
                <div class="agent-card-list">
                    ${items.map(renderAgentCard).join('')}
                </div>
            </section>
        `;
    }).join('');
}

function renderAgentCard(agent) {
    const selected = agent.id === currentAgentId;
    const statusClass = agent.enabled ? 'ok' : 'warn';
    const statusText = agent.enabled ? t('agents.available') : t('agents.unavailable');
    const tone = getAgentTone(agent);
    const pinned = isAgentPinned(agent.id);
    const capabilities = (agent.capabilities || [])
        .slice(0, 4)
        .map((item) => `<span class="chip">${escapeHtml(capabilityLabel(item))}</span>`)
        .join('');
    const disabledReason = !agent.enabled
        ? (agent.metadata?.dependency_hint || t('agents.dependencyHint'))
        : '';

    return `
        <article class="agent-card tone-${tone} ${selected ? 'selected' : ''}">
            <div class="agent-card-main">
                <div class="agent-icon">${escapeHtml(agentIconText(agent))}</div>
                <div class="agent-copy">
                    <div class="agent-title-row">
                        <h3>${escapeHtml(agent.name || agent.id)}</h3>
                        <span class="agent-type-badge">${escapeHtml(agentTypeLabel(agent))}</span>
                    </div>
                    <p>${escapeHtml(agent.description || '')}</p>
                </div>
            </div>
            <div class="agent-status-row">
                <span class="status-chip ${statusClass}">${statusText}</span>
                ${agent.experimental ? `<span class="status-chip experiment">${escapeHtml(t('agents.experimental'))}</span>` : ''}
                ${pinned ? `<span class="status-chip neutral">${escapeHtml(t('agents.pinned'))}</span>` : ''}
            </div>
            <div class="agent-usecase">
                <span>${escapeHtml(t('agents.fit'))}</span>
                <strong>${escapeHtml(agentUseCase(agent))}</strong>
            </div>
            <div class="agent-detail-grid">
                <div>
                    <span>${escapeHtml(t('agents.implementation'))}</span>
                    <strong>${escapeHtml(agentImplementationLabel(agent))}</strong>
                </div>
                <div>
                    <span>${escapeHtml(t('agents.entry'))}</span>
                    <strong>${agent.enabled ? t('agents.canStart') : t('agents.waiting')}</strong>
                </div>
            </div>
            ${disabledReason ? `<p class="agent-note">${escapeHtml(disabledReason)}</p>` : ''}
            <div class="chip-row">${capabilities || `<span class="chip muted">${escapeHtml(t('agents.capabilityMissing'))}</span>`}</div>
            <div class="agent-id-line">${escapeHtml(agent.id)}</div>
            <div class="agent-card-actions">
                <button class="btn-secondary" type="button" data-start-agent-id="${escapeAttr(agent.id)}" ${agent.enabled ? '' : 'disabled'}>
                    ${escapeHtml(t('actions.startTask'))}
                </button>
                <button class="btn-secondary" type="button" data-pin-agent-id="${escapeAttr(agent.id)}">
                    ${pinned ? escapeHtml(t('actions.unpin')) : escapeHtml(t('actions.pin'))}
                </button>
            </div>
        </article>
    `;
}

function getAgentGroup(agent) {
    const id = agent.id || '';
    const caps = agent.capabilities || [];
    if (id.includes('super')) return 'entry';
    if (id.includes('image') || id.includes('aigc') || caps.includes('aigc')) return 'creative';
    if (id.includes('research') || agent.framework === 'langgraph' || agent.framework === 'crewai' || agent.framework === 'autogen') return 'research';
    return 'general';
}

function getAgentTone(agent) {
    const group = getAgentGroup(agent);
    if (group === 'creative') return 'rose';
    if (group === 'research') return 'amber';
    if (group === 'entry') return 'blue';
    return 'slate';
}

function agentTypeLabel(agent) {
    const group = getAgentGroup(agent);
    return I18N[currentLanguage].agents.type[group] || 'Agent';
}

function agentUseCase(agent) {
    const id = agent.id || '';
    if (id.includes('super')) return t('agents.useCase.super');
    if (id.includes('image')) return t('agents.useCase.image');
    if (id.includes('weight') || id.includes('loss')) return t('agents.useCase.weightLoss');
    if (id.includes('research')) return t('agents.useCase.research');
    return t('agents.useCase.default');
}

function agentImplementationLabel(agent) {
    if (agent.framework === 'native') return t('agents.implementationSelf');
    if (agent.framework === 'langgraph') return 'LangGraph';
    if (agent.framework === 'crewai') return 'CrewAI';
    if (agent.framework === 'autogen') return 'AutoGen';
    return agent.framework || agent.runtime || (currentLanguage === 'zh' ? '未知' : 'Unknown');
}

function capabilityLabel(capability) {
    return I18N[currentLanguage].capabilities[capability] || capability;
}

function renderPulse() {
    if (!pulseItems || !pulseTopicList) return;

    updatePulseTopicSubmitState();

    if (pulseDateTitle) {
        pulseDateTitle.textContent = pulse.date ? `${t('pulse.todayTitle')} · ${pulse.date}` : t('pulse.todayTitle');
    }
    if (pulseGeneratedAt) {
        pulseGeneratedAt.textContent = pulse.refreshing
            ? t('pulse.refreshing')
            : pulse.generated_at
                ? t('pulse.generatedAt', { time: formatFullTime(pulse.generated_at) })
                : t('pulse.neverGenerated');
    }

    renderPulseTopics();
    renderPulseSuggestedTopics();

    if (pulseError) {
        pulseItems.innerHTML = emptyState(formatPulseError(), '');
        return;
    }

    const items = Array.isArray(pulse.items) ? pulse.items : [];
    renderPulseTopicFilter(items);
    if (!items.length) {
        const empty = pulseEmptyStateContent();
        pulseItems.innerHTML = emptyState(empty.title, empty.detail);
        return;
    }

    const filteredItems = filterPulseItemsByTopic(items);
    if (!filteredItems.length) {
        pulseItems.innerHTML = emptyState(t('pulse.emptyFiltered'), '');
        return;
    }

    pulseItems.innerHTML = renderPulseFeed(filteredItems);
    renderPulsePostWindow();
    observePulseExposures();
}

function pulseEmptyStateContent() {
    if (pulse.refreshing) {
        return {
            title: t('pulse.emptyComputingTitle'),
            detail: t('pulse.emptyComputingDetail'),
        };
    }
    const moduleDetail = pulseFallbackModuleDetail();
    if (moduleDetail) {
        return {
            title: t('pulse.emptyUnavailableTitle'),
            detail: moduleDetail,
        };
    }
    return {
        title: t('pulse.emptyTitle'),
        detail: t('pulse.emptyDetail'),
    };
}

function pulseFallbackModuleDetail() {
    const modules = Array.isArray(pulse.modules) ? pulse.modules : [];
    const summaries = modules
        .map((module) => module?.summary || '')
        .filter((summary) => /搜索|检索|可核验|失败|暂不可用|search|verifiable|failed|unavailable/i.test(summary))
        .slice(0, 2);
    if (!summaries.length) return '';
    return [t('pulse.emptyUnavailableDetail'), ...summaries].join('\n');
}

function formatPulseError() {
    const key = pulseErrorType === 'create'
        ? 'pulse.createFailed'
        : pulseErrorType === 'delete'
            ? 'pulse.deleteFailed'
            : 'pulse.loadFailed';
    return t(key, { message: pulseError });
}

function renderPulseFeed(items = []) {
    return `
        <div class="pulse-post-grid">
            ${items.map(renderPulseCard).join('')}
        </div>
    `;
}

function renderPulseModules(items = [], generatedModules = []) {
    const moduleSources = ['topic_hot', 'memory', 'interest_hot'];
    const modules = moduleSources.map((source) => {
        const generated = Array.isArray(generatedModules)
            ? generatedModules.find((module) => module.key === source)
            : null;
        return generated || { key: source, items: items.filter((item) => item.source === source) };
    });

    return modules.map((module) => {
        const [fallbackTitle, fallbackDetail] = pulseModuleCopy(module.key);
        const title = module.title || fallbackTitle;
        const detail = module.summary || fallbackDetail;
        const moduleItems = items.filter((item) => item.source === module.key);
        return `
            <section class="pulse-module pulse-module-${escapeAttr(pulseModuleClass(module.key))}">
                <div class="pulse-module-head">
                    <div>
                        <h3>${escapeHtml(title)}</h3>
                        <p>${escapeHtml(detail)}</p>
                    </div>
                    <span class="section-count">${moduleItems.length || ''}</span>
                </div>
                <div class="pulse-module-items">
                    ${moduleItems.length
                        ? moduleItems.map(renderPulseCard).join('')
                        : `<div class="empty-state pulse-module-empty"><strong>${escapeHtml(t('pulse.emptyModule'))}</strong><span>${escapeHtml(detail)}</span></div>`}
                </div>
            </section>
        `;
    }).join('');
}

function pulseModuleCopy(key) {
    const copyKey = key === 'topic_hot' ? 'topicHot' : (key === 'interest_hot' ? 'interestHot' : key);
    const fallback = I18N.en.pulse.modules[copyKey] || [key, ''];
    return I18N[currentLanguage].pulse.modules[copyKey] || fallback;
}

function pulseModuleClass(key = '') {
    if (key === 'topic_hot') return 'topicHot';
    if (key === 'interest_hot') return 'interestHot';
    return key || 'pulse';
}

function renderPulseTopics() {
    const topics = Array.isArray(pulse.topics) ? pulse.topics : [];
    if (!topics.length) {
        pulseTopicList.innerHTML = `<div class="empty-inline">${escapeHtml(t('pulse.emptyTopics'))}</div>`;
        return;
    }

    pulseTopicList.innerHTML = topics.map((topic) => {
        const keywords = Array.isArray(topic.keywords) ? topic.keywords : [];
        const deleting = pendingPulseTopicDeletes.has(topic.id);
        const selected = selectedPulseTopicId && topic.id === selectedPulseTopicId;
        return `
            <div class="pulse-topic-item ${topic.enabled ? '' : 'muted'} ${selected ? 'selected' : ''}">
                <button class="pulse-topic-select" type="button" data-pulse-select-topic="${escapeAttr(topic.id)}">
                    <strong>${escapeHtml(topic.name || '')}</strong>
                    <span>${keywords.map(escapeHtml).join(' / ') || escapeHtml(t('pulse.subscribed'))}</span>
                </button>
                <button class="icon-button pulse-topic-delete" type="button"
                        data-pulse-delete-topic="${escapeAttr(topic.id)}"
                        title="${escapeAttr(t('actions.delete'))}"
                        ${deleting ? 'disabled aria-busy="true"' : ''}>
                    <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.4">
                        <path d="M3 6h18"/>
                        <path d="M8 6V4h8v2"/>
                        <path d="M19 6l-1 14H6L5 6"/>
                        <path d="M10 11v5M14 11v5"/>
                    </svg>
                </button>
            </div>
        `;
    }).join('');
}

function renderPulseSuggestedTopics() {
    if (!pulseSuggestedTopics) return;
    const suggestions = Array.isArray(pulse.suggested_topics) ? pulse.suggested_topics : [];
    if (!suggestions.length) {
        pulseSuggestedTopics.innerHTML = `<div class="empty-inline">${escapeHtml(t('pulse.emptySuggestedTopics'))}</div>`;
        return;
    }

    pulseSuggestedTopics.innerHTML = suggestions.map((topic, index) => {
        const keywords = normalizePulseKeywordList(topic.keywords || []);
        return `
            <button class="pulse-suggested-topic" type="button" data-pulse-suggest-topic="${index}">
                <span class="pulse-suggested-topic-main">
                    <strong>${escapeHtml(topic.name || '')}</strong>
                    <small>${escapeHtml(topic.reason || keywords.join(' / '))}</small>
                </span>
                <span class="pulse-suggested-topic-action">
                    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.4">
                        <path d="M12 5v14M5 12h14"/>
                    </svg>
                    ${escapeHtml(t('pulse.addSuggestedTopic'))}
                </span>
            </button>
        `;
    }).join('');
}

function renderPulseTopicFilter(items = []) {
    if (!pulseTopicFilter) return;
    const topics = Array.isArray(pulse.topics) ? pulse.topics : [];
    if (!topics.length) {
        pulseTopicFilter.innerHTML = '';
        selectedPulseTopicId = '';
        return;
    }
    if (selectedPulseTopicId && !topics.some((topic) => topic.id === selectedPulseTopicId)) {
        selectedPulseTopicId = '';
    }

    const allActive = !selectedPulseTopicId;
    const countByTopic = new Map();
    items.forEach((item) => {
        if (item.topic_id) {
            countByTopic.set(item.topic_id, (countByTopic.get(item.topic_id) || 0) + 1);
            return;
        }
        const matched = topics.find((topic) => topic.name && topic.name === item.topic_name);
        if (matched) countByTopic.set(matched.id, (countByTopic.get(matched.id) || 0) + 1);
    });

    const chips = [`
        <button class="pulse-filter-chip ${allActive ? 'active' : ''}" type="button" data-pulse-filter-topic="">
            ${escapeHtml(t('pulse.topicFilterAll'))}
            <span>${items.length}</span>
        </button>
    `];
    topics.forEach((topic) => {
        const active = topic.id === selectedPulseTopicId;
        chips.push(`
            <button class="pulse-filter-chip ${active ? 'active' : ''}" type="button" data-pulse-filter-topic="${escapeAttr(topic.id)}">
                ${escapeHtml(topic.name || '')}
                <span>${countByTopic.get(topic.id) || 0}</span>
            </button>
        `);
    });
    pulseTopicFilter.innerHTML = chips.join('');
}

function filterPulseItemsByTopic(items = []) {
    if (!selectedPulseTopicId) return items;
    const topics = Array.isArray(pulse.topics) ? pulse.topics : [];
    const selectedTopic = topics.find((topic) => topic.id === selectedPulseTopicId);
    if (!selectedTopic) return items;
    return items.filter((item) => item.topic_id === selectedTopic.id || (selectedTopic.name && item.topic_name === selectedTopic.name));
}

function renderPulseCard(item) {
    const sourceLabel = pulseSourceLabel(item.source);
    const topicLabel = item.topic_name || item.category || sourceLabel;
    const feedback = item.feedback || {};
    const liked = Boolean(feedback.liked);
    const vote = feedback.vote || '';
    const note = item.recommendation_note || pulseRecommendationNote(item);
    const featureScore = item.feature_score || item.heat_score || 0;
    return `
        <article class="pulse-card pulse-post-card" data-pulse-card-id="${escapeAttr(item.id)}">
            <button class="pulse-card-open" type="button" data-pulse-open-post="${escapeAttr(item.id)}" aria-label="${escapeAttr(t('pulse.openPost'))}">
                <div class="pulse-card-topline">
                    <span class="status-chip ${pulseSourceTone(item.source)}">${escapeHtml(sourceLabel)}</span>
                    <span class="status-chip neutral">${escapeHtml(topicLabel)}</span>
                    <span class="pulse-heat">${escapeHtml(t('pulse.featureScore', { score: featureScore }))}</span>
                </div>
                <h3>${escapeHtml(item.title || '')}</h3>
                <p>${escapeHtml(compactPulsePostSummary(item))}</p>
            </button>
            ${renderPulseCardSources(item)}
            <div class="pulse-card-footer">
                <span class="pulse-recommend-note">${escapeHtml(note)}</span>
                <div class="pulse-feedback-actions">
                    ${renderPulseFeedbackButton(item.id, pulseEventLike, liked ? 0 : 1, liked ? t('pulse.liked') : t('pulse.like'), liked, feedback.like_count)}
                    ${renderPulseFeedbackButton(item.id, pulseEventUpvote, vote === 'up' ? 0 : 1, t('pulse.upvote'), vote === 'up', feedback.upvote_count)}
                    ${renderPulseFeedbackButton(item.id, pulseEventDownvote, vote === 'down' ? 0 : 1, t('pulse.downvote'), vote === 'down', feedback.downvote_count)}
                </div>
            </div>
        </article>
    `;
}

const pulseEventExposure = 'exposure';
const pulseEventOpen = 'open';
const pulseEventLike = 'like';
const pulseEventUpvote = 'upvote';
const pulseEventDownvote = 'downvote';

function renderPulseFeedbackButton(itemId, eventType, value, label, active = false, count = 0) {
    return `
        <button class="pulse-feedback-button ${active ? 'active' : ''}" type="button"
                data-pulse-feedback="${escapeAttr(itemId)}"
                data-pulse-feedback-type="${escapeAttr(eventType)}"
                data-pulse-feedback-value="${escapeAttr(value)}"
                aria-pressed="${active ? 'true' : 'false'}"
                title="${escapeAttr(label)}">
            ${pulseFeedbackIcon(eventType)}
            <span>${escapeHtml(label)}</span>
            ${count ? `<small>${escapeHtml(formatPulseFeedbackCount(count))}</small>` : ''}
        </button>
    `;
}

function pulseFeedbackIcon(eventType) {
    if (eventType === pulseEventLike) {
        return '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.3"><path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.6l-1-1a5.5 5.5 0 0 0-7.8 7.8l1 1L12 21l7.8-7.6 1-1a5.5 5.5 0 0 0 0-7.8Z"/></svg>';
    }
    if (eventType === pulseEventDownvote) {
        return '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.3"><path d="M12 5v14"/><path d="m19 12-7 7-7-7"/></svg>';
    }
    return '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.3"><path d="M12 19V5"/><path d="m5 12 7-7 7 7"/></svg>';
}

function formatPulseFeedbackCount(value = 0) {
    const count = Number(value) || 0;
    if (count >= 1000) return `${(count / 1000).toFixed(1)}k`;
    return String(count);
}

function compactPulsePostSummary(item = {}) {
    return truncateText(item.summary || item.detail?.quick_context || '', 180);
}

function renderPulseCardSources(item = {}) {
    const detail = item.detail || {};
    const sources = normalizePulseNewsSources(detail.news_sources, detail.sources, detail.related_news).slice(0, 2);
    if (!sources.length) return '';
    return `
        <div class="pulse-card-sources">
            ${sources.map((source) => `
                <a class="pulse-card-source" href="${escapeAttr(source.url)}" target="_blank" rel="noopener noreferrer">
                    <span>${escapeHtml(hostFromUrl(source.url) || source.source || t('pulse.newsSources'))}</span>
                    <strong>${escapeHtml(truncateText(source.title || source.url, 46))}</strong>
                </a>
            `).join('')}
        </div>
    `;
}

function pulseRecommendationNote(item = {}) {
    if (item.recommendation_note) return item.recommendation_note;
    if (item.source === 'topic_hot') return item.topic_name ? `可能对「${item.topic_name}」推荐` : '可能对订阅 Topic 推荐';
    if (item.source === 'memory') return '可能对近期 Memory 推荐';
    return item.topic_name ? `可能对「${item.topic_name}」延伸推荐` : '可能对兴趣外扩推荐';
}

function pulseSourceLabel(source) {
    if (source === 'topic_hot' || source === 'topic') return t('pulse.sourceTopic');
    if (source === 'memory') return t('pulse.sourceMemory');
    return t('pulse.sourceHot');
}

function pulseSourceTone(source) {
    if (source === 'topic_hot' || source === 'topic') return 'ok';
    if (source === 'memory') return 'warn';
    return 'neutral';
}

function renderPulseDetail(item = {}, detail = {}) {
    const keyPoints = Array.isArray(detail.key_points) ? detail.key_points : [];
    const questions = Array.isArray(detail.suggested_questions) ? detail.suggested_questions : [];
    const signals = Array.isArray(detail.signals) ? detail.signals : [];
    const newsSources = normalizePulseNewsSources(detail.news_sources, detail.sources, detail.related_news);
    const relatedClusters = Array.isArray(item.related_clusters) ? item.related_clusters : [];
    return `
        <div class="pulse-detail">
            ${detail.recommendation_reason ? `
                <section>
                    <h4>${escapeHtml(t('pulse.reason'))}</h4>
                    <p>${escapeHtml(detail.recommendation_reason)}</p>
                </section>
            ` : ''}
            ${detail.quick_context ? `
                <section>
                    <h4>${escapeHtml(t('pulse.quickContext'))}</h4>
                    <p>${escapeHtml(detail.quick_context)}</p>
                </section>
            ` : ''}
            ${newsSources.length ? `
                <section>
                    <h4>${escapeHtml(t('pulse.newsSources'))}</h4>
                    ${renderPulseNewsSources(newsSources)}
                </section>
            ` : ''}
            ${keyPoints.length ? `
                <section>
                    <h4>${escapeHtml(t('pulse.keyPoints'))}</h4>
                    <ul>
                        ${keyPoints.map((point) => `<li>${escapeHtml(point)}</li>`).join('')}
                    </ul>
                </section>
            ` : ''}
            ${signals.length ? `
                <section>
                    <h4>${escapeHtml(t('pulse.signals'))}</h4>
                    <ul>
                        ${signals.map((signal) => `<li>${escapeHtml(signal)}</li>`).join('')}
                    </ul>
                </section>
            ` : ''}
            ${questions.length ? `
                <section>
                    <h4>${escapeHtml(t('pulse.suggestedQuestions'))}</h4>
                    <div class="pulse-question-list">
                        ${questions.map((question) => `
                            <button class="pulse-question" type="button" data-pulse-chat="${escapeAttr(buildPulseChatPrompt(item, question))}">
                                ${escapeHtml(question)}
                            </button>
                        `).join('')}
                    </div>
                </section>
            ` : ''}
            ${relatedClusters.length ? `
                <section>
                    <h4>${escapeHtml(t('pulse.relatedClusters'))}</h4>
                    ${renderPulseRelatedClusters(relatedClusters)}
                </section>
            ` : ''}
        </div>
    `;
}

function renderPulseRelatedClusters(clusters = []) {
    return `
        <div class="pulse-related-list">
            ${clusters.map((cluster) => `
                <button class="pulse-related-item" type="button" data-pulse-open-post="${escapeAttr(cluster.id)}">
                    <span class="pulse-related-main">
                        <strong>${escapeHtml(cluster.title || '')}</strong>
                        <small>${escapeHtml(cluster.reason || cluster.summary || '')}</small>
                    </span>
                    <span class="pulse-related-action">${escapeHtml(t('pulse.openCluster'))}</span>
                </button>
            `).join('')}
        </div>
    `;
}

function openPulseCluster(itemId = '') {
    openPulsePost(itemId);
}

function findPulseItem(itemId = '') {
    const items = Array.isArray(pulse.items) ? pulse.items : [];
    return items.find((item) => item.id === itemId) || null;
}

function openPulsePost(itemId = '', trigger = null) {
    const item = findPulseItem(itemId);
    if (!item) return;
    selectedPulsePostId = itemId;
    pulsePostReturnFocus = trigger || document.activeElement;
    renderPulsePostWindow();
    recordPulseEvent(itemId, pulseEventOpen, 1, { surface: 'post_window' });
}

function closePulsePost() {
    selectedPulsePostId = '';
    renderPulsePostWindow();
    const returnFocus = pulsePostReturnFocus;
    pulsePostReturnFocus = null;
    if (returnFocus && document.contains(returnFocus)) {
        returnFocus.focus({ preventScroll: true });
    }
}

function pulsePostIsOpen() {
    return Boolean(pulsePostWindow && !pulsePostWindow.classList.contains('hidden'));
}

function renderPulsePostWindow() {
    if (!pulsePostWindow || !pulsePostTitle || !pulsePostBody || !pulsePostFooter) return;
    const item = findPulseItem(selectedPulsePostId);
    if (!item) {
        pulsePostWindow.classList.add('hidden');
        document.body.classList.remove('pulse-post-open');
        return;
    }

    pulsePostWindow.classList.remove('hidden');
    document.body.classList.add('pulse-post-open');
    if (pulsePostNote) pulsePostNote.textContent = item.recommendation_note || pulseRecommendationNote(item);
    pulsePostTitle.textContent = item.title || '';
    pulsePostBody.innerHTML = renderPulsePostBody(item);
    pulsePostFooter.innerHTML = renderPulsePostFooter(item);
}

function renderPulsePostBody(item = {}) {
    const detail = item.detail || {};
    const paragraphs = [];
    const newsSources = normalizePulseNewsSources(detail.news_sources, detail.sources, detail.related_news);
    paragraphs.push(item.summary || detail.quick_context || '');
    if (detail.quick_context && detail.quick_context !== item.summary) {
        paragraphs.push(detail.quick_context);
    }
    const keyPoints = Array.isArray(detail.key_points) ? detail.key_points : [];
    if (keyPoints.length) {
        paragraphs.push(keyPoints.slice(0, 4).join('\n'));
    }
    const body = paragraphs
        .map((paragraph) => String(paragraph || '').trim())
        .filter(Boolean)
        .map((paragraph) => `<p>${escapeHtml(paragraph)}</p>`)
        .join('') || `<p>${escapeHtml(item.summary || '')}</p>`;
    if (!newsSources.length) return body;
    return `
        ${body}
        <section class="pulse-post-source-section">
            <h4>${escapeHtml(t('pulse.newsSources'))}</h4>
            ${renderPulseNewsSources(newsSources)}
        </section>
    `;
}

function renderPulsePostFooter(item = {}) {
    const feedback = item.feedback || {};
    const vote = feedback.vote || '';
    const liked = Boolean(feedback.liked);
    const relatedClusters = Array.isArray(item.related_clusters) ? item.related_clusters : [];
    const chatPrompt = buildPulseChatPrompt(item);
    return `
        <div class="pulse-post-feedback">
            ${renderPulseFeedbackButton(item.id, pulseEventLike, liked ? 0 : 1, liked ? t('pulse.liked') : t('pulse.like'), liked, feedback.like_count)}
            ${renderPulseFeedbackButton(item.id, pulseEventUpvote, vote === 'up' ? 0 : 1, t('pulse.upvote'), vote === 'up', feedback.upvote_count)}
            ${renderPulseFeedbackButton(item.id, pulseEventDownvote, vote === 'down' ? 0 : 1, t('pulse.downvote'), vote === 'down', feedback.downvote_count)}
            <button class="pulse-feedback-button pulse-ask-button" type="button" data-pulse-chat="${escapeAttr(chatPrompt)}">
                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2">
                    <path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4Z"/>
                </svg>
                <span>${escapeHtml(t('pulse.ask'))}</span>
            </button>
        </div>
        ${relatedClusters.length ? renderPulseRelatedClusters(relatedClusters) : ''}
    `;
}

async function recordPulseEvent(itemId, eventType, value = 1, metadata = {}) {
    if (!itemId || !eventType) return null;
    const item = findPulseItem(itemId);
    const eventMetadata = { ...(metadata || {}) };
    if (item) {
        if (item.cluster_key) eventMetadata.cluster_key = item.cluster_key;
        if (item.title) eventMetadata.title = item.title;
        if (item.source) eventMetadata.source = item.source;
        if (item.topic_id) eventMetadata.topic_id = item.topic_id;
        if (item.topic_name) eventMetadata.topic_name = item.topic_name;
    }
    try {
        const data = await apiCall('POST', '/api/pulse/events', {
            date: pulse.date || undefined,
            item_id: itemId,
            event_type: eventType,
            value,
            metadata: eventMetadata,
        });
        if (data?.feedback) {
            updatePulseItemFeedback(itemId, data.feedback);
        }
        return data;
    } catch (err) {
        console.warn('Pulse event failed', err);
        return null;
    }
}

function updatePulseItemFeedback(itemId, feedback) {
    if (!itemId || !feedback) return;
    const update = (item) => item?.id === itemId ? { ...item, feedback } : item;
    pulse = {
        ...pulse,
        items: (Array.isArray(pulse.items) ? pulse.items : []).map(update),
        modules: (Array.isArray(pulse.modules) ? pulse.modules : []).map((module) => ({
            ...module,
            items: Array.isArray(module.items) ? module.items.map(update) : module.items,
        })),
    };
    renderPulse();
}

function observePulseExposures() {
    if (!pulseItems) return;
    if (pulseExposureObserver) {
        pulseExposureObserver.disconnect();
        pulseExposureObserver = null;
    }
    const cards = Array.from(pulseItems.querySelectorAll('[data-pulse-card-id]'));
    if (!cards.length) return;

    const markExposed = (itemId) => {
        const key = `${pulse.date || ''}:${itemId}`;
        if (!itemId || exposedPulseItemKeys.has(key)) return;
        exposedPulseItemKeys.add(key);
        recordPulseEvent(itemId, pulseEventExposure, 1, { surface: 'feed' });
    };

    if (!('IntersectionObserver' in window)) {
        cards.forEach((card) => markExposed(card.getAttribute('data-pulse-card-id')));
        return;
    }

    pulseExposureObserver = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
            if (!entry.isIntersecting || entry.intersectionRatio < 0.45) return;
            const itemId = entry.target.getAttribute('data-pulse-card-id');
            markExposed(itemId);
            pulseExposureObserver?.unobserve(entry.target);
        });
    }, { threshold: [0.45, 0.75] });

    cards.forEach((card) => pulseExposureObserver.observe(card));
}

function normalizePulseNewsSources(...groups) {
    const sources = [];
    const seen = new Set();
    groups.forEach((group) => {
        if (!Array.isArray(group)) return;
        group.forEach((source) => {
            if (!source || typeof source !== 'object') return;
            const url = String(source.url || source.link || '').trim();
            if (!url || seen.has(url)) return;
            seen.add(url);
            sources.push({
                title: String(source.title || hostFromUrl(url) || url).trim(),
                url,
                source: String(source.source || '').trim(),
                snippet: String(source.snippet || source.summary || '').trim(),
                published_at: String(source.published_at || source.publishedAt || '').trim(),
            });
        });
    });
    return sources.slice(0, 5);
}

function renderPulseNewsSources(sources = []) {
    return `
        <div class="pulse-source-list">
            ${sources.map((source) => {
                const meta = [source.source, hostFromUrl(source.url), source.published_at].filter(Boolean);
                return `
                    <a class="pulse-source-item" href="${escapeAttr(source.url)}" target="_blank" rel="noopener noreferrer">
                        <span class="pulse-source-link">${escapeHtml(source.title)}</span>
                        ${meta.length ? `<span class="pulse-source-meta">${escapeHtml(Array.from(new Set(meta)).join(' / '))}</span>` : ''}
                        ${source.snippet ? `<span class="pulse-source-snippet">${escapeHtml(source.snippet)}</span>` : ''}
                    </a>
                `;
            }).join('')}
        </div>
    `;
}

function buildPulseChatPrompt(item = {}, question = '') {
    const userQuestion = String(question || '').trim();
    const context = buildPulseContextBlock(item);
    if (userQuestion) {
        return [
            `我想追问：${userQuestion}`,
            '',
            '请基于下面这条 Pulse 推荐的新闻上下文回答，优先引用来源链接；如果信息不足，请明确说哪些点需要继续核验。',
            '',
            context,
        ].join('\n');
    }

    return [
        '请基于下面这条 Pulse 推荐做一个有用的新闻聚合展开：',
        '1. 先给我 5 分钟版结论。',
        '2. 标出关键证据、待核验点和来源链接。',
        '3. 给我后续可以继续追踪的关键词/公司/指标。',
        '',
        context,
    ].join('\n');
}

function buildPulseContextBlock(item = {}) {
    const detail = item.detail || {};
    const keyPoints = Array.isArray(detail.key_points) ? detail.key_points : [];
    const sources = normalizePulseNewsSources(detail.news_sources, detail.sources, detail.related_news);
    const relatedClusters = Array.isArray(item.related_clusters) ? item.related_clusters : [];
    const lines = [
        '[Pulse 推荐]',
        `模块：${pulseSourceLabel(item.source)}`,
        item.topic_name || item.category ? `Topic/分类：${item.topic_name || item.category}` : '',
        item.title ? `标题：${item.title}` : '',
        item.summary ? `摘要：${truncateText(item.summary, 420)}` : '',
        detail.quick_context ? `展开背景：${truncateText(detail.quick_context, 700)}` : '',
    ].filter(Boolean);

    if (keyPoints.length) {
        lines.push('关键点：');
        keyPoints.slice(0, 4).forEach((point, index) => {
            lines.push(`${index + 1}. ${truncateText(point, 180)}`);
        });
    }

    if (sources.length) {
        lines.push('新闻来源：');
        sources.slice(0, 5).forEach((source, index) => {
            const meta = [source.source, hostFromUrl(source.url), source.published_at].filter(Boolean);
            lines.push(`${index + 1}. ${source.title || hostFromUrl(source.url) || '来源'}${meta.length ? `（${Array.from(new Set(meta)).join(' / ')}）` : ''}`);
            lines.push(`   URL: ${source.url}`);
            if (source.snippet) lines.push(`   摘要: ${truncateText(source.snippet, 220)}`);
        });
    }

    if (relatedClusters.length) {
        lines.push('相关信息簇：');
        relatedClusters.slice(0, 3).forEach((cluster, index) => {
            lines.push(`${index + 1}. ${cluster.title || '未命名信息簇'}${cluster.reason ? `（${cluster.reason}）` : ''}`);
        });
    }

    return lines.join('\n');
}

function renderTools() {
    if (toolsError) {
        toolsGrid.innerHTML = emptyState(t('tools.unavailableTitle'), toolsError);
        return;
    }
    const total = tools.length;
    const enabledCount = tools.filter(toolEffectiveEnabled).length;
    const visibleTools = filteredTools();
    const grouped = groupToolsBySource(visibleTools);
    const statusClass = toolSettingsStatusType === 'error' ? 'error' : (toolSettingsStatusType === 'ok' ? 'ok' : 'neutral');

    toolsGrid.innerHTML = `
        <div class="tools-workbench">
            <section class="tools-toolbar">
                <div class="tools-toolbar-copy">
                    <h2>${escapeHtml(t('tools.title'))}</h2>
                    <p>${escapeHtml(t('tools.detail'))}</p>
                </div>
                <div class="tools-toolbar-controls">
                    <input class="tools-search" type="search"
                           data-tool-search
                           placeholder="${escapeAttr(t('tools.search'))}"
                           value="${escapeAttr(toolSearchQuery)}">
                    <div class="segmented-control tools-filter" role="group" aria-label="${escapeAttr(t('tools.title'))}">
                        ${['all', 'enabled', 'disabled'].map((filter) => `
                            <button class="${toolFilter === filter ? 'active' : ''}" type="button" data-tool-filter="${escapeAttr(filter)}">
                                ${escapeHtml(t(`tools.${filter}`))}
                            </button>
                        `).join('')}
                    </div>
                </div>
                <span class="status-chip neutral">${escapeHtml(t('tools.total', { enabled: enabledCount, total }))}</span>
            </section>

            <section class="tool-mcp-panel">
                <div class="tool-mcp-head">
                    <div>
                        <h2>${escapeHtml(t('tools.mcpTitle'))}</h2>
                        <p>${escapeHtml(t('tools.mcpDetail'))}</p>
                    </div>
                    <label class="toggle-switch">
                        <input type="checkbox" data-mcp-enabled ${toolMcpConfig.enabled ? 'checked' : ''} ${toolSettingsSaving ? 'disabled' : ''}>
                        <span>${escapeHtml(t('tools.mcpEnabled'))}</span>
                    </label>
                </div>
                <label class="tool-mcp-editor">
                    <span>${escapeHtml(t('tools.mcpServers'))}</span>
                    <textarea data-mcp-servers
                              rows="5"
                              spellcheck="false"
                              placeholder="${escapeAttr(t('tools.mcpPlaceholder'))}"
                              ${toolSettingsSaving ? 'disabled' : ''}>${escapeHtml(toolMcpConfig.servers || '')}</textarea>
                </label>
                <div class="tool-mcp-actions">
                    <button class="btn-secondary" type="button" data-save-mcp-settings ${toolSettingsSaving ? 'disabled aria-busy="true"' : ''}>
                        ${escapeHtml(toolSettingsSaving ? t('tools.saving') : t('tools.saveMcp'))}
                    </button>
                    ${toolSettingsStatus ? `<span class="status-chip ${statusClass}">${escapeHtml(toolSettingsStatus)}</span>` : ''}
                </div>
            </section>

            ${renderToolGroups(grouped, total)}
        </div>
    `;
}

function renderToolGroups(grouped, total) {
    if (!total) return emptyState(t('tools.emptyTitle'), t('tools.emptyDetail'));
    if (!grouped.length) return emptyState(t('tools.noMatches'), t('tools.search'));
    return grouped.map(({ source, items }) => `
        <section class="tool-group">
            <div class="tool-group-head">
                <h2>${escapeHtml(t('tools.sourceGroup', { source, count: items.length }))}</h2>
            </div>
            <div class="tool-list">
                ${items.map(renderToolRow).join('')}
            </div>
        </section>
    `).join('');
}

function renderToolRow(tool) {
    const params = Array.isArray(tool.parameters) ? tool.parameters : [];
    const tags = Array.isArray(tool.tags) ? tool.tags : [];
    const baseEnabled = tool.enabled !== false;
    const effectiveEnabled = toolEffectiveEnabled(tool);
    const userEnabled = toolUserEnabled(tool);
    const statusText = !baseEnabled
        ? t('tools.baseDisabled')
        : (effectiveEnabled ? t('tools.userEnabled') : t('tools.userDisabled'));
    const statusTone = effectiveEnabled ? 'ok' : 'warn';
    const disabledAttr = (!baseEnabled || toolSettingsSaving) ? 'disabled' : '';
    return `
        <article class="tool-row ${effectiveEnabled ? '' : 'disabled'}">
            <div class="tool-row-main">
                <div class="tool-identity">
                    <span class="status-dot ${statusTone}"></span>
                    <span class="mono">${escapeHtml(tool.name || t('tools.unnamed'))}</span>
                    ${tool.version ? `<span class="status-chip neutral">v${escapeHtml(tool.version)}</span>` : ''}
                    <span class="status-chip ${statusTone}">${escapeHtml(statusText)}</span>
                </div>
                <p>${escapeHtml(tool.description || '')}</p>
                <div class="tool-meta-line">
                    <div class="tool-tags">
                        ${tool.source ? `<span class="chip">${escapeHtml(tool.source)}</span>` : ''}
                        ${tags.slice(0, 4).map((tag) => `<span class="chip">${escapeHtml(tag)}</span>`).join('')}
                        ${tags.length > 4 ? `<span class="chip muted">+${tags.length - 4}</span>` : ''}
                    </div>
                    <details class="tool-details">
                        <summary>${escapeHtml(params.length ? t('tools.parameters', { count: params.length }) : t('tools.noParams'))}</summary>
                        ${renderParameters(params)}
                    </details>
                </div>
            </div>
            <label class="toggle-switch tool-toggle">
                <input type="checkbox"
                       data-tool-enabled="${escapeAttr(tool.name || '')}"
                       ${userEnabled ? 'checked' : ''}
                       ${disabledAttr}>
                <span>${escapeHtml(effectiveEnabled ? t('tools.enabled') : t('tools.disabled'))}</span>
            </label>
        </article>
    `;
}

function renderParameters(params) {
    if (!params.length) return `<div class="param-list empty">${escapeHtml(t('tools.noParams'))}</div>`;
    return `
        <div class="param-list compact">
            ${params.map((param) => `
                <div class="param-item">
                    <span class="param-name">${escapeHtml(param.name || '')}</span>
                    <span class="param-type">${escapeHtml(param.type || 'string')}</span>
                    <span class="param-required">${escapeHtml(param.required ? t('tools.required') : t('tools.optional'))}</span>
                    <p>${escapeHtml(param.description || '')}</p>
                </div>
            `).join('')}
        </div>
    `;
}

function toolEffectiveEnabled(tool) {
    if (typeof tool.effective_enabled === 'boolean') return tool.effective_enabled;
    if (typeof tool.effectiveEnabled === 'boolean') return tool.effectiveEnabled;
    return tool.enabled !== false && toolUserEnabled(tool);
}

function toolUserEnabled(tool) {
    if (typeof tool.user_enabled === 'boolean') return tool.user_enabled;
    if (typeof tool.userEnabled === 'boolean') return tool.userEnabled;
    const key = toolEnabledSettingKey(tool.name || '');
    if (Object.prototype.hasOwnProperty.call(toolUserSettings, key)) {
        return parseBooleanSetting(toolUserSettings[key], true);
    }
    return true;
}

function toolEnabledSettingKey(toolName) {
    return `tool.${String(toolName || '').trim()}.enabled`;
}

function parseBooleanSetting(value, fallback = false) {
    const normalized = String(value ?? '').trim().toLowerCase();
    if (['true', '1', 'yes', 'on'].includes(normalized)) return true;
    if (['false', '0', 'no', 'off'].includes(normalized)) return false;
    return fallback;
}

function filteredTools() {
    const query = toolSearchQuery.trim().toLowerCase();
    return tools
        .filter((tool) => {
            const effectiveEnabled = toolEffectiveEnabled(tool);
            if (toolFilter === 'enabled' && !effectiveEnabled) return false;
            if (toolFilter === 'disabled' && effectiveEnabled) return false;
            if (!query) return true;
            const haystack = [
                tool.name,
                tool.description,
                tool.source,
                ...(Array.isArray(tool.tags) ? tool.tags : []),
            ].join(' ').toLowerCase();
            return haystack.includes(query);
        })
        .sort((a, b) => {
            const sourceCompare = String(a.source || 'builtin').localeCompare(String(b.source || 'builtin'));
            if (sourceCompare !== 0) return sourceCompare;
            return String(a.name || '').localeCompare(String(b.name || ''));
        });
}

function groupToolsBySource(items) {
    const groups = new Map();
    items.forEach((tool) => {
        const source = String(tool.source || 'builtin').trim() || 'builtin';
        if (!groups.has(source)) groups.set(source, []);
        groups.get(source).push(tool);
    });
    return Array.from(groups.entries()).map(([source, groupItems]) => ({ source, items: groupItems }));
}

async function updateToolSettings(updates) {
    toolSettingsSaving = true;
    toolSettingsStatus = '';
    renderTools();
    try {
        const data = await apiCall('PUT', '/api/tools/settings', { settings: updates });
        toolUserSettings = data.user_settings || { ...toolUserSettings, ...updates };
        toolMcpConfig = data.mcp || {
            enabled: parseBooleanSetting(toolUserSettings['mcp.enabled'], false),
            servers: toolUserSettings['mcp.servers'] || '',
        };
        await loadTools();
        toolSettingsStatus = t('tools.saved');
        toolSettingsStatusType = 'ok';
    } catch (err) {
        toolSettingsStatus = t('tools.saveFailed', { message: err.message });
        toolSettingsStatusType = 'error';
    } finally {
        toolSettingsSaving = false;
        renderTools();
        updateCounts();
    }
}

async function saveMcpSettings() {
    const textarea = document.querySelector('[data-mcp-servers]');
    const servers = textarea ? textarea.value.trim() : (toolMcpConfig.servers || '');
    if (servers) {
        try {
            JSON.parse(servers);
        } catch {
            toolSettingsStatus = t('tools.invalidJson');
            toolSettingsStatusType = 'error';
            renderTools();
            return;
        }
    }
    await updateToolSettings({
        'mcp.enabled': toolMcpConfig.enabled ? 'true' : 'false',
        'mcp.servers': servers,
    });
}

function renderRuns() {
    if (runsError) {
        runList.innerHTML = emptyState(t('runs.unavailableTitle'), runsError);
        runDetail.innerHTML = '';
        return;
    }
    if (!runs.length) {
        runList.innerHTML = emptyState(t('runs.emptyTitle'), t('runs.emptyDetail'));
        runDetail.innerHTML = '';
        return;
    }

    runList.innerHTML = runs.map((run) => {
        const active = run.run_id === selectedRunId;
        const statusClass = runStatusClass(run.status);
        const queryText = runQueryText(run);
        const queryPreview = truncateText(queryText, 120) || t('runs.noQuery');
        const scenario = runScenarioLabel(run);
        const runAgent = getRunAgent(run);
        const agentLabel = runAgent?.name || run.agent_id || '';
        const meta = [agentLabel, run.runtime].filter(Boolean).join(' / ');
        const time = formatTime(run.started_at);
        return `
            <button class="run-item ${active ? 'active' : ''}" type="button" data-run-id="${escapeAttr(run.run_id)}">
                <span class="status-dot ${statusClass}"></span>
                <span class="run-item-body">
                    <span class="run-item-topline">
                        <span class="run-scenario" title="${escapeAttr(`${t('runs.scenario')}: ${scenario}`)}">${escapeHtml(scenario)}</span>
                        ${time ? `<small>${escapeHtml(time)}</small>` : ''}
                    </span>
                    <strong class="run-query" title="${escapeAttr(queryText || t('runs.noQuery'))}">${escapeHtml(queryPreview)}</strong>
                    ${meta ? `<span class="run-meta" title="${escapeAttr(meta)}">${escapeHtml(meta)}</span>` : ''}
                    <span class="run-id-line">
                        <code title="${escapeAttr(run.run_id || '')}">${escapeHtml(t('runs.runId'))}:${escapeHtml(shortRunId(run.run_id || ''))}</code>
                    </span>
                </span>
            </button>
        `;
    }).join('');

    const selected = runs.find((run) => run.run_id === selectedRunId) || runs[0];
    if (selected) {
        const runChanged = selectedRunId !== selected.run_id;
        selectedRunId = selected.run_id;
        if (runChanged) selectedTraceNodeId = '';
        renderRunDetail(selected);
    }
}

function runStatusClass(status = '') {
    if (status === 'completed') return 'ok';
    if (status === 'failed') return 'error';
    if (status === 'cancelled') return 'neutral';
    return 'warn';
}

function renderRunDetail(run) {
    const runChanged = selectedTraceRunId !== run.run_id;
    if (runChanged) {
        collapsedTraceNodeIds = new Set();
        expandedTraceNodeIds = new Set();
    }
    const preserveTreeScroll = !runChanged;
    const previousTreeScroll = preserveTreeScroll
        ? (runDetail.querySelector('.trace-tree-panel')?.scrollTop || 0)
        : 0;
    const traceTree = buildTraceTree(run);
    if (runChanged || !findTraceNode(traceTree, selectedTraceNodeId)) {
        selectedTraceNodeId = defaultTraceNodeId(traceTree);
        selectedTraceRunId = run.run_id;
    }
    const selectedNode = findTraceNode(traceTree, selectedTraceNodeId) || traceTree;
    const tokens = Object.entries(run.tokens_used || {})
        .map(([key, value]) => `${key}: ${value}`)
        .join(' / ');
    const returnConversationId = String(run.conversation_id || currentConversationId || '').trim();

    runDetail.innerHTML = `
        <article class="run-panel trace-page-panel">
            <div class="trace-run-summary">
                <div class="run-panel-head">
                    <div>
                        <span class="trace-run-id-copy">
                            <span class="mono">${escapeHtml(run.run_id || '')}</span>
                            ${renderTraceIdCopyButton(run.run_id)}
                        </span>
                        <h2>${escapeHtml(run.agent_id || 'agent')}</h2>
                    </div>
                    <div class="run-panel-actions">
                        ${renderTraceReturnButton(returnConversationId)}
                        <span class="status-chip ${runStatusClass(run.status)}">${escapeHtml(run.status || '')}</span>
                    </div>
                </div>
                <dl class="run-facts">
                    <div><dt>Runtime</dt><dd>${escapeHtml(run.runtime || '')}</dd></div>
                    <div><dt>Model</dt><dd>${escapeHtml(run.model_used || '-')}</dd></div>
                    <div><dt>Duration</dt><dd>${formatDuration(run.duration_ms)}</dd></div>
                    <div><dt>Tokens</dt><dd>${escapeHtml(tokens || '-')}</dd></div>
                    <div><dt>Events</dt><dd>${escapeHtml(String((run.events || []).length))}</dd></div>
                </dl>
            </div>
            <div class="trace-workbench">
                <section class="trace-tree-panel" aria-label="${escapeAttr(t('trace.hierarchy'))}">
                    <div class="trace-section-title">${escapeHtml(t('trace.hierarchy'))}</div>
                    <div class="trace-tree">${renderTraceTreeNode(traceTree)}</div>
                </section>
                <section class="trace-node-panel" aria-label="${escapeAttr(t('trace.details'))}">
                    ${renderTraceNodeDetails(selectedNode, run)}
                </section>
            </div>
        </article>
    `;
    if (preserveTreeScroll) {
        const treePanel = runDetail.querySelector('.trace-tree-panel');
        if (treePanel) treePanel.scrollTop = previousTreeScroll;
    }
}

function renderTraceReturnButton(conversationId = '') {
    return `
        <button class="btn-secondary trace-return-button" type="button"
                data-trace-return-conversation="${escapeAttr(conversationId)}"
                title="${escapeAttr(t('trace.backToChat'))}"
                aria-label="${escapeAttr(t('trace.backToChat'))}">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.4">
                <path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4Z"/>
                <path d="m10 8-4 4 4 4"/>
                <path d="M7 12h10"/>
            </svg>
            <span>${escapeHtml(t('trace.backToChat'))}</span>
        </button>
    `;
}

function renderTraceIdCopyButton(runId = '') {
    if (!runId) return '';

    const label = t('trace.copyTraceId');
    return `
        <button class="trace-copy-id-button assistant-copy" type="button"
                data-copy-trace-id="${escapeAttr(runId)}"
                data-copy-label-key="trace.copyTraceId"
                title="${escapeAttr(label)}"
                aria-label="${escapeAttr(label)}">
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="9" y="9" width="10" height="10" rx="2"/>
                <path d="M5 15H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v1"/>
            </svg>
            ${renderAssistantActionLabel(label)}
        </button>
    `;
}

async function returnToTraceConversation(conversationId = '') {
    const targetId = String(conversationId || currentConversationId || '').trim();
    if (!targetId) {
        setView('chat');
        focusMessageInput();
        return;
    }

    try {
        if (!conversations.some((conv) => conv.id === targetId)) {
            await loadConversations();
        }
        if (conversations.some((conv) => conv.id === targetId)) {
            await selectConversation(targetId);
            return;
        }
        setView('chat');
        ensureCurrentConversationVisible();
        focusMessageInput();
    } catch {
        setView('chat');
        focusMessageInput();
    }
}

function runQueryText(run = {}) {
    return String(run.query || run.input || '').replace(/\s+/g, ' ').trim();
}

function getRunAgent(run = {}) {
    const agent = agents.find((item) => item.id === run.agent_id);
    if (agent) return agent;
    if (!run.agent_id) return null;
    return {
        id: run.agent_id,
        name: run.agent_id,
        runtime: run.runtime || '',
        framework: run.runtime || '',
        capabilities: [],
    };
}

function runScenarioLabel(run = {}) {
    const modeIds = runModeIds(run);
    if (modeIds.length) {
        return modeIds
            .map((modeId) => modeCopy({ id: modeId }).name || modeId)
            .filter(Boolean)
            .join(' / ');
    }

    const agent = getRunAgent(run);
    if (agent) return agentUseCase(agent);
    return run.runtime || run.agent_id || '';
}

function runModeIds(run = {}) {
    const ids = [];
    const addModeIds = (value) => {
        if (Array.isArray(value)) {
            value.forEach(addModeIds);
            return;
        }
        const modeId = String(value || '').trim();
        if (modeId) ids.push(modeId);
    };

    addModeIds(run.mode_ids || run.modeIds);
    (run.events || []).forEach((event) => {
        const payload = event?.payload || {};
        addModeIds(payload.mode_ids || payload.modeIds);
    });

    return Array.from(new Set(ids));
}

function buildTraceTree(run) {
    const root = createTraceNode({
        id: `run:${run.run_id || 'unknown'}`,
        kind: 'run',
        label: t('trace.runOverview'),
        detail: run.run_id || '',
        status: normalizeTraceStatus(run.status),
        duration_ms: run.duration_ms,
        meta: { run },
    });
    const state = {
        run,
        root,
        nodes: new Map([[root.id, root]]),
        planNode: null,
        planStepSpecs: new Map(),
        toolParentByStep: new Map(),
    };

    (run.events || []).forEach((event, index) => {
        attachTraceEvent(state, event, index);
    });

    finalizeTraceNode(root);
    return root;
}

function createTraceNode({ id, kind, label, detail = '', status = 'neutral', duration_ms = null, event = null, events = [], meta = {}, children = [] }) {
    return { id, kind, label, detail, status, duration_ms, event, events, meta, children };
}

function attachTraceEvent(state, event = {}, index = 0) {
    const type = event.type || '';
    const payload = event.payload || {};

    if (type.startsWith('workflow.')) {
        const workflowNode = workflowParentNode(state, event) || ensureWorkflowRootNode(state, payload.workflow || 'workflow');
        addTraceEventLeaf(state, workflowNode, event, index);
        return;
    }

    if (type === 'aigc.plan.created' || type === 'thinking.plan.created') {
        const planNode = ensurePlanNode(state, type.startsWith('thinking.') ? 'thinking' : 'aigc');
        registerPlanSteps(state, payload.steps || []);
        addTraceEventLeaf(state, planNode, event, index);
        return;
    }

    if (type.startsWith('aigc.plan.step.') || type.startsWith('thinking.step.')) {
        const stepNode = ensurePlanStepNode(state, payload.step || event.step_id || 'unknown');
        addTraceEventLeaf(state, stepNode, event, index);
        return;
    }

    if (type === 'aigc.plan.completed' || type === 'thinking.plan.started') {
        addTraceEventLeaf(state, ensurePlanNode(state, type.startsWith('thinking.') ? 'thinking' : 'aigc'), event, index);
        return;
    }

    if (type.startsWith('thinking.summary.')) {
        const stage = ensureStageNode(
            state,
            state.planNode || ensureExecutionStageNode(state),
            'thinking-summary',
            traceCopy('思考汇总', 'Thinking Summary'),
            traceCopy('合并计划步骤、工具结果和风险', 'Combine plan steps, tool results, and risks'),
        );
        addTraceEventLeaf(state, stage, event, index);
        return;
    }

    if (type === 'aigc.command.received') {
        const stage = ensureAigcStageNode(
            state,
            'image_generation',
            'command',
            traceCopy('生图命令', 'Image Command'),
            traceCopy('解析 agent_command.v1 输入', 'Parse agent_command.v1 input'),
        );
        addTraceEventLeaf(state, stage, event, index);
        return;
    }

    if (type.startsWith('aigc.research.model.')) {
        const stage = ensureAigcStageNode(
            state,
            'retrieval',
            'research',
            traceCopy('资料检索', 'Research'),
            traceCopy('检索事实、来源和约束', 'Gather facts, sources, and constraints'),
        );
        const modelNode = ensureModelNode(state, stage, event, 'research');
        addTraceEventLeaf(state, modelNode, event, index);
        registerToolParentsFromModelEvent(state, event, modelNode);
        return;
    }

    if (type.startsWith('aigc.research.')) {
        const stage = ensureAigcStageNode(
            state,
            'retrieval',
            'research',
            traceCopy('资料检索', 'Research'),
            traceCopy('检索事实、来源和约束', 'Gather facts, sources, and constraints'),
        );
        addTraceEventLeaf(state, stage, event, index);
        return;
    }

    if (type.startsWith('aigc.prompt_review.')) {
        const stage = ensureAigcStageNode(
            state,
            'image_generation',
            'prompt-review',
            traceCopy('提示词修饰', 'Prompt Review'),
            traceCopy('把用户意图转成可生图 prompt', 'Turn user intent into an image prompt'),
        );
        addTraceEventLeaf(state, stage, event, index);
        return;
    }

    if (type.startsWith('aigc.image.')) {
        const stage = ensureAigcStageNode(
            state,
            'image_generation',
            'image',
            traceCopy('图片生成', 'Image Generation'),
            traceCopy('调用图像模型生成结果', 'Call the image model'),
        );
        addTraceEventLeaf(state, stage, event, index);
        return;
    }

    if (type.startsWith('aigc.summary.')) {
        const stage = ensureAigcStageNode(
            state,
            'final_summary',
            'summary',
            traceCopy('结果汇总', 'Final Summary'),
            traceCopy('合并检索结论、图片和来源', 'Combine findings, images, and sources'),
        );
        addTraceEventLeaf(state, stage, event, index);
        return;
    }

    if (type.startsWith('model.')) {
        const stage = workflowParentNode(state, event) || ensureExecutionStageNode(state);
        const modelNode = ensureModelNode(state, stage, event, 'main');
        addTraceEventLeaf(state, modelNode, event, index);
        registerToolParentsFromModelEvent(state, event, modelNode);
        return;
    }

    if (type.startsWith('tool.')) {
        const parent = toolParentNode(state, event) || workflowParentNode(state, event) || ensureExecutionStageNode(state);
        const toolNode = ensureToolNode(state, parent, event);
        addTraceEventLeaf(state, toolNode, event, index);
        return;
    }

    if (type.startsWith('citations.')) {
        const toolParent = toolParentNode(state, event);
        const citationParent = toolParent || ensureStageNode(
            state,
            workflowParentNode(state, event) || state.root,
            'citations',
            traceCopy('来源整理', 'Citations'),
            'citations',
        );
        addTraceEventLeaf(state, citationParent, event, index);
        return;
    }

    if (type.startsWith('agent.')) {
        addTraceEventLeaf(
            state,
            ensureAgentEventParent(state, event),
            event,
            index,
        );
        return;
    }

    if (type.startsWith('weight_loss.')) {
        addTraceEventLeaf(
            state,
            ensureStageNode(
                state,
                state.root,
                'weight-loss',
                traceCopy('减脂记录', 'Weight Loss'),
                traceCopy('食物热量估算、数据库记录和缺口统计', 'Food calorie estimates, database logs, and deficit stats'),
            ),
            event,
            index,
        );
        return;
    }

    if (type.startsWith('run.')) {
        addTraceEventLeaf(
            state,
            ensureStageNode(state, state.root, 'lifecycle', traceCopy('生命周期', 'Lifecycle'), 'run.*'),
            event,
            index,
        );
        return;
    }

    if (type.startsWith('memory.') || type === 'context.built') {
        const contextStage = ensureStageNode(
            state,
            state.root,
            'context',
            traceCopy('上下文与记忆', 'Context & Memory'),
            traceCopy('角色记忆、Prompt 和会话上下文', 'Role memory, prompt, and conversation context'),
            { stageType: 'context' },
        );
        if (type === 'context.built') {
            attachContextTraceNodes(state, contextStage, payload.context_nodes || []);
        }
        addTraceEventLeaf(
            state,
            contextStage,
            event,
            index,
        );
        return;
    }

    addTraceEventLeaf(
        state,
        ensureStageNode(state, state.root, 'other', traceCopy('其他事件', 'Other Events'), type || 'event'),
        event,
        index,
    );
}

function ensureTraceChild(state, parent, id, spec) {
    let node = state.nodes.get(id);
    if (!node) {
        node = createTraceNode({
            id,
            kind: spec.kind,
            label: spec.label,
            detail: spec.detail || '',
            status: spec.status || 'neutral',
            duration_ms: spec.duration_ms ?? null,
            meta: spec.meta || {},
        });
        state.nodes.set(id, node);
    } else {
        node.kind = spec.kind || node.kind;
        node.label = spec.label || node.label;
        if ('detail' in spec) node.detail = spec.detail || '';
        if (spec.meta) node.meta = { ...(node.meta || {}), ...spec.meta };
    }

    if (parent && !(parent.children || []).some((child) => child.id === node.id)) {
        parent.children.push(node);
    }
    return node;
}

function ensureStageNode(state, parent, key, label, detail = '', meta = {}) {
    const safeParentId = parent?.id || state.root.id;
    return ensureTraceChild(state, parent || state.root, `${safeParentId}:stage:${key}`, {
        kind: 'stage',
        label,
        detail,
        meta: { stageKey: key, ...meta },
    });
}

function ensureExecutionStageNode(state) {
    return ensureStageNode(
        state,
        state.root,
        'execution',
        traceCopy('执行过程', 'Execution'),
        traceCopy('模型调用、工具调用和最终生成', 'Model calls, tool calls, and generation'),
    );
}

function workflowDisplayName(workflow = '') {
    const labels = {
        thinking: traceCopy('Thinking Workflow', 'Thinking Workflow'),
        agent_loop: traceCopy('Agent Loop', 'Agent Loop'),
        generic_tool_loop: traceCopy('通用工具循环', 'Generic Tool Loop'),
        deep_research: traceCopy('Deep Research Workflow', 'Deep Research Workflow'),
    };
    return labels[workflow] || workflow || traceCopy('Workflow', 'Workflow');
}

function workflowNodeDisplayName(node = '') {
    const labels = {
        analyze: traceCopy('Analyze', 'Analyze'),
        plan: traceCopy('Plan', 'Plan'),
        execute: traceCopy('Execute', 'Execute'),
        summary: traceCopy('Summary', 'Summary'),
        main_loop: traceCopy('Main Loop', 'Main Loop'),
    };
    return labels[node] || node || traceCopy('Workflow Node', 'Workflow Node');
}

function safeTraceKey(value = '') {
    return String(value || 'unknown').trim().replace(/[^a-zA-Z0-9_-]+/g, '-').replace(/^-+|-+$/g, '') || 'unknown';
}

function ensureWorkflowRootNode(state, workflow = '') {
    const workflowId = safeTraceKey(workflow || 'workflow');
    return ensureStageNode(
        state,
        state.root,
        `workflow:${workflowId}`,
        workflowDisplayName(workflow),
        workflow,
        { workflow },
    );
}

function ensureWorkflowNode(state, workflow = '', node = '') {
    const workflowRoot = ensureWorkflowRootNode(state, workflow);
    if (!node) return workflowRoot;
    const nodeId = safeTraceKey(node);
    return ensureStageNode(
        state,
        workflowRoot,
        `node:${nodeId}`,
        workflowNodeDisplayName(node),
        node,
        { workflow, workflowNode: node },
    );
}

function workflowParentNode(state, event = {}) {
    const payload = event.payload || {};
    const workflow = payload.workflow || payload.final_model_request?.workflow || '';
    if (!workflow) return null;
    const node = payload.workflow_node || payload.node || payload.final_model_request?.workflow_node || '';
    return ensureWorkflowNode(state, workflow, node);
}

function ensureAgentEventParent(state, event = {}) {
    const payload = event.payload || {};
    const packet = payload.packet || {};
    const targetAgent = payload.target_agent_id || packet.target_agent_id || payload.agent_id || 'agent';
    const sourceAgent = payload.source_agent_id || packet.source_agent_id || '';
    const detail = [sourceAgent ? `${sourceAgent} -> ${targetAgent}` : targetAgent, payload.reason || '']
        .filter(Boolean)
        .join(' / ');
    const agentNode = ensureStageNode(
        state,
        state.root,
        `agent:${safeTraceKey(targetAgent)}`,
        `Agent: ${targetAgent}`,
        detail,
        { targetAgent, sourceAgent },
    );
    const stageContexts = Array.isArray(packet.stage_contexts) ? packet.stage_contexts : [];
    const latestStage = stageContexts[stageContexts.length - 1];
    if (!latestStage?.stage_id) return agentNode;
    return ensureStageNode(
        state,
        agentNode,
        `stage:${safeTraceKey(latestStage.stage_id)}`,
        latestStage.stage_id,
        latestStage.summary || '',
        { targetAgent, sourceAgent, agentStage: latestStage.stage_id },
    );
}

function ensurePlanNode(state, scope = 'workflow') {
    if (!state.planNode) {
        state.planNode = ensureTraceChild(state, state.root, `${state.root.id}:plan:${scope}`, {
            kind: 'plan',
            label: t('trace.plan'),
            detail: '',
            meta: { steps: [], run: state.run, scope },
        });
    }
    return state.planNode;
}

function registerPlanSteps(state, steps = []) {
    const planNode = ensurePlanNode(state);
    const normalized = Array.isArray(steps) ? steps : [];
    planNode.meta.steps = normalized.map((step, index) => ({ ...step, index: index + 1 }));
    planNode.detail = traceCopy(`${normalized.length} 个步骤`, `${normalized.length} steps`);
    normalized.forEach((step, index) => {
        if (!step?.id) return;
        state.planStepSpecs.set(step.id, { ...step, index: index + 1 });
        ensurePlanStepNode(state, step.id);
    });
}

function ensurePlanStepNode(state, stepId) {
    const planNode = ensurePlanNode(state);
    const step = state.planStepSpecs.get(stepId) || { id: stepId };
    const title = tracePlanStepTitle(stepId, step);
    return ensureTraceChild(state, planNode, `${planNode.id}:step:${stepId || 'unknown'}`, {
        kind: 'plan-step',
        label: step.index ? `${step.index}. ${title}` : title,
        detail: tracePlanStepDetail(stepId, step),
        meta: { stepId, step },
    });
}

function ensureAigcStageNode(state, stepId, stageKey, label, detail = '') {
    const parent = state.planNode ? ensurePlanStepNode(state, stepId) : ensureExecutionStageNode(state);
    return ensureStageNode(state, parent, stageKey, label, detail, { planStepId: stepId });
}

function ensureModelNode(state, parent, event, scope) {
    const payload = event.payload || {};
    const round = payload.round || 'unknown';
    const modelLabel = scope === 'research' ? traceCopy('研究模型轮次', 'Research Model Round') : traceCopy('模型轮次', 'Model Round');
    return ensureTraceChild(state, parent, `${parent.id}:model:${scope}:${round}`, {
        kind: 'model',
        label: `${modelLabel} ${round}`,
        detail: payload.model || payload.model_preference || event.title || '',
        meta: { round, scope },
    });
}

function ensureToolNode(state, parent, event) {
    const payload = event.payload || {};
    const key = traceToolKey(event);
    const name = payload.name || traceCopy('工具', 'Tool');
    return ensureTraceChild(state, parent, `${parent.id}:tool:${key}`, {
        kind: 'tool',
        label: `${t('trace.toolCall')}: ${name}`,
        detail: event.step_id || payload.tool_call_id || '',
        meta: { toolName: name, stepId: key },
    });
}

function attachContextTraceNodes(state, parent, nodes = []) {
    if (!Array.isArray(nodes)) return;
    nodes.forEach((contextNode, index) => {
        if (!contextNode || typeof contextNode !== 'object') return;
        const type = contextNode.type || 'context';
        const label = contextNodeLabel(contextNode);
        const detail = contextNodeDetail(contextNode);
        const node = ensureTraceChild(state, parent, `${parent.id}:context:${contextNode.id || `${type}:${index}`}`, {
            kind: 'context-node',
            label,
            detail,
            status: contextNode.injected === false ? 'neutral' : 'completed',
            meta: { contextNode },
        });
        attachContextTraceNodes(state, node, contextNode.children || []);
    });
}

function contextNodeLabel(node = {}) {
    const type = node.type || '';
    const labels = {
        system_prompt: traceCopy('System / Developer Prompt', 'System / Developer Prompt'),
        prompt_section: node.label || traceCopy('Prompt Section', 'Prompt Section'),
        long_term_memory: traceCopy('长期记忆', 'Long-term Memory'),
        role_persona_memory: traceCopy('角色 / 人设记忆', 'Role / Persona Memory'),
        short_term_memory: traceCopy('短期会话记忆', 'Short-term Conversation Memory'),
        conversation_window: traceCopy('当前对话窗口', 'Current Conversation Window'),
        turn_context: traceCopy('本轮附加上下文', 'Turn Context Blocks / Attachments'),
        context_block: node.label || traceCopy('Context Block', 'Context Block'),
        tool_definitions: traceCopy('工具定义', 'Tool Definitions'),
    };
    return labels[type] || node.label || type || traceCopy('上下文节点', 'Context Node');
}

function contextNodeDetail(node = {}) {
    const parts = [];
    if (node.injected === false) parts.push(traceCopy('未注入', 'not injected'));
    if (node.record_count != null) parts.push(traceCopy(`记录 ${node.record_count}`, `${node.record_count} records`));
    if (node.message_count != null) parts.push(traceCopy(`消息 ${node.message_count}`, `${node.message_count} messages`));
    if (node.block_count != null) parts.push(traceCopy(`块 ${node.block_count}`, `${node.block_count} blocks`));
    if (node.tools_count != null) parts.push(traceCopy(`工具 ${node.tools_count}`, `${node.tools_count} tools`));
    if (node.token_estimate != null) parts.push(traceCopy(`约 ${node.token_estimate} tokens`, `~${node.token_estimate} tokens`));
    return parts.join(' / ');
}

function traceToolKey(event = {}) {
    const payload = event.payload || {};
    return event.step_id || payload.tool_call_id || payload.name || event.id || 'unknown';
}

function toolParentNode(state, event = {}) {
    const key = traceToolKey(event);
    const parentId = state.toolParentByStep.get(key);
    return parentId ? state.nodes.get(parentId) : null;
}

function registerToolParentsFromModelEvent(state, event = {}, modelNode) {
    const payload = event.payload || {};
    const toolCalls = Array.isArray(payload.tool_calls) ? payload.tool_calls : [];
    toolCalls.forEach((toolCall) => {
        if (toolCall?.id) state.toolParentByStep.set(toolCall.id, modelNode.id);
    });
}

function addTraceEventLeaf(state, parent, event = {}, index = 0) {
    const display = traceEventDisplay(event);
    const eventNode = createTraceNode({
        id: `event:${event.id || index}`,
        kind: 'event',
        label: display.label,
        detail: display.detail || event.type || '',
        status: normalizeTraceStatus(event.status),
        duration_ms: event.duration_ms,
        event,
        events: [event],
        meta: { eventIndex: index },
    });
    parent.children.push(eventNode);
    parent.events.push(event);
    parent.status = mergeTraceStatus(parent.status, eventNode.status);
    state.nodes.set(eventNode.id, eventNode);
    return eventNode;
}

function finalizeTraceNode(node) {
    (node.children || []).forEach(finalizeTraceNode);
    const childStatuses = (node.children || []).map((child) => child.status);
    const eventStatuses = (node.events || []).map((event) => normalizeTraceStatus(event.status));
    node.status = mergeTraceStatus(node.status, ...eventStatuses, ...childStatuses);
    if (!Number.isInteger(node.duration_ms)) {
        const timedEvent = [...(node.events || [])].reverse().find((event) => Number.isInteger(event.duration_ms));
        if (timedEvent) node.duration_ms = timedEvent.duration_ms;
    }
}

function traceCopy(zh, en) {
    return currentLanguage === 'zh' ? zh : en;
}

function tracePlanStepTitle(stepId = '', step = {}) {
    const labels = {
        retrieval: traceCopy('检索并整理资料', 'Research and organize sources'),
        image_generation: traceCopy('基于资料生成图片', 'Generate image from the brief'),
        final_summary: traceCopy('合并检索结论和图片结果', 'Merge findings and image results'),
    };
    if (currentLanguage === 'zh' && step.title) return step.title;
    return labels[stepId] || step.title || stepId || t('trace.planStep');
}

function tracePlanStepDetail(stepId = '', step = {}) {
    if (currentLanguage === 'zh' && step.description) return step.description;
    const details = {
        retrieval: traceCopy('先收集事实、数据、风险和来源', 'Collect facts, data, risks, and sources first'),
        image_generation: traceCopy('提示词修饰后调用图像模型', 'Polish the prompt, then call the image model'),
        final_summary: traceCopy('整理成最终答复', 'Assemble the final response'),
    };
    return details[stepId] || step.description || stepId || '';
}

function traceEventDisplay(event = {}) {
    const type = event.type || '';
    const payload = event.payload || {};
    const round = payload.round || '';
    const stepTitle = tracePlanStepTitle(payload.step || event.step_id || '');
    const duration = Number.isInteger(event.duration_ms) ? formatDuration(event.duration_ms) : '';

    if (type === 'run.started') return { label: traceCopy('Run 开始', 'Run started'), detail: `${payload.agent_id || ''} ${payload.runtime || ''}`.trim() };
    if (type === 'run.completed') return { label: traceCopy('Run 完成', 'Run completed'), detail: [payload.model_used, duration].filter(Boolean).join(' / ') };
    if (type === 'run.partial') return { label: traceCopy('Run 部分完成', 'Run partial'), detail: payload.error_message || payload.error_type || payload.response_status || '' };
    if (type === 'run.failed') return { label: traceCopy('Run 失败', 'Run failed'), detail: payload.error_message || payload.error_type || '' };
    if (type === 'run.cancelled') return { label: traceCopy('Run 已取消', 'Run cancelled'), detail: payload.error_message || payload.error_type || '' };
    if (type === 'workflow.started') return { label: traceCopy('Workflow 开始', 'Workflow started'), detail: workflowDisplayName(payload.workflow) };
    if (type === 'workflow.completed') return { label: traceCopy('Workflow 完成', 'Workflow completed'), detail: [workflowDisplayName(payload.workflow), payload.result].filter(Boolean).join(' / ') };
    if (type === 'workflow.failed') return { label: traceCopy('Workflow 失败', 'Workflow failed'), detail: payload.error_message || payload.error_type || workflowDisplayName(payload.workflow) };
    if (type === 'workflow.node.started') return { label: traceCopy(`节点开始：${workflowNodeDisplayName(payload.node)}`, `Node started: ${workflowNodeDisplayName(payload.node)}`), detail: payload.workflow || '' };
    if (type === 'workflow.node.completed') return { label: traceCopy(`节点完成：${workflowNodeDisplayName(payload.node)}`, `Node completed: ${workflowNodeDisplayName(payload.node)}`), detail: [payload.result, duration].filter(Boolean).join(' / ') };
    if (type === 'workflow.node.failed') return { label: traceCopy(`节点失败：${workflowNodeDisplayName(payload.node)}`, `Node failed: ${workflowNodeDisplayName(payload.node)}`), detail: payload.error_message || payload.error_type || '' };
    if (type === 'agent.delegated') return { label: traceCopy('转交给专业 Agent', 'Delegated to specialist agent'), detail: payload.reason || payload.target_agent_id || '' };
    if (type === 'agent.command.routed') return { label: traceCopy('路由 Agent 命令', 'Routed agent command'), detail: `${payload.target_agent_id || ''} ${payload.command_text || ''}`.trim() };
    if (type.startsWith('agent.')) return { label: type, detail: payload.target_agent_id || payload.reason || payload.current_request_preview || '' };
    if (type === 'memory.loaded') return { label: traceCopy('读取角色记忆', 'Loaded role memory'), detail: traceCopy(`长期 ${payload.long_term_count || 0} / 角色 ${payload.persona_count || 0}`, `Long-term ${payload.long_term_count || 0} / role ${payload.persona_count || 0}`) };
    if (type === 'context.built') return { label: traceCopy('构建 Prompt 上下文', 'Built prompt context'), detail: traceCopy(`${payload.message_count || 0} 条消息 / ${payload.tools_count || 0} 个工具`, `${payload.message_count || 0} messages / ${payload.tools_count || 0} tools`) };
    if (type === 'memory.review.started') return { label: traceCopy('开始长期记忆检查', 'Started long-term memory review'), detail: payload.agent_id || '' };
    if (type === 'memory.review.completed') return { label: traceCopy('长期记忆检查完成', 'Long-term memory review completed'), detail: traceCopy(`候选 ${payload.candidate_count || 0}`, `${payload.candidate_count || 0} candidates`) };
    if (type === 'memory.review.failed') return { label: traceCopy('长期记忆检查降级', 'Long-term memory review fallback'), detail: payload.error_message || '' };
    if (type === 'memory.compaction.started') return { label: traceCopy('开始压缩会话记忆', 'Started conversation compaction'), detail: traceCopy(`${payload.message_count || 0} 条消息`, `${payload.message_count || 0} messages`) };
    if (type === 'memory.compaction.completed') return { label: traceCopy('会话记忆已压缩', 'Conversation memory compacted'), detail: traceCopy(`${payload.before_count || 0} -> ${payload.after_count || 0}`, `${payload.before_count || 0} -> ${payload.after_count || 0}`) };
    if (type === 'memory.compaction.skipped') return { label: traceCopy('跳过会话压缩', 'Skipped conversation compaction'), detail: payload.reason || '' };
    if (type === 'memory.compaction.failed') return { label: traceCopy('会话压缩降级', 'Conversation compaction fallback'), detail: payload.error_message || '' };
    if (type === 'memory.extracted') return { label: traceCopy('记忆检查完成', 'Memory review completed'), detail: traceCopy(`新增 ${payload.stored_count || 0}`, `${payload.stored_count || 0} stored`) };
    if (type === 'memory.failed') return { label: traceCopy('记忆处理失败', 'Memory failed'), detail: payload.error_message || '' };

    if (type === 'weight_loss.db.summary.loaded') return { label: traceCopy('读取减脂数据库', 'Loaded weight-loss database'), detail: traceCopy(`${payload.meal_count || 0} 条餐食记录`, `${payload.meal_count || 0} meal logs`) };
    if (type === 'weight_loss.command.received') return { label: traceCopy('执行减脂命令', 'Ran weight-loss command'), detail: `/${payload.command || ''}` };
    if (type === 'weight_loss.analysis.started') return { label: traceCopy('开始估算热量', 'Started calorie analysis'), detail: traceCopy(`${payload.image_count || 0} 张图片`, `${payload.image_count || 0} images`) };
    if (type === 'weight_loss.analysis.completed') return { label: traceCopy('热量分析完成', 'Calorie analysis completed'), detail: payload.intent || payload.model || '' };
    if (type === 'weight_loss.analysis.failed') return { label: traceCopy('热量分析降级', 'Calorie analysis fallback'), detail: payload.error_message || '' };
    if (type === 'weight_loss.profile.updated') return { label: traceCopy('更新减脂档案', 'Updated weight-loss profile'), detail: (payload.updated_keys || []).join(', ') };
    if (type === 'weight_loss.meal.logged') return { label: traceCopy('写入餐食记录', 'Logged meal'), detail: `${payload.total_calories || 0} kcal` };
    if (type === 'weight_loss.exercise.logged') return { label: traceCopy('写入运动记录', 'Logged exercise'), detail: `${payload.calories_burned || 0} kcal` };
    if (type === 'weight_loss.entry.deleted') return { label: traceCopy('撤销减脂记录', 'Deleted weight-loss entry'), detail: payload.entry_type || '' };
    if (type === 'weight_loss.summary.completed') return { label: traceCopy('完成缺口统计', 'Completed deficit stats'), detail: traceCopy(`${payload.period_days || 0} 天`, `${payload.period_days || 0} days`) };

    if (type === 'aigc.plan.created') return { label: traceCopy('创建执行计划', 'Created execution plan'), detail: traceCopy(`${(payload.steps || []).length} 个步骤`, `${(payload.steps || []).length} steps`) };
    if (type === 'aigc.plan.completed') return { label: traceCopy('执行计划完成', 'Execution plan completed'), detail: traceCopy(`图片 ${payload.image_count || 0} / 来源 ${payload.citation_count || 0}`, `Images ${payload.image_count || 0} / citations ${payload.citation_count || 0}`) };
    if (type === 'aigc.plan.step.started') return { label: traceCopy(`开始：${stepTitle}`, `Started: ${stepTitle}`), detail: payload.step || event.step_id || '' };
    if (type === 'aigc.plan.step.completed') return { label: traceCopy(`完成：${stepTitle}`, `Completed: ${stepTitle}`), detail: tracePlanStepEventSummary(payload) };
    if (type === 'aigc.plan.step.failed') return { label: traceCopy(`失败：${stepTitle}`, `Failed: ${stepTitle}`), detail: payload.error_message || '' };
    if (type === 'thinking.plan.started') return { label: traceCopy('思考计划开始', 'Thinking plan started'), detail: traceCopy(`${payload.max_steps || 0} 个步骤上限`, `${payload.max_steps || 0} step limit`) };
    if (type === 'thinking.plan.created') return { label: traceCopy('思考计划已创建', 'Thinking plan created'), detail: traceCopy(`${(payload.steps || []).length} 个步骤`, `${(payload.steps || []).length} steps`) };
    if (type === 'thinking.step.started') return { label: traceCopy(`开始：${stepTitle}`, `Started: ${stepTitle}`), detail: payload.step_type || payload.step || event.step_id || '' };
    if (type === 'thinking.step.completed') return { label: traceCopy(`完成：${stepTitle}`, `Completed: ${stepTitle}`), detail: tracePlanStepEventSummary(payload) };
    if (type === 'thinking.step.failed') return { label: traceCopy(`失败：${stepTitle}`, `Failed: ${stepTitle}`), detail: payload.error_message || payload.result_preview || '' };
    if (type === 'thinking.summary.completed') return { label: traceCopy('思考汇总完成', 'Thinking summary completed'), detail: traceCopy(`来源 ${payload.citation_count || 0} / 工具 ${(payload.skills_used || []).length}`, `${payload.citation_count || 0} citations / ${(payload.skills_used || []).length} tools`) };

    if (type === 'aigc.command.received') return { label: traceCopy('解析生图命令', 'Parsed image command'), detail: `/${payload.command || payload.raw_command || ''}` };
    if (type === 'aigc.research.started') return { label: traceCopy('资料检索开始', 'Research started'), detail: traceCopy(`${payload.tools_count || 0} 个可用工具`, `${payload.tools_count || 0} tools`) };
    if (type === 'aigc.research.completed') return { label: traceCopy('资料检索完成', 'Research completed'), detail: traceCopy(`来源 ${payload.citation_count || 0} / 工具 ${(payload.skills_used || []).length}`, `${payload.citation_count || 0} citations / ${(payload.skills_used || []).length} tools`) };
    if (type === 'aigc.research.failed') return { label: traceCopy('资料检索失败', 'Research failed'), detail: payload.error_message || '' };
    if (type === 'aigc.research.model.started') return { label: traceCopy(`研究模型 #${round || '?' } 开始`, `Research model #${round || '?'} started`), detail: payload.model_preference || '' };
    if (type === 'aigc.research.model.completed') return { label: traceCopy(`研究模型 #${round || '?' } 完成`, `Research model #${round || '?'} completed`), detail: traceModelEventDetail(payload) };

    if (type === 'aigc.prompt_review.started') return { label: traceCopy('提示词修饰开始', 'Prompt review started'), detail: payload.model_preference || '' };
    if (type === 'aigc.prompt_review.completed') return { label: traceCopy('提示词修饰完成', 'Prompt review completed'), detail: traceCopy(`比例 ${payload.aspect_ratio || '-'} / ${payload.should_generate ? '可生成' : '需澄清'}`, `Ratio ${payload.aspect_ratio || '-'} / ${payload.should_generate ? 'ready' : 'needs clarification'}`) };
    if (type === 'aigc.prompt_review.failed') return { label: traceCopy('提示词修饰失败', 'Prompt review failed'), detail: payload.error_message || '' };
    if (type === 'aigc.image.started') return { label: traceCopy('图片生成开始', 'Image generation started'), detail: payload.aspect_ratio || '' };
    if (type === 'aigc.image.completed') return { label: traceCopy('图片生成完成', 'Image generation completed'), detail: traceCopy(`${payload.image_count || 0} 张图片`, `${payload.image_count || 0} images`) };
    if (type === 'aigc.image.failed') return { label: traceCopy('图片生成失败', 'Image generation failed'), detail: payload.error_message || '' };
    if (type === 'aigc.summary.completed') return { label: traceCopy('结果汇总完成', 'Summary completed'), detail: traceCopy(`图片 ${payload.image_count || 0} / 来源 ${payload.citation_count || 0}`, `Images ${payload.image_count || 0} / citations ${payload.citation_count || 0}`) };

    if (type === 'model.started') return { label: traceCopy(`模型 #${round || '?' } 开始`, `Model #${round || '?'} started`), detail: payload.model_preference || '' };
    if (type === 'model.completed') return { label: traceCopy(`模型 #${round || '?' } 完成`, `Model #${round || '?'} completed`), detail: traceModelEventDetail(payload) };
    if (type === 'model.failed') return { label: traceCopy('模型调用失败', 'Model call failed'), detail: payload.error_message || payload.provider || '' };
    if (type === 'tool.started') return { label: traceCopy(`调用工具：${payload.name || 'tool'}`, `Call tool: ${payload.name || 'tool'}`), detail: event.step_id || '' };
    if (type === 'tool.completed') return { label: traceCopy(`工具完成：${payload.name || 'tool'}`, `Tool completed: ${payload.name || 'tool'}`), detail: duration || event.step_id || '' };
    if (type === 'tool.failed') return { label: traceCopy(`工具失败：${payload.name || 'tool'}`, `Tool failed: ${payload.name || 'tool'}`), detail: payload.error_message || duration || event.step_id || '' };
    if (type === 'citations.collected') return { label: traceCopy('收集引用来源', 'Collected citations'), detail: traceCopy(`新增 ${payload.count || 0} / 共 ${payload.total || 0}`, `${payload.count || 0} new / ${payload.total || 0} total`) };

    return { label: event.title || type || t('trace.event'), detail: type || '' };
}

function traceModelEventDetail(payload = {}) {
    const toolCount = Array.isArray(payload.tool_calls) ? payload.tool_calls.length : 0;
    const usage = payload.usage && typeof payload.usage === 'object'
        ? Object.entries(payload.usage).map(([key, value]) => `${key}:${value}`).join(', ')
        : '';
    return [
        payload.model,
        toolCount ? traceCopy(`${toolCount} 个工具调用`, `${toolCount} tool calls`) : '',
        usage,
    ].filter(Boolean).join(' / ');
}

function tracePlanStepEventSummary(payload = {}) {
    return [
        payload.step,
        Number.isFinite(payload.image_count) ? traceCopy(`图片 ${payload.image_count}`, `images ${payload.image_count}`) : '',
        Number.isFinite(payload.citation_count) ? traceCopy(`来源 ${payload.citation_count}`, `citations ${payload.citation_count}`) : '',
        Array.isArray(payload.skills_used) && payload.skills_used.length ? traceCopy(`工具 ${payload.skills_used.length}`, `${payload.skills_used.length} tools`) : '',
    ].filter(Boolean).join(' / ');
}

function mergeTraceStatus(...statuses) {
    const normalized = statuses.map((status) => normalizeTraceStatus(status));
    if (normalized.includes('error')) return 'error';
    if (normalized.includes('partial')) return 'partial';
    if (normalized.includes('completed')) return 'completed';
    if (normalized.includes('running')) return 'running';
    return 'neutral';
}

function findTraceNode(node, id) {
    if (!node || !id) return null;
    if (node.id === id) return node;
    for (const child of node.children || []) {
        const found = findTraceNode(child, id);
        if (found) return found;
    }
    return null;
}

function flattenTraceTree(node) {
    if (!node) return [];
    return [node, ...(node.children || []).flatMap(flattenTraceTree)];
}

function defaultTraceNodeId(root) {
    const nodes = flattenTraceTree(root);
    const failed = nodes.find((node) => node.kind === 'event' && node.status === 'error');
    return (failed || root)?.id || '';
}

function renderTraceTreeNode(node, depth = 0) {
    const active = node.id === selectedTraceNodeId;
    const count = node.children?.length || node.events?.length || 0;
    const childCount = node.children?.length || 0;
    const hasChildren = childCount > 0;
    const collapsed = isTraceNodeCollapsed(node, depth);
    const statusClass = traceStatusDotClass(node.status);
    const detail = traceTreeNodeDetail(node);
    const children = collapsed ? '' : (node.children || [])
        .map((child) => renderTraceTreeNode(child, depth + 1))
        .join('');
    const toggleLabel = collapsed ? t('trace.expand') : t('trace.collapse');

    return `
        <div class="trace-tree-branch" style="--depth: ${depth}">
            <div class="trace-tree-row">
                ${hasChildren ? `
                    <button class="trace-node-toggle ${collapsed ? 'collapsed' : ''}" type="button"
                            data-trace-toggle-id="${escapeAttr(node.id)}"
                            data-trace-collapsed="${collapsed ? 'true' : 'false'}"
                            aria-label="${escapeAttr(toggleLabel)}"
                            title="${escapeAttr(toggleLabel)}">
                        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5">
                            <path d="m6 9 6 6 6-6"/>
                        </svg>
                    </button>
                ` : '<span class="trace-node-toggle-spacer"></span>'}
                <button class="trace-tree-node ${active ? 'active' : ''} ${collapsed ? 'collapsed' : ''} ${escapeAttr(node.kind)}" type="button" data-trace-node-id="${escapeAttr(node.id)}">
                    <span class="status-dot ${statusClass}"></span>
                    <span class="trace-tree-copy">
                        <strong>${escapeHtml(node.label || node.id)}</strong>
                        ${detail ? `<small title="${escapeAttr(node.detail || detail)}">${escapeHtml(detail)}</small>` : ''}
                    </span>
                    ${count ? `<span class="trace-node-count">${count}</span>` : ''}
                </button>
            </div>
            ${children ? `<div class="trace-node-children">${children}</div>` : ''}
        </div>
    `;
}

function isTraceNodeCollapsed(node, depth = 0) {
    if (!node?.children?.length) return false;
    if (expandedTraceNodeIds.has(node.id)) return false;
    if (collapsedTraceNodeIds.has(node.id)) return true;
    return traceNodeDefaultCollapsed(node, depth);
}

function traceNodeDefaultCollapsed(node, depth = 0) {
    return depth >= 2 && node.kind !== 'event';
}

function traceTreeNodeDetail(node) {
    const detail = node.detail || '';
    if (!detail) return '';
    return truncateText(detail, node.kind === 'event' ? 92 : 110);
}

function renderTraceNodeDetails(node, run) {
    if (!node) return `<div class="empty-inline">${escapeHtml(t('trace.noSelection'))}</div>`;

    if (node.kind === 'run') {
        return renderRunNodeDetails(node, run);
    }
    if (node.kind === 'plan') {
        return renderPlanNodeDetails(node, run);
    }
    if (node.kind === 'plan-step') {
        return renderPlanStepNodeDetails(node);
    }
    if (node.kind === 'model') {
        return renderModelNodeDetails(node);
    }
    if (node.kind === 'tool') {
        return renderToolNodeDetails(node);
    }
    if (node.kind === 'context-node') {
        return renderContextNodeDetails(node);
    }
    if (node.kind === 'stage') {
        return renderStageNodeDetails(node);
    }
    return renderEventNodeDetails(node);
}

function renderRunNodeDetails(node, run) {
    const tokens = Object.entries(run.tokens_used || {})
        .map(([key, value]) => `${key}: ${value}`)
        .join(' / ');
    const rows = [
        ['Run ID', run.run_id],
        ['Conversation', run.conversation_id],
        ['Agent', run.agent_id],
        ['Runtime', run.runtime],
        ['Model', run.model_used],
        ['Status', run.status],
        ['Duration', formatDuration(run.duration_ms)],
        ['Started', formatFullTime(run.started_at)],
        ['Completed', formatFullTime(run.completed_at)],
        ['Tokens', tokens],
    ];
    return `
        <div class="trace-detail-head">
            <div>
                <span class="trace-kind">${escapeHtml(t('trace.runOverview'))}</span>
                <h3>${escapeHtml(run.agent_id || 'agent')}</h3>
            </div>
            <span class="status-chip ${runStatusClass(run.status)}">${escapeHtml(run.status || '')}</span>
        </div>
        ${renderTraceDetailGrid(rows)}
        ${renderTraceTextSection(t('trace.input'), run.input)}
        ${run.output ? renderTraceTextSection(t('trace.output'), run.output) : ''}
        ${run.error_message ? renderTraceTextSection(t('trace.error'), run.error_message) : ''}
    `;
}

function renderPlanNodeDetails(node, run) {
    const steps = node.meta?.steps || (node.children || [])
        .filter((child) => child.kind === 'plan-step')
        .map((child, index) => ({ id: child.meta?.stepId || child.id, title: child.label, description: child.detail, index: index + 1 }));
    const createdEvent = node.events.find((event) => event.type === 'aigc.plan.created');
    const completedEvent = [...node.events].reverse().find((event) => event.type === 'aigc.plan.completed' || event.type === 'aigc.plan.failed');
    const rows = [
        ['Node', node.id],
        ['Type', t('trace.plan')],
        ['Status', node.status],
        ['Steps', String(steps.length)],
        ['Events', String(node.events.length)],
        ['Duration', formatDuration(traceNodeDuration(node))],
    ];

    const modeIds = createdEvent?.payload?.mode_ids || [];
    const inputText = [
        run?.input ? `${traceCopy('用户输入', 'User input')}:\n${run.input}` : '',
        modeIds.length ? `${traceCopy('模式', 'Modes')}: ${modeIds.join(', ')}` : '',
    ].filter(Boolean).join('\n\n');
    const result = completedEvent
        ? tracePlanResultText(completedEvent.payload || {})
        : traceCopy('计划仍在执行或尚未写入完成事件。', 'The plan is still running or has no completion event yet.');

    return `
        ${renderTraceDetailHead(t('trace.plan'), node.label, node.detail, node.status)}
        ${renderTraceDetailGrid(rows)}
        ${renderTraceTextSection(t('trace.input'), inputText)}
        ${renderTraceListSection(t('trace.output'), steps.map((step, index) => ({
            title: `${step.index || index + 1}. ${tracePlanStepTitle(step.id, step)}`,
            detail: tracePlanStepDetail(step.id, step),
        })))}
        ${renderTraceTextSection(t('trace.result'), result)}
        ${renderTraceChildList(node)}
        ${renderTraceEventTimeline(node.events)}
    `;
}

function renderPlanStepNodeDetails(node) {
    const step = node.meta?.step || {};
    const completedEvent = [...node.events].reverse().find((event) => event.type === 'aigc.plan.step.completed' || event.type === 'aigc.plan.step.failed');
    const rows = [
        ['Node', node.id],
        ['Type', t('trace.planStep')],
        ['Step ID', node.meta?.stepId],
        ['Status', node.status],
        ['Events', String(node.events.length)],
        ['Children', String(node.children.length)],
        ['Duration', formatDuration(traceNodeDuration(node))],
    ];
    const outputItems = (node.children || [])
        .filter((child) => child.kind !== 'event')
        .map((child) => ({ title: child.label, detail: child.detail || child.status }));
    const result = completedEvent
        ? tracePlanStepResultText(completedEvent.payload || {})
        : traceCopy('等待步骤结果。', 'Waiting for the step result.');

    return `
        ${renderTraceDetailHead(t('trace.planStep'), node.label, node.detail, node.status)}
        ${renderTraceDetailGrid(rows)}
        ${renderTraceTextSection(t('trace.input'), step.description || node.detail || node.meta?.stepId)}
        ${renderTraceListSection(t('trace.output'), outputItems)}
        ${renderTraceTextSection(t('trace.result'), result)}
        ${renderTraceEventTimeline(node.events)}
    `;
}

function renderModelNodeDetails(node) {
    const startedEvent = node.events.find((event) => event.type.endsWith('.started'));
    const finishedEvent = [...node.events].reverse().find((event) => event.type.endsWith('.completed') || event.type.endsWith('.failed'));
    const startPayload = startedEvent?.payload || {};
    const finishPayload = finishedEvent?.payload || {};
    const toolCalls = Array.isArray(finishPayload.tool_calls) ? finishPayload.tool_calls : [];
    const rows = [
        ['Node', node.id],
        ['Type', t('trace.modelCall')],
        ['Round', node.meta?.round],
        ['Scope', node.meta?.scope],
        ['Model', finishPayload.model || startPayload.model_preference],
        ['Status', node.status],
        ['Duration', formatDuration(traceNodeDuration(node))],
        ['Tool Calls', String(toolCalls.length)],
    ];
    const input = {
        message_count: startPayload.message_count,
        tools_count: startPayload.tools_count,
        model_preference: startPayload.model_preference,
        streaming: startPayload.streaming,
    };
    const result = {
        model: finishPayload.model,
        usage: finishPayload.usage,
        tool_calls: toolCalls,
        error_message: finishPayload.error_message,
    };

    return `
        ${renderTraceDetailHead(t('trace.modelCall'), node.label, node.detail, node.status)}
        ${renderTraceDetailGrid(rows)}
        ${renderTraceJsonSection(t('trace.input'), compactObject(input))}
        ${startPayload.final_model_request ? renderFinalModelRequest(startPayload.final_model_request) : ''}
        ${finishPayload.content_preview ? renderTraceTextSection(t('trace.output'), finishPayload.content_preview) : ''}
        ${renderTraceJsonSection(t('trace.result'), compactObject(result))}
        ${renderTraceChildList(node)}
        ${renderTraceEventTimeline(node.events)}
    `;
}

function renderToolNodeDetails(node) {
    const startedEvent = node.events.find((event) => event.type === 'tool.started');
    const finishedEvent = [...node.events].reverse().find((event) => event.type === 'tool.completed' || event.type === 'tool.failed');
    const citationEvents = node.events.filter((event) => event.type.startsWith('citations.'));
    const startPayload = startedEvent?.payload || {};
    const finishPayload = finishedEvent?.payload || {};
    const rows = [
        ['Node', node.id],
        ['Type', t('trace.toolCall')],
        ['Tool', node.meta?.toolName || startPayload.name || finishPayload.name],
        ['Step ID', node.meta?.stepId],
        ['Status', node.status],
        ['Duration', formatDuration(traceNodeDuration(node))],
        ['Citation Events', citationEvents.length ? String(citationEvents.length) : ''],
    ];
    const result = {
        status: finishedEvent?.status,
        result_preview: finishPayload.result_preview,
        citations: citationEvents.map((event) => event.payload),
    };

    return `
        ${renderTraceDetailHead(t('trace.toolCall'), node.label, node.detail, node.status)}
        ${renderTraceDetailGrid(rows)}
        ${renderTraceJsonSection(t('trace.input'), startPayload.arguments || finishPayload.arguments)}
        ${finishPayload.result_preview ? renderTraceTextSection(t('trace.output'), finishPayload.result_preview) : ''}
        ${renderTraceJsonSection(t('trace.result'), compactObject(result))}
        ${renderTraceEventTimeline(node.events)}
    `;
}

function renderContextNodeDetails(node) {
    const contextNode = node.meta?.contextNode || {};
    const rows = [
        ['Node', node.id],
        ['Type', contextNode.type || 'context'],
        ['Injected', contextNode.injected === false ? 'false' : 'true'],
        ['Persistent', contextNode.persistent == null ? '' : String(Boolean(contextNode.persistent))],
        ['Records', contextNode.record_count == null ? '' : String(contextNode.record_count)],
        ['Messages', contextNode.message_count == null ? '' : String(contextNode.message_count)],
        ['Blocks', contextNode.block_count == null ? '' : String(contextNode.block_count)],
        ['Tools', contextNode.tools_count == null ? '' : String(contextNode.tools_count)],
        ['Token estimate', contextNode.token_estimate == null ? '' : String(contextNode.token_estimate)],
    ];
    const records = Array.isArray(contextNode.records) ? contextNode.records : [];
    const recordGroups = Array.isArray(contextNode.record_groups) ? contextNode.record_groups : [];
    const summaryGroups = Array.isArray(contextNode.summary_groups) ? contextNode.summary_groups : [];
    const messages = Array.isArray(contextNode.messages) ? contextNode.messages : [];
    const toolNames = Array.isArray(contextNode.tool_names) ? contextNode.tool_names : [];

    return `
        ${renderTraceDetailHead(traceCopy('上下文节点', 'Context Node'), node.label, node.detail, node.status)}
        ${renderTraceDetailGrid(rows)}
        ${contextNode.content ? renderTraceDisclosureSection(traceCopy('完整内容', 'Full Content'), contextNode.content, { pre: true }) : ''}
        ${summaryGroups.length ? renderTraceSummaryGroups(summaryGroups) : (contextNode.summary ? renderTraceTextSection(traceCopy('摘要', 'Summary'), contextNode.summary) : '')}
        ${contextNode.preview ? renderTraceTextSection(traceCopy('预览', 'Preview'), contextNode.preview) : ''}
        ${recordGroups.length ? renderTraceMemoryRecordGroups(recordGroups) : (records.length ? renderTraceMemoryRecordList(records) : '')}
        ${messages.length ? renderTraceJsonSection(traceCopy('对话消息', 'Conversation Messages'), messages.map((message) => compactObject(message))) : ''}
        ${toolNames.length ? renderTraceListSection(traceCopy('工具', 'Tools'), toolNames.map((name) => ({ title: name, detail: '' }))) : ''}
        ${contextNode.role ? renderTraceJsonSection(traceCopy('角色', 'Role'), compactObject(contextNode.role)) : ''}
        ${renderTraceChildList(node)}
    `;
}

function renderTraceSummaryGroups(groups = []) {
    return renderTraceListSection(
        traceCopy('短期摘要日期块', 'Short-term Summary by Date'),
        groups.map((group) => ({
            title: group.date || traceCopy('未标日期', 'Undated'),
            detail: group.summary || '',
        })),
    );
}

function renderTraceMemoryRecordGroups(groups = []) {
    return renderTraceListSection(
        traceCopy('按日期收纳的记忆', 'Memory by Date'),
        groups.map((group) => {
            const records = Array.isArray(group.records) ? group.records : [];
            return {
                title: `${group.date || traceCopy('未标日期', 'Undated')} · ${records.length || group.record_count || 0}`,
                detail: records.map((record) => [
                    `${record.kind || 'memory'} · ${record.status || 'active'} · ${shortDebugId(record.id || '')}`,
                    record.content || '',
                    record.source ? `${traceCopy('来源', 'Source')}: ${record.source}` : '',
                    record.confidence != null ? `${traceCopy('置信度', 'Confidence')}: ${record.confidence}` : '',
                    record.updated_at ? `${traceCopy('更新', 'Updated')}: ${formatFullTime(record.updated_at)}` : '',
                ].filter(Boolean).join('\n')).join('\n\n'),
            };
        }),
    );
}

function renderTraceMemoryRecordList(records = []) {
    return renderTraceListSection(
        traceCopy('记忆记录', 'Memory Records'),
        records.map((record) => ({
            title: `${record.kind || 'memory'} · ${record.status || 'active'} · ${shortDebugId(record.id || '')}`,
            detail: [
                record.content || '',
                record.source ? `${traceCopy('来源', 'Source')}: ${record.source}` : '',
                record.confidence != null ? `${traceCopy('置信度', 'Confidence')}: ${record.confidence}` : '',
                record.last_used_at ? `${traceCopy('上次注入', 'Last injected')}: ${formatFullTime(record.last_used_at)}` : '',
            ].filter(Boolean).join('\n'),
        })),
    );
}

function renderStageNodeDetails(node) {
    const rows = [
        ['Node', node.id],
        ['Type', t('trace.stage')],
        ['Status', node.status],
        ['Events', String(node.events.length)],
        ['Children', String(node.children.length)],
        ['Duration', formatDuration(traceNodeDuration(node))],
    ];
    const contextEvent = node.meta?.stageType === 'context'
        ? node.events.find((event) => event.type === 'context.built')
        : null;
    const memoryEvent = node.meta?.stageType === 'context'
        ? node.events.find((event) => event.type === 'memory.loaded')
        : null;
    const contextSummary = contextEvent ? compactObject({
        role_id: contextEvent.payload?.role_id,
        role_name: contextEvent.payload?.role_name,
        message_count: contextEvent.payload?.message_count,
        tools_count: contextEvent.payload?.tools_count,
        tool_names: contextEvent.payload?.tool_names,
        mode_ids: contextEvent.payload?.mode_ids,
        context_block_count: contextEvent.payload?.context_block_count,
        persona_count: memoryEvent?.payload?.persona_count,
        long_term_count: memoryEvent?.payload?.long_term_count,
    }) : null;

    return `
        ${renderTraceDetailHead(t('trace.stage'), node.label, node.detail, node.status)}
        ${renderTraceDetailGrid(rows)}
        ${contextSummary ? renderTraceJsonSection(t('trace.output'), contextSummary) : ''}
        ${contextEvent?.payload?.prompt_sources ? renderPromptSources(contextEvent.payload.prompt_sources) : ''}
        ${contextEvent?.payload?.final_model_request ? renderFinalModelRequest(contextEvent.payload.final_model_request) : ''}
        ${contextEvent?.payload?.context_nodes ? renderTraceDisclosureSection('Context Nodes', JSON.stringify(contextEvent.payload.context_nodes.map((item) => compactObject(item)), null, 2), { pre: true }) : ''}
        ${contextEvent?.payload?.system_prompt ? renderTraceDisclosureSection('System Prompt', contextEvent.payload.system_prompt, { pre: true }) : ''}
        ${renderTraceChildList(node)}
        ${renderTraceEventTimeline(node.events)}
    `;
}

function renderEventNodeDetails(node) {
    const event = node.event || {};
    const display = traceEventDisplay(event);
    const payload = summarizePayload(event.payload);
    const rows = [
        ['Event ID', event.id],
        ['Step ID', event.step_id],
        ['Run ID', event.run_id],
        ['Type', event.type],
        ['Status', event.status],
        ['Duration', Number.isInteger(event.duration_ms) ? `${event.duration_ms}ms` : ''],
        ['Created', formatFullTime(event.created_at)],
    ];
    return `
        <div class="trace-detail-head">
            <div>
                <span class="trace-kind">${escapeHtml(t('trace.event'))}</span>
                <h3>${escapeHtml(display.label || event.title || event.type || '')}</h3>
                ${event.type ? `<p>${escapeHtml(event.type)}</p>` : ''}
            </div>
            <span class="status-chip ${traceStatusChipClass(node.status)}">${escapeHtml(event.status || '')}</span>
        </div>
        ${renderTraceDetailGrid(rows)}
        <section class="trace-detail-section">
            <h4>${escapeHtml(t('trace.payload'))}</h4>
            <pre class="trace-detail-pre">${escapeHtml(payload || t('trace.emptyPayload'))}</pre>
        </section>
    `;
}

function renderTraceDetailHead(kind, title, detail, status) {
    return `
        <div class="trace-detail-head">
            <div>
                <span class="trace-kind">${escapeHtml(kind || '')}</span>
                <h3>${escapeHtml(title || '')}</h3>
                ${detail ? `<p>${escapeHtml(detail)}</p>` : ''}
            </div>
            <span class="status-chip ${traceStatusChipClass(status)}">${escapeHtml(status || '')}</span>
        </div>
    `;
}

function renderTraceListSection(title, items = []) {
    const normalized = (items || []).filter((item) => item && (item.title || item.detail));
    if (!normalized.length) return '';
    const rows = normalized.map((item) => `
        <li>
            <span>${escapeHtml(item.title || '')}</span>
            ${item.detail ? `<small>${escapeHtml(item.detail)}</small>` : ''}
        </li>
    `).join('');
    return `
        <section class="trace-detail-section">
            <h4>${escapeHtml(title)}</h4>
            <ol class="trace-detail-list">${rows}</ol>
        </section>
    `;
}

function renderTraceJsonSection(title, value) {
    const compact = compactObject(value);
    if (!compact || (typeof compact === 'object' && !Object.keys(compact).length)) return '';
    const text = typeof compact === 'string' ? compact : JSON.stringify(compact, null, 2);
    return `
        <section class="trace-detail-section">
            <h4>${escapeHtml(title)}</h4>
            <pre class="trace-detail-pre">${escapeHtml(text)}</pre>
        </section>
    `;
}

function renderTraceDisclosureSection(title, value, options = {}) {
    if (!value) return '';
    const text = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
    const body = options.pre
        ? `<pre class="trace-detail-pre">${escapeHtml(text)}</pre>`
        : `<div class="trace-detail-text">${escapeHtml(text)}</div>`;
    return `
        <details class="trace-detail-disclosure">
            <summary>${escapeHtml(title)}</summary>
            ${body}
        </details>
    `;
}

function renderPromptSources(sources = []) {
    const normalized = Array.isArray(sources) ? sources.filter((source) => source?.content) : [];
    if (!normalized.length) return '';
    const items = normalized.map((source, index) => {
        const label = source.label || source.id || `${traceCopy('片段', 'Part')} ${index + 1}`;
        const meta = [
            source.id ? `id=${source.id}` : '',
            source.priority != null ? `priority=${source.priority}` : '',
        ].filter(Boolean).join(' / ');
        return `
            <details class="trace-detail-disclosure nested">
                <summary>
                    <span>${escapeHtml(label)}</span>
                    ${meta ? `<small>${escapeHtml(meta)}</small>` : ''}
                </summary>
                <pre class="trace-detail-pre">${escapeHtml(source.content || '')}</pre>
            </details>
        `;
    }).join('');
    return `
        <section class="trace-detail-section">
            <h4>${escapeHtml(traceCopy('Prompt 分段来源', 'Prompt Sources'))}</h4>
            <div class="trace-disclosure-stack">${items}</div>
        </section>
    `;
}

function renderFinalModelRequest(request = {}) {
    if (!request || typeof request !== 'object') return '';
    const messages = Array.isArray(request.messages) ? request.messages : [];
    const tools = Array.isArray(request.tools) ? request.tools : [];
    const summary = compactObject({
        workflow: request.workflow,
        model_preference: request.model_preference,
        temperature: request.temperature,
        tool_choice: request.tool_choice,
        message_count: messages.length,
        tools_count: tools.length,
    });
    const messageBlocks = messages.map((message, index) => `
        <details class="trace-detail-disclosure nested">
            <summary>
                <span>${escapeHtml(`${index + 1}. ${message.role || 'message'}`)}</span>
                ${message.tool_call_id ? `<small>${escapeHtml(message.tool_call_id)}</small>` : ''}
            </summary>
            <pre class="trace-detail-pre">${escapeHtml(typeof message.content === 'string' ? message.content : JSON.stringify(message.content, null, 2))}</pre>
            ${message.tool_calls ? `<pre class="trace-detail-pre">${escapeHtml(JSON.stringify(message.tool_calls, null, 2))}</pre>` : ''}
        </details>
    `).join('');
    const toolBlocks = tools.map((tool, index) => {
        const name = tool.name || tool.function?.name || `${traceCopy('工具', 'Tool')} ${index + 1}`;
        return `
            <details class="trace-detail-disclosure nested">
                <summary><span>${escapeHtml(name)}</span></summary>
                <pre class="trace-detail-pre">${escapeHtml(JSON.stringify(tool, null, 2))}</pre>
            </details>
        `;
    }).join('');
    return `
        <section class="trace-detail-section">
            <h4>${escapeHtml(traceCopy('最终模型请求', 'Final Model Request'))}</h4>
            ${renderTraceJsonSection(traceCopy('请求摘要', 'Request Summary'), summary)}
            <div class="trace-disclosure-stack">
                ${messageBlocks ? `
                    <details class="trace-detail-disclosure" open>
                        <summary>${escapeHtml(traceCopy('Messages', 'Messages'))}</summary>
                        ${messageBlocks}
                    </details>
                ` : ''}
                ${toolBlocks ? `
                    <details class="trace-detail-disclosure">
                        <summary>${escapeHtml(traceCopy('Tools', 'Tools'))}</summary>
                        ${toolBlocks}
                    </details>
                ` : ''}
            </div>
        </section>
    `;
}

function renderTraceChildList(node) {
    const children = (node.children || []).filter((child) => child.kind !== 'event');
    return renderTraceListSection(
        t('trace.childNodes'),
        children.map((child) => ({
            title: child.label || child.id,
            detail: [child.detail, child.status].filter(Boolean).join(' / '),
        })),
    );
}

function renderTraceEventTimeline(events = []) {
    if (!events.length) return '';
    const rows = events.map((event) => {
        const display = traceEventDisplay(event);
        return `
            <li>
                <span>${escapeHtml(display.label || event.type || '')}</span>
                ${display.detail ? `<small>${escapeHtml(truncateText(display.detail, 180))}</small>` : ''}
                ${event.id ? `<code title="${escapeAttr(event.id)}">event:${escapeHtml(shortDebugId(event.id))}</code>` : ''}
                ${event.step_id ? `<code title="${escapeAttr(event.step_id)}">step:${escapeHtml(shortDebugId(event.step_id))}</code>` : ''}
            </li>
        `;
    }).join('');
    return `
        <section class="trace-detail-section">
            <h4>${escapeHtml(t('trace.timeline'))}</h4>
            <ol class="trace-detail-events">${rows}</ol>
        </section>
    `;
}

function compactObject(value) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return value;
    const compact = {};
    Object.entries(value).forEach(([key, item]) => {
        if (item === undefined || item === null || item === '') return;
        if (Array.isArray(item) && item.length === 0) return;
        if (typeof item === 'object' && !Array.isArray(item) && Object.keys(item).length === 0) return;
        compact[key] = item;
    });
    return compact;
}

function tracePlanResultText(payload = {}) {
    return [
        payload.steps?.length ? traceCopy(`完成步骤：${payload.steps.join(', ')}`, `Completed steps: ${payload.steps.join(', ')}`) : '',
        Number.isFinite(payload.citation_count) ? traceCopy(`引用来源：${payload.citation_count}`, `Citations: ${payload.citation_count}`) : '',
        Number.isFinite(payload.image_count) ? traceCopy(`图片数量：${payload.image_count}`, `Images: ${payload.image_count}`) : '',
        payload.error_message || '',
    ].filter(Boolean).join('\n') || summarizePayload(payload);
}

function tracePlanStepResultText(payload = {}) {
    return [
        payload.brief_preview ? `${traceCopy('检索摘要', 'Brief')}:\n${payload.brief_preview}` : '',
        Array.isArray(payload.skills_used) && payload.skills_used.length ? `${traceCopy('使用工具', 'Tools')}: ${payload.skills_used.join(', ')}` : '',
        Number.isFinite(payload.image_count) ? traceCopy(`图片数量：${payload.image_count}`, `Images: ${payload.image_count}`) : '',
        Number.isFinite(payload.citation_count) ? traceCopy(`引用来源：${payload.citation_count}`, `Citations: ${payload.citation_count}`) : '',
        payload.model ? `${traceCopy('模型', 'Model')}: ${payload.model}` : '',
        payload.error_message || '',
    ].filter(Boolean).join('\n') || summarizePayload(payload);
}

function traceNodeDuration(node) {
    if (Number.isInteger(node.duration_ms)) return node.duration_ms;
    const timedEvent = [...(node.events || [])].reverse().find((event) => Number.isInteger(event.duration_ms));
    return timedEvent?.duration_ms;
}

function renderTraceDetailGrid(rows) {
    return `
        <dl class="trace-detail-grid">
            ${rows.filter(([, value]) => value !== undefined && value !== null && value !== '').map(([key, value]) => `
                <div>
                    <dt>${escapeHtml(key)}</dt>
                    <dd>${renderDebugValue(value)}</dd>
                </div>
            `).join('')}
        </dl>
    `;
}

function renderTraceTextSection(title, value) {
    if (!value) return '';
    return `
        <section class="trace-detail-section">
            <h4>${escapeHtml(title)}</h4>
            <div class="trace-detail-text">${escapeHtml(value)}</div>
        </section>
    `;
}

function renderDebugValue(value) {
    const text = String(value);
    if (/^(run_|evt_|step_|call_)/.test(text) || text.length > 42) {
        return `<code title="${escapeAttr(text)}">${escapeHtml(text)}</code>`;
    }
    return escapeHtml(text);
}

function traceStatusDotClass(status) {
    const normalized = normalizeTraceStatus(status);
    if (normalized === 'completed') return 'ok';
    if (normalized === 'running') return 'warn';
    if (normalized === 'partial') return 'warn';
    if (normalized === 'cancelled') return '';
    if (normalized === 'error') return 'error';
    return '';
}

function traceStatusChipClass(status) {
    const normalized = normalizeTraceStatus(status);
    if (normalized === 'completed') return 'ok';
    if (normalized === 'error') return 'error';
    if (normalized === 'cancelled') return 'neutral';
    if (normalized === 'running' || normalized === 'partial') return 'warn';
    return 'neutral';
}

function renderSettings() {
    if (!settingsGrid) return;

    const providerCards = PROVIDERS.map((provider) => {
        const configured = isProviderConfigured(provider);
        const status = providerSummaryStatus(provider, configured);
        const models = readModels(provider.key);
        const selected = settings['llm.default_provider'] === provider.key;
        return `
            <article class="data-card compact-card">
                <div class="card-topline">
                    <span class="status-dot ${status.tone}"></span>
                    <span class="status-chip ${status.tone}">${escapeHtml(status.text)}</span>
                    ${selected ? `<span class="status-chip neutral">${escapeHtml(t('settings.default'))}</span>` : ''}
                </div>
                <h2>${escapeHtml(provider.label)}</h2>
                <p>${escapeHtml(models.length ? models.slice(0, 3).join(', ') : t('settings.noModels'))}</p>
                <div class="provider-card-actions">
                    <button class="btn-secondary" type="button" data-test-provider="${escapeAttr(provider.key)}" ${configured ? '' : 'disabled'}>
                        ${escapeHtml(t('actions.test'))}
                    </button>
                    <span class="provider-test-result" id="provider-test-${escapeAttr(provider.key)}"></span>
                </div>
            </article>
        `;
    }).join('');

    const agentOk = health?.agent === 'ok';
    settingsGrid.innerHTML = `
        <article class="data-card compact-card">
            <div class="card-topline">
                <span class="status-dot ${agentOk ? 'ok' : 'warn'}"></span>
                <span class="status-chip ${agentOk ? 'ok' : 'warn'}">${agentOk ? 'ok' : escapeHtml(t('health.unavailable'))}</span>
            </div>
            <h2>${escapeHtml(t('settings.serviceTitle'))}</h2>
            <p>${escapeHtml(health ? `Gateway: ${health.status || '-'} / Agent: ${health.agent || '-'}` : t('settings.serviceChecking'))}</p>
        </article>
        <article class="data-card compact-card action-card">
            <h2>${escapeHtml(t('settings.modelKeys'))}</h2>
            <p>${escapeHtml(settings['llm.default_provider'] || t('settings.noDefaultProvider'))}</p>
            <a class="btn-secondary link-button" href="/admin.html">${escapeHtml(t('actions.openConfig'))}</a>
        </article>
        ${providerCards}
    `;
}

function providerSummaryStatus(provider, configured) {
    if (!configured) return { tone: 'warn', text: t('settings.missing') };
    const status = settings[`llm.${provider.key}.validation_status`];
    if (status === 'verified') return { tone: 'ok', text: t('settings.verified') };
    if (status === 'error') return { tone: 'error', text: t('settings.error') };
    if (status === 'pending') return { tone: 'warn', text: t('settings.pending') };
    return { tone: 'ok', text: t('settings.configured') };
}

async function testProvider(providerKey, button) {
    const resultEl = document.getElementById(`provider-test-${providerKey}`);
    if (!resultEl) return;

    const original = button.textContent;
    button.disabled = true;
    button.textContent = t('actions.testing');
    resultEl.textContent = '';
    resultEl.className = 'provider-test-result';

    try {
        const result = await apiCall('POST', '/api/admin/validate-provider', { provider: providerKey });
        const item = result.validation?.[providerKey];
        if (item) {
            settings[`llm.${providerKey}.validation_status`] = item.status || (item.success ? 'verified' : 'error');
            settings[`llm.${providerKey}.validation_message`] = item.message || '';
        }
        renderSettings();
        const nextResultEl = document.getElementById(`provider-test-${providerKey}`);
        if (nextResultEl) {
            nextResultEl.textContent = item?.success ? t('settings.connected') : t('settings.failed');
            nextResultEl.title = item?.message || '';
            nextResultEl.classList.toggle('ok', Boolean(item?.success));
            nextResultEl.classList.toggle('error', !item?.success);
        }
    } catch (err) {
        resultEl.textContent = t('settings.failed');
        resultEl.title = err.message;
        resultEl.classList.add('error');
    } finally {
        button.disabled = false;
        button.textContent = original;
    }
}

function renderModelSelect() {
    modelSelect.innerHTML = '';
    let defaultModelDisplay = '';

    for (const provider of PROVIDERS) {
        if (!isProviderConfigured(provider)) continue;
        let models = readModels(provider.key);
        if (!models.length) {
            const single = settings[`llm.${provider.key}.model`];
            if (single) models = [single];
        }
        if (!models.length) continue;

        if (settings['llm.default_provider'] === provider.key) {
            defaultModelDisplay = `${provider.label} / ${models[0]}`;
        }

        const group = document.createElement('optgroup');
        group.label = provider.label;
        models.forEach((model) => {
            const opt = document.createElement('option');
            opt.value = `${provider.key}:${model}`;
            opt.textContent = model;
            group.appendChild(opt);
        });
        modelSelect.appendChild(group);
    }

    const defaultOpt = document.createElement('option');
    defaultOpt.value = '';
    defaultOpt.textContent = defaultModelDisplay ? `${t('sidebar.defaultModel')} (${defaultModelDisplay})` : t('sidebar.defaultModel');
    modelSelect.insertBefore(defaultOpt, modelSelect.firstChild);
    modelSelect.value = '';

    defaultModelText = defaultModelDisplay;
    currentModelEl.textContent = defaultModelDisplay || '';
}

function isProviderConfigured(provider) {
    const value = settings[provider.checkKey] || '';
    return Boolean(value);
}

function readModels(providerKey) {
    const raw = settings[`llm.${providerKey}.models`];
    if (!raw) return [];
    try {
        const parsed = JSON.parse(raw);
        return Array.isArray(parsed) ? parsed : [];
    } catch {
        return [];
    }
}

function showWelcome() {
    const currentAgent = getCurrentAgent();
    const isImageAgent = currentAgentId === 'image_generation_v1';
    const title = currentAgent?.name || 'Super Chat';
    const agentActions = currentAgentQuickActions(currentAgent);
    const quickActions = agentActions.length
        ? agentActions
        : isImageAgent
        ? [
            {
                label: t('welcome.imageCreate'),
                query: '/generate ',
            },
            {
                label: t('welcome.imagePolish'),
                query: '/refine 一张有电影感的产品海报',
            },
            {
                label: t('welcome.imageReference'),
                query: '/reference 我会上传参考素材，请根据素材生成一张新的图片。',
            },
        ]
        : [];
    const quickActionsHtml = quickActions.length
        ? `
            <div class="quick-actions">
                ${quickActions.map((item) => `
                    <button class="quick-action" type="button"
                            data-query="${escapeAttr(item.query)}"
                            ${item.modeId ? `data-quick-mode="${escapeAttr(item.modeId)}"` : ''}
                            ${item.autoSend ? 'data-quick-send="true"' : ''}>
                        <span>${escapeHtml(item.label)}</span>
                    </button>
                `).join('')}
            </div>
        `
        : '';
    const promptHtml = currentAgentId === SUPER_CHAT_AGENT_ID
        ? `<p class="welcome-sub">${escapeHtml(t('welcome.prompt'))}</p>`
        : '';
    messagesContainer.innerHTML = `
        <div class="welcome-screen">
            <div class="welcome-icon">
                <svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.5">
                    <path d="M12 3 3 8l9 5 9-5-9-5Z"/>
                    <path d="m3 14 9 5 9-5"/>
                    <path d="m3 11 9 5 9-5"/>
                </svg>
            </div>
            <h2>${escapeHtml(title)}</h2>
            ${promptHtml}
            ${quickActionsHtml}
        </div>
    `;
    updateChatHistoryControls();
}

function refreshWelcomeIfEmpty() {
    if (!currentConversationId || messagesContainer.querySelector('.welcome-screen')) {
        showWelcome();
    }
}

function isMessagePaneEmpty() {
    return !messagesContainer.children.length || Boolean(messagesContainer.querySelector('.welcome-screen'));
}

function ensureCurrentConversationVisible() {
    if (!currentConversationId) {
        if (isMessagePaneEmpty()) showWelcome();
        return;
    }
    if (isMessagePaneEmpty()) {
        renderConversationMessages(currentConversationId);
    }
}

async function renderConversationMessages(id, options = {}) {
    followUpRenderToken += 1;
    const cachedRender = conversationRenderCache.get(id) || null;
    const restoredFromCache = restoreConversationRenderCache(id);
    if (!restoredFromCache) {
        showConversationSwitchLoading();
    }
    try {
        const data = await loadConversation(id);
        if (currentConversationId !== id) return;
        if (activeRunWatcher && activeRunWatcher.conversationId !== id) {
            stopActiveRunWatcher();
        }
        const messages = data.messages || [];
        const signature = conversationMessagesSignature(messages);
        if (data.conversation) {
            const index = conversations.findIndex((conv) => conv.id === data.conversation.id);
            if (index >= 0) conversations[index] = data.conversation;
            applyConversationAgent(data.conversation);
        }
        syncQuestionHistoryFromMessages(messages);
        if (!messages.length) {
            forgetConversationRender(id);
            showWelcome();
        } else if (restoredFromCache && cachedRender?.signature === signature) {
            rememberConversationRender(id, data, cachedRender.html, signature);
        } else {
            const html = renderConversationMessageListHtml(messages);
            messagesContainer.innerHTML = html;
            rememberConversationRender(id, data, html, signature);
            scrollToBottom();
        }
        if (options.watchActiveRuns !== false) {
            watchActiveRunForConversation(id, messages);
        }
        pollLatestAssistantFollowUps(messages, id);
    } catch (err) {
        if (!restoredFromCache) {
            messagesContainer.innerHTML = '';
            appendMessage('assistant', t('chat.loadConversationFailed', { message: err.message }), [], '', 'error');
        }
    }

    updateChatHistoryControls();
    updateTopbar();
    focusMessageInput();
}

function restoreConversationRenderCache(id) {
    const cached = conversationRenderCache.get(id);
    if (!cached) return false;
    conversationRenderCache.delete(id);
    conversationRenderCache.set(id, cached);
    if (currentConversationId !== id) return false;

    messagesContainer.innerHTML = cached.html || '';
    if (cached.conversation) {
        const index = conversations.findIndex((conv) => conv.id === cached.conversation.id);
        if (index >= 0) conversations[index] = cached.conversation;
        applyConversationAgent(cached.conversation);
    }
    syncQuestionHistoryFromMessages(cached.messages || []);
    scrollToBottom();
    updateChatHistoryControls();
    return true;
}

function rememberConversationRender(id, data = {}, html = '', signature = '') {
    if (!id || !html) return;
    conversationRenderCache.delete(id);
    conversationRenderCache.set(id, {
        conversation: data.conversation || null,
        messages: data.messages || [],
        html,
        signature: signature || conversationMessagesSignature(data.messages || []),
        cachedAt: Date.now(),
    });
    while (conversationRenderCache.size > CONVERSATION_RENDER_CACHE_LIMIT) {
        const oldestKey = conversationRenderCache.keys().next().value;
        conversationRenderCache.delete(oldestKey);
    }
}

function forgetConversationRender(id) {
    if (!id) return;
    conversationRenderCache.delete(id);
}

function parseFollowUps(value) {
    if (!value) return [];
    if (Array.isArray(value)) return normalizeFollowUpQuestions(value);
    try {
        return normalizeFollowUpQuestions(JSON.parse(value));
    } catch {
        return [];
    }
}

function normalizeFollowUpQuestions(questions = []) {
    if (!Array.isArray(questions)) return [];
    const seen = new Set();
    const result = [];

    questions.forEach((item) => {
        const question = String(item || '').replace(/\s+/g, ' ').trim();
        if (!question) return;
        const key = question.toLowerCase();
        if (seen.has(key)) return;
        seen.add(key);
        result.push(question);
    });

    return result.slice(0, FOLLOW_UP_QUESTION_COUNT);
}

function renderConversationMessageListHtml(messages = []) {
    const savedRuns = [];
    let latestUserQuery = '';
    const lastMessageIndex = messages.length - 1;
    const html = messages.map((msg, index) => {
        if (msg.role === 'user') {
            latestUserQuery = String(msg.content || '').trim();
        }
        const skillsUsed = parseSkills(msg.skills_used);
        const citations = parseCitations(msg.citations);
        const artifacts = parseArtifacts(msg.artifacts);
        const savedTraceEvents = parseTraceEvents(msg.trace_summary || msg.trace_events);
        const savedRun = runRecordFromMessage(msg, skillsUsed, savedTraceEvents);
        if (savedRun) savedRuns.push(savedRun);
        const traceRun = savedRun;
        const messageHtml = renderMessageHtml(
            msg.role,
            msg.content,
            skillsUsed,
            msg.model_used || traceRun?.model_used || '',
            msg.error_type || '',
            savedTraceEvents.length ? savedTraceEvents : (traceRun?.events || []),
            msg.run_id || traceRun?.run_id || '',
            msg.runtime || traceRun?.runtime || '',
            citations,
            artifacts,
            null,
            msg.role === 'assistant' ? latestUserQuery : ''
        );
        const shouldShowFollowUps = msg.role === 'assistant'
            && index === lastMessageIndex
            && !msg.error_type;
        return shouldShowFollowUps
            ? `${messageHtml}${renderFollowUpMessages(parseFollowUps(msg.follow_ups))}`
            : messageHtml;
    }).join('');
    if (savedRuns.length) mergeRuns(savedRuns);
    return html;
}

function renderProcessPanel(events = [], options = {}) {
    const items = buildProcessTimeline(events);
    if (!items.length) return '';

    const expanded = Boolean(options.expanded);
    const live = Boolean(options.live);
    const totalDuration = processTotalDuration(events);
    const title = traceCopy('执行过程', 'Process');
    const durationLabel = Number.isFinite(totalDuration)
        ? traceCopy(`总耗时 ${formatProcessDuration(totalDuration)}`, `Total ${formatProcessDuration(totalDuration)}`)
        : '';

    return `
        <details class="process-panel ${live ? 'live' : ''}" ${expanded ? 'open' : ''}>
            <summary class="process-summary">
                <span class="process-summary-title">${escapeHtml(title)}</span>
                ${durationLabel ? `<span class="process-summary-duration">${escapeHtml(durationLabel)}</span>` : ''}
                <span class="process-summary-arrow" aria-hidden="true"></span>
            </summary>
            <ol class="process-list">
                ${items.map(renderProcessTimelineItem).join('')}
            </ol>
        </details>
    `;
}

function renderProcessPanelInto(container, panelHtml = '') {
    const scrollState = captureProcessScrollState(container);
    container.innerHTML = panelHtml;
    restoreProcessScrollState(container, scrollState);
}

function captureProcessScrollState(container) {
    const list = container?.querySelector?.('.process-list');
    if (!list) return null;
    const distanceFromBottom = list.scrollHeight - list.scrollTop - list.clientHeight;
    return {
        scrollTop: list.scrollTop,
        stickToBottom: distanceFromBottom <= 24,
    };
}

function restoreProcessScrollState(container, state) {
    if (!state) return;
    const list = container?.querySelector?.('.process-list');
    if (!list) return;
    list.scrollTop = state.stickToBottom
        ? list.scrollHeight
        : Math.min(state.scrollTop, Math.max(0, list.scrollHeight - list.clientHeight));
}

function processTotalDuration(events = []) {
    if (!Array.isArray(events)) return null;
    const completed = [...events]
        .reverse()
        .find((event) => (
            (event?.type === 'run.completed' || event?.type === 'run.failed' || event?.type === 'run.cancelled')
            && Number.isFinite(event.duration_ms)
        ));
    if (completed) return completed.duration_ms;
    const workflowCompleted = [...events]
        .reverse()
        .find((event) => (
            (event?.type === 'workflow.completed' || event?.type === 'workflow.failed')
            && Number.isFinite(event.duration_ms)
        ));
    return workflowCompleted?.duration_ms ?? null;
}

function formatProcessDuration(ms) {
    if (!Number.isFinite(ms)) return '';
    if (ms < 1000) return `${ms}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)}s`;
    const minutes = Math.floor(ms / 60000);
    const seconds = Math.round((ms % 60000) / 1000);
    return seconds ? `${minutes}m ${seconds}s` : `${minutes}m`;
}

function buildProcessTimeline(events = []) {
    if (!Array.isArray(events)) return [];
    return events
        .filter(isProcessEventVisible)
        .map((event, index) => processTimelineItem(event, index))
        .filter(Boolean);
}

function isProcessEventVisible(event = {}) {
    const type = String(event.type || '');
    if (!type) return false;
    if (type === 'context.built' || type === 'memory.loaded') return true;
    if (type === 'memory.review.started' || type === 'memory.review.completed' || type === 'memory.review.failed') return true;
    if (type === 'memory.compaction.started' || type === 'memory.compaction.completed' || type === 'memory.compaction.failed' || type === 'memory.compaction.skipped') return true;
    if (type === 'memory.extracted' || type === 'memory.failed') return true;
    if (type.startsWith('run.')) return true;
    if (type.startsWith('workflow.')) return true;
    if (type.startsWith('thinking.')) return true;
    if (type.startsWith('aigc.')) return true;
    if (type.startsWith('model.')) return true;
    if (type.startsWith('tool.')) return true;
    if (type.startsWith('citations.')) return true;
    if (type.startsWith('agent.')) return true;
    if (type.startsWith('weight_loss.')) return true;
    return false;
}

function processTimelineItem(event = {}, index = 0) {
    const payload = event.payload || {};
    const display = traceEventDisplay(event);
    const status = normalizeTraceStatus(event.status);
    const duration = Number.isInteger(event.duration_ms) ? formatDuration(event.duration_ms) : '';
    return {
        id: event.id || `${event.type || 'event'}-${index}`,
        kind: processEventKind(event),
        status,
        label: display.label || event.title || event.type || t('trace.event'),
        detail: processEventDetail(event, display.detail),
        meta: [
            payload.workflow_node || payload.node || '',
            event.step_id ? `step:${shortDebugId(event.step_id)}` : '',
            duration,
        ].filter(Boolean),
        links: processEventLinks(event),
    };
}

function processEventKind(event = {}) {
    const type = String(event.type || '');
    if (type.startsWith('tool.') || type.startsWith('citations.')) return 'tool';
    if (type.startsWith('model.')) return 'model';
    if (type.startsWith('thinking.') || type.startsWith('workflow.')) return 'plan';
    if (type.startsWith('agent.')) return 'agent';
    if (type.startsWith('aigc.')) return 'media';
    if (type.startsWith('weight_loss.')) return 'agent';
    if (type.startsWith('memory.') || type === 'context.built') return 'context';
    if (type.startsWith('run.')) return 'run';
    return 'event';
}

function processEventDetail(event = {}, fallback = '') {
    const type = String(event.type || '');
    const payload = event.payload || {};
    const parts = [];

    if (type === 'thinking.plan.created') {
        if (payload.goal) parts.push(payload.goal);
        const steps = Array.isArray(payload.steps) ? payload.steps : [];
        if (steps.length) {
            parts.push(steps.map((step, index) => {
                const title = step?.title || step?.type || step?.id || traceCopy('步骤', 'step');
                return `${index + 1}. ${title}`;
            }).join(' · '));
        }
    } else if (type === 'thinking.step.started') {
        const step = payload.step && typeof payload.step === 'object' ? payload.step : {};
        if (step.description) parts.push(step.description);
        if (step.query) parts.push(`${traceCopy('检索', 'Search')}: ${step.query}`);
        if (step.task) parts.push(`${traceCopy('任务', 'Task')}: ${step.task}`);
    } else if (type === 'thinking.step.completed' || type === 'thinking.step.failed') {
        if (payload.summary) parts.push(payload.summary);
        if (payload.arguments?.query) parts.push(`${traceCopy('检索', 'Search')}: ${payload.arguments.query}`);
        if (Number.isFinite(payload.citation_count)) parts.push(traceCopy(`累计来源 ${payload.citation_count}`, `${payload.citation_count} citations so far`));
        parts.push(toolPreviewSummary(payload));
    } else if (type === 'thinking.summary.completed') {
        parts.push(traceCopy('数据和工具结果已汇总，开始生成最终回答。', 'Evidence and tool results are ready; composing the final answer.'));
        if (Number.isFinite(payload.citation_count)) parts.push(traceCopy(`来源 ${payload.citation_count}`, `${payload.citation_count} citations`));
    } else if (type === 'tool.started') {
        parts.push(toolArgumentSummary(payload));
    } else if (type === 'tool.completed' || type === 'tool.failed') {
        parts.push(toolArgumentSummary(payload));
        parts.push(toolPreviewSummary(payload));
    } else if (type === 'model.started') {
        const round = payload.round ? `${traceCopy('轮次', 'Round')} ${payload.round}` : '';
        const tools = Number.isFinite(payload.tools_count) ? traceCopy(`可用工具 ${payload.tools_count}`, `${payload.tools_count} tools`) : '';
        parts.push([round, tools, payload.streaming ? traceCopy('流式输出', 'streaming') : ''].filter(Boolean).join(' / '));
    } else if (type === 'model.completed') {
        const toolCount = Array.isArray(payload.tool_calls) ? payload.tool_calls.length : 0;
        parts.push([
            payload.model || '',
            toolCount ? traceCopy(`产生 ${toolCount} 个工具调用`, `${toolCount} tool calls`) : traceCopy('未请求工具，进入回答/汇总阶段', 'No tool call; moving to answer/summarize'),
            usageSummary(payload.usage),
        ].filter(Boolean).join(' / '));
    } else if (type === 'citations.collected') {
        parts.push(traceCopy(`新增 ${payload.count || 0} 个来源，累计 ${payload.total || 0} 个。`, `${payload.count || 0} new sources, ${payload.total || 0} total.`));
    } else if (type === 'workflow.node.completed' || type === 'workflow.completed') {
        const summary = [
            payload.result || '',
            Number.isFinite(payload.citation_count) ? traceCopy(`来源 ${payload.citation_count}`, `${payload.citation_count} citations`) : '',
            Array.isArray(payload.skills_used) && payload.skills_used.length ? traceCopy(`工具 ${payload.skills_used.join(', ')}`, `Tools: ${payload.skills_used.join(', ')}`) : '',
        ].filter(Boolean).join(' / ');
        if (summary) parts.push(summary);
    } else if (type === 'aigc.plan.created') {
        const steps = Array.isArray(payload.steps) ? payload.steps : [];
        parts.push(traceCopy(`策略：${payload.information_strategy || 'direct'}；步骤 ${steps.length}`, `Strategy: ${payload.information_strategy || 'direct'}; ${steps.length} steps`));
    } else if (type === 'aigc.plan.step.completed') {
        if (payload.brief_preview) parts.push(`${traceCopy('资料摘要', 'Brief')}: ${truncateText(payload.brief_preview, 220)}`);
        if (Number.isFinite(payload.image_count)) parts.push(traceCopy(`图片 ${payload.image_count}`, `${payload.image_count} images`));
        if (payload.model) parts.push(`${traceCopy('模型', 'Model')}: ${payload.model}`);
    } else if (type === 'aigc.prompt_review.completed') {
        parts.push(traceCopy(`比例 ${payload.aspect_ratio || '-'}；提示词 ${payload.final_prompt_char_count || 0} 字符`, `Ratio ${payload.aspect_ratio || '-'}; prompt ${payload.final_prompt_char_count || 0} chars`));
    } else if (type === 'aigc.image.completed') {
        parts.push(traceCopy(`生成 ${payload.image_count || 0} 张图片；${payload.provider || payload.model || ''}`, `${payload.image_count || 0} images; ${payload.provider || payload.model || ''}`));
    } else if (type === 'agent.delegated') {
        parts.push([payload.source_agent_id && payload.target_agent_id ? `${payload.source_agent_id} -> ${payload.target_agent_id}` : payload.target_agent_id || '', payload.reason || ''].filter(Boolean).join(' / '));
    } else if (type === 'agent.command.routed') {
        parts.push([payload.target_agent_id || '', payload.command_text || ''].filter(Boolean).join(' / '));
    } else if (type === 'context.built') {
        parts.push(traceCopy(`${payload.message_count || 0} 条消息，${payload.tools_count || 0} 个工具已进入上下文。`, `${payload.message_count || 0} messages and ${payload.tools_count || 0} tools in context.`));
    } else if (type === 'memory.loaded') {
        parts.push(traceCopy(`长期记忆 ${payload.long_term_count || 0}，角色记忆 ${payload.persona_count || 0}。`, `Long-term ${payload.long_term_count || 0}, role ${payload.persona_count || 0}.`));
    } else if (type === 'run.completed') {
        parts.push(traceCopy('最终结果已生成，过程已折叠。', 'Final result generated; process folded.'));
    } else if (type === 'run.partial') {
        parts.push(payload.error_message || payload.error_type || traceCopy('已生成阶段性总结。', 'Partial summary generated.'));
    } else if (type === 'run.cancelled') {
        parts.push(payload.error_message || payload.error_type || traceCopy('用户已取消任务。', 'Task cancelled by user.'));
    } else if (type.endsWith('.failed') || event.status === 'error') {
        parts.push(payload.error_message || payload.error_type || fallback);
    }

    return parts.filter(Boolean).join('\n') || fallback || '';
}

function toolArgumentSummary(payload = {}) {
    const args = payload.arguments && typeof payload.arguments === 'object' ? payload.arguments : {};
    if (!Object.keys(args).length) return '';
    if (args.query) return `${traceCopy('输入', 'Input')}: ${args.query}`;
    if (args.task) return `${traceCopy('任务', 'Task')}: ${truncateText(args.task, 180)}`;
    return `${traceCopy('参数', 'Args')}: ${truncateText(JSON.stringify(compactObject(args), null, 2), 220)}`;
}

function toolPreviewSummary(payload = {}) {
    const preview = parseToolPreview(payload.result_preview);
    if (!preview) return payload.result_preview ? truncateText(payload.result_preview, 220) : '';

    const parts = [];
    if (preview.success === true) parts.push(traceCopy('工具成功', 'Tool succeeded'));
    if (preview.success === false) parts.push(traceCopy('工具失败', 'Tool failed'));
    if (preview.error) parts.push(String(preview.error));

    const data = preview.data && typeof preview.data === 'object' ? preview.data : {};
    const results = Array.isArray(data.results) ? data.results : [];
    if (results.length) {
        parts.push(traceCopy(`返回 ${results.length} 条结果`, `${results.length} results`));
        const titles = results
            .slice(0, 3)
            .map((item) => String(item?.title || item?.url || '').trim())
            .filter(Boolean);
        if (titles.length) parts.push(titles.join(' · '));
    } else if (preview.display_text) {
        parts.push(truncateText(preview.display_text, 220));
    } else if (Object.keys(data).length) {
        parts.push(truncateText(summarizePayload(data), 220));
    }

    return parts.filter(Boolean).join('\n');
}

function parseToolPreview(value) {
    if (!value) return null;
    if (typeof value === 'object') return value;
    if (typeof value !== 'string') return null;
    try {
        return JSON.parse(value);
    } catch {
        return null;
    }
}

function usageSummary(usage = {}) {
    if (!usage || typeof usage !== 'object') return '';
    return Object.entries(usage)
        .filter(([, value]) => value !== undefined && value !== null && value !== '')
        .map(([key, value]) => `${key}:${value}`)
        .join(', ');
}

function processEventLinks(event = {}) {
    const payload = event.payload || {};
    const urls = [];
    if (Array.isArray(payload.urls)) urls.push(...payload.urls);

    const preview = parseToolPreview(payload.result_preview);
    const results = preview?.data && Array.isArray(preview.data.results) ? preview.data.results : [];
    results.forEach((item) => {
        if (item?.url) urls.push(item.url);
    });

    return [...new Set(urls.map((url) => String(url || '').trim()).filter((url) => url && isSafeContentUrl(url)))].slice(0, 4);
}

function renderProcessTimelineItem(item) {
    const detail = item.detail
        ? `<div class="process-item-detail">${escapeHtml(item.detail)}</div>`
        : '';
    const meta = item.meta.length
        ? `<div class="process-item-meta">${item.meta.map((value) => `<span>${escapeHtml(value)}</span>`).join('')}</div>`
        : '';
    const links = item.links.length
        ? `<div class="process-item-links">${item.links.map((url) => renderSafeLink(url, hostFromUrl(url) || shortDebugId(url))).join('')}</div>`
        : '';
    return `
        <li class="process-item ${escapeAttr(item.status)} ${escapeAttr(item.kind)}">
            <span class="process-item-dot" aria-hidden="true"></span>
            <div class="process-item-body">
                <div class="process-item-head">
                    <strong>${escapeHtml(item.label)}</strong>
                    <span>${escapeHtml(processStatusLabel(item.status))}</span>
                </div>
                ${detail}
                ${links}
                ${meta}
            </div>
        </li>
    `;
}

function processStatusLabel(status = '') {
    if (status === 'running') return traceCopy('进行中', 'running');
    if (status === 'completed') return traceCopy('完成', 'done');
    if (status === 'partial') return traceCopy('部分完成', 'partial');
    if (status === 'cancelled') return traceCopy('已取消', 'cancelled');
    if (status === 'error') return traceCopy('异常', 'error');
    return traceCopy('记录', 'event');
}

function conversationMessagesSignature(messages = []) {
    return (messages || []).map((msg) => [
        msg.id || '',
        msg.role || '',
        msg.run_id || '',
        msg.error_type || '',
        msg.model_used || '',
        msg.runtime || '',
        msg.created_at || '',
        msg.skills_used || '',
        msg.citations || '',
        msg.artifacts || '',
        msg.trace_summary || msg.trace_events || '',
        msg.follow_ups || '',
        msg.content || '',
    ].join('\u001f')).join('\u001e');
}

function showConversationSwitchLoading() {
    messagesContainer.innerHTML = `
        <div class="conversation-switch-loading" aria-hidden="true">
            <div class="loading-dots"><span></span><span></span><span></span></div>
        </div>
    `;
}

function runRecordFromMessage(msg = {}, skillsUsed = [], traceEvents = [], fallbackRun = null) {
    const runId = msg.run_id || fallbackRun?.run_id || '';
    if (!runId || !traceEvents.length) return null;

    const cancelled = traceEvents.some((event) => event?.type === 'run.cancelled' || normalizeTraceStatus(event?.status) === 'cancelled');
    const failed = traceEvents.some((event) => event?.type === 'run.failed' || normalizeTraceStatus(event?.status) === 'error');
    const partial = traceEvents.some((event) => event?.type === 'run.partial' || normalizeTraceStatus(event?.status) === 'partial');
    const completed = traceEvents.some((event) => event?.type === 'run.completed');
    const status = cancelled ? 'cancelled' : (failed ? 'failed' : (partial ? 'partial' : (completed ? 'completed' : (fallbackRun?.status || 'completed'))));

    return {
        ...(fallbackRun || {}),
        run_id: runId,
        agent_id: fallbackRun?.agent_id || inferAgentIdFromTraceEvents(traceEvents) || '',
        conversation_id: msg.conversation_id || currentConversationId || fallbackRun?.conversation_id || '',
        runtime: msg.runtime || fallbackRun?.runtime || '',
        status,
        input: fallbackRun?.input || '',
        output: msg.content || fallbackRun?.output || '',
        model_used: msg.model_used || fallbackRun?.model_used || '',
        skills_used: skillsUsed.length ? skillsUsed : (fallbackRun?.skills_used || []),
        error_type: msg.error_type || fallbackRun?.error_type || '',
        error_message: failed ? (msg.content || fallbackRun?.error_message || '') : (fallbackRun?.error_message || ''),
        started_at: fallbackRun?.started_at || msg.created_at || '',
        completed_at: fallbackRun?.completed_at || msg.created_at || '',
        events: traceEvents,
    };
}

function inferAgentIdFromTraceEvents(events = []) {
    const reversed = [...(events || [])].reverse();
    for (const event of reversed) {
        const payload = event?.payload || {};
        if (event?.type === 'agent.delegated' && payload.target_agent_id) return payload.target_agent_id;
        if (event?.type === 'agent.command.routed' && payload.target_agent_id) return payload.target_agent_id;
        if (event?.type === 'run.started' && payload.agent_id) return payload.agent_id;
    }
    return '';
}

function agentIsSelectable(agentId) {
    return agents.some((agent) => agent.id === agentId && agent.enabled);
}

function setCurrentAgent(agentId, { refreshWelcome = false } = {}) {
    const nextAgentId = agentId || SUPER_CHAT_AGENT_ID;
    if (!agentIsSelectable(nextAgentId) && nextAgentId !== SUPER_CHAT_AGENT_ID) return false;
    currentAgentId = nextAgentId;
    if (agentSelect) agentSelect.value = currentAgentId;
    renderAgentCommandBar();
    renderModes();
    renderAgents();
    renderPinnedAgents();
    updateTopbar();
    if (refreshWelcome) refreshWelcomeIfEmpty();
    return true;
}

function stopActiveRunWatcher() {
    if (activeRunWatcher?.timer) clearTimeout(activeRunWatcher.timer);
    activeRunWatcher = null;
}

function runIsActive(run) {
    return run && run.status && run.status !== 'completed' && run.status !== 'failed' && run.status !== 'partial' && run.status !== 'cancelled';
}

function hasAssistantAfterLastUser(messages = []) {
    const lastUserIndex = [...messages].map((msg) => msg.role).lastIndexOf('user');
    if (lastUserIndex < 0) return false;
    return messages.slice(lastUserIndex + 1).some((msg) => msg.role === 'assistant');
}

async function watchActiveRunForConversation(id, messages = []) {
    if (!id || messages[messages.length - 1]?.role !== 'user' || hasAssistantAfterLastUser(messages)) {
        if (activeRunWatcher?.conversationId === id) stopActiveRunWatcher();
        return;
    }
    if (activeRunWatcher?.conversationId === id) return;

    try {
        const data = await apiCall('GET', `/api/runs?conversation_id=${encodeURIComponent(id)}&limit=5`);
        if (currentConversationId !== id) return;

        const availableRuns = data.runs || [];
        const run = availableRuns.find(runIsActive) || availableRuns.find((item) => (
            item && item.status === 'completed' && item.output
        ));
        if (!run) return;

        if (!runIsActive(run)) {
            appendRecoveredRunMessage(run);
            await Promise.allSettled([loadConversations(), loadRuns()]);
            return;
        }

        const pendingQuery = [...messages].reverse().find((msg) => msg?.role === 'user')?.content || '';
        const streamView = appendStreamingAssistantMessage(pendingQuery, id);
        streamView.setPending(t('chat.resumePending'));
        streamView.setTrace(run.events || [], {
            runId: run.run_id || '',
            runtime: run.runtime || '',
            modelUsed: run.model_used || '',
        });
        activeRunWatcher = {
            conversationId: id,
            runId: run.run_id || '',
            streamView,
            attempts: 0,
            completedChecks: 0,
            timer: null,
        };
        pollActiveRunWatcher();
    } catch {
        // A watcher is best-effort recovery UI; normal conversation rendering should stay quiet.
    }
}

async function pollActiveRunWatcher() {
    const watcher = activeRunWatcher;
    if (!watcher || currentConversationId !== watcher.conversationId) {
        stopActiveRunWatcher();
        return;
    }

    watcher.attempts += 1;
    try {
        const [conversationData, runData] = await Promise.all([
            loadConversation(watcher.conversationId),
            watcher.runId ? apiCall('GET', `/api/runs/${encodeURIComponent(watcher.runId)}`).catch(() => null) : Promise.resolve(null),
        ]);
        if (activeRunWatcher !== watcher || currentConversationId !== watcher.conversationId) return;

        const messages = conversationData.messages || [];
        const run = runData || {};
        if (run.events) {
            watcher.streamView.setTrace(run.events || [], {
                runId: run.run_id || watcher.runId,
                runtime: run.runtime || '',
                modelUsed: run.model_used || '',
            });
        }

        if (hasAssistantAfterLastUser(messages)) {
            stopActiveRunWatcher();
            await Promise.allSettled([loadConversations(), loadRuns()]);
            await renderConversationMessages(watcher.conversationId, { watchActiveRuns: false });
            return;
        }

        if (run.status && !runIsActive(run)) {
            watcher.completedChecks += 1;
            if (run.status === 'completed' && run.output) {
                watcher.streamView.finalize(chatResponseFromRun(run));
                stopActiveRunWatcher();
                await Promise.allSettled([loadConversations(), loadRuns()]);
                return;
            }
        }
        if (watcher.attempts >= ACTIVE_RUN_MAX_POLLS || watcher.completedChecks >= 3) {
            stopActiveRunWatcher();
            await renderConversationMessages(watcher.conversationId, { watchActiveRuns: false });
            return;
        }
    } catch {
        if (watcher.attempts >= ACTIVE_RUN_MAX_POLLS) {
            stopActiveRunWatcher();
            return;
        }
    }

    if (activeRunWatcher === watcher) {
        watcher.timer = setTimeout(pollActiveRunWatcher, ACTIVE_RUN_POLL_MS);
    }
}

function appendRecoveredRunMessage(run) {
    const streamView = appendStreamingAssistantMessage(run?.input || '', run?.conversation_id || currentConversationId);
    streamView.finalize(chatResponseFromRun(run));
}

function chatResponseFromRun(run = {}) {
    return {
        response: run.output || '',
        events: run.events || [],
        run_id: run.run_id || '',
        runtime: run.runtime || '',
        model_used: run.model_used || '',
        skills_used: run.skills_used || [],
        citations: [],
        artifacts: run.artifacts || [],
        tokens_used: run.tokens_used || {},
        agent_id: run.agent_id || currentAgentId,
    };
}

async function selectConversation(id) {
    stopActiveRunWatcher();
    currentConversationId = id;
    saveCurrentConversationId(id);
    applyConversationAgent(currentConversationRecord(id));
    setSelectedModesForConversation(id);
    setView('chat', { restore: false });
    renderConversationList();
    await renderConversationMessages(id);
}

async function restoreInitialConversation() {
    const storedValue = localStorage.getItem(accountStorageKey(CURRENT_CONVERSATION_STORAGE_KEY));
    const hasStoredPreference = storedValue !== null;
    const storedConversationExists = currentConversationId
        && conversations.some((conv) => conv.id === currentConversationId);

    if (!storedConversationExists && !hasStoredPreference && conversations.length) {
        currentConversationId = conversations[0].id;
        saveCurrentConversationId(currentConversationId);
    }

    if (currentConversationId && conversations.some((conv) => conv.id === currentConversationId)) {
        applyConversationAgent(currentConversationRecord(currentConversationId));
        setSelectedModesForConversation(currentConversationId);
        renderConversationList();
        await renderConversationMessages(currentConversationId);
    } else {
        currentConversationId = null;
        saveCurrentConversationId(null);
        stopActiveRunWatcher();
        clearQuestionHistory();
        setCurrentAgent(SUPER_CHAT_AGENT_ID);
        setSelectedModesForConversation(null, [], { persist: true });
        showWelcome();
    }
}

async function startAgentTask(agentId) {
	const agent = agents.find((item) => item.id === agentId);
	if (agent && !agent.enabled) return;

    stopActiveRunWatcher();
    currentConversationId = null;
    saveCurrentConversationId(null);
    clearQuestionHistory();
    setSelectedModesForConversation(null, [], { persist: true });
    setCurrentAgent(agentId || 'super_chat');
    setView('chat', { restore: false });
    showWelcome();
    renderConversationList();
    messageInput.value = '';
    clearAttachments();
    updateSendState();
    autoResizeInput();
	focusMessageInput();
}

function openPulseChat(query = '') {
	stopActiveRunWatcher();
	currentConversationId = null;
	saveCurrentConversationId(null);
	clearQuestionHistory();
	clearAttachments();
	setSelectedModesForConversation(null, [], { persist: true });
	setCurrentAgent(SUPER_CHAT_AGENT_ID);
	setView('chat', { restore: false });
	showWelcome();
	renderConversationList();
	messageInput.value = query;
	autoResizeInput();
	updateSendState();
	focusMessageInput();
}

async function startNewTopic() {
	stopActiveRunWatcher();
	setView('chat', { restore: false });
	clearQuestionHistory();
    setCurrentAgent(SUPER_CHAT_AGENT_ID);
    setSelectedModesForConversation(null, [], { persist: true });
    messageInput.value = '';
    clearAttachments();
    updateSendState();
    autoResizeInput();

    try {
        await createConversation();
        showWelcome();
    } catch (err) {
        currentConversationId = null;
        saveCurrentConversationId(null);
        renderConversationList();
        showWelcome();
        appendMessage('assistant', t('chat.createConversationFailed', { message: err.message }), [], '', 'error');
    }

    focusMessageInput();
}

async function handleSend(queryOverride = '') {
    if (!currentUserId) {
        showAccountLogin();
        return;
    }
    const typedQuery = (queryOverride || messageInput.value).trim();
    if (hasPendingAttachments()) return;

    const attachmentsForTurn = attachedContexts
        .filter((item) => item.status === 'ready' && (item.content || item.dataUrl))
        .map((item) => ({ ...item }));
    const attachmentContext = buildAttachmentContext(attachmentsForTurn);
    const attachmentPayload = chatAttachmentPayload(attachmentsForTurn);
    const query = typedQuery || (attachmentContext ? defaultAttachmentPrompt() : '');
    if (!query) return;

    if (!currentConversationId) {
        try {
            await createConversation();
        } catch (err) {
            appendMessage('assistant', t('chat.createConversationFailed', { message: err.message }), [], '', 'error');
            return;
        }
    }

    const conversationId = currentConversationId;
    if (!conversationId || activeConversationRequests.has(conversationId)) return;

    activeConversationRequests.add(conversationId);
    forgetConversationRender(conversationId);
    appendQuestionHistory(query);
    removeFollowUpMessages();
    updateSendState();
    messageInput.value = '';
    autoResizeInput();

    const modeMeta = getSelectedModes().map((mode) => ({ id: mode.id, name: modeCopy(mode).name }));
    appendMessage('user', query, [], '', '', [], '', '', [], [], {
        modes: modeMeta,
        attachments: attachmentSummary(attachmentsForTurn),
    });
    const streamView = appendStreamingAssistantMessage(query, conversationId);
    clearAttachments();
    scrollToBottom();

    try {
        const contextBlocks = [attachmentContext].filter(Boolean);
        const resp = await sendMessageStream(conversationId, query, streamView, attachmentContext, attachmentPayload, {
            context_blocks: contextBlocks,
        });
        streamView.finalize(resp);
        captureMemoryDebug(resp, conversationId);
        if (driveWriteToolsUsed(resp)) void loadProjects();
        if (activeView === 'developer') void loadDeveloperMemory();
        void Promise.allSettled([loadConversations(), loadRuns()]).then(() => {
            if (currentConversationId === conversationId) updateTopbar();
        });
    } catch (err) {
        streamView.showError(`Error: ${err.message}`);
    } finally {
        activeConversationRequests.delete(conversationId);
        updateSendState();
        if (currentConversationId === conversationId) {
            scrollToBottom();
            focusMessageInput();
        }
    }
}

async function sendFollowUpQuestion(button) {
    const query = String(button?.dataset.followUpQuestion || '').trim();
    if (!query || button?.disabled) return;

    removeFollowUpMessages();
    resetQuestionHistoryBrowse();
    messageInput.value = query;
    autoResizeInput();
    updateSendState();
    await handleSend(query);
}

async function regenerateAssistantAnswer(button) {
    if (!currentUserId) {
        showAccountLogin();
        return;
    }

    const conversationId = currentConversationId;
    const message = button.closest('.message.assistant');
    const query = String(message?.dataset.regenerateQuery || '').trim();
    if (!conversationId || !query || activeConversationRequests.has(conversationId)) return;

    stopActiveRunWatcher();
    activeConversationRequests.add(conversationId);
    forgetConversationRender(conversationId);
    removeFollowUpMessages();
    updateSendState();

    const streamView = appendStreamingAssistantMessage(query, conversationId);
    scrollToBottom();

    try {
        const resp = await sendMessageStream(conversationId, query, streamView, '', [], { regenerate: true });
        streamView.finalize(resp);
        captureMemoryDebug(resp, conversationId);
        if (driveWriteToolsUsed(resp)) void loadProjects();
        if (activeView === 'developer') void loadDeveloperMemory();
        void Promise.allSettled([loadConversations(), loadRuns()]).then(() => {
            if (currentConversationId === conversationId) updateTopbar();
        });
    } catch (err) {
        streamView.showError(`Error: ${err.message}`);
    } finally {
        activeConversationRequests.delete(conversationId);
        updateSendState();
        if (currentConversationId === conversationId) {
            scrollToBottom();
            focusMessageInput();
        }
    }
}

async function sendMessage(conversationId, query, attachmentContext = '', attachments = []) {
    const model = modelSelect.value || undefined;
    const modePayload = selectedModePayload();
    const targetAgentId = selectedModeAgentId();
    const driveContext = drivePromptContext(targetAgentId);
    return apiCall('POST', '/api/chat', {
        conversation_id: conversationId,
        user_id: currentUserId,
        query,
        stream: false,
        model_preference: model || undefined,
        agent_id: targetAgentId,
        role_id: currentRoleId || undefined,
        context_blocks: attachmentContext ? [attachmentContext] : [],
        drive_context: driveContext || undefined,
        attachments,
        ...modePayload,
    });
}

async function sendMessageStream(conversationId, query, streamView, attachmentContext = '', attachments = [], extraPayload = {}) {
    const model = modelSelect.value || undefined;
    const modePayload = selectedModePayload();
    const targetAgentId = selectedModeAgentId();
    const effectiveAgentId = extraPayload.agent_id || targetAgentId;
    const driveContext = drivePromptContext(effectiveAgentId);
    const { signal, onRunId, ...requestPayload } = extraPayload || {};
    const resp = await fetch(API_BASE + '/api/chat', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            ...(currentAccountToken ? { 'X-Account-Session': currentAccountToken } : {}),
            ...(currentUserId ? { 'X-User-ID': currentUserId } : {}),
        },
        signal,
        body: JSON.stringify({
            conversation_id: conversationId,
            user_id: currentUserId,
            query,
            stream: true,
            model_preference: model || undefined,
            agent_id: targetAgentId,
            role_id: currentRoleId || undefined,
            context_blocks: attachmentContext ? [attachmentContext] : [],
            drive_context: driveContext || undefined,
            attachments,
            ...modePayload,
            ...requestPayload,
        }),
    });

    if (!resp.ok || !resp.body) {
        const err = await resp.json().catch(() => ({ error: resp.statusText }));
        throw new Error(err.error || t('errors.requestFailed'));
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let streamedText = '';
    let finalResponse = null;
    const traceEvents = [];
    let runId = '';
    let runtime = '';
    let modelUsed = '';

    while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const parts = buffer.split('\n\n');
        buffer = parts.pop() || '';

        for (const part of parts) {
            const parsed = parseSseBlock(part);
            if (!parsed) continue;
            const { event, data } = parsed;

            if (event === 'meta') {
                runId = data.run_id || runId;
                if (runId && typeof onRunId === 'function') onRunId(runId);
                streamView.setMeta({ runId, runtime, modelUsed });
            } else if (event === 'trace') {
                traceEvents.push(data);
                runId = data.run_id || runId;
                streamView.setTrace(traceEvents, { runId, runtime, modelUsed });
            } else if (event === 'token') {
                streamedText += data.text || '';
                streamView.setContent(streamedText);
            } else if (event === 'response') {
                finalResponse = data;
                runId = data.run_id || runId;
                runtime = data.runtime || runtime;
                modelUsed = data.model_used || modelUsed;
                if (!streamedText) {
                    streamedText = data.response || '';
                    streamView.setContent(streamedText);
                }
                streamView.setTrace(traceEvents.length ? traceEvents : (data.events || []), { runId, runtime, modelUsed });
            } else if (event === 'error') {
                const error = new Error(data.error || t('errors.streamFailed'));
                error.errorType = data.error_type || '';
                error.runId = data.run_id || runId || '';
                throw error;
            }
        }
    }

    return finalResponse || {
        response: streamedText,
        events: traceEvents,
        run_id: runId,
        runtime,
        model_used: modelUsed,
        skills_used: [],
        citations: [],
    };
}

function appendStreamingAssistantMessage(regenerateQuery = '', conversationId = currentConversationId, options = {}) {
    const welcome = messagesContainer.querySelector('.welcome-screen');
    if (welcome) welcome.remove();

    const cancelTaskId = String(options.cancelTaskId || '');
    const cancellable = Boolean(cancelTaskId && typeof options.onCancel === 'function');
    const div = document.createElement('div');
    div.className = 'message assistant streaming';
    div.dataset.copyText = '';
    if (cancelTaskId) div.dataset.streamingTaskId = cancelTaskId;
    if (regenerateQuery) div.dataset.regenerateQuery = regenerateQuery;
    div.innerHTML = `
        <div class="avatar">AI</div>
        <div class="bubble">
            <div class="streaming-status"></div>
            <div class="streaming-trace"></div>
            <div class="streaming-content">
                <div class="loading-dots"><span></span><span></span><span></span></div>
            </div>
            <div class="streaming-artifacts"></div>
            <div class="streaming-citations"></div>
            <div class="streaming-skills"></div>
            ${cancellable ? renderStreamingCancelButton(cancelTaskId) : ''}
            ${renderAssistantActions({ copyEnabled: false, regenerateQuery, regenerateEnabled: false })}
        </div>
    `;
    messagesContainer.appendChild(div);
    if (cancellable) streamingTaskCancellers.set(cancelTaskId, options.onCancel);

    const statusEl = div.querySelector('.streaming-status');
    const contentEl = div.querySelector('.streaming-content');
    const artifactsEl = div.querySelector('.streaming-artifacts');
    const citationsEl = div.querySelector('.streaming-citations');
    const skillsEl = div.querySelector('.streaming-skills');
    const traceEl = div.querySelector('.streaming-trace');
    const cancelActionsEl = div.querySelector('.streaming-task-actions');
    let lastContent = '';
    let lastEvents = [];
    let lastMeta = {};
    let processExpanded = true;
    let processTouched = false;

    function finishStreamingTask() {
        if (cancelTaskId) streamingTaskCancellers.delete(cancelTaskId);
        cancelActionsEl?.remove();
    }

    function rememberProcessPanelIntent(summary) {
        const panel = summary?.closest?.('.process-panel');
        if (!panel || !traceEl.contains(panel)) return;
        processExpanded = !panel.open;
        processTouched = true;
    }

    traceEl.addEventListener('click', (event) => {
        const summary = event.target?.closest?.('.process-summary');
        if (summary) rememberProcessPanelIntent(summary);
    });

    traceEl.addEventListener('keydown', (event) => {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        const summary = event.target?.closest?.('.process-summary');
        if (summary) rememberProcessPanelIntent(summary);
    });

    return {
        setContent(text) {
            const wasEmpty = !lastContent;
            lastContent = text || '';
            div.classList.toggle('has-final-content', Boolean(lastContent));
            div.dataset.copyText = lastContent;
            updateCopyButtonState(div, Boolean(lastContent));
            statusEl.hidden = true;
            if (wasEmpty && lastContent && lastEvents.length) {
                if (!processTouched) processExpanded = false;
                renderProcessPanelInto(traceEl, renderProcessPanel(lastEvents, {
                    expanded: processExpanded,
                    live: false,
                }));
            }
            contentEl.innerHTML = formatContent(lastContent);
            scrollToBottom();
        },
        setMeta(meta) {
            lastMeta = { ...lastMeta, ...meta };
        },
        setPending(label) {
            statusEl.hidden = false;
            statusEl.innerHTML = `
                <div class="streaming-progress">
                    <span class="streaming-progress-dot"></span>
                    <div>
                        <div class="streaming-progress-label">${escapeHtml(label)}</div>
                    </div>
                </div>
            `;
        },
        setTrace(events = [], meta = {}) {
            lastEvents = events;
            lastMeta = { ...lastMeta, ...meta };
            const shouldExpand = processTouched ? processExpanded : !lastContent;
            const processPanel = renderProcessPanel(lastEvents, {
                expanded: shouldExpand,
                live: !lastContent,
            });
            renderProcessPanelInto(traceEl, processPanel);
            if (!lastContent && !processPanel) {
                statusEl.hidden = false;
                statusEl.innerHTML = renderStreamingStatus(lastEvents);
            } else {
                statusEl.hidden = true;
                statusEl.innerHTML = '';
            }
            updateAssistantActions(div, {
                copyEnabled: Boolean(lastContent),
                traceEvents: lastEvents,
                runId: lastMeta.runId || '',
                runtime: lastMeta.runtime || '',
                modelUsed: lastMeta.modelUsed || '',
                regenerateQuery,
                regenerateEnabled: false,
            });
        },
        finalize(resp) {
            finishStreamingTask();
            const displayError = resp.error_type
                ? (resp.error_type === 'rate_limit' ? 'rate_limit' : 'error')
                : '';
            if (displayError) {
                this.showError(resp.response || t('errors.requestFailed'), displayError);
                return;
            }
            this.setContent(resp.response || lastContent);
            artifactsEl.innerHTML = renderArtifactPanel(resp.artifacts || []);
            citationsEl.innerHTML = renderCitationPanel(resp.citations || []);
            const skills = resp.skills_used || [];
            skillsEl.innerHTML = skills.length
                ? `<div class="skill-badges">${skills.map((s) => `<span class="skill-badge">${escapeHtml(s)}</span>`).join('')}</div>`
                : '';
            this.setTrace(resp.events || lastEvents, {
                runId: resp.run_id || lastMeta.runId || '',
                runtime: resp.runtime || lastMeta.runtime || '',
                modelUsed: resp.model_used || lastMeta.modelUsed || '',
            });
            div.classList.remove('streaming');
            updateAssistantActions(div, {
                copyEnabled: Boolean(div.dataset.copyText),
                traceEvents: lastEvents,
                runId: lastMeta.runId || '',
                runtime: lastMeta.runtime || '',
                modelUsed: lastMeta.modelUsed || '',
                regenerateQuery,
                regenerateEnabled: Boolean(regenerateQuery),
            });
            void renderPersistedFollowUpsAfterMessage(div, conversationId, resp.run_id || lastMeta.runId || '');
            updateFollowUpButtonsState();
            updateRegenerateButtonsState();
        },
        showError(message, type = 'error') {
            finishStreamingTask();
            statusEl.hidden = true;
            div.dataset.copyText = message || '';
            div.classList.toggle('has-final-content', Boolean(message));
            updateCopyButtonState(div, Boolean(message));
            if (lastEvents.length) {
                if (!processTouched) processExpanded = false;
                renderProcessPanelInto(traceEl, renderProcessPanel(lastEvents, {
                    expanded: processExpanded,
                    live: false,
                }));
            }
            contentEl.innerHTML = errorBanner(
                type === 'rate_limit' ? t('errors.rateLimit') : t('errors.error'),
                message,
                type === 'rate_limit' ? 'rate-limit' : 'generic-error'
            );
            div.classList.remove('streaming');
            updateAssistantActions(div, {
                copyEnabled: Boolean(message),
                traceEvents: lastEvents,
                runId: lastMeta.runId || '',
                runtime: lastMeta.runtime || '',
                modelUsed: lastMeta.modelUsed || '',
                regenerateQuery,
                regenerateEnabled: Boolean(regenerateQuery),
            });
            updateRegenerateButtonsState();
        },
        showCancelled(message) {
            finishStreamingTask();
            statusEl.hidden = true;
            div.dataset.copyText = message || '';
            div.classList.toggle('has-final-content', Boolean(message));
            updateCopyButtonState(div, Boolean(message));
            contentEl.innerHTML = `<div class="streaming-cancelled">${escapeHtml(message)}</div>`;
            div.classList.remove('streaming');
            updateAssistantActions(div, {
                copyEnabled: Boolean(message),
                traceEvents: lastEvents,
                runId: lastMeta.runId || '',
                runtime: lastMeta.runtime || '',
                modelUsed: lastMeta.modelUsed || '',
                regenerateQuery,
                regenerateEnabled: Boolean(regenerateQuery),
            });
            updateRegenerateButtonsState();
        },
    };
}

function renderStreamingCancelButton(taskId = '') {
    return `
        <div class="streaming-task-actions">
            <button class="btn-secondary streaming-cancel-button" type="button"
                    data-cancel-streaming-task="${escapeAttr(taskId)}">
                ${escapeHtml(t('actions.cancelTask'))}
            </button>
        </div>
    `;
}

function parseSseBlock(block) {
    const lines = block.split('\n');
    let event = 'message';
    const dataLines = [];

    for (const line of lines) {
        if (line.startsWith('event:')) {
            event = line.slice(6).trim();
        } else if (line.startsWith('data:')) {
            dataLines.push(line.slice(5).trimStart());
        }
    }

    if (!dataLines.length) return null;
    try {
        return { event, data: JSON.parse(dataLines.join('\n')) };
    } catch {
        return { event, data: { text: dataLines.join('\n') } };
    }
}

function renderStreamingStatus(events = []) {
    const latest = [...events].reverse().find((event) => event && event.type) || {};
    const label = traceProgressLabel(latest);
    const detail = traceProgressDetail(latest);
    return `
        <div class="streaming-progress">
            <span class="streaming-progress-dot"></span>
            <div>
                <div class="streaming-progress-label">${escapeHtml(label)}</div>
                ${detail ? `<div class="streaming-progress-detail">${escapeHtml(detail)}</div>` : ''}
            </div>
        </div>
    `;
}

function traceProgressLabel(event = {}) {
    const type = event.type || '';
    const status = event.status || '';
    if (!type) return currentLanguage === 'zh' ? '准备开始' : 'Preparing';
    if (type === 'memory.loaded') return currentLanguage === 'zh' ? '已加载角色记忆' : 'Role memory loaded';
    if (type === 'context.built') return currentLanguage === 'zh' ? '已构建上下文' : 'Prompt context built';
    if (type === 'model.started') return currentLanguage === 'zh' ? '模型正在生成' : 'Model is generating';
    if (type === 'model.completed') return currentLanguage === 'zh' ? '模型生成完成' : 'Model completed';
    if (type === 'aigc.command.received') return currentLanguage === 'zh' ? '已解析生图命令' : 'Image command parsed';
    if (type === 'aigc.prompt_review.started') return currentLanguage === 'zh' ? '正在修饰生图提示词' : 'Polishing image prompt';
    if (type === 'aigc.prompt_review.completed') return currentLanguage === 'zh' ? '提示词修饰完成' : 'Prompt polish completed';
    if (type === 'aigc.prompt_review.failed') return currentLanguage === 'zh' ? '提示词修饰降级' : 'Prompt polish fallback';
    if (type === 'aigc.image.started') return currentLanguage === 'zh' ? '正在生成图片' : 'Generating image';
    if (type === 'aigc.image.completed') return currentLanguage === 'zh' ? '图片生成完成' : 'Image generated';
    if (type === 'aigc.image.failed') return currentLanguage === 'zh' ? '图片生成失败' : 'Image generation failed';
    if (type === 'agent.command.routed') return currentLanguage === 'zh' ? '正在路由 Agent 命令' : 'Routing agent command';
    if (type === 'weight_loss.analysis.started') return currentLanguage === 'zh' ? '正在估算热量' : 'Estimating calories';
    if (type === 'weight_loss.analysis.completed') return currentLanguage === 'zh' ? '热量估算完成' : 'Calorie estimate completed';
    if (type === 'weight_loss.command.received') return currentLanguage === 'zh' ? '正在执行减脂命令' : 'Running weight-loss command';
    if (type === 'weight_loss.meal.logged') return currentLanguage === 'zh' ? '已记录餐食' : 'Meal logged';
    if (type === 'weight_loss.exercise.logged') return currentLanguage === 'zh' ? '已记录运动' : 'Exercise logged';
    if (type === 'weight_loss.entry.deleted') return currentLanguage === 'zh' ? '已撤销记录' : 'Entry deleted';
    if (type === 'weight_loss.summary.completed') return currentLanguage === 'zh' ? '已完成缺口统计' : 'Deficit stats completed';
    if (type === 'tool.started') return currentLanguage === 'zh' ? '正在调用工具' : 'Calling tool';
    if (type === 'tool.completed') return currentLanguage === 'zh' ? '工具调用完成' : 'Tool completed';
    if (type === 'tool.failed') return currentLanguage === 'zh' ? '工具调用失败，继续整理回答' : 'Tool failed, continuing';
    if (type === 'memory.extracted') return currentLanguage === 'zh' ? '已完成记忆检查' : 'Memory review completed';
    if (type === 'run.completed') return currentLanguage === 'zh' ? '回答完成' : 'Done';
    if (type === 'run.partial') return currentLanguage === 'zh' ? '已生成阶段性总结' : 'Partial summary ready';
    if (type === 'run.cancelled') return currentLanguage === 'zh' ? '任务已取消' : 'Task cancelled';
    if (status === 'error') return currentLanguage === 'zh' ? '执行遇到问题' : 'Issue encountered';
    return event.title || type;
}

function traceProgressDetail(event = {}) {
    const payload = event.payload || {};
    if (event.type === 'tool.started' || event.type === 'tool.completed' || event.type === 'tool.failed') {
        const name = payload.name || event.title || 'tool';
        return currentLanguage === 'zh' ? `工具：${name}` : `Tool: ${name}`;
    }
    if (event.type === 'model.started') {
        const round = payload.round ? ` #${payload.round}` : '';
        const streaming = payload.streaming
            ? (currentLanguage === 'zh' ? '，正在流式输出' : ', streaming')
            : '';
        return `${currentLanguage === 'zh' ? '生成轮次' : 'Round'}${round}${streaming}`;
    }
    if (event.type === 'aigc.prompt_review.completed') {
        return currentLanguage === 'zh'
            ? `比例：${payload.aspect_ratio || '1:1'}`
            : `Aspect ratio: ${payload.aspect_ratio || '1:1'}`;
    }
    if (event.type === 'aigc.image.started') {
        return currentLanguage === 'zh'
            ? `参考素材：${payload.subject_reference_count || 0}`
            : `References: ${payload.subject_reference_count || 0}`;
    }
    if (event.type === 'aigc.image.completed') {
        return currentLanguage === 'zh'
            ? `图片：${payload.image_count || 0}`
            : `Images: ${payload.image_count || 0}`;
    }
    if (event.type === 'context.built' && Array.isArray(payload.tool_names)) {
        return currentLanguage === 'zh'
            ? `可用工具：${payload.tool_names.join(', ')}`
            : `Tools: ${payload.tool_names.join(', ')}`;
    }
    if (event.type === 'memory.loaded') {
        return currentLanguage === 'zh'
            ? `长期记忆 ${payload.long_term_count || 0}，人设记忆 ${payload.persona_count || 0}`
            : `Long-term ${payload.long_term_count || 0}, persona ${payload.persona_count || 0}`;
    }
    return event.title || '';
}

function appendMessage(
    role,
    content,
    skillsUsed = [],
    modelUsed = '',
    errorType = '',
    traceEvents = [],
    runId = '',
    runtime = '',
    citations = [],
    artifacts = [],
    inputMeta = null,
    regenerateQuery = ''
) {
    const welcome = messagesContainer.querySelector('.welcome-screen');
    if (welcome) welcome.remove();

    messagesContainer.insertAdjacentHTML('beforeend', renderMessageHtml(
        role,
        content,
        skillsUsed,
        modelUsed,
        errorType,
        traceEvents,
        runId,
        runtime,
        citations,
        artifacts,
        inputMeta,
        regenerateQuery
    ));
    updateChatHistoryControls();
}

function renderMessageHtml(
    role,
    content,
    skillsUsed = [],
    modelUsed = '',
    errorType = '',
    traceEvents = [],
    runId = '',
    runtime = '',
    citations = [],
    artifacts = [],
    inputMeta = null,
    regenerateQuery = ''
) {
    const avatar = role === 'user' ? 'You' : 'AI';
    const assistantActions = role === 'assistant'
        ? renderAssistantActions({
            copyEnabled: Boolean(content),
            traceEvents,
            runId,
            runtime,
            modelUsed,
            regenerateQuery,
            regenerateEnabled: Boolean(regenerateQuery),
        })
        : '';
    const userActions = role === 'user'
        ? renderUserMessageActions({ copyEnabled: Boolean(content) })
        : '';
    const displayError = errorType
        ? (errorType === 'rate_limit' ? 'rate_limit' : 'error')
        : '';

    let bubbleContent = '';
    if (displayError === 'rate_limit') {
        const processPanel = renderProcessPanel(traceEvents, { expanded: false });
        bubbleContent = `${processPanel}${processPanel ? renderMessageDivider() : ''}${errorBanner(t('errors.rateLimit'), content, 'rate-limit')}${assistantActions}`;
    } else if (displayError === 'error') {
        const processPanel = renderProcessPanel(traceEvents, { expanded: false });
        bubbleContent = `${processPanel}${processPanel ? renderMessageDivider() : ''}${errorBanner(t('errors.error'), content, 'generic-error')}${assistantActions}`;
    } else {
        const skillBadges = skillsUsed && skillsUsed.length
            ? `<div class="skill-badges">${skillsUsed.map((s) => `<span class="skill-badge">${escapeHtml(s)}</span>`).join('')}</div>`
            : '';
        const processPanel = role === 'assistant'
            ? renderProcessPanel(traceEvents, { expanded: false })
            : '';
        const citationPanel = renderCitationPanel(citations);
        const artifactPanel = renderArtifactPanel(artifacts);
        bubbleContent = [
            renderInputMeta(inputMeta),
            processPanel,
            processPanel ? renderMessageDivider() : '',
            formatContent(content),
            artifactPanel,
            citationPanel ? renderMessageDivider() : '',
            citationPanel,
            skillBadges,
            assistantActions || userActions,
        ].join('');
    }

    const dataAttrs = [
        `data-message-role="${escapeAttr(role)}"`,
        role === 'assistant' || role === 'user' ? `data-copy-text="${escapeAttr(content || '')}"` : '',
        role === 'assistant' && regenerateQuery ? `data-regenerate-query="${escapeAttr(regenerateQuery)}"` : '',
    ].filter(Boolean).join(' ');

    return `
        <div class="message ${escapeAttr(role)}" ${dataAttrs}>
            <div class="avatar">${avatar}</div>
            <div class="bubble">${bubbleContent}</div>
        </div>
    `;
}

function renderMessageDivider() {
    return '<div class="message-divider" aria-hidden="true"></div>';
}

function renderAssistantActions(options = {}) {
    return `
        <div class="assistant-actions">
            ${renderAssistantActionButtons(options)}
        </div>
    `;
}

function renderAssistantActionButtons(options = {}) {
    const {
        copyEnabled = true,
        regenerateQuery = '',
        regenerateEnabled = true,
        traceEvents = [],
        runId = '',
        runtime = '',
        modelUsed = '',
    } = options;
    const label = t('actions.copyAnswer');
    return `
        ${renderTraceActionButton(traceEvents, runId, runtime, modelUsed)}
        ${renderRegenerateActionButton(regenerateQuery, regenerateEnabled)}
        ${renderSaveToDriveActionButton(copyEnabled)}
        ${renderCopyActionButton(copyEnabled, label)}
    `;
}

function renderUserMessageActions(options = {}) {
    const { copyEnabled = true } = options;
    return `
        <div class="assistant-actions user-message-actions">
            ${renderCopyActionButton(copyEnabled, t('actions.copyMessage'), 'actions.copyMessage')}
        </div>
    `;
}

function renderCopyActionButton(copyEnabled = true, label = t('actions.copyAnswer'), labelKey = 'actions.copyAnswer') {
    const disabled = copyEnabled ? '' : 'disabled aria-disabled="true"';
    return `
        <button class="assistant-action-button assistant-copy" type="button" data-copy-answer
                data-copy-label-key="${escapeAttr(labelKey)}" ${disabled}
                title="${escapeAttr(label)}" aria-label="${escapeAttr(label)}">
            <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="9" y="9" width="10" height="10" rx="2"/>
                <path d="M5 15H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v1"/>
            </svg>
            ${renderAssistantActionLabel(label)}
        </button>
    `;
}

function renderSaveToDriveActionButton(enabled = true) {
    const label = t('actions.saveToDrive');
    const disabled = enabled ? '' : 'disabled aria-disabled="true"';
    return `
        <button class="assistant-action-button assistant-save-drive" type="button" data-save-answer-to-drive ${disabled}
                title="${escapeAttr(label)}" aria-label="${escapeAttr(label)}">
            <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M4 5h7l2 2h7v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2Z"/>
                <path d="M12 11v6M9 14h6"/>
            </svg>
            ${renderAssistantActionLabel(label)}
        </button>
    `;
}

function renderAssistantActionLabel(label = '', visibleLabel = label) {
    return `
        <span class="assistant-action-label" aria-hidden="true">${escapeHtml(visibleLabel)}</span>
        <span class="visually-hidden">${escapeHtml(label)}</span>
    `;
}

function renderCodeCopyButton() {
    const label = t('actions.copyCode');
    return `
        <button class="code-copy-button assistant-copy" type="button" data-copy-code
                data-copy-label-key="actions.copyCode"
                title="${escapeAttr(label)}" aria-label="${escapeAttr(label)}">
            <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="9" y="9" width="10" height="10" rx="2"/>
                <path d="M5 15H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v1"/>
            </svg>
            <span class="visually-hidden">${escapeHtml(label)}</span>
        </button>
    `;
}

function updateAssistantActions(messageEl, options = {}) {
    const actions = messageEl?.querySelector?.('.assistant-actions');
    if (!actions) return;
    actions.innerHTML = renderAssistantActionButtons(options);
}

function renderRegenerateActionButton(query = '', enabled = true) {
    if (!query) return '';

    const label = t('actions.regenerateAnswer');
    const disabled = enabled ? '' : 'disabled aria-disabled="true"';
    return `
        <button class="assistant-action-button assistant-regenerate" type="button" data-regenerate-answer ${disabled}
                title="${escapeAttr(label)}" aria-label="${escapeAttr(label)}">
            <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M21 12a9 9 0 1 1-2.64-6.36"/>
                <path d="M21 3v6h-6"/>
            </svg>
            ${renderAssistantActionLabel(label)}
        </button>
    `;
}

function renderTraceActionButton(events = [], runId = '', runtime = '', modelUsed = '') {
    const normalizedEvents = Array.isArray(events) ? events : [];
    if (!normalizedEvents.length && !runId) return '';

    const disabled = runId ? '' : 'disabled aria-disabled="true"';
    const title = traceActionTitle(normalizedEvents, runId, runtime, modelUsed);
    return `
        <button class="assistant-action-button assistant-trace" type="button" ${disabled}
                ${runId ? `data-open-trace-run="${escapeAttr(runId)}"` : ''}
                title="${escapeAttr(title)}" aria-label="${escapeAttr(title)}">
            <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M4 19V5"/>
                <path d="M4 12h6l2-4 3 8 2-4h3"/>
            </svg>
            ${renderAssistantActionLabel(title, t('trace.open'))}
        </button>
    `;
}

function traceActionTitle(events = [], runId = '', runtime = '', modelUsed = '') {
    const parts = [
        t('trace.open'),
        t('trace.events', { count: events.length }),
        runId ? shortRunId(runId) : t('trace.waiting'),
        runtime,
        modelUsed,
    ].filter(Boolean);
    return parts.join(' · ');
}

function updateCopyButtonState(messageEl, enabled = true) {
    const button = messageEl?.querySelector?.('[data-copy-answer]');
    if (!button) return;

    button.disabled = !enabled;
    if (enabled) {
        button.removeAttribute('aria-disabled');
    } else {
        button.setAttribute('aria-disabled', 'true');
    }
    resetCopyButtonFeedback(button);
}

function resetCopyButtonFeedback(button) {
    if (!button) return;
    const label = t(button.dataset.copyLabelKey || 'actions.copyAnswer');
    button.classList.remove('copied', 'failed');
    button.title = label;
    button.setAttribute('aria-label', label);
    const text = button.querySelector('.visually-hidden');
    if (text) text.textContent = label;
    const visibleText = button.querySelector('.assistant-action-label');
    if (visibleText) visibleText.textContent = label;
}

function setCopyButtonFeedback(button, ok) {
    const label = ok ? t('actions.copied') : t('actions.copyFailed');
    clearTimeout(button._copyFeedbackTimer);
    button.classList.toggle('copied', ok);
    button.classList.toggle('failed', !ok);
    button.title = label;
    button.setAttribute('aria-label', label);
    const text = button.querySelector('.visually-hidden');
    if (text) text.textContent = label;
    const visibleText = button.querySelector('.assistant-action-label');
    if (visibleText) visibleText.textContent = label;
    button._copyFeedbackTimer = setTimeout(() => resetCopyButtonFeedback(button), 1400);
}

async function copyTextToClipboard(text) {
    if (navigator.clipboard?.writeText) {
        try {
            await navigator.clipboard.writeText(text);
            return;
        } catch {
            // Fall through to the textarea path for browsers that expose the API
            // but deny it in the current permission context.
        }
    }

    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.setAttribute('readonly', '');
    textarea.style.position = 'fixed';
    textarea.style.top = '-1000px';
    textarea.style.left = '-1000px';
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    textarea.setSelectionRange(0, textarea.value.length);
    const copied = document.execCommand('copy');
    textarea.remove();
    if (!copied) throw new Error('copy failed');
}

function renderInputMeta(meta) {
    if (!meta || (!meta.modes?.length && !meta.drive?.length && !meta.attachments?.length)) return '';
    const modes = (meta.modes || []).map((mode) => `<span>${escapeHtml(mode.name)}</span>`).join('');
    const drive = (meta.drive || []).map((item) => `
        <span title="${escapeAttr(item.name)}">
            ${escapeHtml(`${t('views.projects.title')}: ${item.name}`)}
            <small>${escapeHtml(projectTypeLabel(item))}</small>
        </span>
    `).join('');
    const attachments = (meta.attachments || []).map((item) => `
        <span title="${escapeAttr(item.name)}">
            ${escapeHtml(item.name)}
            <small>${escapeHtml(item.kind || 'file')} / ${escapeHtml(formatBytes(item.size))}${item.truncated ? ` / ${escapeHtml(t('attachments.truncated'))}` : ''}</small>
        </span>
    `).join('');
    return `
        <div class="input-meta">
            ${modes ? `<div class="input-meta-row">${modes}</div>` : ''}
            ${drive ? `<div class="input-meta-row drive-meta-row">${drive}</div>` : ''}
            ${attachments ? `<div class="input-meta-row attachment-meta-row">${attachments}</div>` : ''}
        </div>
    `;
}

function errorBanner(title, detail, cls) {
    return `
        <div class="error-banner ${cls}">
            <div class="error-icon">
                <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10"/>
                    <path d="M12 8v4M12 16h.01"/>
                </svg>
            </div>
            <div class="error-content">
                <div class="error-title">${escapeHtml(title)}</div>
                <div class="error-detail">${escapeHtml(detail)}</div>
            </div>
        </div>
    `;
}

function renderCitationPanel(citations = []) {
    const normalized = normalizeCitations(citations);
    if (!normalized.length) return '';

    const rows = normalized.map((citation) => {
        const host = hostFromUrl(citation.url);
        const title = citation.title || host || citation.url;
        return `
            <li class="citation-item">
                <a class="citation-link" href="${escapeAttr(citation.url)}" target="_blank" rel="noopener noreferrer" title="${escapeAttr(citation.url)}">
                    <span class="citation-link-title">${escapeHtml(title)}</span>
                    ${host ? `<span class="citation-link-host">${escapeHtml(host)}</span>` : ''}
                </a>
            </li>
        `;
    }).join('');

    return `
        <details class="citation-panel" aria-label="${escapeAttr(t('chat.citations'))}">
            <summary class="citation-summary">
                <span class="citation-title">${escapeHtml(t('chat.citations'))}</span>
                <span class="citation-count">${escapeHtml(traceCopy(`${normalized.length} 个来源`, `${normalized.length} sources`))}</span>
            </summary>
            <ol class="citation-list">${rows}</ol>
        </details>
    `;
}

function renderArtifactPanel(artifacts = []) {
    const normalized = normalizeArtifacts(artifacts);
    if (!normalized.length) return '';
    return `
        <div class="message-artifacts">
            ${normalized.map(renderDriveArtifactCard).join('')}
        </div>
    `;
}

function renderDriveArtifactCard(artifact) {
    const item = driveArtifactAsItem(artifact);
    const title = artifact.title || artifact.name || artifact.item_id || t('projects.activeDocument');
    const meta = [
        projectTypeLabel(item),
        artifact.size ? formatBytes(artifact.size) : '',
        artifact.summary || '',
    ].filter(Boolean).join(' · ');
    return `
        <button class="drive-artifact-card" type="button" data-drive-artifact-id="${escapeAttr(artifact.item_id)}">
            <span class="drive-artifact-icon">${driveItemIconSvg(item)}</span>
            <span class="drive-artifact-main">
                <strong>${escapeHtml(title)}</strong>
                <small>${escapeHtml(meta || t('projects.saveDone'))}</small>
            </span>
        </button>
    `;
}

function driveArtifactAsItem(artifact) {
    return {
        id: artifact.item_id || '',
        type: artifact.type === 'drive_folder' ? 'folder' : 'file',
        name: artifact.name || artifact.title || '',
        mime_type: artifact.mime_type || '',
        size: artifact.size || 0,
        summary: artifact.summary || '',
        parent_id: artifact.metadata?.parent_id || '',
        updated_at: artifact.metadata?.updated_at || '',
    };
}

function normalizeCitations(citations = []) {
    if (!Array.isArray(citations)) return [];
    const seen = new Set();
    const normalized = [];
    citations.forEach((item) => {
        if (!item || typeof item !== 'object') return;
        const url = String(item.url || item.URL || '').trim();
        if (!url || !isSafeContentUrl(url) || seen.has(url)) return;
        seen.add(url);
        const metadata = (item.metadata || item.Metadata || {});
        normalized.push({
            index: Number(item.index || item.Index || normalized.length + 1),
            title: String(item.title || item.Title || '').trim(),
            url,
            snippet: String(item.snippet || item.Snippet || '').trim(),
            source: String(item.source || item.Source || '').trim(),
            metadata: metadata && typeof metadata === 'object' ? metadata : {},
        });
    });
    return normalized;
}

function normalizeArtifacts(artifacts = []) {
    if (!Array.isArray(artifacts)) return [];
    const seen = new Set();
    const normalized = [];
    artifacts.forEach((item) => {
        if (!item || typeof item !== 'object') return;
        const type = String(item.type || item.Type || 'drive_file').trim() || 'drive_file';
        const itemId = String(item.item_id || item.ItemID || item.id || '').trim();
        const name = String(item.name || item.Name || item.title || item.Title || '').trim();
        if (!itemId && !name) return;
        const key = `${type}:${itemId || name}`;
        if (seen.has(key)) return;
        seen.add(key);
        const metadata = item.metadata || item.Metadata || {};
        normalized.push({
            type,
            item_id: itemId,
            name,
            title: String(item.title || item.Title || name).trim(),
            mime_type: String(item.mime_type || item.MimeType || '').trim(),
            size: Number(item.size || item.Size || 0),
            summary: String(item.summary || item.Summary || '').trim(),
            url: String(item.url || item.URL || '').trim(),
            metadata: metadata && typeof metadata === 'object' ? metadata : {},
        });
    });
    return normalized;
}

function hostFromUrl(url = '') {
    try {
        return new URL(url, window.location.origin).hostname.replace(/^www\./, '');
    } catch {
        return '';
    }
}

function truncateText(text = '', maxLength = 220) {
    const value = String(text).replace(/\s+/g, ' ').trim();
    if (value.length <= maxLength) return value;
    return `${value.slice(0, Math.max(0, maxLength - 3))}...`;
}

function renderFollowUpMessages(questions = []) {
    const normalized = normalizeFollowUpQuestions(questions);
    if (!normalized.length) return '';

    return normalized.map((question) => `
        <div class="message assistant follow-up-message" data-follow-up-container>
            <div class="avatar follow-up-avatar" aria-hidden="true"></div>
            <button class="bubble follow-up-question" type="button"
                    data-follow-up-question="${escapeAttr(question)}"
                    aria-label="${escapeAttr(t('chat.followUpAria'))}: ${escapeAttr(question)}">
                ${escapeHtml(question)}
            </button>
        </div>
    `).join('');
}

async function renderPersistedFollowUpsAfterMessage(anchorEl, conversationId, runId = '') {
    const targetConversationId = String(conversationId || '').trim();
    const targetRunId = String(runId || '').trim();
    if (!targetConversationId || !targetRunId || currentAgentId !== SUPER_CHAT_AGENT_ID) return;

    followUpRenderToken += 1;
    const renderToken = followUpRenderToken;
    clearFollowUpMessagesOnly();

    for (const delay of FOLLOW_UP_POLL_DELAYS_MS) {
        await wait(delay);
        if (
            renderToken !== followUpRenderToken
            || currentConversationId !== targetConversationId
            || !document.contains(anchorEl)
        ) {
            return;
        }

        let data = null;
        try {
            data = await loadConversation(targetConversationId);
        } catch {
            continue;
        }

        if (
            renderToken !== followUpRenderToken
            || currentConversationId !== targetConversationId
            || !document.contains(anchorEl)
        ) {
            return;
        }

        const messages = data?.messages || [];
        const message = [...messages].reverse().find((item) => (
            item?.role === 'assistant' && String(item.run_id || '') === targetRunId
        ));
        const followUpHtml = renderFollowUpMessages(parseFollowUps(message?.follow_ups));
        if (!followUpHtml) continue;

        clearFollowUpMessagesOnly();
        anchorEl.insertAdjacentHTML('afterend', followUpHtml);
        updateFollowUpButtonsState();
        updateRegenerateButtonsState();
        rememberConversationRender(
            targetConversationId,
            data,
            messagesContainer.innerHTML,
            conversationMessagesSignature(messages)
        );
        return;
    }
}

function pollLatestAssistantFollowUps(messages = [], conversationId = currentConversationId) {
    if (currentAgentId !== SUPER_CHAT_AGENT_ID) return;
    const normalizedMessages = messages || [];
    const latestAssistant = [...normalizedMessages].reverse().find((message) => message?.role === 'assistant');
    if (latestAssistant !== normalizedMessages[normalizedMessages.length - 1]) return;
    if (!latestAssistant || latestAssistant.error_type || parseFollowUps(latestAssistant.follow_ups).length) return;
    const runId = String(latestAssistant.run_id || '').trim();
    if (!runId) return;

    const assistantMessages = [...messagesContainer.querySelectorAll('.message.assistant:not(.follow-up-message)')];
    const anchorEl = assistantMessages[assistantMessages.length - 1];
    if (!anchorEl) return;
    void renderPersistedFollowUpsAfterMessage(anchorEl, conversationId, runId);
}

function renderTraceEvent(event) {
    const status = normalizeTraceStatus(event.status);
    const payload = summarizePayload(event.payload);
    const durationText = Number.isInteger(event.duration_ms) ? `${event.duration_ms}ms` : '';
    const eventId = event.id || '';
    const stepId = event.step_id || '';
    return `
        <div class="trace-event ${status}">
            <div class="trace-dot"></div>
            <div class="trace-body">
                <div class="trace-row">
                    <span class="trace-type">${escapeHtml(event.type || '')}</span>
                    <span class="trace-status">${escapeHtml(event.status || '')}</span>
                    ${durationText ? `<span class="trace-duration">${escapeHtml(durationText)}</span>` : ''}
                    ${eventId ? `<code class="trace-id" title="${escapeAttr(eventId)}">event:${escapeHtml(shortDebugId(eventId))}</code>` : ''}
                    ${stepId ? `<code class="trace-id" title="${escapeAttr(stepId)}">step:${escapeHtml(shortDebugId(stepId))}</code>` : ''}
                </div>
                <div class="trace-title">${escapeHtml(event.title || event.type || 'event')}</div>
                ${payload ? `<pre class="trace-payload">${escapeHtml(payload)}</pre>` : ''}
            </div>
        </div>
    `;
}

function normalizeTraceStatus(status = '') {
    if (status === 'completed') return 'completed';
    if (status === 'running') return 'running';
    if (status === 'partial') return 'partial';
    if (status === 'cancelled' || status === 'canceled') return 'cancelled';
    if (status === 'error' || status === 'failed') return 'error';
    return 'neutral';
}

function appendLoading() {
    const welcome = messagesContainer.querySelector('.welcome-screen');
    if (welcome) welcome.remove();

    const div = document.createElement('div');
    div.className = 'message assistant';
    div.id = 'loading-message';
    div.innerHTML = `
        <div class="avatar">AI</div>
        <div class="bubble">
            <div class="loading-dots"><span></span><span></span><span></span></div>
        </div>
    `;
    messagesContainer.appendChild(div);
    scrollToBottom();
}

function removeLoading() {
    const el = document.getElementById('loading-message');
    if (el) el.remove();
}

function formatContent(text) {
    if (!text) return '<p></p>';
    const codeBlocks = [];
    let processed = String(text).replace(/\r\n/g, '\n').replace(/\r/g, '\n');

    processed = processed.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
        const idx = codeBlocks.length;
        const language = lang ? ` data-language="${escapeAttr(lang)}"` : '';
        codeBlocks.push(`
            <div class="code-block"${language}>
                ${renderCodeCopyButton()}
                <pre${language}><code>${escapeHtml(code.trim())}</code></pre>
            </div>
        `);
        return `%%CODEBLOCK_${idx}%%`;
    });

    const lines = processed.split('\n');
    const html = [];
    let paragraph = [];
    let listType = '';
    let listItems = [];
    let quoteLines = [];

    const flushParagraph = () => {
        if (!paragraph.length) return;
        html.push(`<p>${renderInlineMarkdown(paragraph.join(' '))}</p>`);
        paragraph = [];
    };
    const flushList = () => {
        if (!listType) return;
        html.push(`<${listType}>${listItems.map((item) => `<li>${item}</li>`).join('')}</${listType}>`);
        listType = '';
        listItems = [];
    };
    const flushQuote = () => {
        if (!quoteLines.length) return;
        html.push(`<blockquote>${quoteLines.map((line) => `<p>${renderInlineMarkdown(line)}</p>`).join('')}</blockquote>`);
        quoteLines = [];
    };
    const flushAll = () => {
        flushParagraph();
        flushList();
        flushQuote();
    };

    for (let index = 0; index < lines.length; index += 1) {
        const rawLine = lines[index];
        const line = rawLine.trimEnd();
        const trimmed = line.trim();

        if (!trimmed) {
            flushAll();
            continue;
        }

        const codeMatch = trimmed.match(/^%%CODEBLOCK_(\d+)%%$/);
        if (codeMatch) {
            flushAll();
            html.push(codeBlocks[Number(codeMatch[1])] || '');
            continue;
        }

        const media = renderMediaMarkdown(trimmed);
        if (media) {
            flushAll();
            html.push(media);
            continue;
        }

        if (isMarkdownTableStart(lines, index)) {
            flushAll();
            const tableLines = [];
            while (index < lines.length && isMarkdownTableRow(lines[index])) {
                tableLines.push(lines[index]);
                index += 1;
            }
            index -= 1;
            html.push(renderMarkdownTable(tableLines));
            continue;
        }

        const heading = trimmed.match(/^(#{1,6})\s+(.+)$/);
        if (heading) {
            flushAll();
            const level = Math.min(6, heading[1].length);
            html.push(`<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`);
            continue;
        }

        if (/^([-*_])\s*\1\s*\1\s*$/.test(trimmed)) {
            flushAll();
            html.push('<hr>');
            continue;
        }

        const ordered = trimmed.match(/^(\d+)[.)]\s+(.+)$/);
        if (ordered) {
            flushParagraph();
            flushQuote();
            if (listType && listType !== 'ol') flushList();
            listType = 'ol';
            listItems.push(renderInlineMarkdown(ordered[2]));
            continue;
        }

        const unordered = trimmed.match(/^[-*+]\s+(.+)$/);
        if (unordered) {
            flushParagraph();
            flushQuote();
            if (listType && listType !== 'ul') flushList();
            listType = 'ul';
            listItems.push(renderInlineMarkdown(unordered[1]));
            continue;
        }

        const quote = trimmed.match(/^>\s?(.+)$/);
        if (quote) {
            flushParagraph();
            flushList();
            quoteLines.push(quote[1]);
            continue;
        }

        flushList();
        flushQuote();
        paragraph.push(trimmed);
    }

    flushAll();
    return html.join('') || '<p></p>';
}

function isMarkdownTableStart(lines, index) {
    const header = lines[index] || '';
    const separator = lines[index + 1] || '';
    if (!isMarkdownTableRow(header) || !isMarkdownTableRow(separator)) return false;
    const headerCells = splitMarkdownTableRow(header);
    const separatorCells = splitMarkdownTableRow(separator);
    return headerCells.length > 1
        && separatorCells.length >= headerCells.length
        && separatorCells.every(isMarkdownTableSeparatorCell);
}

function isMarkdownTableRow(line = '') {
    const trimmed = String(line).trim();
    return trimmed.includes('|') && splitMarkdownTableRow(trimmed).length > 1;
}

function isMarkdownTableSeparatorCell(cell = '') {
    return /^:?-{3,}:?$/.test(String(cell).trim());
}

function splitMarkdownTableRow(line = '') {
    let value = String(line).trim();
    if (value.startsWith('|')) value = value.slice(1);
    if (value.endsWith('|')) value = value.slice(0, -1);

    const cells = [];
    let current = '';
    let escaped = false;
    for (const char of value) {
        if (escaped) {
            current += char;
            escaped = false;
            continue;
        }
        if (char === '\\') {
            escaped = true;
            current += char;
            continue;
        }
        if (char === '|') {
            cells.push(current.replace(/\\\|/g, '|').trim());
            current = '';
            continue;
        }
        current += char;
    }
    cells.push(current.replace(/\\\|/g, '|').trim());
    return cells;
}

function markdownTableAlign(separator = '') {
    const value = String(separator).trim();
    if (/^:-{3,}:$/.test(value)) return 'center';
    if (/^-{3,}:$/.test(value)) return 'right';
    return 'left';
}

function normalizeTableCells(cells, size) {
    const normalized = cells.slice(0, size);
    while (normalized.length < size) normalized.push('');
    return normalized;
}

function renderMarkdownTable(tableLines = []) {
    const header = splitMarkdownTableRow(tableLines[0] || '');
    const separator = splitMarkdownTableRow(tableLines[1] || '');
    const bodyRows = tableLines.slice(2).map(splitMarkdownTableRow);
    const columnCount = Math.max(
        header.length,
        separator.length,
        ...bodyRows.map((row) => row.length)
    );
    const aligns = normalizeTableCells(separator, columnCount).map(markdownTableAlign);
    const alignAttr = (align) => align === 'left' ? '' : ` style="text-align: ${align}"`;
    const head = normalizeTableCells(header, columnCount)
        .map((cell, index) => `<th${alignAttr(aligns[index])}>${renderInlineMarkdown(cell)}</th>`)
        .join('');
    const body = bodyRows
        .map((row) => normalizeTableCells(row, columnCount)
            .map((cell, index) => `<td${alignAttr(aligns[index])}>${renderInlineMarkdown(cell)}</td>`)
            .join(''))
        .map((cells) => `<tr>${cells}</tr>`)
        .join('');

    return `
        <div class="markdown-table-wrap" role="region" tabindex="0">
            <table class="markdown-table">
                <thead><tr>${head}</tr></thead>
                ${body ? `<tbody>${body}</tbody>` : ''}
            </table>
        </div>
    `;
}

function renderInlineMarkdown(text) {
    const placeholders = [];
    let processed = String(text);

    processed = processed.replace(/`([^`]+)`/g, (_, code) => {
        const idx = placeholders.length;
        placeholders.push(`<code>${escapeHtml(code)}</code>`);
        return `%%INLINE_${idx}%%`;
    });

    processed = processed.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, (_, label, url) => {
        const idx = placeholders.length;
        placeholders.push(renderSafeLink(url, label));
        return `%%INLINE_${idx}%%`;
    });

    processed = processed.replace(/(^|[\s(])((https?:\/\/[^\s<)]+))/g, (_, prefix, url) => {
        const idx = placeholders.length;
        placeholders.push(renderSafeLink(url, url));
        return `${prefix}%%INLINE_${idx}%%`;
    });

    processed = escapeHtml(processed);
    processed = processed.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    processed = processed.replace(/(^|[\s>])_([^_\n]+)_/g, '$1<em>$2</em>');
    processed = processed.replace(/(^|[\s>])\*([^*\n]+)\*/g, '$1<em>$2</em>');

    placeholders.forEach((html, idx) => {
        processed = processed.replace(`%%INLINE_${idx}%%`, html);
    });
    return processed;
}

function renderMediaMarkdown(line) {
    const image = line.match(/^!\[([^\]]*)\]\((https?:\/\/[^\s)]+|\/[^\s)]+|data:image\/[a-z0-9.+-]+;base64,[^\s)]+)\)$/i);
    if (image) {
        return renderImageBlock(image[2], image[1]);
    }

    const video = line.match(/^\[(?:video|视频)\]\((https?:\/\/[^\s)]+|\/[^\s)]+)\)$/i);
    if (video) {
        return renderVideoBlock(video[1]);
    }

    if (isImageUrl(line)) {
        return renderImageBlock(line, '');
    }
    if (isVideoUrl(line)) {
        return renderVideoBlock(line);
    }
    return '';
}

function renderImageBlock(url, alt = '') {
    if (!isSafeContentUrl(url) || !isImageUrl(url)) return '';
    const label = alt || t('media.preview');
    const downloadName = suggestedImageDownloadName(url, alt);
    return `
        <figure class="message-media">
            <button class="media-preview-trigger" type="button"
                    data-media-preview-src="${escapeAttr(url)}"
                    data-media-preview-alt="${escapeAttr(alt)}"
                    data-media-download-name="${escapeAttr(downloadName)}"
                    aria-label="${escapeAttr(t('media.preview'))}: ${escapeAttr(label)}"
                    title="${escapeAttr(t('media.preview'))}">
                <img src="${escapeAttr(url)}" alt="${escapeAttr(alt)}" loading="lazy">
            </button>
            ${alt ? `<figcaption>${escapeHtml(alt)}</figcaption>` : ''}
        </figure>
    `;
}

function renderVideoBlock(url) {
    if (!isSafeContentUrl(url)) return '';
    return `
        <figure class="message-media">
            <video src="${escapeAttr(url)}" controls preload="metadata"></video>
        </figure>
    `;
}

function openMediaPreviewFromTrigger(trigger) {
    openMediaPreview({
        src: trigger.dataset.mediaPreviewSrc || '',
        alt: trigger.dataset.mediaPreviewAlt || '',
        downloadName: trigger.dataset.mediaDownloadName || '',
    }, trigger);
}

function openMediaPreview({ src, alt = '', downloadName = '' }, returnFocus = null) {
    if (!mediaLightbox || !mediaLightboxImage || !isSafeContentUrl(src) || !isImageUrl(src)) return;

    mediaPreviewReturnFocus = returnFocus;
    mediaLightbox.dataset.previewSrc = src;
    mediaLightbox.dataset.previewAlt = alt;
    mediaLightbox.dataset.downloadName = downloadName || suggestedImageDownloadName(src, alt);
    mediaLightboxImage.src = src;
    mediaLightboxImage.alt = alt || t('media.preview');
    setMediaPreviewScale(1);
    setMediaPreviewRotation(0);
    clearMediaPreviewStatus();
    refreshMediaPreviewLabels();

    mediaLightbox.classList.remove('hidden');
    document.body.classList.add('media-lightbox-open');
    mediaLightboxClose?.focus({ preventScroll: true });
}

function closeMediaPreview() {
    if (!mediaLightbox || mediaLightbox.classList.contains('hidden')) return;

    mediaLightbox.classList.add('hidden');
    document.body.classList.remove('media-lightbox-open');
    mediaLightbox.removeAttribute('data-preview-src');
    mediaLightbox.removeAttribute('data-preview-alt');
    mediaLightbox.removeAttribute('data-download-name');
    if (mediaLightboxImage) {
        mediaLightboxImage.removeAttribute('src');
        mediaLightboxImage.removeAttribute('style');
    }
    clearMediaPreviewStatus();

    const returnFocus = mediaPreviewReturnFocus;
    mediaPreviewReturnFocus = null;
    if (returnFocus && document.contains(returnFocus)) {
        returnFocus.focus({ preventScroll: true });
    }
}

function mediaPreviewIsOpen() {
    return Boolean(mediaLightbox && !mediaLightbox.classList.contains('hidden'));
}

function refreshMediaPreviewLabels() {
    if (!mediaLightboxTitle || !mediaLightbox) return;
    mediaLightboxTitle.textContent = mediaLightbox.dataset.previewAlt || t('media.preview');
}

function setMediaPreviewScale(nextScale) {
    if (!mediaLightbox || !mediaLightboxImage) return;

    mediaPreviewScale = Math.max(0.5, Math.min(3, Number(nextScale) || 1));
    mediaLightboxImage.style.setProperty('--media-preview-width', mediaPreviewScale === 1 ? 'auto' : `${mediaPreviewScale * 100}%`);
    mediaLightboxStage?.classList.toggle('is-zoomed', mediaPreviewScale > 1.01);
    mediaLightbox.querySelector('[data-media-preview-zoom-out]')?.toggleAttribute('disabled', mediaPreviewScale <= 0.5);
    mediaLightbox.querySelector('[data-media-preview-zoom-in]')?.toggleAttribute('disabled', mediaPreviewScale >= 3);
}

function setMediaPreviewRotation(nextRotation) {
    if (!mediaLightbox || !mediaLightboxImage) return;

    mediaPreviewRotation = ((Number(nextRotation) || 0) % 360 + 360) % 360;
    mediaLightboxImage.style.setProperty('--media-preview-rotation', `${mediaPreviewRotation}deg`);
    mediaLightboxStage?.classList.toggle('is-rotated', mediaPreviewRotation === 90 || mediaPreviewRotation === 270);
}

async function downloadMediaPreview() {
    if (!mediaLightbox) return;

    const src = mediaLightbox.dataset.previewSrc || '';
    if (!isSafeContentUrl(src) || !isImageUrl(src)) return;

    const downloadButton = mediaLightbox.querySelector('[data-media-preview-download]');
    const filename = mediaLightbox.dataset.downloadName || suggestedImageDownloadName(src, mediaLightbox.dataset.previewAlt || '');
    downloadButton?.toggleAttribute('disabled', true);
    showMediaPreviewStatus(t('media.downloading'));
    try {
        await saveImageFromUrl(src, filename);
        showMediaPreviewStatus(t('media.downloaded'), 'success');
    } catch {
        showMediaPreviewStatus(t('media.downloadFailed'), 'error');
    } finally {
        downloadButton?.toggleAttribute('disabled', false);
    }
}

async function saveImageFromUrl(url, filename) {
    if (isSafeDataImageUrl(url)) {
        triggerDownload(url, filename);
        return;
    }

    try {
        const downloadUrl = mediaDownloadUrl(url, filename);
        const resp = await fetch(downloadUrl, {
            mode: 'cors',
            credentials: downloadUrl.startsWith('/') ? 'same-origin' : 'omit',
        });
        if (!resp.ok) throw new Error(`Download failed: ${resp.status}`);
        const blob = await resp.blob();
        if (blob.type && !blob.type.startsWith('image/')) throw new Error('Not an image response');
        const objectUrl = URL.createObjectURL(blob);
        triggerDownload(objectUrl, filename);
        setTimeout(() => URL.revokeObjectURL(objectUrl), 30000);
        return;
    } catch (err) {
        throw err;
    }
}

function mediaDownloadUrl(url, filename) {
    if (/^https?:\/\//i.test(url)) {
        return `/api/media/download?url=${encodeURIComponent(url)}&filename=${encodeURIComponent(filename)}`;
    }
    return url;
}

function triggerDownload(href, filename) {
    const link = document.createElement('a');
    link.href = href;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
}

function showMediaPreviewStatus(message, type = '') {
    if (!mediaLightboxStatus) return;
    mediaLightboxStatus.textContent = message || '';
    mediaLightboxStatus.hidden = !message;
    mediaLightboxStatus.classList.toggle('error', type === 'error');
    mediaLightboxStatus.classList.toggle('success', type === 'success');
}

function clearMediaPreviewStatus() {
    showMediaPreviewStatus('');
}

function suggestedImageDownloadName(url, alt = '') {
    const fromUrl = imageFileNameFromUrl(url);
    if (fromUrl && /\.(png|jpe?g|gif|webp|avif|bmp|svg)$/i.test(fromUrl)) {
        return sanitizeFileName(fromUrl);
    }

    const base = sanitizeFileName(fromUrl || alt || 'superchat-image');
    return `${base}.${imageExtensionFromUrl(url) || 'png'}`;
}

function imageFileNameFromUrl(url = '') {
    if (isSafeDataImageUrl(url)) return '';
    try {
        const { pathname } = new URL(url, window.location.origin);
        const segment = pathname.split('/').filter(Boolean).pop() || '';
        return decodeURIComponent(segment);
    } catch {
        return '';
    }
}

function imageExtensionFromUrl(url = '') {
    if (isSafeDataImageUrl(url)) {
        const mime = url.match(/^data:image\/([a-z0-9.+-]+);base64,/i)?.[1] || '';
        if (mime === 'jpeg') return 'jpg';
        if (mime === 'svg+xml') return 'svg';
        return mime || 'png';
    }
    const fromUrl = imageFileNameFromUrl(url).match(/\.([a-z0-9]+)$/i)?.[1] || '';
    if (fromUrl) return fromUrl.toLowerCase() === 'jpeg' ? 'jpg' : fromUrl.toLowerCase();
    return 'png';
}

function sanitizeFileName(value = '') {
    const cleaned = String(value)
        .trim()
        .replace(/[\\/:*?"<>|]+/g, '-')
        .replace(/\s+/g, '-')
        .replace(/-+/g, '-')
        .replace(/^[.-]+|[.-]+$/g, '')
        .slice(0, 90);
    return cleaned || 'superchat-image';
}

function renderSafeLink(url, label) {
    if (!isSafeContentUrl(url)) return escapeHtml(label || url);
    return `<a href="${escapeAttr(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(label || url)}</a>`;
}

function isSafeContentUrl(url = '') {
    const value = String(url).trim();
    return /^https?:\/\//i.test(value) || value.startsWith('/') || isSafeDataImageUrl(value);
}

function isSafeDataImageUrl(url = '') {
    return /^data:image\/(?:png|jpe?g|gif|webp|avif|bmp);base64,[a-z0-9+/=\s]+$/i.test(String(url).trim());
}

function isImageUrl(url = '') {
    return isSafeDataImageUrl(url) || (isSafeContentUrl(url) && /\.(png|jpe?g|gif|webp|avif|bmp|svg)(\?.*)?$/i.test(url));
}

function isVideoUrl(url = '') {
    return isSafeContentUrl(url) && /\.(mp4|webm|ogg|mov)(\?.*)?$/i.test(url);
}

function parseSkills(skillsStr) {
    if (!skillsStr) return [];
    try {
        const parsed = JSON.parse(skillsStr);
        return Array.isArray(parsed) ? parsed : [];
    } catch {
        return [];
    }
}

function parseCitations(citations) {
    if (!citations) return [];
    if (Array.isArray(citations)) return citations;
    try {
        const parsed = JSON.parse(citations);
        return Array.isArray(parsed) ? parsed : [];
    } catch {
        return [];
    }
}

function parseArtifacts(artifacts) {
    if (!artifacts) return [];
    if (Array.isArray(artifacts)) return artifacts;
    try {
        const parsed = JSON.parse(artifacts);
        return Array.isArray(parsed) ? parsed : [];
    } catch {
        return [];
    }
}

function parseTraceEvents(events) {
    if (!events) return [];
    if (Array.isArray(events)) return events;
    try {
        const parsed = JSON.parse(events);
        return Array.isArray(parsed) ? parsed : [];
    } catch {
        return [];
    }
}

function summarizePayload(payload) {
    if (!payload || typeof payload !== 'object') return '';
    const compact = {};
    Object.entries(payload).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== '') compact[key] = value;
    });
    const text = JSON.stringify(compact, null, 2);
    const limit = compact.system_prompt || compact.role_context || compact.messages ? 6000 : 1200;
    return text === '{}' ? '' : text.slice(0, limit);
}

function getCurrentAgent() {
    return agents.find((agent) => agent.id === currentAgentId) || null;
}

function getCurrentAgentName() {
    return getCurrentAgent()?.name || currentAgentId;
}

function localizedMetaText(value, fallback = '') {
    if (typeof value === 'string') return value;
    if (value && typeof value === 'object') {
        const candidates = [value[currentLanguage], value.zh, value.en, ...Object.values(value)];
        const match = candidates.find((item) => typeof item === 'string' && item.trim());
        if (match) return match;
    }
    return fallback;
}

function actionAutoSend(action = {}) {
    const explicit = action.auto_send ?? action.autoSend;
    if (explicit === true || explicit === 'true') return true;
    if (explicit === false || explicit === 'false') return false;

    const query = String(action.query || '');
    return Boolean(query.trim()) && query === query.trim();
}

function currentAgentQuickActions(agent = getCurrentAgent()) {
    const rawActions = agent?.metadata?.quick_actions;
    if (!Array.isArray(rawActions)) return [];
    return rawActions
        .filter((action) => action && action.query)
        .map((action, index) => ({
            id: String(action.id || action.query || `quick-${index}`),
            label: localizedMetaText(action.label, action.id || action.query),
            description: localizedMetaText(action.description, ''),
            query: String(action.query || ''),
            modeId: String(action.mode_id || action.modeId || ''),
            autoSend: actionAutoSend(action),
        }));
}

function renderAgentCommandBar() {
    if (!agentCommandBar) return;
    const actions = currentAgentQuickActions();
    agentCommandBar.hidden = actions.length === 0;
    agentCommandBar.innerHTML = actions.map((action) => `
        <button class="agent-command" type="button"
                data-query="${escapeAttr(action.query)}"
                ${action.modeId ? `data-quick-mode="${escapeAttr(action.modeId)}"` : ''}
                ${action.autoSend ? 'data-quick-send="true"' : ''}
                title="${escapeAttr(action.description || action.label)}">
            ${escapeHtml(action.label)}
        </button>
    `).join('');
}

function shortRunId(runId = '') {
    if (runId.length <= 14) return runId;
    return `${runId.slice(0, 8)}...${runId.slice(-4)}`;
}

function shortDebugId(id = '') {
    if (!id) return '';
    const text = String(id);
    if (text.length <= 18) return text;
    return `${text.slice(0, 10)}...${text.slice(-6)}`;
}

function formatDuration(ms) {
    if (!Number.isFinite(ms)) return '-';
    return `${ms}ms`;
}

function formatBytes(bytes = 0) {
    const value = Number(bytes) || 0;
    if (value < 1024) return `${value} B`;
    if (value < 1024 * 1024) return `${(value / 1024).toFixed(value < 10 * 1024 ? 1 : 0)} KB`;
    return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function formatTime(value) {
    if (!value) return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString(currentLanguage === 'zh' ? 'zh-CN' : 'en-US', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
    });
}

function formatFullTime(value) {
    if (!value) return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString(currentLanguage === 'zh' ? 'zh-CN' : 'en-US', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
    });
}

function emptyState(title, detail) {
    return `
        <div class="empty-state">
            <strong>${escapeHtml(title)}</strong>
            <span>${escapeHtml(detail || '')}</span>
        </div>
    `;
}

function autoResizeInput() {
    messageInput.style.height = 'auto';
    messageInput.style.height = `${Math.min(messageInput.scrollHeight, 150)}px`;
    updateChatNavigationOffset();
}

function insertMessageInputNewline() {
    const start = messageInput.selectionStart ?? messageInput.value.length;
    const end = messageInput.selectionEnd ?? start;

    if (typeof messageInput.setRangeText === 'function') {
        messageInput.setRangeText('\n', start, end, 'end');
    } else {
        const value = messageInput.value;
        const cursor = start + 1;
        messageInput.value = `${value.slice(0, start)}\n${value.slice(end)}`;
        if (messageInput.setSelectionRange) messageInput.setSelectionRange(cursor, cursor);
    }

    messageInput.dispatchEvent(new Event('input', { bubbles: true }));
}

function focusMessageInput(options = {}) {
    const { allowMobile = true } = options;
    if (!messageInput || (!allowMobile && isMobileLayout())) return;
    try {
        messageInput.focus({ preventScroll: true });
    } catch {
        messageInput.focus();
    }
}

function scrollToBottom() {
    requestAnimationFrame(() => {
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    });
}

function chatUserMessageElements() {
    if (!messagesContainer) return [];
    return [...messagesContainer.querySelectorAll('.message.user[data-message-role="user"]')];
}

function chatUserMessageText(messageEl) {
    return String(messageEl?.dataset?.copyText || '')
        .replace(/\s+/g, ' ')
        .trim();
}

function updateChatNavigationOffset() {
    if (!chatHistoryTools || !inputArea) return;
    requestAnimationFrame(() => {
        chatHistoryTools.style.setProperty('--chat-input-offset', `${inputArea.offsetHeight || 0}px`);
    });
}

function chatMessageScrollTop(messageEl) {
    if (!messagesContainer || !messageEl) return 0;
    const containerRect = messagesContainer.getBoundingClientRect();
    const messageRect = messageEl.getBoundingClientRect();
    return messagesContainer.scrollTop + messageRect.top - containerRect.top;
}

function currentChatUserMessageIndex(userMessages = chatUserMessageElements()) {
    if (!messagesContainer || !userMessages.length) return -1;
    const anchorTop = messagesContainer.scrollTop + 32;
    let activeIndex = -1;

    userMessages.forEach((messageEl, index) => {
        if (chatMessageScrollTop(messageEl) <= anchorTop) activeIndex = index;
    });

    return activeIndex >= 0 ? activeIndex : 0;
}

function renderChatHistoryList() {
    if (!chatHistoryList) return;
    const userMessages = chatUserMessageElements();
    const activeIndex = currentChatUserMessageIndex(userMessages);

    if (chatHistoryCount) {
        chatHistoryCount.textContent = userMessages.length
            ? t('chatNav.count', { count: userMessages.length })
            : '';
    }

    if (!userMessages.length) {
        chatHistoryList.innerHTML = `<div class="chat-history-empty">${escapeHtml(t('chatNav.empty'))}</div>`;
        return;
    }

    chatHistoryList.innerHTML = userMessages.map((messageEl, index) => {
        const query = chatUserMessageText(messageEl) || t('chatNav.emptyQuery');
        const active = index === activeIndex;
        return `
            <button class="chat-history-item ${active ? 'active' : ''}" type="button"
                    data-chat-history-index="${index}"
                    title="${escapeAttr(query)}"
                    aria-label="${escapeAttr(t('chatNav.jumpToQuery', { index: index + 1 }))}">
                <span class="chat-history-index">${index + 1}</span>
                <span class="chat-history-query">${escapeHtml(truncateText(query, 150))}</span>
                ${active ? `<span class="chat-history-current">${escapeHtml(t('chatNav.current'))}</span>` : ''}
            </button>
        `;
    }).join('');
}

function setChatHistoryPanelOpen(open) {
    const userMessages = chatUserMessageElements();
    chatHistoryPanelOpen = Boolean(open && userMessages.length);
    if (chatHistoryPanel) chatHistoryPanel.hidden = !chatHistoryPanelOpen;
    if (btnChatHistory) {
        const label = t(chatHistoryPanelOpen ? 'chatNav.historyClose' : 'chatNav.historyOpen');
        btnChatHistory.setAttribute('aria-expanded', String(chatHistoryPanelOpen));
        btnChatHistory.title = label;
        btnChatHistory.setAttribute('aria-label', label);
    }
    if (chatHistoryPanelOpen) renderChatHistoryList();
}

function updateChatHistoryControls() {
    if (!chatHistoryTools) return;

    updateChatNavigationOffset();
    const userMessages = chatUserMessageElements();
    const showTools = activeView === 'chat' && Boolean(currentConversationId) && userMessages.length > 0;
    chatHistoryTools.hidden = !showTools;

    if (!showTools) {
        setChatHistoryPanelOpen(false);
        return;
    }

    if (btnChatPrevUser) {
        btnChatPrevUser.disabled = !userMessages.length;
        btnChatPrevUser.toggleAttribute('aria-disabled', !userMessages.length);
    }
    if (btnChatHistory) {
        btnChatHistory.disabled = !userMessages.length;
        btnChatHistory.toggleAttribute('aria-disabled', !userMessages.length);
    }
    if (chatHistoryPanelOpen) renderChatHistoryList();
}

function scheduleChatHistoryControlsUpdate() {
    if (chatNavigationUpdateScheduled) return;
    chatNavigationUpdateScheduled = true;
    requestAnimationFrame(() => {
        chatNavigationUpdateScheduled = false;
        updateChatHistoryControls();
    });
}

function highlightChatMessage(messageEl) {
    if (!messageEl) return;
    messageEl.classList.remove('jump-highlight');
    void messageEl.offsetWidth;
    messageEl.classList.add('jump-highlight');
    clearTimeout(messageEl._jumpHighlightTimer);
    messageEl._jumpHighlightTimer = setTimeout(() => {
        messageEl.classList.remove('jump-highlight');
    }, 1500);
}

function scrollToChatUserMessage(index) {
    const userMessages = chatUserMessageElements();
    const target = userMessages[index];
    if (!target || !messagesContainer) return false;
    const top = Math.max(0, chatMessageScrollTop(target) - 14);
    messagesContainer.scrollTo({ top, behavior: 'smooth' });
    highlightChatMessage(target);
    scheduleChatHistoryControlsUpdate();
    return true;
}

function jumpToPreviousUserMessage() {
    const userMessages = chatUserMessageElements();
    if (!userMessages.length || !messagesContainer) return;

    const threshold = messagesContainer.scrollTop + 12;
    let targetIndex = -1;

    userMessages.forEach((messageEl, index) => {
        if (chatMessageScrollTop(messageEl) < threshold) targetIndex = index;
    });

    if (targetIndex < 0) targetIndex = 0;
    scrollToChatUserMessage(targetIndex);
    setChatHistoryPanelOpen(false);
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text == null ? '' : String(text);
    return div.innerHTML;
}

function escapeAttr(text) {
    return escapeHtml(text).replace(/"/g, '&quot;');
}

document.addEventListener('click', async (event) => {
    if (event.target === sidebarBackdrop) {
        event.preventDefault();
        setSidebarOpen(false);
        return;
    }

    const driveSaveCancelButton = event.target.closest('[data-drive-save-cancel]');
    if (driveSaveCancelButton) {
        event.preventDefault();
        closeDriveSaveDialog({ saved: false });
        return;
    }

    const streamingCancelButton = event.target.closest('[data-cancel-streaming-task]');
    if (streamingCancelButton) {
        event.preventDefault();
        event.stopPropagation();
        if (streamingCancelButton.disabled) return;
        const taskId = streamingCancelButton.dataset.cancelStreamingTask || '';
        const cancelTask = streamingTaskCancellers.get(taskId);
        if (!cancelTask) return;
        streamingCancelButton.disabled = true;
        streamingCancelButton.textContent = t('projects.canceling');
        Promise.resolve(cancelTask()).catch((err) => {
            if (!isCancelledError(err)) console.warn('Cancel streaming task failed', err);
        });
        return;
    }

    const driveSaveFolderButton = event.target.closest('[data-drive-save-folder]');
    if (driveSaveFolderButton) {
        event.preventDefault();
        selectDriveSaveFolder(driveSaveFolderButton.dataset.driveSaveFolder);
        return;
    }

    const drivePathCancelButton = event.target.closest('[data-drive-path-cancel]');
    if (drivePathCancelButton) {
        event.preventDefault();
        closeDrivePathDialog();
        return;
    }

    const drivePathFolderButton = event.target.closest('[data-drive-path-folder]');
    if (drivePathFolderButton) {
        event.preventDefault();
        selectDrivePathFolder(drivePathFolderButton.dataset.drivePathFolder);
        return;
    }

    const openChatDrivePathButton = event.target.closest('[data-open-chat-drive-path]');
    if (openChatDrivePathButton) {
        event.preventDefault();
        await openChatDrivePathDialog(openChatDrivePathButton);
        return;
    }

    const driveToggleFolderButton = event.target.closest('[data-drive-toggle-folder]');
    if (driveToggleFolderButton && !driveToggleFolderButton.disabled) {
        event.preventDefault();
        event.stopPropagation();
        toggleDriveFolderCollapsed(driveToggleFolderButton.dataset.driveToggleFolder);
        return;
    }

    const driveGoParentButton = event.target.closest('[data-drive-go-parent]');
    if (driveGoParentButton && !driveGoParentButton.disabled) {
        event.preventDefault();
        goToDriveParentFolder();
        return;
    }

    const driveBackToFolderButton = event.target.closest('[data-drive-back-to-folder]');
    if (driveBackToFolderButton && !driveBackToFolderButton.disabled) {
        event.preventDefault();
        clearDriveFileInlineDetail();
        return;
    }

    const drivePreviewCloseButton = event.target.closest('[data-drive-preview-close]');
    if (drivePreviewCloseButton) {
        event.preventDefault();
        closeDriveDocumentPreview();
        return;
    }

    const drivePreviewDownloadButton = event.target.closest('[data-drive-preview-download]');
    if (drivePreviewDownloadButton && !drivePreviewDownloadButton.disabled) {
        event.preventDefault();
        downloadDriveItem(drivePreviewDownloadButton.dataset.drivePreviewDownload);
        return;
    }

    const mediaCloseButton = event.target.closest('[data-media-preview-close]');
    if (mediaCloseButton) {
        event.preventDefault();
        closeMediaPreview();
        return;
    }

    const mediaZoomInButton = event.target.closest('[data-media-preview-zoom-in]');
    if (mediaZoomInButton && !mediaZoomInButton.disabled) {
        event.preventDefault();
        setMediaPreviewScale(mediaPreviewScale + 0.25);
        return;
    }

    const mediaZoomOutButton = event.target.closest('[data-media-preview-zoom-out]');
    if (mediaZoomOutButton && !mediaZoomOutButton.disabled) {
        event.preventDefault();
        setMediaPreviewScale(mediaPreviewScale - 0.25);
        return;
    }

    const mediaRotateButton = event.target.closest('[data-media-preview-rotate]');
    if (mediaRotateButton) {
        event.preventDefault();
        setMediaPreviewRotation(mediaPreviewRotation + 90);
        return;
    }

    const mediaDownloadButton = event.target.closest('[data-media-preview-download]');
    if (mediaDownloadButton && !mediaDownloadButton.disabled) {
        event.preventDefault();
        await downloadMediaPreview();
        return;
    }

    const mediaPreviewTrigger = event.target.closest('[data-media-preview-src]');
    if (mediaPreviewTrigger) {
        event.preventDefault();
        openMediaPreviewFromTrigger(mediaPreviewTrigger);
        return;
    }

    const chatPrevUserButton = event.target.closest('#btn-chat-prev-user');
    if (chatPrevUserButton) {
        event.preventDefault();
        if (!chatPrevUserButton.disabled) jumpToPreviousUserMessage();
        return;
    }

    const chatHistoryButton = event.target.closest('#btn-chat-history');
    if (chatHistoryButton) {
        event.preventDefault();
        if (!chatHistoryButton.disabled) setChatHistoryPanelOpen(!chatHistoryPanelOpen);
        return;
    }

    const chatHistoryItem = event.target.closest('[data-chat-history-index]');
    if (chatHistoryItem) {
        event.preventDefault();
        const index = Number(chatHistoryItem.dataset.chatHistoryIndex);
        if (Number.isInteger(index) && scrollToChatUserMessage(index)) {
            setChatHistoryPanelOpen(false);
        }
        return;
    }

    if (chatHistoryPanelOpen && !event.target.closest('#chat-history-tools')) {
        setChatHistoryPanelOpen(false);
    }

    const sidebarSectionToggle = event.target.closest('[data-toggle-sidebar-section]');
    if (sidebarSectionToggle) {
        event.stopPropagation();
        const sectionId = sidebarSectionToggle.dataset.toggleSidebarSection;
        setSidebarSectionCollapsed(sectionId, !collapsedSidebarSections.includes(sectionId));
        return;
    }

    const roleMemoryToggle = event.target.closest('#btn-role-memory');
    if (roleMemoryToggle) {
        event.stopPropagation();
        closeModePopover();
        toggleRoleMemoryPopover();
        return;
    }

    const roleMemoryCloseButton = event.target.closest('[data-role-memory-close]');
    if (roleMemoryCloseButton) {
        event.preventDefault();
        closeRoleMemoryPopover();
        return;
    }

    const roleMemoryDeleteButton = event.target.closest('[data-delete-role-memory]');
    if (roleMemoryDeleteButton && !roleMemoryDeleteButton.disabled) {
        event.stopPropagation();
        await deleteRoleMemory(roleMemoryDeleteButton.dataset.deleteRoleMemory);
        return;
    }

    if (event.target.closest('#role-memory-popover') || event.target.closest('#role-picker')) {
        closeModePopover();
        return;
    }

    closeRoleMemoryPopover();

    const modeToggle = event.target.closest('#btn-mode-toggle');
    if (modeToggle) {
        event.stopPropagation();
        toggleModePopover();
        return;
    }

    if (event.target.closest('#mode-popover')) {
        return;
    }

    closeModePopover();

    const navGroupToggle = event.target.closest('[data-toggle-nav-group]');
    if (navGroupToggle) {
        event.preventDefault();
        const group = navGroupToggle.closest('[data-nav-group]');
        if (group) {
            const collapsed = group.classList.toggle('collapsed');
            navGroupToggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
        }
        return;
    }

    const viewTarget = event.target.closest('[data-view]');
    if (viewTarget) {
        if (viewTarget.dataset.view === 'chat') {
            await startAgentTask('super_chat');
            return;
        }
        setView(viewTarget.dataset.view);
        return;
    }

    const createProjectButton = event.target.closest('[data-create-project]');
    if (createProjectButton) {
        event.preventDefault();
        await createProject();
        return;
    }

    const selectProjectButton = event.target.closest('[data-select-project]');
    if (selectProjectButton) {
        event.preventDefault();
        await selectProject(selectProjectButton.dataset.selectProject);
        return;
    }

    const deleteProjectButton = event.target.closest('[data-delete-project]');
    if (deleteProjectButton && !deleteProjectButton.disabled) {
        event.preventDefault();
        event.stopPropagation();
        await deleteProject(deleteProjectButton.dataset.deleteProject);
        return;
    }

    const moveProjectButton = event.target.closest('[data-project-move]');
    if (moveProjectButton && !moveProjectButton.disabled) {
        event.preventDefault();
        await reorderProject(moveProjectButton.dataset.projectMove, moveProjectButton.dataset.projectMoveDirection);
        return;
    }

    const projectUploadButton = event.target.closest('[data-project-upload-trigger]');
    if (projectUploadButton && !projectUploadButton.disabled) {
        event.preventDefault();
        projectUploadInput?.click();
        return;
    }

    const projectRefreshButton = event.target.closest('[data-project-refresh]');
    if (projectRefreshButton) {
        event.preventDefault();
        await Promise.allSettled([loadProjects(), loadProjectDetail(currentProjectId)]);
        return;
    }

    const projectOpenDocumentButton = event.target.closest('[data-project-open-document]');
    if (projectOpenDocumentButton) {
        event.preventDefault();
        if (handleProjectDocumentModifiedClick(projectOpenDocumentButton, event)) return;
        const documentId = projectOpenDocumentButton.dataset.projectOpenDocument || '';
        noteDrivePlainClick(documentId);
        const item = driveItemById(documentId);
        const surface = projectOpenDocumentButton.dataset.projectOpenSurface || 'library';
        const isExpandableLibraryFolder = surface === 'library' && item?.type === 'folder' && driveChildren(item.id).length > 0;
        if (isExpandableLibraryFolder) {
            if (event.detail > 1) {
                clearProjectOpenClickTimer();
                toggleDriveFolderCollapsed(item.id);
                return;
            }
            clearProjectOpenClickTimer();
            projectOpenClickTimer = window.setTimeout(() => {
                projectOpenClickTimer = null;
                openProjectDocument(item.id, { surface });
            }, 220);
            return;
        }
        clearProjectOpenClickTimer();
        openProjectDocument(documentId, {
            surface,
        });
        return;
    }

    const projectChatPathButton = event.target.closest('[data-project-chat-path]');
    if (projectChatPathButton && !projectChatPathButton.disabled) {
        event.preventDefault();
        openChatWithDrivePath(projectChatPathButton.dataset.projectChatPath);
        return;
    }

    const projectDeleteDocumentButton = event.target.closest('[data-project-delete-document]');
    if (projectDeleteDocumentButton && !projectDeleteDocumentButton.disabled) {
        event.preventDefault();
        await deleteProjectDocument(currentProjectId, projectDeleteDocumentButton.dataset.projectDeleteDocument);
        return;
    }

    const projectDownloadDocumentButton = event.target.closest('[data-project-download-document]');
    if (projectDownloadDocumentButton && !projectDownloadDocumentButton.disabled) {
        event.preventDefault();
        downloadDriveItem(projectDownloadDocumentButton.dataset.projectDownloadDocument);
        return;
    }

    const projectCreateFromSelectionButton = event.target.closest('[data-project-create-from-selection]');
    if (projectCreateFromSelectionButton && !projectCreateFromSelectionButton.disabled) {
        event.preventDefault();
        await createProjectFromSelection();
        return;
    }

    const projectClearSelectionButton = event.target.closest('[data-project-clear-selection]');
    if (projectClearSelectionButton && !projectClearSelectionButton.disabled) {
        event.preventDefault();
        selectedProjectDocumentIds = new Set();
        renderModes();
        renderProjects();
        return;
    }

    const projectAskButton = event.target.closest('[data-project-ask]');
    if (projectAskButton && !projectAskButton.disabled) {
        event.preventDefault();
        await askProject();
        return;
    }

    const projectExpandButton = event.target.closest('[data-project-expand]');
    if (projectExpandButton && !projectExpandButton.disabled) {
        event.preventDefault();
        await expandProjectMap();
        return;
    }

    const projectSaveAnswerButton = event.target.closest('[data-project-save-answer]');
    if (projectSaveAnswerButton && !projectSaveAnswerButton.disabled) {
        event.preventDefault();
        await saveProjectAnswerAsDocument();
        return;
    }

    const developerRefreshButton = event.target.closest('[data-developer-refresh]');
    if (developerRefreshButton && !developerRefreshButton.disabled) {
        event.preventDefault();
        await loadDeveloperMemory();
        return;
    }

    const developerMemoryResetButton = event.target.closest('[data-developer-memory-reset]');
    if (developerMemoryResetButton) {
        event.preventDefault();
        developerMemoryViewState = { ...DEFAULT_DEVELOPER_MEMORY_VIEW_STATE };
        renderDeveloperView();
        return;
    }

    const developerMemorySelectionButton = event.target.closest('[data-developer-memory-selection]');
    if (developerMemorySelectionButton && !developerMemorySelectionButton.disabled) {
        event.preventDefault();
        const action = developerMemorySelectionButton.dataset.developerMemorySelection;
        if (action === 'select-visible') {
            filterDeveloperMemories(developerMemoryState.memories || [])
                .filter(isSelectableDeveloperMemory)
                .forEach((memory) => selectedDeveloperMemoryKeys.add(developerMemoryKey(memory)));
        } else if (action === 'clear') {
            selectedDeveloperMemoryKeys.clear();
        }
        renderDeveloperView();
        return;
    }

    const developerMemoryDeleteSelectedButton = event.target.closest('[data-developer-memory-delete-selected]');
    if (developerMemoryDeleteSelectedButton && !developerMemoryDeleteSelectedButton.disabled) {
        event.preventDefault();
        await deleteSelectedDeveloperMemories();
        return;
    }

    const developerMemoryBulkButton = event.target.closest('[data-developer-memory-bulk]');
    if (developerMemoryBulkButton) {
        event.preventDefault();
        const action = developerMemoryBulkButton.dataset.developerMemoryBulk;
        if (action === 'expand') {
            filterDeveloperMemories(developerMemoryState.memories || [])
                .filter((memory) => memory.kind !== 'long_term')
                .forEach((memory) => expandedDeveloperMemoryIds.add(developerMemoryKey(memory)));
        } else {
            expandedDeveloperMemoryIds.clear();
        }
        renderDeveloperView();
        return;
    }

    const developerMemoryToggleButton = event.target.closest('[data-developer-memory-toggle]');
    if (developerMemoryToggleButton) {
        event.preventDefault();
        const key = developerMemoryToggleButton.dataset.developerMemoryToggle || '';
        const willExpand = key && !expandedDeveloperMemoryIds.has(key);
        const list = developerMemoryToggleButton.closest('[data-developer-memory-list]');
        const scrollTop = list ? list.scrollTop : null;
        if (!willExpand) {
            expandedDeveloperMemoryIds.delete(key);
        } else if (key) {
            expandedDeveloperMemoryIds.add(key);
        }
        renderDeveloperView();
        restoreDeveloperMemoryRecord(key, scrollTop);
        return;
    }

    const developerMemoryEditButton = event.target.closest('[data-developer-memory-edit]');
    if (developerMemoryEditButton && !developerMemoryEditButton.disabled) {
        event.preventDefault();
        await editDeveloperMemory(
            developerMemoryEditButton.dataset.developerMemoryRole,
            developerMemoryEditButton.dataset.developerMemoryEdit,
        );
        return;
    }

    const developerMemoryStatusButton = event.target.closest('[data-developer-memory-status]');
    if (developerMemoryStatusButton && !developerMemoryStatusButton.disabled) {
        event.preventDefault();
        await updateDeveloperMemory(
            developerMemoryStatusButton.dataset.developerMemoryRole,
            developerMemoryStatusButton.dataset.developerMemoryId,
            {
                status: developerMemoryStatusButton.dataset.developerMemoryStatus,
                review_state: 'reviewed',
                review_notes: 'Status changed from Developer view',
            },
        );
        return;
    }

    const developerMemoryDeleteButton = event.target.closest('[data-developer-memory-delete]');
    if (developerMemoryDeleteButton && !developerMemoryDeleteButton.disabled) {
        event.preventDefault();
        await deleteDeveloperMemory(
            developerMemoryDeleteButton.dataset.developerMemoryRole,
            developerMemoryDeleteButton.dataset.developerMemoryDelete,
        );
        return;
    }

    const toolFilterButton = event.target.closest('[data-tool-filter]');
    if (toolFilterButton) {
        event.preventDefault();
        toolFilter = toolFilterButton.dataset.toolFilter || 'all';
        renderTools();
        return;
    }

    const saveMcpButton = event.target.closest('[data-save-mcp-settings]');
    if (saveMcpButton && !saveMcpButton.disabled) {
        event.preventDefault();
        await saveMcpSettings();
        return;
    }

    const pulseRefreshButton = event.target.closest('[data-pulse-refresh]');
    if (pulseRefreshButton) {
        pulseRefreshButton.disabled = true;
        await refreshPulse();
        pulseRefreshButton.disabled = false;
        return;
    }

    const pulseClosePostButton = event.target.closest('[data-pulse-close-post]');
    if (pulseClosePostButton) {
        event.preventDefault();
        closePulsePost();
        return;
    }

    const pulseSuggestedTopicButton = event.target.closest('[data-pulse-suggest-topic]');
    if (pulseSuggestedTopicButton) {
        event.preventDefault();
        const index = Number(pulseSuggestedTopicButton.dataset.pulseSuggestTopic);
        const suggestions = Array.isArray(pulse.suggested_topics) ? pulse.suggested_topics : [];
        if (Number.isInteger(index) && suggestions[index]) {
            await createPulseTopic(suggestions[index]);
        }
        return;
    }

    const pulseFilterTopicButton = event.target.closest('[data-pulse-filter-topic]');
    if (pulseFilterTopicButton) {
        selectedPulseTopicId = pulseFilterTopicButton.dataset.pulseFilterTopic || '';
        renderPulse();
        return;
    }

    const pulseSelectTopicButton = event.target.closest('[data-pulse-select-topic]');
    if (pulseSelectTopicButton) {
        selectedPulseTopicId = pulseSelectTopicButton.dataset.pulseSelectTopic || '';
        renderPulse();
        return;
    }

    const pulseFeedbackButton = event.target.closest('[data-pulse-feedback]');
    if (pulseFeedbackButton) {
        event.preventDefault();
        event.stopPropagation();
        const itemId = pulseFeedbackButton.dataset.pulseFeedback || '';
        const eventType = pulseFeedbackButton.dataset.pulseFeedbackType || '';
        const value = Number(pulseFeedbackButton.dataset.pulseFeedbackValue || '1');
        pulseFeedbackButton.disabled = true;
        await recordPulseEvent(itemId, eventType, Number.isFinite(value) ? value : 1, { surface: selectedPulsePostId ? 'post_window' : 'feed' });
        pulseFeedbackButton.disabled = false;
        return;
    }

    const pulseOpenPostButton = event.target.closest('[data-pulse-open-post]');
    if (pulseOpenPostButton) {
        event.preventDefault();
        openPulsePost(pulseOpenPostButton.dataset.pulseOpenPost || '', pulseOpenPostButton);
        return;
    }

    const pulseDeleteTopicButton = event.target.closest('[data-pulse-delete-topic]');
    if (pulseDeleteTopicButton) {
        event.stopPropagation();
        await deletePulseTopic(pulseDeleteTopicButton.dataset.pulseDeleteTopic);
        return;
    }

    const pulseToggleButton = event.target.closest('[data-pulse-toggle-item]');
    if (pulseToggleButton) {
        const itemId = pulseToggleButton.dataset.pulseToggleItem;
        if (expandedPulseItemIds.has(itemId)) {
            expandedPulseItemIds.delete(itemId);
        } else {
            expandedPulseItemIds.add(itemId);
        }
        renderPulse();
        return;
    }

    const pulseOpenClusterButton = event.target.closest('[data-pulse-open-cluster]');
    if (pulseOpenClusterButton) {
        openPulseCluster(pulseOpenClusterButton.dataset.pulseOpenCluster);
        return;
    }

	const pulseChatButton = event.target.closest('[data-pulse-chat]');
	if (pulseChatButton) {
		const query = pulseChatButton.dataset.pulseChat || '';
		if (pulsePostIsOpen()) closePulsePost();
		openPulseChat(query);
		return;
	}

    const deleteButton = event.target.closest('[data-delete-conversation]');
    if (deleteButton) {
        event.stopPropagation();
        await deleteConversation(deleteButton.dataset.deleteConversation);
        return;
    }

    const conversationTarget = event.target.closest('[data-conversation-id]');
    if (conversationTarget) {
        await selectConversation(conversationTarget.dataset.conversationId);
        return;
    }

    const removeAttachmentButton = event.target.closest('[data-remove-attachment]');
    if (removeAttachmentButton) {
        event.stopPropagation();
        removeAttachment(removeAttachmentButton.dataset.removeAttachment);
        return;
    }

    const followUpButton = event.target.closest('[data-follow-up-question]');
    if (followUpButton) {
        event.preventDefault();
        event.stopPropagation();
        await sendFollowUpQuestion(followUpButton);
        return;
    }

    const quickAction = event.target.closest('[data-query]');
    if (quickAction) {
        if (quickAction.dataset.quickMode) {
            setModeSelected(quickAction.dataset.quickMode, true);
        }
        const query = quickAction.dataset.query || '';
        const shouldQuickSend = quickAction.dataset.quickSend === 'true';
        resetQuestionHistoryBrowse();
        messageInput.value = query;
        autoResizeInput();
        updateSendState();
        if (shouldQuickSend) {
            await handleSend(query);
            return;
        }

        focusMessageInput();
        if (messageInput.setSelectionRange) {
            messageInput.setSelectionRange(messageInput.value.length, messageInput.value.length);
        }
        return;
    }

    const startAgentButton = event.target.closest('[data-start-agent-id]');
    if (startAgentButton && !startAgentButton.disabled) {
        await startAgentTask(startAgentButton.dataset.startAgentId);
        return;
    }

    const pinAgentButton = event.target.closest('[data-pin-agent-id]');
    if (pinAgentButton) {
        togglePinnedAgent(pinAgentButton.dataset.pinAgentId);
        return;
    }

    const testProviderButton = event.target.closest('[data-test-provider]');
    if (testProviderButton && !testProviderButton.disabled) {
        await testProvider(testProviderButton.dataset.testProvider, testProviderButton);
        return;
    }

    const regenerateAnswerButton = event.target.closest('[data-regenerate-answer]');
    if (regenerateAnswerButton) {
        event.stopPropagation();
        if (regenerateAnswerButton.disabled) return;
        await regenerateAssistantAnswer(regenerateAnswerButton);
        return;
    }

    const driveArtifactButton = event.target.closest('[data-drive-artifact-id]');
    if (driveArtifactButton) {
        event.preventDefault();
        event.stopPropagation();
        await openDriveArtifact(driveArtifactButton.dataset.driveArtifactId);
        return;
    }

    const saveAnswerToDriveButton = event.target.closest('[data-save-answer-to-drive]');
    if (saveAnswerToDriveButton) {
        event.stopPropagation();
        if (saveAnswerToDriveButton.disabled) return;
        await saveAssistantMessageToDrive(saveAnswerToDriveButton);
        return;
    }

    const copyAnswerButton = event.target.closest('[data-copy-answer]');
    if (copyAnswerButton) {
        event.stopPropagation();
        if (copyAnswerButton.disabled) return;

        const message = copyAnswerButton.closest('[data-copy-text]');
        const text = message?.dataset.copyText || '';
        if (!text) return;

        try {
            await copyTextToClipboard(text);
            setCopyButtonFeedback(copyAnswerButton, true);
        } catch {
            setCopyButtonFeedback(copyAnswerButton, false);
        }
        return;
    }

    const copyCodeButton = event.target.closest('[data-copy-code]');
    if (copyCodeButton) {
        event.stopPropagation();
        if (copyCodeButton.disabled) return;

        const code = copyCodeButton.closest('.code-block')?.querySelector('code');
        const text = code?.textContent || '';
        if (!text) return;

        try {
            await copyTextToClipboard(text);
            setCopyButtonFeedback(copyCodeButton, true);
        } catch {
            setCopyButtonFeedback(copyCodeButton, false);
        }
        return;
    }

    const copyTraceIdButton = event.target.closest('[data-copy-trace-id]');
    if (copyTraceIdButton) {
        event.stopPropagation();
        if (copyTraceIdButton.disabled) return;

        const text = copyTraceIdButton.dataset.copyTraceId || '';
        if (!text) return;

        try {
            await copyTextToClipboard(text);
            setCopyButtonFeedback(copyTraceIdButton, true);
        } catch {
            setCopyButtonFeedback(copyTraceIdButton, false);
        }
        return;
    }

    const traceJumpButton = event.target.closest('[data-open-trace-run]');
    if (traceJumpButton && !traceJumpButton.disabled) {
        await openTraceRun(traceJumpButton.dataset.openTraceRun);
        return;
    }

    const traceReturnButton = event.target.closest('[data-trace-return-conversation]');
    if (traceReturnButton && !traceReturnButton.disabled) {
        await returnToTraceConversation(traceReturnButton.dataset.traceReturnConversation);
        return;
    }

    const traceToggleButton = event.target.closest('[data-trace-toggle-id]');
    if (traceToggleButton) {
        event.stopPropagation();
        const nodeId = traceToggleButton.dataset.traceToggleId;
        const currentlyCollapsed = traceToggleButton.dataset.traceCollapsed === 'true';
        const willCollapse = !currentlyCollapsed;
        if (willCollapse) {
            collapsedTraceNodeIds.add(nodeId);
            expandedTraceNodeIds.delete(nodeId);
        } else {
            expandedTraceNodeIds.add(nodeId);
            collapsedTraceNodeIds.delete(nodeId);
        }
        const selected = runs.find((run) => run.run_id === selectedRunId);
        if (selected && willCollapse && selectedTraceNodeId && selectedTraceNodeId !== nodeId) {
            const traceTree = buildTraceTree(selected);
            const toggledNode = findTraceNode(traceTree, nodeId);
            if (findTraceNode(toggledNode, selectedTraceNodeId)) {
                selectedTraceNodeId = nodeId;
            }
        }
        if (selected) renderRunDetail(selected);
        return;
    }

    const traceNodeButton = event.target.closest('[data-trace-node-id]');
    if (traceNodeButton) {
        selectedTraceNodeId = traceNodeButton.dataset.traceNodeId;
        const selected = runs.find((run) => run.run_id === selectedRunId);
        if (selected) renderRunDetail(selected);
        return;
    }

    const runButton = event.target.closest('[data-run-id]');
    if (runButton) {
        selectedRunId = runButton.dataset.runId;
        selectedTraceNodeId = '';
        renderRuns();
    }
});

document.addEventListener('pointerdown', startDriveSelectionBox);
document.addEventListener('pointermove', updateDriveSelectionBox);
document.addEventListener('pointerup', finishDriveSelectionBox);
document.addEventListener('pointercancel', cancelDriveSelectionBox);
document.addEventListener('dragstart', handleDriveDragStart);
document.addEventListener('dragover', handleDriveDragOver);
document.addEventListener('drop', handleDriveDrop);
document.addEventListener('dragend', clearDriveDragState);

document.addEventListener('change', async (event) => {
    const drivePathJump = event.target.closest('[data-drive-path-jump]');
    if (drivePathJump) {
        enterDriveFolder(drivePathJump.value || driveRootItem()?.id || '');
        return;
    }

    if (event.target === projectUploadInput) {
        await handleProjectUpload(projectUploadInput.files);
        return;
    }

    const toolToggle = event.target.closest('[data-tool-enabled]');
    if (toolToggle && !toolToggle.disabled) {
        const toolName = toolToggle.dataset.toolEnabled || '';
        await updateToolSettings({
            [toolEnabledSettingKey(toolName)]: toolToggle.checked ? 'true' : 'false',
        });
        return;
    }

    const mcpEnabledToggle = event.target.closest('[data-mcp-enabled]');
    if (mcpEnabledToggle && !mcpEnabledToggle.disabled) {
        toolMcpConfig = { ...toolMcpConfig, enabled: Boolean(mcpEnabledToggle.checked) };
        await updateToolSettings({ 'mcp.enabled': toolMcpConfig.enabled ? 'true' : 'false' });
    }
});

document.addEventListener('input', (event) => {
    const projectSearch = event.target.closest('[data-project-search]');
    if (projectSearch) {
        scheduleProjectSearch(projectSearch);
        return;
    }

    const projectAsk = event.target.closest('[data-project-ask-input]');
    if (projectAsk) {
        projectAskInput = projectAsk.value || '';
        return;
    }

    const toolSearch = event.target.closest('[data-tool-search]');
    if (toolSearch) {
        toolSearchQuery = toolSearch.value || '';
        const cursor = toolSearch.selectionStart;
        renderTools();
        const nextSearch = document.querySelector('[data-tool-search]');
        if (nextSearch) {
            nextSearch.focus({ preventScroll: true });
            if (typeof cursor === 'number' && nextSearch.setSelectionRange) {
                nextSearch.setSelectionRange(cursor, cursor);
            }
        }
        return;
    }

    const mcpServers = event.target.closest('[data-mcp-servers]');
    if (mcpServers) {
        toolMcpConfig = { ...toolMcpConfig, servers: mcpServers.value };
    }
});

document.addEventListener('compositionstart', (event) => {
    if (!event.target.closest?.('[data-project-search]')) return;
    projectSearchComposing = true;
    clearTimeout(projectSearchDebounceTimer);
});

document.addEventListener('compositionend', (event) => {
    const projectSearch = event.target.closest?.('[data-project-search]');
    if (!projectSearch) return;
    projectSearchComposing = false;
    scheduleProjectSearch(projectSearch, 0);
});

document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && driveSelectionBoxState.active) {
        event.preventDefault();
        cancelDriveSelectionBox();
        return;
    }

    if (event.key === 'Escape' && driveDragState.itemIds.length) {
        event.preventDefault();
        clearDriveDragState();
        return;
    }

    if (event.key === 'Escape' && driveSaveDialogIsOpen()) {
        event.preventDefault();
        closeDriveSaveDialog({ saved: false });
        return;
    }

    if (event.key === 'Escape' && drivePathDialogIsOpen()) {
        event.preventDefault();
        closeDrivePathDialog();
        return;
    }

    if (event.key === 'Escape' && drivePreviewIsOpen()) {
        event.preventDefault();
        closeDriveDocumentPreview();
        return;
    }

    if (event.key === 'Escape' && accountLoginIsOpen()) {
        event.preventDefault();
        dismissAccountLogin();
        return;
    }

    if (event.key === 'Escape' && isMobileSidebarOpen()) {
        event.preventDefault();
        setSidebarOpen(false);
        return;
    }

    if (event.key === 'Escape' && roleMemoryPopover && !roleMemoryPopover.classList.contains('hidden')) {
        event.preventDefault();
        closeRoleMemoryPopover();
        return;
    }

    if (event.key === 'Escape' && chatHistoryPanelOpen) {
        event.preventDefault();
        setChatHistoryPanelOpen(false);
        btnChatHistory?.focus({ preventScroll: true });
        return;
    }

    if (event.key === 'Escape' && pulsePostIsOpen()) {
        event.preventDefault();
        closePulsePost();
        return;
    }

    if (!mediaPreviewIsOpen()) return;

    if (event.key === 'Escape') {
        event.preventDefault();
        closeMediaPreview();
        return;
    }

    if (event.key === '+' || event.key === '=') {
        event.preventDefault();
        setMediaPreviewScale(mediaPreviewScale + 0.25);
        return;
    }

    if (event.key === '-' || event.key === '_') {
        event.preventDefault();
        setMediaPreviewScale(mediaPreviewScale - 0.25);
        return;
    }

    if (event.key === '0') {
        event.preventDefault();
        setMediaPreviewScale(1);
        setMediaPreviewRotation(0);
        return;
    }

    if (event.key.toLowerCase() === 'r') {
        event.preventDefault();
        setMediaPreviewRotation(mediaPreviewRotation + 90);
    }
});

if (mediaLightboxStage) {
    mediaLightboxStage.addEventListener('wheel', (event) => {
        if (!mediaPreviewIsOpen() || !(event.metaKey || event.ctrlKey)) return;
        event.preventDefault();
        setMediaPreviewScale(mediaPreviewScale + (event.deltaY < 0 ? 0.15 : -0.15));
    }, { passive: false });
}

if (modePopover) {
    modePopover.addEventListener('change', (event) => {
        const input = event.target.closest('[data-mode-id]');
        if (!input) return;
        setModeSelected(input.dataset.modeId, input.checked);
    });
}

if (btnAttach && attachmentInput) {
    btnAttach.addEventListener('click', () => {
        attachmentInput.click();
    });
    attachmentInput.addEventListener('change', async () => {
        await handleAttachmentSelection(attachmentInput.files);
        attachmentInput.value = '';
    });
}

if (driveSaveForm) {
    driveSaveForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        await submitDriveSaveDialog();
    });
}

if (drivePathForm) {
    drivePathForm.addEventListener('submit', (event) => {
        event.preventDefault();
        submitDrivePathDialog();
    });
}

if (driveSaveNameInput) {
    driveSaveNameInput.addEventListener('input', () => {
        if (!driveSaveDialogState.open) return;
        driveSaveDialogState.title = driveSaveNameInput.value;
        driveSaveDialogState.error = '';
        if (driveSaveError) {
            driveSaveError.textContent = '';
            driveSaveError.classList.remove('visible');
        }
    });
}

document.addEventListener('paste', handleImagePaste);

if (pulseTopicForm) {
    pulseTopicForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        await createPulseTopic();
    });
}

if (roleMemoryForm) {
    roleMemoryForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        await saveRoleMemory();
    });
}

if (developerWorkbench) {
    developerWorkbench.addEventListener('input', (event) => {
        const searchInput = event.target.closest('[data-developer-memory-search]');
        if (!searchInput) return;

        const cursor = searchInput.selectionStart ?? searchInput.value.length;
        developerMemoryViewState = {
            ...developerMemoryViewState,
            query: searchInput.value,
        };
        renderDeveloperView();
        requestAnimationFrame(() => {
            const nextInput = developerWorkbench.querySelector('[data-developer-memory-search]');
            if (!nextInput) return;
            nextInput.focus({ preventScroll: true });
            try {
                nextInput.setSelectionRange(cursor, cursor);
            } catch {
                // Some search inputs do not expose text selection in every browser.
            }
        });
    });

    developerWorkbench.addEventListener('change', (event) => {
        const memorySelect = event.target.closest('[data-developer-memory-select]');
        if (memorySelect) {
            const key = memorySelect.dataset.developerMemorySelect || '';
            if (key && memorySelect.checked) {
                selectedDeveloperMemoryKeys.add(key);
            } else if (key) {
                selectedDeveloperMemoryKeys.delete(key);
            }
            renderDeveloperView();
            return;
        }

        const filterControl = event.target.closest('[data-developer-memory-filter]');
        if (!filterControl) return;

        const key = filterControl.dataset.developerMemoryFilter;
        if (!Object.prototype.hasOwnProperty.call(developerMemoryViewState, key)) return;
        developerMemoryViewState = {
            ...developerMemoryViewState,
            [key]: filterControl.value || DEFAULT_DEVELOPER_MEMORY_VIEW_STATE[key],
        };
        renderDeveloperView();
    });

    developerWorkbench.addEventListener('mouseover', (event) => {
        const record = event.target.closest('.developer-memory-record.long-term[data-memory-content]');
        if (!record || !developerWorkbench.contains(record)) return;
        showDeveloperMemoryHoverCard(record, event);
    });

    developerWorkbench.addEventListener('mousemove', (event) => {
        const record = event.target.closest('.developer-memory-record.long-term[data-memory-content]');
        if (!record || !developerWorkbench.contains(record)) return;
        showDeveloperMemoryHoverCard(record, event);
    });

    developerWorkbench.addEventListener('mouseout', (event) => {
        const record = event.target.closest('.developer-memory-record.long-term[data-memory-content]');
        if (!record) return;
        const related = event.relatedTarget;
        if (related && record.contains(related)) return;
        if (related && developerMemoryHoverCard?.contains(related)) return;
        hideDeveloperMemoryHoverCard({ delay: 120 });
    });

    developerWorkbench.addEventListener('scroll', hideDeveloperMemoryHoverCard, true);

    document.addEventListener('mousemove', (event) => {
        if (!developerMemoryHoverCard || developerMemoryHoverCard.hidden) return;
        const target = event.target instanceof Element ? event.target : null;
        if (!target) {
            hideDeveloperMemoryHoverCard({ delay: 120 });
            return;
        }
        const overMemoryRecord = target.closest('.developer-memory-record.long-term[data-memory-content]');
        const overHoverCard = developerMemoryHoverCard.contains(target);
        if (overMemoryRecord || overHoverCard) return;
        hideDeveloperMemoryHoverCard({ delay: 120 });
    });
}

messageInput.addEventListener('input', () => {
    if (!applyingQuestionHistory) resetQuestionHistoryBrowse();
    updateSendState();
    autoResizeInput();
});

messageInput.addEventListener('keydown', (event) => {
    if (shouldBrowseQuestionHistory(event)) {
        event.preventDefault();
        browseQuestionHistory(event.key === 'ArrowUp' ? 'up' : 'down');
        return;
    }

    if (event.key !== 'Enter' || event.isComposing || event.keyCode === 229) return;
    if (event.shiftKey || event.metaKey || event.ctrlKey || event.altKey) {
        event.preventDefault();
        insertMessageInputNewline();
        return;
    }

    event.preventDefault();
    handleSend();
});

btnSend.addEventListener('click', () => handleSend());

if (btnNewChat) {
    btnNewChat.addEventListener('click', () => startNewTopic());
}

btnToggleSidebar.addEventListener('click', () => {
    setSidebarOpen(sidebar.classList.contains('hidden'));
});

btnRefresh.addEventListener('click', async () => {
    if (!currentUserId) {
        showAccountLogin();
        return;
    }
    btnRefresh.classList.add('spinning');
    await refreshAll();
    btnRefresh.classList.remove('spinning');
});

messagesContainer?.addEventListener('scroll', scheduleChatHistoryControlsUpdate, { passive: true });
window.addEventListener('resize', scheduleChatHistoryControlsUpdate);

if (window.ResizeObserver && inputArea) {
    const chatNavigationResizeObserver = new ResizeObserver(scheduleChatHistoryControlsUpdate);
    chatNavigationResizeObserver.observe(inputArea);
}

if (accountSelect) {
    accountSelect.addEventListener('change', () => {
        const selectedUserId = accountSelect.value;
        if (!selectedUserId || selectedUserId === currentUserId) return;
        accountSelect.value = currentUserId || '';
        showAccountLogin('', selectedUserId);
    });
}

if (btnAddAccount) {
    btnAddAccount.addEventListener('click', () => {
        showAccountLogin('', currentUserId, { focus: 'select' });
    });
}

if (accountLogin) {
    accountLogin.addEventListener('click', (event) => {
        if (event.target === accountLogin) dismissAccountLogin();
    });
}

if (accountLoginClose) {
    accountLoginClose.addEventListener('click', () => {
        dismissAccountLogin();
    });
}

if (guestLoginLink) {
    guestLoginLink.addEventListener('click', async (event) => {
        event.preventDefault();
        if (guestLoginBusy) return;

        setGuestLoginBusy(true);
        if (accountLoginError) accountLoginError.textContent = '';
        try {
            await enterGuestAccount();
        } catch (err) {
            if (accountLoginError) accountLoginError.textContent = t('account.guestFailed', { message: err.message });
        } finally {
            setGuestLoginBusy(false);
        }
    });
}

if (btnAccountLogin) {
    btnAccountLogin.addEventListener('click', async () => {
        const userId = loginAccountSelect?.value || '';
        const password = loginPasswordInput?.value || '';
        if (!userId) {
            showAccountLogin();
            return;
        }
        if (password.trim().length < 4) {
            if (accountLoginError) accountLoginError.textContent = t('account.emptyPassword');
            return;
        }
        btnAccountLogin.disabled = true;
        try {
            const data = await loginAccount(userId, password);
            if (data.account) {
                accounts = [...accounts.filter((item) => item.id !== data.account.id), data.account];
            }
            await switchAccount(data.account?.id || userId, { token: data.token, reload: true });
        } catch (err) {
            if (accountLoginError) accountLoginError.textContent = t('account.loginFailed', { message: err.message });
        } finally {
            btnAccountLogin.disabled = accounts.length === 0;
        }
    });
}

if (accountCreateForm) {
    accountCreateForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        const name = (accountNameInput?.value || '').trim();
        const password = accountPasswordInput?.value || '';
        if (!name) {
            if (accountLoginError) accountLoginError.textContent = t('account.emptyName');
            return;
        }
        if (password.trim().length < 4) {
            if (accountLoginError) accountLoginError.textContent = t('account.emptyPassword');
            return;
        }
        if (accountCreateButton) accountCreateButton.disabled = true;
        try {
            const data = await createAccount(name, password);
            if (accountNameInput) accountNameInput.value = '';
            if (accountPasswordInput) accountPasswordInput.value = '';
            await switchAccount(data.account.id, { token: data.token, reload: true });
        } catch (err) {
            if (accountLoginError) accountLoginError.textContent = t('account.createFailed', { message: err.message });
        } finally {
            if (accountCreateButton) accountCreateButton.disabled = false;
        }
    });
}

if (languageToggle) {
    languageToggle.addEventListener('click', () => {
        setLanguage(currentLanguage === 'zh' ? 'en' : 'zh');
    });
}

modelSelect.addEventListener('change', () => {
    const val = modelSelect.value;
    if (!val) {
        currentModelEl.textContent = defaultModelText;
        return;
    }
    const parts = val.split(':');
    currentModelEl.textContent = parts.length > 1 ? parts.slice(1).join(':') : parts[0];
});

if (agentSelect) {
    agentSelect.addEventListener('change', () => {
        setCurrentAgent(agentSelect.value || 'super_chat', { refreshWelcome: true });
    });
}

if (roleSelect) {
    roleSelect.addEventListener('change', () => {
        setCurrentRole(roleSelect.value || 'default');
    });
}

applyI18n();
applySidebarCollapseState();
renderAgentCommandBar();
renderModes();
renderPulse();
renderAccountControls();
renderRoleSelect();
renderRoleMemoryList();
renderDeveloperView();
updateCounts();
renderHealth();
updateSendState();

bootApp();
