import base64
import json
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from PIL import Image
from agent.aigc import creation_review as review
from agent.llm.base import LLMResponse
from agent.trace.store import TraceStore
from tests.test_creation_planning import plan


def test_quote_repair_receives_only_existing_bounded_source_text():
    from agent.aigc.creation_review_evidence import ReviewEvidenceError
    decision = review.ReviewDecision(decision='revise', reason='需检查', findings=[dict(
        candidate_id='candidate', category='environment', source_id='target',
        requirement_quote='模型改写的句子', observation='画面有具体差异')])
    sources = {'target': '两侧是菌塔，远处有光柱。', 'other': '无关来源'}
    hint = review.review_citation_feedback(ReviewEvidenceError('quote_mismatch', '引用不符'), decision, sources)
    assert '两侧是菌塔，远处有光柱。' in hint and '无关来源' not in hint and '模型改写的句子' not in hint
    assert sources['target'] == '两侧是菌塔，远处有光柱。'
    assert review.review_citation_feedback(ValueError('format'), decision, sources) == ''
    assert len(review.review_citation_feedback(ReviewEvidenceError('quote_mismatch', ''), decision, {'target':'字'*100000})) < 4200


def request(**kw):
    return review.ReviewRequest(project_id='p',user_id='alice',messages=[{'role':'user','content':'生成短片'}],current_plan=plan(),node_id='script',**kw)


def test_image_review_uses_stable_contract_not_self_written_repair_requirements():
    req = request(node_context={'image': {'review_contract': {
        'content': '兔大侠侧面御剑，披风向后', 'prompt': '执行技巧：露出两只脚'}}})
    req.current_plan['nodes'].append(dict(id='image', kind='image', title='御剑分镜',
        content='AI新增：两只脚必须可见', prompt='AI新增：禁止护手'))
    req.node_id = 'image'
    plan = review.CreativePlan.model_validate(req.current_plan)
    before = req.model_dump()
    payload = json.loads(review.review_context(req, plan, plan.nodes[-1])[0]['text'])
    assert payload['review_target']['content'] == '兔大侠侧面御剑，披风向后'
    assert 'AI新增' not in json.dumps(payload, ensure_ascii=False)
    assert '执行技巧' not in json.dumps(payload, ensure_ascii=False)
    assert payload['messages']==[]
    assert req.model_dump() == before


@pytest.mark.asyncio
async def test_invented_image_requirement_is_repaired_before_returning_a_decision(monkeypatch):
    content=BytesIO();Image.new('RGB',(8,8),'red').save(content,format='PNG')
    data='data:image/png;base64,'+base64.b64encode(content.getvalue()).decode()
    req=request(assets=[dict(id='candidate',name='候选',mime_type='image/png',data_url=data)],candidate_ids=['candidate'])
    req.current_plan['nodes'].append(dict(id='image',kind='image',title='御剑',content='侧面御剑',prompt='露出两只脚'))
    req.node_id='image'
    provider=SimpleNamespace(max_tokens=None,chat=AsyncMock(side_effect=[
        LLMResponse(content=json.dumps(dict(decision='revise',asset_id='',reason='脚少了',findings=[
            dict(candidate_id='candidate',category='action',source_id='target',requirement_quote='两只脚必须可见',observation='只看见一只脚')]))),
        LLMResponse(content=json.dumps(dict(decision='select',asset_id='candidate',reason='侧面遮挡合理',findings=[])))]))
    monkeypatch.setattr(review,'create_provider',lambda:provider)
    result=await review.review_creation(req)
    assert result.decision=='select' and provider.chat.await_count==2
    assert provider.max_tokens==4096
    assert '原文不匹配' in provider.chat.call_args.args[0][-1].content


