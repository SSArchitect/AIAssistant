# 视频提示词与分镜

2026-09-17：`generate_video` 增加 `storyboard` 输入，在工具准备阶段转换成 H3 提示词，沿用现有 Spark Provider、治理、下载与恢复流程。普通文本 `prompt` 继续逐字透传，两者必须且只能选择一个。没有增加独立改写模型调用，也不自动发起额外视频生成。

2026-09-18：根据用户提供的 MiniMax 语义分镜审阅范例，扩展产品内的视频设计指导、语义 Panel 与全局约束。指导注入创作导演 workflow；校验和编译仍位于视频 tool 层，不安装或修改 Codex 个人 skill。新增结构可选，已有项目和原始 `prompt` 调用保持兼容。

## 参考与适配范围

依据 MiniMax 官方 [h3-prompt-writing skill](https://github.com/MiniMax-AI/MiniMax-H3/tree/main/skills/h3-prompt-writing)、[基础模式指南](https://github.com/MiniMax-AI/MiniMax-H3/blob/main/skills/h3-prompt-writing/references/base-en.txt)和[完整参考模式指南](https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/docs/VIDEO_PROMPT_WRITING_GUIDE_ref_en.md)。采用按镜头描述动作变化、明确声音来源和参考内容保留关系的方式；不接入官方示例中的 Hub 画布、整片剪辑或逐阶段确认流程。

当前支持：

| Spark 模式 | 提示词形式 | 图片的作用 |
| --- | --- | --- |
| `text_to_video` | 三节，镜头1先交代风格 | 无图片 |
| `image_to_video` | 首帧对齐指令 + 三节 | 单图是起始画面 |
| `reference_to_video` | 六节，风格写在镜头1之前 | 1–9图提供主体、服装、环境或构图参考 |

三节依次为 `integrated_multimodal_description`、`overall_soundscape`、`non_diegetic_music`。六节依次为 `subject_definitions`、`summary`、`retention_analysis`、`detailed_description`、`overall_soundscape`、`non_diegetic_music`。

Provider 暂不提供尾帧硬约束、视频编辑/续写、视频或音频参考输入。分镜编译拒绝 `<Video N>` / `<Audio N>` 引用。多图参考中的构图描述属于生成指导，不等于首尾帧硬约束。原生音轨仍由 Provider 生成；提示静音不等于 API 关闭音轨。

## 创作规则

模型在工具可用时收到统一的创作指导：

- 先确定最终文件数、总时长/单片时长、画幅、叙事重点、出场角色与声音方案。多个 Panel 或 Logical Shot 不等于多个视频文件；用户要求完整单片时，只提交一个视频节点。时长与完整剧情/台词冲突时提出具体取舍，不自行删台词、快读或拆片。
- 保留用户的风格、主体身份与数量、时长、画幅和限制。不给已有台词加字，不自动增加字幕、品牌、人物或剧情。
- 用可见动作和空间关系描述开场、发展与收束；每镜头一项主要动作，给动作完成和台词留时间。少量连贯镜头优先于频繁无意义切镜。
- 英文组织视觉描述；对白、歌词和画内文字保留原语言和标点。说话者沿用 `(S1)` 等编号，台词使用 `<d>[Chinese] 原话</d>`。画内文字放在英文双引号内。
- 运镜说明方向、幅度和速度，区分推轨、变焦与摇镜，避免同一时段冲突。首帧模式保持图中的身份、衣着、构图和空间关系再展开动作。
- 对白、局部同步音效写在镜头内；整体环境声与观众配乐分开。无配乐填 `non_diegetic_music: N/A`，整体静音才填 `overall_soundscape: N/A`。旁白应说明画内人物闭嘴，跨切镜对白说明声音连续。
- 只有真实观看、听取成片后才能声称完成视觉和声音质量检查。程序校验通过不代表模型一定生成正确的人物、口型或文字。

## 审阅稿与执行稿

创作导演将中文审阅稿存入 `purpose=script` 文本节点。复杂叙事按「制作简报 → 素材贡献与统一规则 → 角色与连续性锁 → Panel 语义分镜 → Logical Shot 分组 → 主时间线 → 执行锁」组织。简单单动作可以精简；范例的题材、15秒、9个Panel、3个镜头组不是固定要求。

`storyboard.shots` 仍表示真正的切镜/Logical Shot；每项可增加 `panels`，包含全片绝对时间 `start_seconds`、`end_seconds` 与 `description`。Panel 描述其景别/空间、主动作与表演、运镜、同步对白/声音、连续状态与转场，Panel 边界不会自动增加切镜或请求。每组必须精确覆盖本组起点至下一组起点/全片结束。主时间线采用时间、画面与动作、摄影机、声音四列；它与 Panel 共用时间安排，不能另写一套冲突时间。

执行版可以附带三组可选约束：

| 字段 | 用途 |
| --- | --- |
| `reference_rules` | 每图贡献、保留/修改项、唯一画风权威、排除设定图三视图/色板/文字。主视觉参考不是精确首帧。 |
| `continuity_locks` | 角色形体/衣着、道具形制与持有者、总数与局部变化、状态、相对站位和空间轴线。 |
| `execution_constraints` | 用户指定的文件数量/单次生成、准确对白、音效、字幕与旁白等要求。不是新增 Provider 参数。 |

三组约束进入现有视觉描述节，不增加 H3 顶层节数。编译会保留每个 Panel 的绝对时间段，压缩的是模型规划时的重复描述，程序不会静默删词来满足 4000 字符上限。中文审阅稿与英文执行稿由导演保持语义一致；工具只能确定性校验时间、引用和标签，无法证明自然语言描述等义或台词的真实发声时长。规划要求主动给对白、停顿和结尾留出合理时间，不能照抄范例中过短的对白窗口。

## 文生或首帧示例

“生成5秒水彩纸鹤视频，在窗边轻轻展开翅膀，慢慢推近，有雨声，无对白无配乐。”对应：

```json
{
  "duration_seconds": 5,
  "width": 864,
  "height": 480,
  "storyboard": {
    "style": "Watercolor animation with soft grey daylight and muted colors.",
    "shots": [
      {
        "start_seconds": 0,
        "description": "A medium close shot frames one red paper crane on a wooden desk beside a rain-streaked window. Its folded wings lift gently, open a little, then settle back into their original position. The camera slowly pushes in a short distance, keeping the whole crane visible. Paper rustles in sync with the wings. No speech or visible text."
      }
    ],
    "overall_soundscape": "Rain taps steadily against the glass beneath the soft rustle of folded paper.",
    "non_diegetic_music": "N/A"
  }
}
```

首帧模式增加 `mode: image_to_video` 和一个有效图片来源，例如 `image_attachment_index: 1`；风格与首镜描述应以实际图片为准。工具自动在首行加入 `<Picture 1>` 对齐0秒的指令。不要仅为调用首帧模式而凭空描述图片内容。

## 多图参考示例

假设用户选择附件3中的纸鹤和附件1中的房间，`reference_image_attachment_indices: [3, 1]` 中的第一个元素就是 `<Picture 1>`：

```json
{
  "mode": "reference_to_video",
  "reference_image_attachment_indices": [3, 1],
  "duration_seconds": 5,
  "storyboard": {
    "style": "Watercolor animation with soft daylight.",
    "subject_definitions": "<Subject 1> is the red paper crane from <Picture 1>, preserving its folded shape.\n<Subject 2> is the room from <Picture 2>, preserving the window and wooden desk arrangement.",
    "summary": "[reference generation] <Subject 1> gently moves its wings on the desk in <Subject 2>.",
    "retention_analysis": "<Subject 1> (appears in [Shot 1]): fully_preserved - red color and folded shape.\n<Subject 2> (appears in [Shot 1]): fully_preserved - window and desk arrangement.",
    "shots": [
      {
        "start_seconds": 0,
        "description": "A medium close shot frames <Subject 1> on the desk in <Subject 2>. Its red wings rise slightly, open a little, and settle. The camera holds still. No speech or visible text."
      }
    ],
    "overall_soundscape": "Soft room ambience with light paper rustling as the wings move.",
    "non_diegetic_music": "N/A"
  }
}
```

`subject_definitions` 逐行定义要跟踪的主体或构图锚点。同一主体可从多个图片取不同特征，不强制一张图对应一个主体。`retention_analysis` 每行对应一个定义，标记为 `fully_preserved`、`partially_preserved`、`attribute_transfer` 或 `weak_reference`，并说明保留和变化的内容。新增动作不自动意味着主体外观只被部分保留。

## 校验与恢复

- 分镜1–12个。`style`、`shots`、`overall_soundscape` 必填；无配乐可省略 `non_diegetic_music`，默认为 `N/A`。未知字段、空白描述、空镜头数组直接报错。
- 首镜 `start_seconds` 必须为0；后续严格递增，小于请求的 `duration_seconds`。按帧请求或默认帧数时，用对齐后的原生帧数/24作为边界，输出FPS不改变时间线。切镜最多三位小数，不静默舍入。
- 带 Panel 的镜头必须无空档、无重叠地覆盖本镜头；零时长、跨镜头或缺失结尾均拒绝提交。按原生帧数请求时，仅最终覆盖端点按毫秒精度表示（例如124/24秒表示为5.167秒）；明确请求5秒时仍校验到5秒，不改成对齐后的时长。
- 镜头编号与时间戳由工具生成，`description` 不再写 `[Shot N]`。后续镜头使用 `At MM:SS.mmm`。最后镜头隐含延续到片段结束；显式请求5秒仍会受Provider帧网格影响输出约5.17秒。
- 校验图片编号与实际选择数量、主体是否定义、每张图是否分配用途、保留关系是否覆盖定义，以及引用的镜头是否存在。只校验可确定的结构，不宣称自动理解素材或验证台词可读时长。
- 对白标签必须闭合、含语言标记和原话。编译不翻译、不改标点、不删词。整体静音与已填写的对白/配乐冲突时拒绝提交。
- 最终提示词最多4000字符，包括章节、标签与时间戳；超限报错，需精简重复描述，不能截断对白或引用定义。官方参考指南的详细程度建议需服从当前Provider长度限制。
- 编译发生在权限与提交之前，不访问网络；只有编译后的 `prompt` 和原生成参数进入Provider。权限通过后冻结这份请求，续查同一幂等键使用首次编译结果，即使模型重新填写了分镜也不会改写或重复生成。
- 原始 `storyboard` 按敏感参数脱敏；Provider协议和返回结构不变，成功结果的 `prompt` 为实际提交文本。

## 测试

`tests/test_video_prompting.py` 使用离线单元测试覆盖三种模式、切镜时间边界、参考图顺序与引用、台词原文、音频区分、长度限制、schema、敏感参数、旧提示词兼容，以及治理层冻结后的重试。`tests/test_video_direction.py` 覆盖9个Panel/3个镜头组的一次生成、时间空档/重叠/越界、Panel与全局锁中的引用/对白校验、静音冲突、约束超长、原生帧端点、创作 Agent 运行时接入、序列化保留以及审阅后约束变更阻止提交。

```bash
python3 -m pytest tests/test_video_direction.py tests/test_video_prompting.py tests/test_creation_planning.py tests/test_creation.py -q
./scripts/test.sh
```

真实观感仍需同一素材和参数的生成样片对比。本次单元测试不调用GPU，不代表实测画质提升。
