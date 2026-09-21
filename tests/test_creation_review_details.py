import base64
from io import BytesIO
from types import SimpleNamespace
import pytest
from PIL import Image


def fixture():
    out=BytesIO();Image.new('RGB',(576,1024),(240,100,20)).save(out,format='PNG')
    a=SimpleNamespace(id='candidate',data_url='data:image/png;base64,'+base64.b64encode(out.getvalue()).decode())
    g=[dict(candidate_id=a.id,uncertain=False,subjects=[dict(body_box=dict(left=185,top=776,right=300,bottom=864),ridden_prop_box=dict(left=185,top=850,right=326,bottom=878))])]
    return a,g


def test_details_are_labeled_original_candidate_pixels_and_leave_geometry_unchanged():
    import copy
    from agent.aigc.creation_review_details import detail_previews
    a,g=fixture();before=copy.deepcopy(g)
    parts,metadata=detail_previews([a],['candidate'],g)
    assert len(parts)==2 and metadata[0]['candidate_id']=='candidate'
    assert '不能用于判断全图比例或位置' in parts[0]['text']
    assert g==before and 'image_url' in parts[1]
    raw=base64.b64decode(parts[1]['image_url']['url'].split(',',1)[1]);im=Image.open(BytesIO(raw))
    assert im.size==(512,512) and im.getpixel((250,250))==(240,100,20)
    assert metadata[0]['box'][0]<185/1000*576 and metadata[0]['box'][2]>326/1000*576


@pytest.mark.parametrize('mode',['uncertain','foreign','large','malformed','too_many'])
def test_unreliable_or_out_of_scope_details_are_skipped(mode):
    from agent.aigc.creation_review_details import detail_previews
    a,g=fixture();ids=['candidate']
    if mode=='uncertain':g[0]['uncertain']=True
    if mode=='foreign':g[0]['candidate_id']='reference'
    if mode=='large':g[0]['subjects'][0]['body_box']['top']=200
    if mode=='malformed':g[0]['subjects'][0]['body_box']['left']=2000
    if mode=='too_many':ids=['candidate','b','c','d']
    assert detail_previews([a],ids,g)==([],[])


def test_ridden_subject_is_preferred_to_small_background_animals():
    from agent.aigc.creation_review_details import detail_previews
    a,g=fixture()
    g[0]['subjects'].insert(0,dict(body_box=dict(left=310,top=60,right=700,bottom=240),ridden_prop_box=None))
    parts,meta=detail_previews([a],['candidate'],g)
    assert len(meta)==1 and meta[0]['box'][1]>700


@pytest.mark.asyncio
@pytest.mark.parametrize('too_large',[False,True])
async def test_review_keeps_full_frame_scale_authoritative_with_detail_context(monkeypatch,too_large):
    import json
    from unittest.mock import AsyncMock
    from agent.aigc import creation_review as review
    from agent.llm.base import LLMResponse
    from agent.trace.store import TraceStore
    from tests.test_creation_review import request
    a,g=fixture();g[0]['subject_count']=1
    g[0]['subjects'][0]['body_and_prop_height_percent']=10.2
    g[0]['subjects'][0]['body_height_percent']=8.8
    if too_large:
        g[0]['subjects'][0]['body_box']['top']=500
        g[0]['subjects'][0]['body_and_prop_height_percent']=37.8
        g[0]['subjects'][0]['body_height_percent']=36.4
    req=request(assets=[dict(id=a.id,name='图',mime_type='image/png',data_url=a.data_url)],candidate_ids=[a.id])
    req.current_plan['nodes'].append(dict(id='image',kind='image',purpose='shot_reference',title='树',content='整体高度约为画面高度的十分之一',prompt='draw'))
    req.node_id='image'
    provider=SimpleNamespace(chat=AsyncMock(return_value=LLMResponse(content=json.dumps(dict(decision='select',asset_id=a.id,reason='ok')))))
    monkeypatch.setattr(review,'create_provider',lambda:provider)
    monkeypatch.setattr(review,'locate_subjects',AsyncMock(return_value=(g,{})))
    trace=TraceStore();result=await review.review_creation(req,trace)
    parts=provider.chat.call_args.args[0][1].content
    assert sum(p['type']=='image_url' for p in parts)==(1 if too_large else 2)
    assert result.decision==('revise' if too_large else 'select')
    if too_large:assert result.findings[0].category=='scale'
    else:
        payload=json.loads(parts[0]['text'])
        assert payload['candidate_ids']==[a.id] and payload['visual_measurements']==g
        assert any(e.type=='creation.review.details' for e in trace.get_run(result.run_id).events)