@pytest.mark.asyncio
@pytest.mark.parametrize('measurement_failed',[False,True])
async def test_scale_review_uses_independent_geometry_without_auto_approving_on_tool_failure(monkeypatch,measurement_failed):
    content=BytesIO();Image.new('RGB',(576,1024),'red').save(content,format='PNG')
    data='data:image/png;base64,'+base64.b64encode(content.getvalue()).decode()
    req=request(assets=[dict(id='candidate',name='图',mime_type='image/png',data_url=data)],candidate_ids=['candidate'])
    req.current_plan['nodes'].append(dict(id='image',kind='image',purpose='shot_reference',title='远景',content='人物约占画高3%',prompt='微小角色'))
    req.node_id='image'
    geometry=[dict(candidate_id='candidate',uncertain=False,subject_count=1,subjects=[dict(body_height_percent=2.5)])]
    locator=AsyncMock(side_effect=ValueError('unavailable')) if measurement_failed else AsyncMock(return_value=(geometry,{'input':12}))
    monkeypatch.setattr(review,'locate_subjects',locator)
    provider=SimpleNamespace(chat=AsyncMock(return_value=LLMResponse(content=json.dumps(
        dict(decision='select',asset_id='candidate',reason='比例与环境符合',findings=[])),usage={'input':20})))
    monkeypatch.setattr(review,'create_provider',lambda:provider)
    trace=TraceStore()
    result=await review.review_creation(req,trace)
    assert provider.chat.await_count==1 and result.asset_id=='candidate'
    payload=json.loads(provider.chat.call_args.args[0][1].content[0]['text'])
    if measurement_failed:
        assert payload['visual_measurements_unavailable'] and 'visual_measurements' not in payload
        assert result.tokens_used['input']==20
    else:
        assert payload['visual_measurements']==geometry and result.tokens_used['input']==32
    run=trace.get_run(result.run_id)
    events=[e for e in run.events if e.type=='creation.review.geometry']
    assert len(events)==1 and run.status=='completed'
    assert events[0].status==('failed' if measurement_failed else 'completed')
    assert 'unavailable' not in events[0].model_dump_json()
    assert payload['scale_contract']['minimum_percent']==2.4
    # The locator accepts no plan/messages/requirements or prior judgments.
    assert len(locator.call_args.args)==3 and locator.call_args.args[2]==['candidate']


@pytest.mark.asyncio
@pytest.mark.parametrize('uncertain',[False,True])
async def test_chinese_fraction_cannot_be_approved_against_clear_out_of_range_measurement(monkeypatch,uncertain):
    from tests.test_creation_review_geometry import asset
    data=asset().data_url
    req=request(assets=[dict(id='candidate',name='图',mime_type='image/png',data_url=data)],candidate_ids=['candidate'])
    req.current_plan['nodes'].append(dict(id='image',kind='image',purpose='shot_reference',title='树',
        content='兔子站在剑上，整体高度约为画面高度的十分之一。',prompt='执行技巧不改变验收'))
    req.node_id='image'
    geometry=[dict(candidate_id='candidate',uncertain=uncertain,subject_count=1,subjects=[dict(body_and_prop_height_percent=20)])]
    monkeypatch.setattr(review,'locate_subjects',AsyncMock(return_value=(geometry,{})))
    provider=SimpleNamespace(chat=AsyncMock(return_value=LLMResponse(content=json.dumps(dict(
        decision='select',asset_id='candidate',reason='符合十分之一',findings=[])))))
    monkeypatch.setattr(review,'create_provider',lambda:provider)
    trace=TraceStore();result=await review.review_creation(req,trace)
    assert provider.chat.await_count==1
    assert result.decision==('select' if uncertain else 'revise')
    if not uncertain:
        assert result.asset_id=='' and result.findings[0].category=='scale'
        assert result.findings[0].requirement_quote in req.current_plan['nodes'][-1]['content']
        assert '20%' in result.reason and '8%–12%' in result.reason
        assert any(e.type=='creation.review.scale_guard' for e in trace.get_run(result.run_id).events)


@pytest.mark.asyncio
async def test_multi_candidate_scale_guard_reconsiders_selection_instead_of_rejecting_every_image(monkeypatch):
    from tests.test_creation_review_geometry import asset
    req=request(assets=[dict(id=n,name=n,mime_type='image/png',data_url=asset().data_url) for n in ['large','good']],candidate_ids=['large','good'])
    req.current_plan['nodes'].append(dict(id='image',kind='image',purpose='shot_reference',title='树',content='人物约占画高10%',prompt='远景'))
    req.node_id='image'
    geometry=[dict(candidate_id=n,uncertain=False,subject_count=1,subjects=[dict(body_height_percent=size)]) for n,size in [('large',20),('good',10)]]
    monkeypatch.setattr(review,'locate_subjects',AsyncMock(return_value=(geometry,{})))
    provider=SimpleNamespace(chat=AsyncMock(side_effect=[LLMResponse(content=json.dumps(dict(decision='select',asset_id=n,reason='选择候选',findings=[]))) for n in ['large','good']]))
    monkeypatch.setattr(review,'create_provider',lambda:provider)
    result=await review.review_creation(req)
    assert result.decision=='select' and result.asset_id=='good' and provider.chat.await_count==2


