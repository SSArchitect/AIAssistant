"""H3 direction guidance and a deterministic, tool-side storyboard compiler.

Adapted to Spark's supported modes from MiniMax-AI/MiniMax-H3's
skills/h3-prompt-writing and its base-en.txt / ref-en.txt guides (2026-09-17).
No model call or prompt rewrite happens during retries.
"""
from __future__ import annotations

from fractions import Fraction
import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from agent.schemas.aigc import VIDEO_NATIVE_FPS, VideoGenerationRequest


VIDEO_PROMPT_GUIDANCE = (
    "\n- 视频创作：优先用 storyboard 组织分镜，与 prompt 二选一；用户提供要求原样执行的完整提示词时用 prompt 原文透传。"
    "先依据用户目标和已知素材确定风格、主体、动作起点、变化和收束，再调用工具；普通短片无需额外确认。"
    "保留指定时长、画幅、人物数量、身份、服装、场景、文字和禁止事项，不擅自增加品牌、人物、台词或字幕。"
    "不要将插画、定格等风格改成写实，也不要靠堆砌‘电影感、超高清’替代可见细节。"
    "\n- 先锁定交付意图：最终文件数量、单片时长、画幅、叙事重点、出场/不出场人物、声音与字幕要求。"
    "Panel是一个可审阅的动作/信息段，Logical Shot是一组摄影机与时空连续的Panel，视频节点才是一次生成和一个交付文件；三者不能等同。"
    "用户要求一条完整15秒时，可以包含多个Panel和Logical Shot，但仍只规划一个视频节点、一次生成；不擅自拆片或承诺后期拼接。"
    "若剧情、完整台词与能力上限无法同时满足，先提出可选择的叙事精简/延长或分段方案，不自动删台词、快读、截断或拆单。"
    "\n- 对复杂叙事先形成可审阅的制作简报→素材贡献与统一规则→角色/道具/空间连续性锁→Panel语义分镜→Logical Shot分组→无空档主时间线→执行锁。"
    "简单单动作短片可以精简，不机械套用9个Panel或3个镜头组。审阅语言跟随用户；执行提示词用紧凑英文表达。"
    "审阅稿详细解释选择，执行稿复用全局规则并压缩重复内容；关键动作、准确对白、素材职责和交付约束不能在压缩时丢失。"
    "\n- reference_rules逐图说明身份、服装/道具、环境或画风的贡献、保留项与明确修改项，排除不出场的角色。"
    "已确认主视觉若指定为唯一画风权威，角色设定图只提供身份，不混入其底纸/配色/渲染风格；主视觉不自动等于精确首帧。"
    "提取具体媒介特征，例如书法墨线、飞白干笔、宣纸渗化、墨色层次与克制水彩，不只写国风或电影感；用户指定的其他风格同样具体化。"
    "从角色设定图提取人物，不把三视图、表情矩阵、编号、色板、说明文字和排版带入成片；道具改造应说明新轮廓与持握方式，不能只改名字。"
    "\n- continuity_locks集中锁定角色形体与衣着、道具形制/持有者、数量与局部变化、疲惫等状态、角色相对站位和空间轴线。"
    "全局状态可以随剧情改变，但必须描述变化发生的动作及后续状态；未参与动作的角色/道具仍保持可解释的位置，不突然消失或串形。"
    "\n- storyboard 的 style 和 shots[].description 用英文写视觉及声音描述；台词、歌词和画内文字保持原文、原语言与标点。"
    "每个镜头说明景别/构图、主体位置、光线/材质、一项主要动作的起因→变化→结果、合理的物理接触与结束状态。"
    "短片优先少量连贯镜头，动作与台词必须能在时长内完成，给收尾留时间；不为凑字数扩剧情。"
    "运镜写成自然句子，交代方向、幅度、速度，区分推轨与变焦；同一时段避免冲突运镜。"
    "\n- shots[].start_seconds 是相对视频起点的切镜秒数，首镜必须为0，后续严格递增且小于请求时长，最多三位小数。"
    "未指定秒数时按对齐后的原生帧数/24规划，不用输出fps换算时长。工具自动生成[Shot N]与At MM:SS.mmm，description不要重复写镜头编号。"
    "只有需要新的信息/视角才切镜，轻微景别变化优先用连续运镜。"
    "复杂分镜用shots代表Logical Shot，其panels按全片绝对秒数填写start_seconds、end_seconds和description；"
    "每组Panel必须从该Shot起点无空档、无重叠覆盖到下一Shot起点或视频终点。Panel边界只是动作节拍，不自动切镜。"
    "每个Panel交代景别/机位与前中后景、主要动作、表演、摄影机、同步声音、结束状态和下一段转场接口；只写本段需要的信息。"
    "每个Logical Shot的description概括叙事职责、起止状态和摄影机轴线，不重复整组Panel。收尾需要可读停留，不能全部时间堆在动作前奏。"
    "\n- 有台词时按首次发声顺序赋予稳定(S1)、(S2)，跨镜头不改号；无发声人物不加编号。"
    "语速、音色、情绪、动作在标签外，原话写成<d>[Chinese] 原文</d>（语言标签对应真实语言）。"
    "旁白写says in an off-screen voiceover，说明对应画内人物闭嘴，避免旁白引起错误口型；对白跨切镜用<scenetrans>连接并说明声音连续。"
    "只有明确要求片尾截断说话才用<cutoff>，不为塞入过长台词擅自截断。可见文字用英文双引号包住原文，不自动添加字幕。"
    "\n- overall_soundscape 写环境声与物理声，局部同步音效和对白写入相应镜头；整体静音才填N/A。"
    "non_diegetic_music 只写观众能听到的配乐（乐器、节奏、强弱变化），没有配乐写N/A。"
    "无配乐不等于整体静音，无对白不等于没有环境声。静音是创作提示，当前接口没有关闭音轨的参数。"
    "对白要给真实发声与停顿留时间；不能把长句塞进一两秒并声称可执行。对白时环境声/配乐适当让位，跨段声音说明延续与收束。"
    "execution_constraints保存本片的单次生成/文件数量约定、精确台词与声音来源、字幕/旁白等用户明确要求；不默认禁用用户想要的文字或音乐。"
    "\n- image_to_video 从真实首帧出发，保持身份、构图、服装、颜色与空间关系，再描述动作发展；不编造看不到的素材细节。"
    "reference_to_video 必须填写 subject_definitions、summary、retention_analysis；工具按官方六节顺序编译。"
    "<Picture N>按实际选择的图片数组顺序编号，不是附件原序号；先在subject_definitions逐行定义<Subject N>并引用来源<Picture N>，"
    "同一主体可引用多张图；只作构图锚点的图片可独立定义。summary以[reference generation]开头。"
    "retention_analysis逐行写每项已定义内容出现在哪些[Shot N]，用fully_preserved、partially_preserved、attribute_transfer或weak_reference"
    "说明保留/变化的特征；镜头沿用标签，不把参考图中没有要求的背景或文字带入成片。"
    "\n- 当前仅支持文生、单首帧和1–9图参考；不承诺尾帧硬约束、视频编辑/续写、参考视频或参考音频，不能虚构<Video N>/<Audio N>素材。"
    "最终编译prompt仍限4000字符，超限压缩重复环境描述，保留台词、参考关系和关键动作，不截断原文。"
    "生成后只根据真实返回信息交付链接、尺寸和时长；没有观看/听取成片时，不声称已验证人物一致性、口型、文字或音画同步。"
)

