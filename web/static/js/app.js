const API_BASE = '';
const LANGUAGE_KEY = 'agent_assistant_language';
const MODE_STORAGE_KEY = 'super_chat_mode_ids';
const CURRENT_CONVERSATION_STORAGE_KEY = 'agent_assistant_current_conversation_id';
const SIDEBAR_COLLAPSE_STORAGE_KEY = 'agent_assistant_sidebar_collapsed_sections';
const CURRENT_USER_ID_STORAGE_KEY = 'agent_assistant_current_user_id';
const ACCOUNT_SESSION_STORAGE_KEY = 'agent_assistant_account_session';
const MOBILE_BREAKPOINT_QUERY = '(max-width: 720px)';

const VIEW_COPY = {
    chat: ['views.chat.title', 'views.chat.subtitle'],
    pulse: ['views.pulse.title', 'views.pulse.subtitle'],
    agents: ['views.agents.title', 'views.agents.subtitle'],
    tools: ['views.tools.title', 'views.tools.subtitle'],
    trace: ['views.trace.title', 'views.trace.subtitle'],
    settings: ['views.settings.title', 'views.settings.subtitle'],
};

const I18N = {
    zh: {
        app: { name: '阿安的工作台' },
        nav: { chat: 'Super Chat', pulse: 'Pulse', agents: 'Agents', tools: 'Tools', trace: 'Trace', runs: 'Runs', settings: 'Settings' },
        sidebar: {
            navigation: '导航',
            pinned: '固定 Agent',
            recent: '最近会话',
            fullConfig: '完整配置',
            modelSelect: '模型选择',
            defaultModel: '默认模型',
            emptyConversations: '暂无会话',
            emptyPinned: '在 Agents 中固定常用功能',
        },
        topbar: { agent: 'Agent' },
        account: {
            label: '帐号',
            add: '新帐号',
            loginTitle: '选择帐号',
            existing: '已有帐号',
            enter: '进入',
            newName: '新帐号',
            password: '密码',
            namePlaceholder: '输入帐号名',
            passwordPlaceholder: '输入密码',
            create: '创建并进入',
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
            delete: '删除',
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
            copyAnswer: '复制回答',
            copied: '已复制',
            copyFailed: '复制失败',
            confirmDeleteConversation: '确定删除这个会话及其全部消息吗？',
            confirmDeleteTopic: '确定删除 Topic「{name}」吗？',
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
            pulse: { title: 'Pulse', subtitle: '每日推荐、Topic 订阅与预计算知识入口' },
            agents: { title: 'Agents', subtitle: 'Agent 功能入口、实现版本和能力状态' },
            tools: { title: 'Tools', subtitle: '内置工具、参数和调用状态' },
            runs: { title: 'Runs', subtitle: '执行轨迹、事件和调试信息' },
            trace: { title: 'Trace', subtitle: '层级事件、节点详情与调试定位' },
            settings: { title: 'Settings', subtitle: '模型、密钥和系统配置摘要' },
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
            placeholder: '输入任务，Cmd/Ctrl + Enter 发送',
            currentConversation: '当前会话',
            loadConversationFailed: '加载会话失败：{message}',
            createConversationFailed: '创建会话失败：{message}',
            resumePending: 'AI 仍在生成，完成后会自动恢复到当前会话',
            citations: '引用来源',
        },
        pulse: {
            topicsTitle: 'Topic 订阅',
            topicsSubtitle: '每天为订阅主题预生成学习入口',
            topicName: 'Topic',
            topicPlaceholder: '例如：AI 应用开发',
            keywords: '关键词',
            keywordsPlaceholder: 'Agent, RAG, 多模态',
            subscribe: '订阅',
            subscribing: '订阅中...',
            refresh: '刷新今日推荐',
            todayTitle: '今日 Pulse',
            generatedAt: '已预计算：{time}',
            neverGenerated: '等待生成',
            loading: '正在加载 Pulse...',
            emptyTitle: '还没有推荐',
            emptyDetail: '添加一个 Topic 或刷新今日推荐。',
            emptyTopics: '还没有订阅 Topic',
            emptyModule: '这个模块暂时没有推荐',
            subscribed: '订阅',
            hot: '热度',
            heat: '热度 {score}',
            expand: '展开',
            collapse: '收起',
            ask: '继续聊',
            reason: '推荐理由',
            signals: '依据线索',
            quickContext: '背景',
            keyPoints: '关键点',
            newsSources: '新闻来源',
            suggestedQuestions: '可以追问',
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
                knowledge_qa: ['智能问答', '必须输出结论 / 依据 / 不确定性'],
                research: ['研究', '拆解问题、对比来源、标明证据'],
                plan: ['计划模式', '必须输出计划、风险和下一步'],
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
                research: ['研究实验', 'LangGraph、CrewAI、AutoGen 等框架实验'],
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
            currentAgent: '当前 Agent：{name}',
            enterAgent: '进入当前 Agent',
            routePrompt: '帮我判断这个任务应该由哪个 Agent 处理，并给出回答：',
            planPrompt: '总结一下这个任务：先识别意图，再说明应该调用哪个 Agent，最后给出答复。',
            superPlan: 'Super Chat 规划',
            calculator: '工具计算',
            time: '时间工具',
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
        nav: { chat: 'Super Chat', pulse: 'Pulse', agents: 'Agents', tools: 'Tools', trace: 'Trace', runs: 'Runs', settings: 'Settings' },
        sidebar: {
            navigation: 'Navigation',
            pinned: 'Pinned Agents',
            recent: 'Recent Chats',
            fullConfig: 'Full Settings',
            modelSelect: 'Model selection',
            defaultModel: 'Default Model',
            emptyConversations: 'No conversations',
            emptyPinned: 'Pin frequent agents from Agents',
        },
        topbar: { agent: 'Agent' },
        account: {
            label: 'Account',
            add: 'New account',
            loginTitle: 'Choose Account',
            existing: 'Existing account',
            enter: 'Enter',
            newName: 'New account',
            password: 'Password',
            namePlaceholder: 'Account name',
            passwordPlaceholder: 'Password',
            create: 'Create and enter',
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
            delete: 'Delete',
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
            copyAnswer: 'Copy Answer',
            copied: 'Copied',
            copyFailed: 'Copy Failed',
            confirmDeleteConversation: 'Delete this conversation and all of its messages?',
            confirmDeleteTopic: 'Delete topic "{name}"?',
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
            pulse: { title: 'Pulse', subtitle: 'Daily recommendations, topic subscriptions, and precomputed knowledge cards' },
            agents: { title: 'Agents', subtitle: 'Agent entry points, runtimes, and capability status' },
            tools: { title: 'Tools', subtitle: 'Built-in tools, parameters, and execution status' },
            runs: { title: 'Runs', subtitle: 'Execution traces, events, and debugging details' },
            trace: { title: 'Trace', subtitle: 'Hierarchical events, node details, and debugging context' },
            settings: { title: 'Settings', subtitle: 'Model, key, and system configuration summary' },
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
            placeholder: 'Type a task. Cmd/Ctrl + Enter to send',
            currentConversation: 'Current conversation',
            loadConversationFailed: 'Failed to load conversation: {message}',
            createConversationFailed: 'Failed to create conversation: {message}',
            resumePending: 'AI is still generating. The answer will reappear here when it finishes.',
            citations: 'Sources',
        },
        pulse: {
            topicsTitle: 'Topic Subscriptions',
            topicsSubtitle: 'Precomputed daily learning entries for topics you follow',
            topicName: 'Topic',
            topicPlaceholder: 'Example: AI app development',
            keywords: 'Keywords',
            keywordsPlaceholder: 'Agents, RAG, multimodal',
            subscribe: 'Subscribe',
            subscribing: 'Subscribing...',
            refresh: 'Refresh Today',
            todayTitle: "Today's Pulse",
            generatedAt: 'Precomputed: {time}',
            neverGenerated: 'Waiting to generate',
            loading: 'Loading Pulse...',
            emptyTitle: 'No recommendations yet',
            emptyDetail: 'Add a topic or refresh today.',
            emptyTopics: 'No topic subscriptions yet',
            emptyModule: 'No recommendations in this module yet',
            subscribed: 'Topic',
            hot: 'Hot',
            heat: 'Heat {score}',
            expand: 'Expand',
            collapse: 'Collapse',
            ask: 'Ask',
            reason: 'Why this',
            signals: 'Signals',
            quickContext: 'Context',
            keyPoints: 'Key Points',
            newsSources: 'News Sources',
            suggestedQuestions: 'Suggested Questions',
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
                knowledge_qa: ['Knowledge Q&A', 'Must show answer, evidence, uncertainty'],
                research: ['Research', 'Break down, compare sources, cite evidence'],
                plan: ['Plan Mode', 'Must show plan, risks, next action'],
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
                research: ['Research Experiments', 'LangGraph, CrewAI, AutoGen, and runtime trials'],
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
            currentAgent: 'Current Agent: {name}',
            enterAgent: 'Enter Current Agent',
            routePrompt: 'Help me decide which Agent should handle this task, then answer it: ',
            planPrompt: 'Summarize this task: identify intent, choose the right Agent, then provide an answer.',
            superPlan: 'Super Chat Plan',
            calculator: 'Tool Calculation',
            time: 'Time Tool',
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
        id: 'knowledge_qa',
        prompts: {
            zh: '【智能问答】本轮必须用清晰可见的问答结构输出：先给“结论”，再给“依据”，最后给“需要确认/不确定性”。如果问题不需要检索，直接基于当前上下文回答；如果需要事实、最新信息或外部资料，优先使用可用搜索工具或说明无法验证。不要只说自己处于智能问答模式。',
            en: '[Knowledge Q&A] For this turn, the visible answer must include: "Answer", "Evidence", and "Uncertainty / Needs confirmation". If retrieval is unnecessary, answer from the current context; if factual, current, or external information is needed, use available search tools or state what cannot be verified. Do not merely announce the mode.',
        },
    },
    {
        id: 'research',
        prompts: {
            zh: '【研究】本轮必须先拆解研究问题，再收集/对比可靠信息。遇到时效性、事实性或外部资料问题时优先搜索，尽量使用多组不同查询并把 search limit 提高到 12-20；至少比较多个来源，保留可引用 URL、关键数字、日期和不确定性。输出时包含“问题拆解”“关键发现”“证据强度/来源”“下一步验证”。如果不能检索，明确标注依据限制。',
            en: '[Research] For this turn, break down the research question first, then gather and compare reliable information. For time-sensitive, factual, or external-information topics, search first, use several distinct queries when useful, and raise search limit to 12-20. Compare multiple sources and keep citable URLs, key numbers, dates, and uncertainty. The visible answer must include "Question breakdown", "Key findings", "Evidence strength / sources", and "Next verification". If retrieval is unavailable, state the evidence limits.',
        },
    },
    {
        id: 'plan',
        prompts: {
            zh: '【计划模式】本轮必须让用户看见计划。回答开头输出“计划”小节，包含目标、分阶段步骤、依赖/风险、下一步行动。若用户要的是执行结果，也先给一个简短计划，再给执行结果；不要把计划藏在思考里。',
            en: '[Plan Mode] For this turn, the user must see the plan. Start with a visible "Plan" section containing the goal, staged steps, dependencies / risks, and next action. If the user asks for an execution result, give a compact plan first, then the result. Do not hide the plan in internal reasoning.',
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
    if (currentAgentId === 'image_generation_v1') return [];
    if (currentAgentId === 'weight_loss_v1') return [];
    return SUPER_CHAT_MODES;
}

function allModes() {
    return [...SUPER_CHAT_MODES, ...IMAGE_CHAT_MODES];
}

const MAX_TEXT_ATTACHMENT_BYTES = 1024 * 1024;
const MAX_MEDIA_ATTACHMENT_BYTES = 8 * 1024 * 1024;
const MAX_ATTACHMENT_CHARS = 12000;
const MAX_TOTAL_ATTACHMENT_CHARS = 24000;
const ACTIVE_RUN_POLL_MS = 1500;
const ACTIVE_RUN_MAX_POLLS = 240;
const TEXT_ATTACHMENT_EXTENSIONS = new Set([
    'txt', 'md', 'markdown', 'csv', 'tsv', 'json', 'jsonl', 'yaml', 'yml',
    'xml', 'html', 'htm', 'log', 'ini', 'toml', 'env',
    'js', 'jsx', 'ts', 'tsx', 'css', 'scss', 'less',
    'py', 'go', 'java', 'c', 'h', 'cpp', 'hpp', 'cs', 'rs', 'rb', 'php',
    'sh', 'bash', 'zsh', 'sql',
]);
const IMAGE_ATTACHMENT_EXTENSIONS = new Set(['png', 'jpg', 'jpeg', 'webp', 'gif', 'avif', 'bmp', 'heic', 'heif', 'svg']);
const AUDIO_ATTACHMENT_EXTENSIONS = new Set(['mp3', 'wav', 'm4a', 'aac', 'ogg', 'flac', 'webm']);
const VIDEO_ATTACHMENT_EXTENSIONS = new Set(['mp4', 'mov', 'webm', 'm4v', 'avi', 'mkv', 'ogv']);

let activeView = 'chat';
let currentConversationId = null;
let conversations = [];
let agents = [];
let tools = [];
let runs = [];
let settings = {};
let health = null;
let pulse = { date: '', generated_at: '', topics: [], items: [] };
let currentLanguage = localStorage.getItem(LANGUAGE_KEY) || 'zh';
let currentUserId = loadCurrentUserId();
let currentAccountToken = '';
let accounts = [];
let currentAgentId = 'super_chat';
let selectedRunId = '';
let selectedTraceNodeId = '';
let selectedTraceRunId = '';
let collapsedTraceNodeIds = new Set();
let expandedTraceNodeIds = new Set();
let defaultModelText = '';
const activeConversationRequests = new Set();
const pendingConversationDeletes = new Set();
const pendingPulseTopicDeletes = new Set();
let toolsError = '';
let runsError = '';
let pulseError = '';
let pulseErrorType = 'load';
let pulseTopicSubmitting = false;
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
let userQuestionHistory = [];
let questionHistoryIndex = -1;
let questionHistoryDraft = '';
let applyingQuestionHistory = false;

const sidebar = document.getElementById('sidebar');
const sidebarBackdrop = document.getElementById('sidebar-backdrop');
const accountSelect = document.getElementById('account-select');
const btnAddAccount = document.getElementById('btn-add-account');
const accountLogin = document.getElementById('account-login');
const loginAccountSelect = document.getElementById('login-account-select');
const loginPasswordInput = document.getElementById('login-password-input');
const btnAccountLogin = document.getElementById('btn-account-login');
const accountCreateForm = document.getElementById('account-create-form');
const accountNameInput = document.getElementById('account-name-input');
const accountPasswordInput = document.getElementById('account-password-input');
const accountLoginError = document.getElementById('account-login-error');
const conversationList = document.getElementById('conversation-list');
const messagesContainer = document.getElementById('messages');
const messageInput = document.getElementById('message-input');
const btnSend = document.getElementById('btn-send');
const btnNewChat = document.getElementById('btn-new-chat');
const btnToggleSidebar = document.getElementById('btn-toggle-sidebar');
const btnRefresh = document.getElementById('btn-refresh');
const modelSelect = document.getElementById('model-select');
const currentModelEl = document.getElementById('current-model');
const agentSelect = document.getElementById('agent-select');
const viewTitle = document.getElementById('view-title');
const viewSubtitle = document.getElementById('view-subtitle');
const systemStatus = document.getElementById('system-status');
const agentCount = document.getElementById('agent-count');
const toolCount = document.getElementById('tool-count');
const runCount = document.getElementById('run-count');
const pinnedAgentList = document.getElementById('pinned-agent-list');
const navSectionCount = document.getElementById('nav-section-count');
const pinnedSectionCount = document.getElementById('pinned-section-count');
const conversationSectionCount = document.getElementById('conversation-section-count');
const agentsGrid = document.getElementById('agents-grid');
const toolsGrid = document.getElementById('tools-grid');
const runList = document.getElementById('run-list');
const runDetail = document.getElementById('run-detail');
const settingsGrid = document.getElementById('settings-grid');
const pulseTopicForm = document.getElementById('pulse-topic-form');
const pulseTopicInput = document.getElementById('pulse-topic-input');
const pulseKeywordsInput = document.getElementById('pulse-keywords-input');
const pulseTopicList = document.getElementById('pulse-topic-list');
const pulseItems = document.getElementById('pulse-items');
const pulseDateTitle = document.getElementById('pulse-date-title');
const pulseGeneratedAt = document.getElementById('pulse-generated-at');
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
    document.querySelectorAll('[data-copy-answer]').forEach(resetCopyButtonFeedback);
    if (languageToggle) languageToggle.textContent = currentLanguage === 'zh' ? 'EN' : '中';
}

function setLanguage(language) {
    currentLanguage = language;
    localStorage.setItem(LANGUAGE_KEY, currentLanguage);
    applyI18n();
    renderHealth();
    renderConversationList();
    renderAgentSelect();
    renderPinnedAgents();
    renderAgents();
    renderAgentCommandBar();
    renderModes();
    renderTools();
    renderRuns();
    renderSettings();
    renderPulse();
    renderAccountControls();
    renderModelSelect();
    updateTopbar();
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
    const allowed = ['nav', 'pinned', 'conversations'];
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

function loadSelectedModes() {
    try {
        const raw = localStorage.getItem(MODE_STORAGE_KEY);
        const parsed = JSON.parse(raw || '[]');
        if (!Array.isArray(parsed)) return [];
        const allowed = new Set(allModes().map((mode) => mode.id));
        return parsed.filter((id) => allowed.has(id));
    } catch {
        return [];
    }
}

function saveSelectedModes() {
    localStorage.setItem(MODE_STORAGE_KEY, JSON.stringify(selectedModeIds));
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

function showAccountLogin(message = '', selectedUserId = '') {
    if (!accountLogin) return;
    accountLogin.classList.remove('hidden');
    document.body.classList.add('account-login-open');
    if (accountLoginError) accountLoginError.textContent = message || '';
    renderAccountControls();
    if (selectedUserId && loginAccountSelect && accounts.some((account) => account.id === selectedUserId)) {
        loginAccountSelect.value = selectedUserId;
    }
    if (loginPasswordInput) loginPasswordInput.value = '';
    requestAnimationFrame(() => {
        if (accounts.length && loginPasswordInput) {
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
    currentConversationId = loadCurrentConversationId();
    conversations = [];
    runs = [];
    pulse = { date: '', generated_at: '', topics: [], items: [] };
    runsError = '';
    pulseError = '';
    pulseErrorType = 'load';
    pulseTopicSubmitting = false;
    selectedRunId = '';
    selectedTraceNodeId = '';
    selectedTraceRunId = '';
    expandedPulseItemIds = new Set();
    clearQuestionHistory();
    clearAttachments();
    messageInput.value = '';
    autoResizeInput();
    updateSendState();
    renderAccountControls();
    renderConversationList();
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
    const fallback = I18N.en.modes.items[mode.id] || [mode.id, ''];
    const localized = I18N[currentLanguage].modes.items[mode.id] || fallback;
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
    if (modeChips) {
        modeChips.innerHTML = renderInputContextChips(activeModes);
        modeChips.hidden = activeModes.length === 0 && attachedContexts.length === 0;
    }
    if (modeCount) {
        modeCount.textContent = activeModes.length ? String(activeModes.length) : '';
    }
    if (btnModeToggle) {
        const names = activeModes.map((mode) => modeCopy(mode).name).join(', ');
        btnModeToggle.classList.toggle('active', activeModes.length > 0);
        btnModeToggle.title = activeModes.length ? t('modes.active', { names }) : t('modes.toggle');
    }
}

function renderInputContextChips(activeModes = getSelectedModes()) {
    const modeItems = activeModes.map((mode) => {
        const copy = modeCopy(mode);
        return `<span class="mode-chip" title="${escapeAttr(copy.detail)}">${escapeHtml(copy.name)}</span>`;
    });
    const attachmentItems = attachedContexts.map(renderAttachmentChip);
    return [...modeItems, ...attachmentItems].join('');
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
    const allowed = availableModes().some((mode) => mode.id === modeId);
    if (!allowed) return;
    if (selected) {
        selectedModeIds = Array.from(new Set([...selectedModeIds, modeId]));
    } else {
        selectedModeIds = selectedModeIds.filter((id) => id !== modeId);
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

function isReadableAttachment(file) {
    const type = (file.type || '').toLowerCase();
    if (type.startsWith('text/')) return true;
    if (['application/json', 'application/xml', 'application/x-yaml', 'application/yaml'].includes(type)) {
        return true;
    }
    const ext = fileExtension(file.name);
    return TEXT_ATTACHMENT_EXTENSIONS.has(ext);
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
}

function clearAttachments() {
    attachedContexts = [];
    renderModes();
    updateSendState();
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
    renderConversationList();
    updateTopbar();
}

async function createConversation() {
    const conv = await apiCall('POST', '/api/conversations', { user_id: currentUserId });
    conversations.unshift(conv);
    currentConversationId = conv.id;
    saveCurrentConversationId(currentConversationId);
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

async function loadTools() {
    toolsError = '';
    try {
        const data = await apiCall('GET', '/api/tools');
        tools = data.skills || data.tools || [];
    } catch (err) {
        tools = [];
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
}

async function createPulseTopic() {
    if (!pulseTopicInput || pulseTopicSubmitting) return;
    const name = pulseTopicInput.value.trim();
    if (!name) {
        pulseError = t('pulse.topicRequired');
        pulseErrorType = 'create';
        renderPulse();
        pulseTopicInput.focus();
        return;
    }

    const keywords = parsePulseKeywords(pulseKeywordsInput?.value || '');
    pulseTopicSubmitting = true;
    updatePulseTopicSubmitState();
    try {
        const data = await apiCall('POST', '/api/pulse/topics', { name, keywords });
        upsertPulseTopic(data.topic);
        pulseError = '';
        pulseErrorType = 'load';
        pulseTopicInput.value = '';
        if (pulseKeywordsInput) pulseKeywordsInput.value = '';
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
    return String(value)
        .split(/[,\n，;；]/)
        .map((item) => item.trim())
        .filter(Boolean);
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
        loadAgents(),
        loadTools(),
        loadRuns(),
        loadSettings(),
        loadPulse(),
    ]);
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
    document.querySelectorAll('[data-view-panel]').forEach((panel) => {
        panel.classList.toggle('active', panel.dataset.viewPanel === view);
    });

    updateTopbar();
    if (view === 'trace' && !options.skipLoad) loadRuns();
    if (view === 'tools') renderTools();
    if (view === 'agents') renderAgents();
    if (view === 'settings') renderSettings();
    if (view === 'pulse') {
        renderPulse();
        if (!pulse.items.length && !pulseError) loadPulse();
    }
    if (view === 'chat' && options.restore !== false) ensureCurrentConversationVisible();
    if (options.closeSidebar !== false) closeMobileSidebar();
}

function updateTopbar() {
    const copy = VIEW_COPY[activeView] || VIEW_COPY.chat;

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
    toolCount.textContent = tools.length ? String(tools.length) : '';
    runCount.textContent = runs.length ? String(runs.length) : '';
    if (navSectionCount) {
        const navItems = document.querySelectorAll('#sidebar-nav .nav-item').length;
        navSectionCount.textContent = navItems ? String(navItems) : '';
    }
    if (pinnedSectionCount) pinnedSectionCount.textContent = pinnedAgentIds.length ? String(pinnedAgentIds.length) : '';
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
        pulseGeneratedAt.textContent = pulse.generated_at
            ? t('pulse.generatedAt', { time: formatFullTime(pulse.generated_at) })
            : t('pulse.neverGenerated');
    }

    renderPulseTopics();

    if (pulseError) {
        pulseItems.innerHTML = emptyState(formatPulseError(), '');
        return;
    }

    const items = Array.isArray(pulse.items) ? pulse.items : [];
    if (!items.length) {
        pulseItems.innerHTML = emptyState(t('pulse.emptyTitle'), t('pulse.emptyDetail'));
        return;
    }

    pulseItems.innerHTML = renderPulseModules(items, pulse.modules || []);
}

function formatPulseError() {
    const key = pulseErrorType === 'create'
        ? 'pulse.createFailed'
        : pulseErrorType === 'delete'
            ? 'pulse.deleteFailed'
            : 'pulse.loadFailed';
    return t(key, { message: pulseError });
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
        const moduleItems = Array.isArray(module.items)
            ? module.items
            : items.filter((item) => item.source === module.key);
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
        return `
            <div class="pulse-topic-item ${topic.enabled ? '' : 'muted'}">
                <div class="pulse-topic-copy">
                    <strong>${escapeHtml(topic.name || '')}</strong>
                    <span>${keywords.map(escapeHtml).join(' / ') || escapeHtml(t('pulse.subscribed'))}</span>
                </div>
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

function renderPulseCard(item) {
    const expanded = expandedPulseItemIds.has(item.id);
    const sourceLabel = pulseSourceLabel(item.source);
    const detail = item.detail || {};
    const topicLabel = item.topic_name || item.category || sourceLabel;
    const chatPrompt = buildPulseChatPrompt(item);
    return `
        <article class="pulse-card ${expanded ? 'expanded' : ''}">
            <div class="pulse-card-topline">
                <span class="status-chip ${pulseSourceTone(item.source)}">${escapeHtml(sourceLabel)}</span>
                <span class="status-chip neutral">${escapeHtml(topicLabel)}</span>
                <span class="pulse-heat">${escapeHtml(t('pulse.heat', { score: item.heat_score || 0 }))}</span>
            </div>
            <h3>${escapeHtml(item.title || '')}</h3>
            <p>${escapeHtml(item.summary || '')}</p>
            <div class="pulse-card-actions">
                <button class="btn-secondary" type="button" data-pulse-toggle-item="${escapeAttr(item.id)}">
                    <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.3">
                        ${expanded ? '<path d="M5 12h14"/>' : '<path d="M12 5v14M5 12h14"/>'}
                    </svg>
                    <span>${escapeHtml(expanded ? t('pulse.collapse') : t('pulse.expand'))}</span>
                </button>
                <button class="btn-secondary" type="button" data-pulse-chat="${escapeAttr(chatPrompt)}">
                    <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.2">
                        <path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4Z"/>
                    </svg>
                    <span>${escapeHtml(t('pulse.ask'))}</span>
                </button>
            </div>
            ${expanded ? renderPulseDetail(item, detail) : ''}
        </article>
    `;
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
        </div>
    `;
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

    return lines.join('\n');
}

function renderTools() {
    if (toolsError) {
        toolsGrid.innerHTML = emptyState(t('tools.unavailableTitle'), toolsError);
        return;
    }
    if (!tools.length) {
        toolsGrid.innerHTML = emptyState(t('tools.emptyTitle'), t('tools.emptyDetail'));
        return;
    }

    toolsGrid.innerHTML = tools.map((tool) => {
        const params = Array.isArray(tool.parameters) ? tool.parameters : [];
        const tags = Array.isArray(tool.tags) ? tool.tags : [];
        const enabled = tool.enabled !== false;
        return `
            <article class="data-card tool-card">
                <div class="card-topline">
                    <span class="status-dot ${enabled ? 'ok' : 'warn'}"></span>
                    <span class="mono">${escapeHtml(tool.name || '')}</span>
                    ${tool.version ? `<span class="status-chip neutral">v${escapeHtml(tool.version)}</span>` : ''}
                    <span class="status-chip ${enabled ? 'ok' : 'warn'}">${enabled ? 'enabled' : 'disabled'}</span>
                </div>
                <h2>${escapeHtml(tool.name || t('tools.unnamed'))}</h2>
                <p>${escapeHtml(tool.description || '')}</p>
                <div class="chip-row">${tags.map((tag) => `<span class="chip">${escapeHtml(tag)}</span>`).join('')}</div>
                ${tool.source ? `<div class="meta-row"><span>${escapeHtml(tool.source)}</span></div>` : ''}
                ${renderParameters(params)}
            </article>
        `;
    }).join('');
}

function renderParameters(params) {
    if (!params.length) return `<div class="param-list empty">${escapeHtml(t('tools.noParams'))}</div>`;
    return `
        <div class="param-list">
            ${params.map((param) => `
                <div class="param-item">
                    <span class="param-name">${escapeHtml(param.name || '')}</span>
                    <span class="param-type">${escapeHtml(param.type || 'string')}</span>
                    ${param.required ? '<span class="param-required">required</span>' : ''}
                    <p>${escapeHtml(param.description || '')}</p>
                </div>
            `).join('')}
        </div>
    `;
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
        const statusClass = run.status === 'completed' ? 'ok' : (run.status === 'failed' ? 'error' : 'warn');
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

    runDetail.innerHTML = `
        <article class="run-panel trace-page-panel">
            <div class="trace-run-summary">
                <div class="run-panel-head">
                    <div>
                        <span class="mono">${escapeHtml(run.run_id || '')}</span>
                        <h2>${escapeHtml(run.agent_id || 'agent')}</h2>
                    </div>
                    <span class="status-chip ${run.status === 'completed' ? 'ok' : (run.status === 'failed' ? 'error' : 'warn')}">${escapeHtml(run.status || '')}</span>
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

    if (type === 'aigc.plan.created') {
        const planNode = ensurePlanNode(state);
        registerPlanSteps(state, payload.steps || []);
        addTraceEventLeaf(state, planNode, event, index);
        return;
    }

    if (type.startsWith('aigc.plan.step.')) {
        const stepNode = ensurePlanStepNode(state, payload.step || event.step_id || 'unknown');
        addTraceEventLeaf(state, stepNode, event, index);
        return;
    }

    if (type === 'aigc.plan.completed') {
        addTraceEventLeaf(state, ensurePlanNode(state), event, index);
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
        const stage = ensureExecutionStageNode(state);
        const modelNode = ensureModelNode(state, stage, event, 'main');
        addTraceEventLeaf(state, modelNode, event, index);
        registerToolParentsFromModelEvent(state, event, modelNode);
        return;
    }

    if (type.startsWith('tool.')) {
        const parent = toolParentNode(state, event) || ensureExecutionStageNode(state);
        const toolNode = ensureToolNode(state, parent, event);
        addTraceEventLeaf(state, toolNode, event, index);
        return;
    }

    if (type.startsWith('citations.')) {
        const toolParent = toolParentNode(state, event);
        const citationParent = toolParent || ensureStageNode(
            state,
            state.root,
            'citations',
            traceCopy('来源整理', 'Citations'),
            'citations',
        );
        addTraceEventLeaf(state, citationParent, event, index);
        return;
    }

    if (type === 'agent.delegated') {
        addTraceEventLeaf(
            state,
            ensureStageNode(state, state.root, 'routing', traceCopy('Agent 路由', 'Agent Routing'), payload.target_agent_id || ''),
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
        addTraceEventLeaf(
            state,
            ensureStageNode(
                state,
                state.root,
                'context',
                traceCopy('上下文与记忆', 'Context & Memory'),
                traceCopy('角色记忆、Prompt 和会话上下文', 'Role memory, prompt, and conversation context'),
                { stageType: 'context' },
            ),
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

function ensurePlanNode(state) {
    if (!state.planNode) {
        state.planNode = ensureTraceChild(state, state.root, `${state.root.id}:plan:aigc`, {
            kind: 'plan',
            label: t('trace.plan'),
            detail: '',
            meta: { steps: [], run: state.run },
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
    if (type === 'run.failed') return { label: traceCopy('Run 失败', 'Run failed'), detail: payload.error_message || payload.error_type || '' };
    if (type === 'agent.delegated') return { label: traceCopy('转交给专业 Agent', 'Delegated to specialist agent'), detail: payload.reason || payload.target_agent_id || '' };
    if (type === 'agent.command.routed') return { label: traceCopy('路由 Agent 命令', 'Routed agent command'), detail: `${payload.target_agent_id || ''} ${payload.command_text || ''}`.trim() };
    if (type === 'memory.loaded') return { label: traceCopy('读取角色记忆', 'Loaded role memory'), detail: traceCopy(`长期 ${payload.long_term_count || 0} / 人设 ${payload.persona_count || 0}`, `Long-term ${payload.long_term_count || 0} / persona ${payload.persona_count || 0}`) };
    if (type === 'context.built') return { label: traceCopy('构建 Prompt 上下文', 'Built prompt context'), detail: traceCopy(`${payload.message_count || 0} 条消息 / ${payload.tools_count || 0} 个工具`, `${payload.message_count || 0} messages / ${payload.tools_count || 0} tools`) };
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
            <span class="status-chip ${run.status === 'completed' ? 'ok' : (run.status === 'failed' ? 'error' : 'warn')}">${escapeHtml(run.status || '')}</span>
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
        ${contextEvent?.payload?.system_prompt ? renderTraceTextSection('System Prompt', contextEvent.payload.system_prompt) : ''}
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
    if (normalized === 'error') return 'error';
    return '';
}

function traceStatusChipClass(status) {
    const normalized = normalizeTraceStatus(status);
    if (normalized === 'completed') return 'ok';
    if (normalized === 'error') return 'error';
    if (normalized === 'running') return 'warn';
    return 'neutral';
}

function renderSettings() {
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
    const starter = currentAgent?.metadata?.starter_prompt || '';
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
        : [
            {
                label: t('welcome.enterAgent'),
                query: starter || t('welcome.routePrompt'),
            },
            {
                label: t('welcome.superPlan'),
                query: t('welcome.planPrompt'),
            },
            {
                label: t('welcome.calculator'),
                query: 'Calculate 1024 * 768 / 3.14',
            },
            {
                label: t('welcome.time'),
                query: 'What time is it now?',
            },
        ];
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
            <p class="welcome-sub">${escapeHtml(t('welcome.currentAgent', { name: getCurrentAgentName() }))}</p>
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
        </div>
    `;
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
    try {
        const data = await loadConversation(id);
        if (currentConversationId !== id) return;
        if (activeRunWatcher && activeRunWatcher.conversationId !== id) {
            stopActiveRunWatcher();
        }
        messagesContainer.innerHTML = '';
        const messages = data.messages || [];
        const runMatches = await loadConversationRunMatches(id, messages);
        if (currentConversationId !== id) return;
        syncQuestionHistoryFromMessages(messages);
        syncAgentToConversation(messages, runMatches);
        if (!messages.length) {
            showWelcome();
        } else {
            messages.forEach((msg, index) => {
                const matchedRun = runMatches.get(index);
                const skillsUsed = parseSkills(msg.skills_used);
                const citations = parseCitations(msg.citations);
                const savedTraceEvents = parseTraceEvents(msg.trace_events);
                const savedRun = runRecordFromMessage(msg, skillsUsed, savedTraceEvents, matchedRun);
                if (savedRun) mergeRuns([savedRun]);
                const traceRun = savedRun || matchedRun;
                appendMessage(
                    msg.role,
                    msg.content,
                    skillsUsed,
                    msg.model_used || traceRun?.model_used || '',
                    msg.error_type || '',
                    savedTraceEvents.length ? savedTraceEvents : (traceRun?.events || []),
                    msg.run_id || traceRun?.run_id || '',
                    msg.runtime || traceRun?.runtime || '',
                    citations
                );
            });
            scrollToBottom();
        }
        if (options.watchActiveRuns !== false) {
            watchActiveRunForConversation(id, messages);
        }
    } catch (err) {
        appendMessage('assistant', t('chat.loadConversationFailed', { message: err.message }), [], '', 'error');
    }

    updateTopbar();
    focusMessageInput();
}

async function loadConversationRunMatches(id, messages = []) {
    const hasAssistantMessages = messages.some((msg) => msg.role === 'assistant');
    if (!id || !hasAssistantMessages) return new Map();

    try {
        const data = await apiCall('GET', `/api/runs?conversation_id=${encodeURIComponent(id)}&limit=50`);
        const conversationRuns = data.runs || [];
        mergeRuns(conversationRuns);
        return matchRunsToAssistantMessages(messages, conversationRuns);
    } catch {
        return new Map();
    }
}

function matchRunsToAssistantMessages(messages = [], conversationRuns = []) {
    const matches = new Map();
    const runsById = new Map((conversationRuns || [])
        .filter((run) => run?.run_id)
        .map((run) => [run.run_id, run]));
    const availableRuns = [...(conversationRuns || [])]
        .filter((run) => run?.run_id)
        .sort((a, b) => new Date(a.started_at || 0) - new Date(b.started_at || 0));
    const usedRunIds = new Set();

    messages.forEach((msg, index) => {
        if (msg.role !== 'assistant') return;

        if (msg.run_id && runsById.has(msg.run_id)) {
            const run = runsById.get(msg.run_id);
            matches.set(index, run);
            usedRunIds.add(run.run_id);
            return;
        }

        const content = normalizeComparableText(msg.content);
        if (!content) return;

        const run = availableRuns.find((item) => {
            if (usedRunIds.has(item.run_id)) return false;
            return normalizeComparableText(item.output || item.error_message) === content;
        });
        if (run) {
            matches.set(index, run);
            usedRunIds.add(run.run_id);
        }
    });

    return matches;
}

function normalizeComparableText(value = '') {
    return String(value || '').replace(/\s+/g, ' ').trim();
}

function runRecordFromMessage(msg = {}, skillsUsed = [], traceEvents = [], fallbackRun = null) {
    const runId = msg.run_id || fallbackRun?.run_id || '';
    if (!runId || !traceEvents.length) return null;

    const failed = traceEvents.some((event) => event?.type === 'run.failed' || normalizeTraceStatus(event?.status) === 'error');
    const completed = traceEvents.some((event) => event?.type === 'run.completed');
    const status = failed ? 'failed' : (completed ? 'completed' : (fallbackRun?.status || 'completed'));

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
    }
    for (const event of reversed) {
        const payload = event?.payload || {};
        if (event?.type === 'run.started' && payload.agent_id) return payload.agent_id;
    }
    return '';
}

function inferConversationAgentId(messages = [], runMatches = new Map()) {
    for (let index = messages.length - 1; index >= 0; index -= 1) {
        const msg = messages[index];
        if (msg?.role !== 'assistant') continue;
        const matchedRun = runMatches.get(index);
        if (matchedRun?.agent_id) return matchedRun.agent_id;
        const traceAgentId = inferAgentIdFromTraceEvents(parseTraceEvents(msg.trace_events));
        if (traceAgentId) return traceAgentId;
    }
    return '';
}

function agentIsSelectable(agentId) {
    return agents.some((agent) => agent.id === agentId && agent.enabled);
}

function setCurrentAgent(agentId, { refreshWelcome = false } = {}) {
    const nextAgentId = agentId || 'super_chat';
    if (!agentIsSelectable(nextAgentId) && nextAgentId !== 'super_chat') return false;
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

function syncAgentToConversation(messages = [], runMatches = new Map()) {
    const conversationAgentId = inferConversationAgentId(messages, runMatches);
    if (!conversationAgentId || conversationAgentId === currentAgentId) return;
    setCurrentAgent(conversationAgentId);
}

function stopActiveRunWatcher() {
    if (activeRunWatcher?.timer) clearTimeout(activeRunWatcher.timer);
    activeRunWatcher = null;
}

function runIsActive(run) {
    return run && run.status && run.status !== 'completed' && run.status !== 'failed';
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

        const streamView = appendStreamingAssistantMessage();
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
    const streamView = appendStreamingAssistantMessage();
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
        tokens_used: run.tokens_used || {},
        agent_id: run.agent_id || currentAgentId,
    };
}

async function selectConversation(id) {
    stopActiveRunWatcher();
    currentConversationId = id;
    saveCurrentConversationId(id);
    setView('chat', { restore: false });
    renderConversationList();
    await renderConversationMessages(id);
}

async function restoreInitialConversation() {
    const storedValue = localStorage.getItem(CURRENT_CONVERSATION_STORAGE_KEY);
    const hasStoredPreference = storedValue !== null;
    const storedConversationExists = currentConversationId
        && conversations.some((conv) => conv.id === currentConversationId);

    if (!storedConversationExists && !hasStoredPreference && conversations.length) {
        currentConversationId = conversations[0].id;
        saveCurrentConversationId(currentConversationId);
    }

    if (currentConversationId && conversations.some((conv) => conv.id === currentConversationId)) {
        renderConversationList();
        await renderConversationMessages(currentConversationId);
    } else {
        currentConversationId = null;
        saveCurrentConversationId(null);
        stopActiveRunWatcher();
        clearQuestionHistory();
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
	setCurrentAgent('super_chat');
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
    appendQuestionHistory(query);
    updateSendState();
    messageInput.value = '';
    autoResizeInput();

    const modeMeta = getSelectedModes().map((mode) => ({ id: mode.id, name: modeCopy(mode).name }));
    appendMessage('user', query, [], '', '', [], '', '', [], {
        modes: modeMeta,
        attachments: attachmentSummary(attachmentsForTurn),
    });
    const streamView = appendStreamingAssistantMessage();
    clearAttachments();
    scrollToBottom();

    try {
        const resp = await sendMessageStream(conversationId, query, streamView, attachmentContext, attachmentPayload);
        streamView.finalize(resp);
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
    return apiCall('POST', '/api/chat', {
        conversation_id: conversationId,
        user_id: currentUserId,
        query,
        stream: false,
        model_preference: model || undefined,
        agent_id: currentAgentId,
        context_blocks: attachmentContext ? [attachmentContext] : [],
        attachments,
        ...modePayload,
    });
}

async function sendMessageStream(conversationId, query, streamView, attachmentContext = '', attachments = []) {
    const model = modelSelect.value || undefined;
    const modePayload = selectedModePayload();
    const resp = await fetch(API_BASE + '/api/chat', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            ...(currentAccountToken ? { 'X-Account-Session': currentAccountToken } : {}),
            ...(currentUserId ? { 'X-User-ID': currentUserId } : {}),
        },
        body: JSON.stringify({
            conversation_id: conversationId,
            user_id: currentUserId,
            query,
            stream: true,
            model_preference: model || undefined,
            agent_id: currentAgentId,
            context_blocks: attachmentContext ? [attachmentContext] : [],
            attachments,
            ...modePayload,
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
                throw new Error(data.error || t('errors.streamFailed'));
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

function appendStreamingAssistantMessage() {
    const welcome = messagesContainer.querySelector('.welcome-screen');
    if (welcome) welcome.remove();

    const div = document.createElement('div');
    div.className = 'message assistant streaming';
    div.dataset.copyText = '';
    div.innerHTML = `
        <div class="avatar">AI</div>
        <div class="bubble">
            <div class="streaming-status"></div>
            <div class="streaming-content">
                <div class="loading-dots"><span></span><span></span><span></span></div>
            </div>
            <div class="streaming-citations"></div>
            <div class="streaming-skills"></div>
            <div class="streaming-trace"></div>
            ${renderAssistantActions({ copyEnabled: false })}
        </div>
    `;
    messagesContainer.appendChild(div);

    const statusEl = div.querySelector('.streaming-status');
    const contentEl = div.querySelector('.streaming-content');
    const citationsEl = div.querySelector('.streaming-citations');
    const skillsEl = div.querySelector('.streaming-skills');
    const traceEl = div.querySelector('.streaming-trace');
    let lastContent = '';
    let lastEvents = [];
    let lastMeta = {};

    return {
        setContent(text) {
            lastContent = text || '';
            div.dataset.copyText = lastContent;
            updateCopyButtonState(div, Boolean(lastContent));
            statusEl.hidden = true;
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
            if (!lastContent) {
                statusEl.hidden = false;
                statusEl.innerHTML = renderStreamingStatus(lastEvents);
            }
            traceEl.innerHTML = '';
            updateAssistantActions(div, {
                copyEnabled: Boolean(lastContent),
                traceEvents: lastEvents,
                runId: lastMeta.runId || '',
                runtime: lastMeta.runtime || '',
                modelUsed: lastMeta.modelUsed || '',
            });
        },
        finalize(resp) {
            const displayError = resp.error_type
                ? (resp.error_type === 'rate_limit' ? 'rate_limit' : 'error')
                : '';
            if (displayError) {
                this.showError(resp.response || t('errors.requestFailed'), displayError);
                return;
            }
            this.setContent(resp.response || lastContent);
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
        },
        showError(message, type = 'error') {
            statusEl.hidden = true;
            div.dataset.copyText = message || '';
            updateCopyButtonState(div, Boolean(message));
            contentEl.innerHTML = errorBanner(
                type === 'rate_limit' ? t('errors.rateLimit') : t('errors.error'),
                message,
                type === 'rate_limit' ? 'rate-limit' : 'generic-error'
            );
            div.classList.remove('streaming');
        },
    };
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
    inputMeta = null
) {
    const welcome = messagesContainer.querySelector('.welcome-screen');
    if (welcome) welcome.remove();

    const div = document.createElement('div');
    div.className = `message ${role}`;
    if (role === 'assistant') div.dataset.copyText = content || '';
    const avatar = role === 'user' ? 'You' : 'AI';
    const assistantActions = role === 'assistant'
        ? renderAssistantActions({
            copyEnabled: Boolean(content),
            traceEvents,
            runId,
            runtime,
            modelUsed,
        })
        : '';
    const displayError = errorType
        ? (errorType === 'rate_limit' ? 'rate_limit' : 'error')
        : '';

    let bubbleContent = '';
    if (displayError === 'rate_limit') {
        bubbleContent = errorBanner(t('errors.rateLimit'), content, 'rate-limit') + assistantActions;
    } else if (displayError === 'error') {
        bubbleContent = errorBanner(t('errors.error'), content, 'generic-error') + assistantActions;
    } else {
        const skillBadges = skillsUsed && skillsUsed.length
            ? `<div class="skill-badges">${skillsUsed.map((s) => `<span class="skill-badge">${escapeHtml(s)}</span>`).join('')}</div>`
            : '';
        bubbleContent = `${renderInputMeta(inputMeta)}${formatContent(content)}${renderCitationPanel(citations)}${skillBadges}${assistantActions}`;
    }

    div.innerHTML = `
        <div class="avatar">${avatar}</div>
        <div class="bubble">${bubbleContent}</div>
    `;
    messagesContainer.appendChild(div);
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
        traceEvents = [],
        runId = '',
        runtime = '',
        modelUsed = '',
    } = options;
    const label = t('actions.copyAnswer');
    const disabled = copyEnabled ? '' : 'disabled aria-disabled="true"';
    return `
        ${renderTraceActionButton(traceEvents, runId, runtime, modelUsed)}
        <button class="assistant-action-button assistant-copy" type="button" data-copy-answer ${disabled}
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
            <span class="visually-hidden">${escapeHtml(title)}</span>
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
    const label = t('actions.copyAnswer');
    button.classList.remove('copied', 'failed');
    button.title = label;
    button.setAttribute('aria-label', label);
    const text = button.querySelector('.visually-hidden');
    if (text) text.textContent = label;
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
    if (!meta || (!meta.modes?.length && !meta.attachments?.length)) return '';
    const modes = (meta.modes || []).map((mode) => `<span>${escapeHtml(mode.name)}</span>`).join('');
    const attachments = (meta.attachments || []).map((item) => `
        <span title="${escapeAttr(item.name)}">
            ${escapeHtml(item.name)}
            <small>${escapeHtml(item.kind || 'file')} / ${escapeHtml(formatBytes(item.size))}${item.truncated ? ` / ${escapeHtml(t('attachments.truncated'))}` : ''}</small>
        </span>
    `).join('');
    return `
        <div class="input-meta">
            ${modes ? `<div class="input-meta-row">${modes}</div>` : ''}
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
        const title = citation.title || citation.url;
        const source = citationSourceLabel(citation);
        const snippet = truncateText(citation.snippet || '', 220);
        const media = citationMedia(citation);
        return `
            <li class="citation-item ${media ? 'has-media' : ''}">
                ${media}
                <div class="citation-body">
                    <a class="citation-link" href="${escapeAttr(citation.url)}" target="_blank" rel="noopener noreferrer">
                        ${escapeHtml(title)}
                    </a>
                    ${source ? `<div class="citation-meta">${escapeHtml(source)}</div>` : ''}
                    ${snippet ? `<div class="citation-snippet">${escapeHtml(snippet)}</div>` : ''}
                </div>
            </li>
        `;
    }).join('');

    return `
        <section class="citation-panel" aria-label="${escapeAttr(t('chat.citations'))}">
            <div class="citation-title">${escapeHtml(t('chat.citations'))}</div>
            <ol class="citation-list">${rows}</ol>
        </section>
    `;
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

function citationMedia(citation) {
    const metadata = citation.metadata || {};
    const imageUrl = firstSafeUrl(
        metadata.thumbnail_url,
        metadata.thumbnailUrl,
        metadata.thumbnail,
        metadata.image_url,
        metadata.imageUrl,
        metadata.image,
        metadata.og_image,
        metadata['og:image'],
        metadata.cover,
        metadata.poster
    );
    const videoUrl = firstSafeUrl(
        metadata.video_url,
        metadata.videoUrl,
        metadata.video,
        metadata.embed_url,
        metadata.embedUrl,
        metadata.media_url
    );
    if (videoUrl && isVideoUrl(videoUrl)) {
        return `
            <a class="citation-media video" href="${escapeAttr(citation.url)}" target="_blank" rel="noopener noreferrer" aria-label="${escapeAttr(citation.title || citation.url)}">
                <video src="${escapeAttr(videoUrl)}" preload="metadata" muted playsinline></video>
            </a>
        `;
    }
    if (imageUrl) {
        return `
            <a class="citation-media" href="${escapeAttr(citation.url)}" target="_blank" rel="noopener noreferrer" aria-label="${escapeAttr(citation.title || citation.url)}">
                <img src="${escapeAttr(imageUrl)}" alt="" loading="lazy">
            </a>
        `;
    }
    return '';
}

function firstSafeUrl(...values) {
    for (const value of values) {
        if (Array.isArray(value)) {
            const nested = firstSafeUrl(...value);
            if (nested) return nested;
            continue;
        }
        if (value && typeof value === 'object') {
            const nested = firstSafeUrl(value.url, value.src, value.link, value.contentUrl);
            if (nested) return nested;
            continue;
        }
        const url = String(value || '').trim();
        if (url && isSafeContentUrl(url)) return url;
    }
    return '';
}

function citationSourceLabel(citation) {
    const labels = [citation.source, hostFromUrl(citation.url)].filter(Boolean);
    return Array.from(new Set(labels)).join(' / ');
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
        codeBlocks.push(`<pre${language}><code>${escapeHtml(code.trim())}</code></pre>`);
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

    const sidebarSectionToggle = event.target.closest('[data-toggle-sidebar-section]');
    if (sidebarSectionToggle) {
        event.stopPropagation();
        const sectionId = sidebarSectionToggle.dataset.toggleSidebarSection;
        setSidebarSectionCollapsed(sectionId, !collapsedSidebarSections.includes(sectionId));
        return;
    }

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

    const viewTarget = event.target.closest('[data-view]');
    if (viewTarget) {
        if (viewTarget.dataset.view === 'chat') {
            await startAgentTask('super_chat');
            return;
        }
        setView(viewTarget.dataset.view);
        return;
    }

    const pulseRefreshButton = event.target.closest('[data-pulse-refresh]');
    if (pulseRefreshButton) {
        pulseRefreshButton.disabled = true;
        await refreshPulse();
        pulseRefreshButton.disabled = false;
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

	const pulseChatButton = event.target.closest('[data-pulse-chat]');
	if (pulseChatButton) {
		const query = pulseChatButton.dataset.pulseChat || '';
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

    const copyAnswerButton = event.target.closest('[data-copy-answer]');
    if (copyAnswerButton) {
        event.stopPropagation();
        if (copyAnswerButton.disabled) return;

        const message = copyAnswerButton.closest('.message.assistant');
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

    const traceJumpButton = event.target.closest('[data-open-trace-run]');
    if (traceJumpButton && !traceJumpButton.disabled) {
        await openTraceRun(traceJumpButton.dataset.openTraceRun);
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

document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && isMobileSidebarOpen()) {
        event.preventDefault();
        setSidebarOpen(false);
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

document.addEventListener('paste', handleImagePaste);

if (pulseTopicForm) {
    pulseTopicForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        await createPulseTopic();
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

    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        handleSend();
    }
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
        showAccountLogin();
        accountNameInput?.focus({ preventScroll: true });
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
            await switchAccount(data.account?.id || userId, { token: data.token });
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
        try {
            const data = await createAccount(name, password);
            if (accountNameInput) accountNameInput.value = '';
            if (accountPasswordInput) accountPasswordInput.value = '';
            await switchAccount(data.account.id, { token: data.token });
        } catch (err) {
            if (accountLoginError) accountLoginError.textContent = t('account.createFailed', { message: err.message });
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

applyI18n();
applySidebarCollapseState();
renderAgentCommandBar();
renderModes();
renderPulse();
renderAccountControls();
updateCounts();
renderHealth();
updateSendState();

bootApp();