@pytest.mark.asyncio
async def test_final_verification_cannot_reintroduce_a_known_scale_mismatch(monkeypatch):
    from tests.test_creation_review_geometry import asset
    requirement='人物约占画高10%'
    req=request(assets=[dict(id='candidate',name='图',mime_type='image/png',data_url=asset().data_url)],candidate_ids=['candidate'])
    req.current_plan['nodes'].append(dict(id='image',kind='image',purpose='shot_reference',title='树',content=requirement,prompt='远景'))
    req.node_id='image'
    monkeypatch.setattr(review,'locate_subjects',AsyncMock(return_value=([dict(candidate_id='candidate',uncertain=False,subject_count=1,subjects=[dict(body_height_percent=20)])],{})))
    reject=dict(decision='revise',reason='太大',findings=[dict(candidate_id='candidate',category='scale',source_id='target',requirement_quote=requirement,observation='人物占20%')])
    provider=SimpleNamespace(chat=AsyncMock(side_effect=[LLMResponse(content=json.dumps(reject)),LLMResponse(content=json.dumps(dict(decision='select',asset_id='candidate',reason='复核通过')))]))
    monkeypatch.setattr(review,'create_provider',lambda:provider)
    result=await review.review_creation(req)
    assert result.decision=='revise' and result.asset_id=='' and provider.chat.await_count==2


@pytest.mark.asyncio
async def test_review_only_returns_a_decision_and_preserves_user_plan(monkeypatch):
    provider=SimpleNamespace(chat=AsyncMock(return_value=LLMResponse(content=json.dumps({'decision':'approve','reason':'分镜清楚','asset_id':''}),model='test')))
    monkeypatch.setattr(review,'create_provider',lambda:provider)
    req=request();before=req.model_dump();trace=TraceStore()
    result=await review.review_creation(req,trace)
    assert result.decision=='approve' and req.model_dump()==before
    assert provider.chat.call_args.kwargs['tools'] is None
    assert not hasattr(result,'plan') and not hasattr(result,'approved_revision')
    assert trace.get_run(result.run_id).status=='completed'


@pytest.mark.asyncio
async def test_candidate_selection_receives_real_previews_and_rejects_foreign_ids(monkeypatch):
    content=BytesIO();Image.new('RGB',(8,8),'red').save(content,format='PNG')
    data='data:image/png;base64,'+base64.b64encode(content.getvalue()).decode()
    req=request(assets=[dict(id='chosen',name='候选图',mime_type='image/png',data_url=data)],candidate_ids=['chosen'])
    req.current_plan['nodes'].insert(0,dict(id='image',kind='image',title='主视觉',prompt='red square'));req.node_id='image'
    provider=SimpleNamespace(chat=AsyncMock(side_effect=[LLMResponse(content=json.dumps({'decision':'select','asset_id':'foreign','reason':'选这张'})),LLMResponse(content=json.dumps({'decision':'select','asset_id':'chosen','reason':'符合构图'}))]))
    monkeypatch.setattr(review,'create_provider',lambda:provider)
    result=await review.review_creation(req)
    assert result.asset_id=='chosen' and provider.chat.await_count==2
    user=provider.chat.call_args.args[0][1].content
    assert any(part['type']=='image_url' for part in user)
    req.candidate_ids=['foreign']
    with pytest.raises(ValueError,match='缺失'):await review.review_creation(req)


@pytest.mark.asyncio
async def test_failed_review_closes_trace_without_leaking_provider_secret(monkeypatch):
    provider=SimpleNamespace(chat=AsyncMock(side_effect=RuntimeError('SECRET')))
    monkeypatch.setattr(review,'create_provider',lambda:provider);trace=TraceStore()
    with pytest.raises(RuntimeError):await review.review_creation(request(),trace)
    assert all(r.status=='failed' and 'SECRET' not in r.error_message for r in trace._runs.values())