PromptText = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=4000, pattern=r"\S")]


class VideoPanel(BaseModel):
    """A semantic beat inside a logical shot, not an extra provider request or cut."""
    model_config = ConfigDict(extra="forbid")

    start_seconds: float = Field(strict=True, ge=0, allow_inf_nan=False, multiple_of=.001,
        description="Absolute clip time, inclusive. Must continue exactly from the previous panel/shot start.")
    end_seconds: float = Field(strict=True, gt=0, allow_inf_nan=False, multiple_of=.001,
        description="Absolute clip time, exclusive. Last panel ends at the next shot start or clip duration.")
    description: PromptText = Field(description="Composition and visible action, performance, camera, synchronized dialogue/sound, ending state and transition. A panel boundary alone is not a cut. Preserve original spoken words.")


class VideoShot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_seconds: float = Field(strict=True, ge=0, allow_inf_nan=False, multiple_of=.001,
        description="Cut time in seconds: first shot 0, then strictly increasing within duration. Millisecond precision.")
    description: PromptText = Field(description="English composition, visible subject/action progression, camera and synchronized sounds. No [Shot N] prefix. Preserve original dialogue in <d>[Language] ...</d> and visible text in double quotes.")
    panels: list[VideoPanel] = Field(default_factory=list, max_length=12,
        description="Optional semantic beats within this logical shot. Cover its entire time range without gaps or overlaps. With panels, description gives narrative purpose, start/end state and camera axis.")


