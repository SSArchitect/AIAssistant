"""Ground image rejections in immutable intent and visible, scoped references."""
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ReviewEvidenceError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class ReviewFinding(BaseModel):
    model_config = ConfigDict(extra='forbid')
    candidate_id: str
    category: Literal['identity', 'action', 'composition', 'scale', 'environment', 'artifact']
    source_id: str
    requirement_quote: str = Field(min_length=2, max_length=400)
    observation: str = Field(min_length=2, max_length=400)


def requirement_sources(payload):
    """Only known requirement text can be cited; repair prose is not a source."""
    target = payload['review_target']
    sources = {'target': '\n'.join([target.get('content', ''), target.get('prompt', '')]),
        'quality': '画面应可辨认；无多余主体、身份混淆、身体畸变或非要求的拼图。'}
    for node in payload['current_plan']['nodes']:
        if node['id'] != target['id'] and node['kind'] == 'text' and payload['node_context'].get(node['id'], {}).get('approved'):
            sources['node:' + node['id']] = node.get('content', '')
    for index, message in enumerate(payload['messages']):
        sources['user:' + str(index)] = message['content']
    for ref in payload['review_references']:
        if ref['preview_available']:
            # A reference constrains only its assigned role, not every visible
            # pose/layout/background. Its note is not a newly confirmed goal.
            roles = {'identity': '保持参考中的角色身份、服装和道具特征，不复制其排版或背景。',
                'environment': '保持参考中的地点、环境结构和光色，不复制其中人物。',
                'style': '保持参考画风，不复制其人物身份、构图或排版。',
                'composition': '保持参考的空间、机位与构图关系。',
                'first_frame': '保持首帧参考的空间、构图与关键姿态。',
                'reference': '按当前镜头要求使用参考中相关的可见特征，不扩散无关身份、姿势或排版。'}
            rule = roles.get(ref['role'])
            if rule:
                sources['reference:' + ref['asset_id'] + ':' + ref['role']] = rule
    return {key: value for key, value in sources.items() if value.strip()}


def validate_image_findings(decision, candidates, sources, *, scale_contract=None, geometry=()):
    """Reject invented/missing citations before paying for another image job."""
    if decision.decision != 'revise' or not candidates:
        if decision.findings:
            raise ReviewEvidenceError('unexpected_findings', 'findings仅用于候选图片的revise决策')
        return
    if not decision.findings:
        raise ReviewEvidenceError('missing_findings', '重画需要findings，列出候选、可见问题及review_requirements中的原文依据')
    covered = set()
    compact = lambda value: re.sub(r'\s+', '', value)
    for finding in decision.findings:
        if finding.candidate_id not in candidates:
            raise ReviewEvidenceError('foreign_candidate', 'findings只能评价candidate_ids中的候选')
        source = sources.get(finding.source_id)
        if not source:
            raise ReviewEvidenceError('unknown_source', '未知source_id：' + finding.source_id[:100] + '；只能使用review_requirements的键')
        if finding.source_id.startswith('reference:'):
            # A visible reference has one program-owned role rule. Asking the
            # model to copy it invites confusion with mutable execution notes.
            # Never promote those notes into new acceptance requirements.
            finding.requirement_quote = source
        if compact(finding.requirement_quote) not in compact(source):
            raise ReviewEvidenceError('quote_mismatch', '引用与' + finding.source_id[:100] + '的原文不匹配；按text_path查找原文逐字引用，不能改写、拼接或引用AI返工新增条件')
        if scale_contract:
            from agent.aigc.creation_review_geometry import scale_within_contract
            if finding.category=='composition' and re.search(r'画高|身高|高度占比|角色比例|人物占比|尺寸偏|尺寸过',finding.observation):
                raise ReviewEvidenceError('scale_category', '人物尺寸或占比问题必须单独使用scale分类，不能混入其他构图问题')
            if finding.category=='scale' and scale_within_contract(scale_contract,geometry,finding.candidate_id) is True:
                raise ReviewEvidenceError('scale_in_range', '独立定位的占比已在原约数要求的固定审阅区间内，不能作为返工理由；请select合格候选或指出其他有依据的真实问题')
        covered.add(finding.candidate_id)
    if covered != set(candidates):
        raise ReviewEvidenceError('candidate_coverage', '要求全部重画时，每个候选都需要有依据的问题；存在合格候选应select')
    # The next planner receives the validated evidence, not uncited instructions
    # smuggled into a freeform reason. Full findings accompany this short summary.
    decision.reason = '；'.join('[' + f.source_id + ']“' + f.requirement_quote + '”：' + f.observation
        for f in decision.findings)[:500]