@pytest.mark.asyncio
async def test_reference_role_citations_do_not_repeat_review_or_promote_execution_notes(monkeypatch):
    content=BytesIO();Image.new('RGB',(8,8),'red').save(content,format='PNG')
    data='data:image/png;base64,'+base64.b64encode(content.getvalue()).decode()
    req=request(assets=[dict(id=aid,name=aid,mime_type='image/png',data_url=data) for aid in ['candidate','identity']],candidate_ids=['candidate'])
    req.current_plan['nodes'].append(dict(id='image',kind='image',title='御剑',content='保持白兔身份',prompt='白兔御剑',
        references=[dict(asset_id='identity',role='identity',note='仅取身份；执行备注不能新增验收要求')]))
    req.node_id='image'
    response=LLMResponse(content=json.dumps(dict(decision='revise',reason='身份不符',asset_id='',findings=[dict(
        candidate_id='candidate',category='identity',source_id='reference:identity:identity',
        requirement_quote='自动生成的参考备注：额外禁止手持剑',observation='角色耳朵与实际人设不同')]),ensure_ascii=False))
    provider=SimpleNamespace(chat=AsyncMock(side_effect=[response,response,LLMResponse(content=json.dumps(
        dict(checks=[dict(finding_index=0,supported=True,reason='身份参考要求保持角色耳朵特征')])))]))
    monkeypatch.setattr(review,'create_provider',lambda:provider)
    result=await review.review_creation(req)
    assert result.decision=='revise' and provider.chat.await_count==3
    assert result.findings[0].requirement_quote=='保持参考中的角色身份、服装和道具特征，不复制其排版或背景。'
    assert '额外禁止' not in result.reason


@pytest.mark.asyncio
async def test_invalid_evidence_is_bounded_and_trace_identifies_rule_without_private_text(monkeypatch):
    content=BytesIO();Image.new('RGB',(8,8),'red').save(content,format='PNG')
    data='data:image/png;base64,'+base64.b64encode(content.getvalue()).decode()
    req=request(assets=[dict(id='candidate',name='候选',mime_type='image/png',data_url=data)],candidate_ids=['candidate'])
    req.current_plan['nodes'].append(dict(id='image',kind='image',title='御剑',content='白兔侧面御剑',prompt='白兔御剑'))
    req.node_id='image'
    provider=SimpleNamespace(chat=AsyncMock(return_value=LLMResponse(content=json.dumps(dict(
        decision='revise',reason='角色不符',asset_id='',findings=[dict(candidate_id='candidate',category='identity',
        source_id='target',requirement_quote='SECRET-MATERIAL',observation='SECRET-OBSERVATION')])))))
    monkeypatch.setattr(review,'create_provider',lambda:provider)
    trace=TraceStore()
    with pytest.raises(review.ReviewEvidenceError):await review.review_creation(req,trace)
    run=next(iter(trace._runs.values()))
    events=[e for e in run.events if e.type=='creation.review.validation']
    assert run.error_type=='review_evidence_quote_mismatch' and provider.chat.await_count==3
    assert [e.payload['attempt'] for e in events]==[1,2,3]
    assert all(e.payload['stage']=='judge' for e in events)
    assert 'SECRET' not in run.model_dump_json()


@pytest.mark.asyncio
async def test_schema_diagnostics_do_not_log_unknown_field_names_or_model_output(monkeypatch):
    provider=SimpleNamespace(chat=AsyncMock(return_value=LLMResponse(content=json.dumps(
        dict(decision='approve',reason='SECRET'*100,**{'SECRET-FIELD':'SECRET-OUTPUT'})))))
    monkeypatch.setattr(review,'create_provider',lambda:provider);trace=TraceStore()
    with pytest.raises(ValueError):await review.review_creation(request(),trace)
    run=next(iter(trace._runs.values()))
    events=[e for e in run.events if e.type=='creation.review.validation']
    assert run.error_type=='review_invalid_result' and len(events)==3
    assert any(e['loc']==['reason'] and e['type']=='string_too_long' for e in events[0].payload['validation'])
    assert 'SECRET' not in run.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize('status,code',[(401,'provider_auth_failed'),(429,'provider_rate_limited'),(503,'provider_unavailable')])