class VideoStoryboard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    style: PromptText = Field(description="Overall visual medium, lighting and palette, consistent with the user and source images.")
    shots: list[VideoShot] = Field(min_length=1, max_length=12)
    overall_soundscape: PromptText = Field(description="Ambient and physical sounds across the clip. N/A only for requested complete silence; do not repeat dialogue here.")
    non_diegetic_music: PromptText = Field(default="N/A", description="Audience-only score: instruments, tempo and dynamics. N/A for no score.")
    subject_definitions: PromptText | None = Field(default=None, description="Reference mode only. One definition per line: <Subject 1> is ... from <Picture 1>. Picture indices follow selected input order. Define a standalone <Picture N> only as a composition anchor.")
    summary: PromptText | None = Field(default=None, description="Reference mode only. Start with [reference generation], then summarize subjects and shot flow without introducing new labels.")
    retention_analysis: PromptText | None = Field(default=None, description="Reference mode only. One line per defined subject/anchor: <Subject 1> (appears in [Shot 1]): fully_preserved - retained features. Other markers: partially_preserved, attribute_transfer, weak_reference.")
    reference_rules: list[PromptText] = Field(default_factory=list, max_length=12,
        description="Each selected image's contribution, visual authority, retained/changed features and excluded sheet layout/text. Picture numbering follows actual input order; style reference is not a first frame.")
    continuity_locks: list[PromptText] = Field(default_factory=list, max_length=12,
        description="Shared identity/costume, prop shape/owner, counts and local changes, character state, relative position and spatial axis. Avoid repeating these in every panel.")
    execution_constraints: list[PromptText] = Field(default_factory=list, max_length=12,
        description="User-specific delivery, exact speech, sound, subtitle/narration and other constraints. One tool call outputs one clip regardless of panel/shot count. Not new provider capability flags.")


_LABEL = re.compile(r"<(Subject|Picture|Video|Audio)\s+(\d+)>")
_DEFINITION = re.compile(r"^\s*(<(?:Subject|Picture) [1-9]\d*>)\s+\S", re.MULTILINE)
_SHOT = re.compile(r"\[Shot (\d+)\]")
_RETENTION = re.compile(r"^\s*(<(?:Subject|Picture) [1-9]\d*>)\s*[^\n]*?:\s*(?:fully_preserved|partially_preserved|attribute_transfer|weak_reference)\s*-\s*\S", re.MULTILINE)


def storyboard_schema() -> dict:
    """Inline Pydantic definitions so chat providers receive a self-contained schema."""
    schema = VideoStoryboard.model_json_schema()
    definitions = schema.pop("$defs", {})

    def inline(value):
        if isinstance(value, list):
            return [inline(item) for item in value]
        if isinstance(value, dict):
            if "$ref" in value:
                return inline(definitions[value["$ref"].rsplit("/", 1)[-1]])
            return {key: inline(item) for key, item in value.items()}
        return value

    return inline(schema)


