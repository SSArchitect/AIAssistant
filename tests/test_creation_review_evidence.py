import pytest
from agent.aigc.creation_review import ReviewDecision
from agent.aigc.creation_review_evidence import validate_image_findings, requirement_sources


def finding(**changes):
    return dict(candidate_id='candidate', category='composition', source_id='target',
        requirement_quote='主体占画高4%', observation='候选人物占画高约30%', **changes)


def test_rejection_forwards_verified_requirement_and_observation_not_new_instructions():
    decision = ReviewDecision(decision='revise', reason='额外加上两只脚必须露出、禁止护手', findings=[finding()])
    validate_image_findings(decision, ['candidate'], {'target': '主体占画高4%，远方剪影'})
    assert '画高4%' in decision.reason and '30%' in decision.reason
    assert '两只脚' not in decision.reason and '禁止护手' not in decision.reason


@pytest.mark.parametrize('bad', [
    [],
    [{**finding(), 'source_id':'invented'}],
    [{**finding(), 'requirement_quote':'两只脚必须露出'}],
    [{**finding(), 'candidate_id':'reference-not-candidate'}],
])
def test_missing_invented_or_foreign_evidence_cannot_trigger_image_regeneration(bad):
    decision = ReviewDecision(decision='revise', reason='重画', findings=bad)
    with pytest.raises(ValueError):
        validate_image_findings(decision, ['candidate'], {'target': '主体占画高4%'})


def test_every_rejected_candidate_requires_evidence_and_select_cannot_smuggle_findings():
    with pytest.raises(ValueError, match='每个候选'):
        validate_image_findings(ReviewDecision(decision='revise',reason='都不合格',findings=[finding()]),
            ['candidate','other'], {'target':'主体占画高4%'})
    with pytest.raises(ValueError, match='仅用于'):
        validate_image_findings(ReviewDecision(decision='select',reason='合格',asset_id='candidate',findings=[finding()]),
            ['candidate'], {'target':'主体占画高4%'})


def test_sources_exclude_unconfirmed_scripts_and_nonvisible_reference():
    sources = requirement_sources(dict(review_target={'id':'shot','content':'侧面御剑','prompt':''},
        current_plan={'nodes':[{'id':'script','kind':'text','content':'用户确认的动作'},
            {'id':'draft','kind':'text','content':'AI猜测所有镜头禁止护手'}]},
        node_context={'script':{'approved':True}},messages=[],review_references=[
            dict(asset_id='visible', role='identity', preview_available=True),
            dict(asset_id='hidden', role='environment', preview_available=False)]))
    assert sources['node:script'] == '用户确认的动作'
    assert 'node:draft' not in sources and not any('hidden' in k for k in sources)
    assert '不复制其排版或背景' in sources['reference:visible:identity']


def test_reference_citations_are_compiled_from_assigned_role_not_model_copied_notes():
    source_id = 'reference:identity-asset:identity'
    role_rule = '保持参考中的角色身份、服装和道具特征，不复制其排版或背景。'
    decision = ReviewDecision(decision='revise', reason='角色身份不符', findings=[{
        **finding(), 'category': 'identity', 'source_id': source_id,
        'requirement_quote': '自动返工的参考备注：禁止手持短剑', 'observation': '候选服装与实际人设不同'}])
    validate_image_findings(decision, ['candidate'], {source_id: role_rule})
    assert decision.findings[0].requirement_quote == role_rule
    assert role_rule in decision.reason and '禁止手持短剑' not in decision.reason


def test_reference_citation_does_not_trust_unknown_sources_or_rewrite_target_requirements():
    for source_id in ['reference:foreign:identity', 'target']:
        decision = ReviewDecision(decision='revise', reason='不合格', findings=[{
            **finding(), 'source_id': source_id, 'requirement_quote': '自动新增的无依据要求'}])
        with pytest.raises(ValueError):
            validate_image_findings(decision, ['candidate'], {'target': '主体占画高4%'})