async def test_review_endpoint_preserves_safe_provider_classification(monkeypatch,status,code):
    class ProviderFailure(RuntimeError):
        status_code=status
    monkeypatch.setattr(review,'create_provider',lambda:SimpleNamespace(chat=AsyncMock(side_effect=ProviderFailure('SECRET'))))
    from agent.main import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        response=await client.post('/agent/creation/review',json=request().model_dump())
    assert response.status_code==502 and response.json()['detail']['code']==code
    assert 'SECRET' not in response.text


@pytest.mark.asyncio
async def test_reasoning_only_reviewer_omits_unsupported_switch_and_budgets_reasoning(monkeypatch):
    provider=SimpleNamespace(provider_name='doubao',model='glm-5.3',max_tokens=None,
        chat=AsyncMock(return_value=LLMResponse(content=json.dumps({'decision':'approve','reason':'符合要求','asset_id':''}))))
    monkeypatch.setattr(review,'create_provider',lambda:provider)
    result=await review.review_creation(request())
    assert result.decision=='approve' and 'thinking_enabled' not in provider.chat.call_args.kwargs
    assert provider.max_tokens==8192


@pytest.mark.asyncio
async def test_review_reports_missing_configuration_without_format_error_or_secret(monkeypatch):
    def missing_provider():
        raise ValueError('missing key SECRET-UPSTREAM')
    monkeypatch.setattr(review, 'create_provider', missing_provider)
    from agent.main import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/agent/creation/review', json=request().model_dump())
    assert response.status_code == 502
    assert response.json()['detail']['code'] == 'provider_config_missing'
    assert '配置' in response.text and 'SECRET' not in response.text and '格式' not in response.text


@pytest.mark.asyncio
async def test_quality_failure_requests_revision_instead_of_stopping_or_approving(monkeypatch):
    provider=SimpleNamespace(chat=AsyncMock(return_value=LLMResponse(content=json.dumps({'decision':'revise','reason':'小伞是蘑菇生物，候选错误混入兔大侠的服饰','asset_id':''}))))
    monkeypatch.setattr(review,'create_provider',lambda:provider)
    req=request();before=req.model_dump()
    result=await review.review_creation(req)
    assert result.decision=='revise' and req.model_dump()==before
    assert provider.chat.await_count==1
    assert 'revise' in provider.chat.call_args.args[0][0].content


@pytest.mark.asyncio
async def test_revision_must_not_approve_any_candidate(monkeypatch):
    provider=SimpleNamespace(chat=AsyncMock(side_effect=[
        LLMResponse(content=json.dumps({'decision':'revise','reason':'需要重做','asset_id':'some-image'})),
        LLMResponse(content=json.dumps({'decision':'revise','reason':'需要重做','asset_id':''}))]))
    monkeypatch.setattr(review,'create_provider',lambda:provider)
    result=await review.review_creation(request())
    assert result.decision=='revise' and result.asset_id=='' and provider.chat.await_count==2


@pytest.mark.asyncio
@pytest.mark.parametrize('second,expected', [('select', 'select'), ('revise', 'revise')])
async def test_image_rejection_is_checked_against_original_pixels_before_expensive_regeneration(monkeypatch, second, expected):
    content=BytesIO();Image.new('RGB',(8,8),'red').save(content,format='PNG')
    data='data:image/png;base64,'+base64.b64encode(content.getvalue()).decode()
    req=request(assets=[dict(id='candidate',name='候选',mime_type='image/png',data_url=data)],candidate_ids=['candidate'])
    req.current_plan['nodes'].append(dict(id='image',kind='image',title='飞行分镜',purpose='shot_reference',prompt='保持参考中的护手'))
    req.node_id='image';before=req.model_dump()
    provider=SimpleNamespace(chat=AsyncMock(side_effect=[
        LLMResponse(content=json.dumps({'decision':'revise','asset_id':'','reason':'多出了护手，需要删除',
            'findings':[dict(candidate_id='candidate', category='identity', source_id='target',
                requirement_quote='保持参考中的护手', observation='候选护手形状与参考不一致')]}),usage={'total_tokens':10}),
        LLMResponse(content=json.dumps({'decision':second,'asset_id':'candidate' if second=='select' else '',
            'reason':'与参考一致' if second=='select' else '确有身份错误',
            'findings':[] if second=='select' else [dict(candidate_id='candidate',category='identity',source_id='target',
                requirement_quote='保持参考中的护手',observation='候选护手形状与参考不一致')]}),usage={'total_tokens':20}),
        LLMResponse(content=json.dumps(dict(checks=[dict(finding_index=0,supported=True,reason='护手是明确要求')])))]))
    monkeypatch.setattr(review,'create_provider',lambda:provider)
    result=await review.review_creation(req)
    assert result.decision==expected and provider.chat.await_count==(3 if second=='revise' else 2)
    assert result.tokens_used['total_tokens']==30 and req.model_dump()==before
    messages=provider.chat.call_args_list[1].args[0]
    assert all(m.role!='assistant' for m in messages), 'fresh verification must not inherit the first answer as fact'
    assert any(p['type']=='image_url' for p in messages[1].content)
    assert '不是已确认事实' in messages[-1].content
    assert '明确要求' in messages[-1].content