def compile_storyboard(plan: VideoStoryboard, request: VideoGenerationRequest) -> str:
    """Validate against resolved inputs; render once before governance freezes the request."""
    duration = (Fraction(str(request.duration_seconds)) if request.duration_seconds is not None
                else Fraction(request.resolved_frames(), VIDEO_NATIVE_FPS))
    previous = None
    for index, shot in enumerate(plan.shots):
        start = Fraction(str(shot.start_seconds))
        if ((index == 0 and start != 0) or (previous is not None and start <= previous)
                or start >= duration):
            raise ValueError("storyboard cuts must start at 0, increase strictly and stay within the video duration")
        if (start * 1000).denominator != 1:
            raise ValueError("storyboard cut times accept at most 3 decimal places")
        if _SHOT.search(shot.description):
            raise ValueError("Do not write [Shot N] in description; storyboard supplies shot numbers")
        if shot.panels:
            end = Fraction(str(plan.shots[index + 1].start_seconds)) if index + 1 < len(plan.shots) else duration
            # Native frames / 24 can end on a recurring decimal. For frame-based
            # requests only, express that endpoint to the panel schema's 1ms precision.
            if index + 1 == len(plan.shots) and request.duration_seconds is None:
                end = Fraction(round(end * 1000), 1000)
            cursor = start
            for panel in shot.panels:
                panel_start, panel_end = Fraction(str(panel.start_seconds)), Fraction(str(panel.end_seconds))
                if panel_start != cursor or panel_end <= panel_start or panel_end > end:
                    raise ValueError("Panels must cover their logical shot without gaps, overlaps or out-of-range times")
                if _SHOT.search(panel.description):
                    raise ValueError("Do not write [Shot N] in a panel; panels do not introduce cuts")
                cursor = panel_end
            if cursor != end:
                raise ValueError("Panels must cover their logical shot through its end, including the clip ending")
        previous = start

    fields = [plan.style, *(shot.description for shot in plan.shots),
              *(panel.description for shot in plan.shots for panel in shot.panels),
              *plan.reference_rules, *plan.continuity_locks, *plan.execution_constraints,
              plan.overall_soundscape, plan.non_diegetic_music,
              plan.subject_definitions or "", plan.summary or "", plan.retention_analysis or ""]
    text = "\n".join(fields)
    refs = (request.reference_image_asset_ids or request.reference_image_attachment_indices
            or request.reference_image_urls or request.reference_image_data_urls or [])
    picture_count = len(refs) if request.mode == "reference_to_video" else int(request.mode == "image_to_video")
    labels = _LABEL.findall(text)
    for kind, number in labels:
        if kind in {"Video", "Audio"}:
            raise ValueError("Spark does not support video/audio reference inputs")
        if kind == "Picture" and not 1 <= int(number) <= picture_count:
            raise ValueError(f"<Picture {number}> has no selected input image")
    for number in _SHOT.findall(text):
        if not 1 <= int(number) <= len(plan.shots):
            raise ValueError(f"[Shot {number}] is not in the storyboard")
    for field in fields:
        # Speech spanning cuts uses complete <d> blocks joined by <scenetrans>,
        # never an opening tag in one shot and a closing tag in another.
        _validate_dialogue(field)
    if plan.overall_soundscape.strip() == "N/A" and (
            "<d>" in text or plan.non_diegetic_music.strip() != "N/A"):
        raise ValueError("overall_soundscape N/A means complete silence; remove dialogue/music or describe the intended soundscape")

    reference_fields = (plan.subject_definitions, plan.summary, plan.retention_analysis)
    if request.mode == "reference_to_video":
        if not all(reference_fields):
            raise ValueError("Reference storyboard requires subject_definitions, summary and retention_analysis")
        if not plan.summary.startswith("[reference generation]"):
            raise ValueError("Reference summary must start with [reference generation]; video editing/audio reuse are unsupported")
        definitions = _DEFINITION.findall(plan.subject_definitions)
        defined = set(definitions)
        if not defined or len(definitions) != len(defined):
            raise ValueError("Define each reference subject or composition anchor once, on its own line")
        used_subjects = {f"<Subject {number}>" for kind, number in labels if kind == "Subject"}
        if not used_subjects.issubset(defined):
            raise ValueError("Every <Subject N> must be defined in subject_definitions")
        source_pictures = {int(number) for kind, number in _LABEL.findall(plan.subject_definitions) if kind == "Picture"}
        if source_pictures != set(range(1, picture_count + 1)):
            raise ValueError("subject_definitions must assign a role to every selected <Picture N>")
        retention = _RETENTION.findall(plan.retention_analysis)
        if set(retention) != defined or len(retention) != len(defined):
            raise ValueError("retention_analysis must describe each defined subject/anchor once with a supported retention marker")
    elif any(field is not None for field in reference_fields) or any(kind == "Subject" for kind, _ in labels):
        raise ValueError("Reference definitions and <Subject N> labels require reference_to_video mode")

    direction = [plan.style]
    for title, rules in [('Reference rules', plan.reference_rules), ('Continuity locks', plan.continuity_locks),
                         ('Execution constraints', plan.execution_constraints)]:
        if rules:
            direction.append(f"{title}: " + ' '.join(rules))
    style = '\n'.join(direction)
    shots = []
    for index, shot in enumerate(plan.shots, 1):
        prefix = f"[Shot {index}]"
        if index > 1:
            prefix += f" At {_timestamp(shot.start_seconds)},"
        elif request.mode != "reference_to_video":
            prefix += " " + style
        description = shot.description
        if shot.panels:
            description += '\n' + '\n'.join(
                f"{_timestamp(panel.start_seconds)}–{_timestamp(panel.end_seconds)}: {panel.description}"
                for panel in shot.panels)
        shots.append(prefix + " " + description)
    timeline = "\n".join(shots)
    if request.mode == "reference_to_video":
        sections = [f"subject_definitions: {plan.subject_definitions}", f"summary: {plan.summary}",
                    f"retention_analysis: {plan.retention_analysis}", f"detailed_description: {style}\n{timeline}"]
    else:
        sections = [f"integrated_multimodal_description: {timeline}"]
        if request.mode == "image_to_video":
            sections.insert(0, "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.")
    sections.extend([f"overall_soundscape: {plan.overall_soundscape}", f"non_diegetic_music: {plan.non_diegetic_music}"])
    prompt = "\n\n".join(sections)
    if len(prompt) > 4000:
        raise ValueError(f"Compiled storyboard is {len(prompt)} characters; limit is 4000. Shorten repeated descriptions without truncating dialogue or reference roles")
    return prompt


def _timestamp(value: float) -> str:
    millis = int(Fraction(str(value)) * 1000)
    minutes, remainder = divmod(millis, 60000)
    seconds, fraction = divmod(remainder, 1000)
    return f"{minutes:02d}:{seconds:02d}.{fraction:03d}"


def _validate_dialogue(text: str) -> None:
    """Check tag structure without translating, normalizing or censoring spoken words."""
    opened = None
    for match in re.finditer(r"</?d>", text):
        if match.group() == "<d>":
            if opened is not None:
                raise ValueError("Dialogue <d> tags cannot be nested")
            opened = match.end()
        else:
            if opened is None or not re.fullmatch(r"\[[^\[\]\n]+\]\s*\S[\s\S]*", text[opened:match.start()]):
                raise ValueError("Dialogue must use balanced <d>[Language] original words</d> blocks")
            opened = None
    if opened is not None:
        raise ValueError("Dialogue must close every <d> with </d>")