@pytest.mark.asyncio
async def test_review_isolates_sibling_repairs_and_labels_actual_reference_images(monkeypatch):
    content=BytesIO();Image.new('RGB',(8,8),'red').save(content,format='PNG')
    data='data:image/png;base64,'+base64.b64encode(content.getvalue()).decode()
    req=request(assets=[dict(id=i,name=i+'.png',mime_type='image/png',data_url=data)
        for i in ['candidate','identity','scene-result','unrelated']],candidate_ids=['candidate'],
        node_context={'scene':{'approved':True,'selected_asset_id':'scene-result'},
            'script':{'approved':True},'other':{'approved':False}},locked_node_ids=['script','scene'])
    req.current_plan['nodes'] = [req.current_plan['nodes'][0],
        dict(id='scene',kind='image',purpose='scene',title='已确认场景',prompt='发光孢子带尾迹',depends_on=['script']),
        dict(id='other',kind='image',title='另一张返工草稿',prompt='UNRELATED_REPAIR: 所有孢子绝不能有尾迹',asset_id='unrelated'),
        dict(id='shot',kind='image',purpose='shot_reference',title='触碰孢子',prompt='指尖触碰孢子',depends_on=['script','scene'],
             references=[dict(asset_id='identity',role='identity',note='人物与道具'),
                         dict(node_id='scene',role='environment',note='孢子形态与云海')])]
    req.messages.extend([
        dict(role='assistant',content='UNRELATED_REPAIR: 我推断全项目不能有尾迹'),
        dict(role='user',node_id='other',content='UNRELATED_REPAIR: 仅此节点取消尾迹'),
        dict(role='user',node_id='shot',content='保持当前场景中的孢子形态')])
    req.node_id='shot';before=req.model_dump()
    provider=SimpleNamespace(chat=AsyncMock(return_value=LLMResponse(content=json.dumps(
        {'decision':'select','asset_id':'candidate','reason':'符合已确认场景与动作'}))))
    monkeypatch.setattr(review,'create_provider',lambda:provider)
    result=await review.review_creation(req)
    parts=provider.chat.call_args.args[0][1].content
    payload=json.loads(parts[0]['text'])
    assert [n['id'] for n in payload['current_plan']['nodes']]==['script','scene','shot']
    assert 'UNRELATED_REPAIR' not in json.dumps(parts,ensure_ascii=False)
    assert [m['content'] for m in payload['messages']]==['生成短片','保持当前场景中的孢子形态']
    assert set(payload['node_context'])=={'script','scene'}
    assert {a['id'] for a in payload['assets']}=={'candidate','identity','scene-result'}
    assert len([p for p in parts if p['type']=='image_url'])==3
    bindings=payload['review_references']
    assert [(r['asset_id'],r['role']) for r in bindings]==[('identity','identity'),('scene-result','environment')]
    assert bindings[1]['source_node_id']=='scene' and bindings[1]['source_approved'] is True
    labels=[p['text'] for p in parts[1:] if p['type']=='text']
    assert any('candidate' in label and '候选' in label for label in labels)
    assert any('scene-result' in label and 'environment' in label and '已确认' in label for label in labels)
    assert result.asset_id=='candidate' and req.model_dump()==before


@pytest.mark.asyncio
async def test_review_marks_unavailable_reference_as_unseen_and_keeps_video_dependencies(monkeypatch):
    req=request(assets=[dict(id='rabbit',name='人设.png',mime_type='image/png')])
    req.current_plan=plan('identity');req.node_id='video'
    provider=SimpleNamespace(chat=AsyncMock(return_value=LLMResponse(content=json.dumps(
        {'decision':'approve','reason':'执行方案自洽','asset_id':''}))))
    monkeypatch.setattr(review,'create_provider',lambda:provider)
    await review.review_creation(req)
    parts=provider.chat.call_args.args[0][1].content;payload=json.loads(parts[0]['text'])
    assert [n['id'] for n in payload['current_plan']['nodes']]==['script','video']
    assert payload['review_references'][0]['asset_id']=='rabbit'
    assert payload['review_references'][0]['preview_available'] is False
    assert payload['assets'][0]['preview_available'] is False
    assert not any(p['type']=='image_url' for p in parts)


@pytest.mark.asyncio
async def test_best_available_selects_real_earlier_candidate_without_changing_requirements(monkeypatch):
    content = BytesIO(); Image.new('RGB', (8, 8), 'red').save(content, format='PNG')
    data = 'data:image/png;base64,' + base64.b64encode(content.getvalue()).decode()
    req = request(selection_mode='best_available', candidate_ids=['earlier', 'latest'],
        assets=[dict(id=i, name=i, mime_type='image/png', data_url=data) for i in ['earlier', 'latest']])
    req.current_plan['nodes'].insert(0, dict(id='image', kind='image', title='主视觉', prompt='红色主视觉'))
    req.node_id = 'image'; before = req.model_dump()
    provider = SimpleNamespace(chat=AsyncMock(side_effect=[
        LLMResponse(content=json.dumps({'decision': 'revise', 'reason': '还不完美'})),
        LLMResponse(content=json.dumps({'decision': 'select', 'asset_id': 'foreign', 'reason': '这张好'})),
        LLMResponse(content=json.dumps({'decision': 'select', 'asset_id': 'earlier', 'reason': '较早的图更接近目标，仍有少量细节问题'})),
    ]))
    monkeypatch.setattr(review, 'create_provider', lambda: provider)
    result = await review.review_creation(req)
    assert result.asset_id == 'earlier' and provider.chat.await_count == 3
    assert req.model_dump() == before
    payload = json.loads(provider.chat.call_args.args[0][1].content[0]['text'])
    assert payload['selection_mode'] == 'best_available'
    assert {a['id'] for a in payload['assets']} == {'earlier', 'latest'}


@pytest.mark.asyncio
async def test_best_available_cannot_approve_text_or_missing_images(monkeypatch):
    provider = SimpleNamespace(chat=AsyncMock())
    monkeypatch.setattr(review, 'create_provider', lambda: provider)
    with pytest.raises(ValueError, match='仅适用'):
        await review.review_creation(request(selection_mode='best_available'))
    assert provider.chat.await_count == 0


@pytest.mark.asyncio
async def test_best_available_keeps_measured_scale_defect_as_residual_instead_of_repainting(monkeypatch):
    from tests.test_creation_region_review import fixture
    assets, _ = fixture()
    req = request(selection_mode='best_available', candidate_ids=['candidate'],
        assets=[dict(id=a.id, name=a.id, mime_type='image/png', data_url=a.data_url) for a in assets])
    req.current_plan['nodes'].append(dict(id='image', kind='image', title='主视觉', prompt='draw'))
    req.node_id = 'image'
    provider = SimpleNamespace(chat=AsyncMock(return_value=LLMResponse(content=json.dumps(
        dict(decision='select', asset_id='candidate', reason='现有候选中最接近目标')))))
    monkeypatch.setattr(review, 'create_provider', lambda: provider)
    monkeypatch.setattr(review, 'measured_scale_rejection', lambda *args: {'observation': '人物占比偏大'})
    result = await review.review_creation(req)
    assert result.decision == 'select' and result.asset_id == 'candidate'
    assert '残余比例问题：人物占比偏大' in result.reason
    assert not result.findings and provider.chat.await_count == 1
