"""Versioned foreground-v1 recipe: keyed subject, padded completion, alpha compose.

The intermediate task is independently recoverable. Only the completion task is
owned by the outer Creation run; neither stage bypasses final image review.
"""
import asyncio
import base64
from dataclasses import dataclass
from io import BytesIO
import os
import tempfile
from types import SimpleNamespace

import numpy as np
from PIL import Image

from agent.aigc.creation_identity_context import isolated_identity_view
from agent.aigc.creation_image_layout import png_bytes, read_image
from agent.aigc.creation_media_state import CreationMediaState
from agent.aigc.image_inputs import decode_image_data_url, load_image_url
from agent.aigc.progress import background_enabled, emit_progress, progress_scope
from agent.aigc.spark_client import SparkImageClient, SparkProviderError
from agent.aigc.spark_uploads import UPLOAD_CACHE_DIR
from agent.config import runtime_config
from agent.schemas.aigc import ImageGenerationRequest

KEYS = {'magenta': ((255,0,255),(0,2),(1,),('magenta','洋红','品红')),
        'green': ((0,255,0),(1,),(0,2),('green','绿色','绿衣')),
        'cyan': ((0,255,255),(1,2),(0,),('cyan','青色','青衣')),
        'blue': ((0,0,255),(2,),(0,1),('blue','蓝色','蓝衣'))}


@dataclass
class ForegroundRegion:
    scene: Image.Image
    placement: object
    key_name: str


def invalid_foreground():
    return SparkProviderError('Foreground is clipped or cannot be separated safely', code='invalid_output')


def key_score(array, name):
    _, high, low, _ = KEYS[name]
    return array[:,:,high].min(axis=2) - array[:,:,low].max(axis=2)


def choose_key(identity, subject):
    array=np.asarray(identity.resize((256,256)).convert('RGB'),dtype=float)
    for name, (_, _, _, words) in KEYS.items():
        if not any(word in subject.lower() for word in words) and np.mean(key_score(array,name)>30)<.0001:
            return name
    # Do not silently erase a costume color; the planner may use another method.
    raise invalid_foreground()


def foreground_client():
    return SparkImageClient(runtime_config.get('aigc.spark.base_url'),runtime_config.get('aigc.spark.api_key'),upload_cache_dir=UPLOAD_CACHE_DIR)


def data(image):
    return 'data:image/png;base64,'+base64.b64encode(png_bytes(image)).decode()


def save_private(path, raw):
    fd, temporary=tempfile.mkstemp(dir=path.parent,suffix='.pending')
    try:
        with os.fdopen(fd,'wb') as output:output.write(raw)
        os.replace(temporary,path)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)


async def prepare_foreground(request, original, crop, identity, ref, index, *, resume):
    placement=request.image_layout[0]
    key_name=choose_key(read_image(identity),placement.subject_prompt)
    region=ForegroundRegion(original,placement,key_name)
    options=dict(mode='reference_to_image',aspect_ratio='1:1',width=512,height=512)
    if resume:
        # The outer accepted job is status-only. Its actual frozen input is already
        # with the Provider; never regenerate/reinspect the intermediate here.
        return region,dict(options,prompt='Resume accepted foreground completion',reference_image_data_urls=[identity])
    emit_progress(stage='preparing_foreground')
    identity=await isolated_identity_view(identity,ref,placement.subject_prompt,request.idempotency_key+':foreground-v1:'+str(index))
    rgb=KEYS[key_name][0]
    prompt=('Create one isolated subject for compositing. Picture 1 provides ONLY lighting and rendering style, never its landscape. '
        'Picture 2 provides identity, costume and owned props, never its studio background or sheet layout. '
        'Reference responsibility: '+ref.note+'\nSubject and action: '+placement.subject_prompt+'\n'
        'The whole subject AND its ridden/held prop must be contained, approximately 45 percent of the square height, '
        'with empty margins on all four sides. The entire background and spaces between limbs are flat uniform '
        +key_name+' chroma-key RGB'+str(rgb)+'. No ground, background shadow, fog on the backdrop, scenery, border, text or extra figures. '
        'Only the subject and its owned prop are opaque. Match Picture 1 lighting on the subject.')
    # Hashing keeps the derived key below the Provider limit even for a 128-char
    # parent key; it is a distinct stable namespace, never a fabricated task ID.
    import hashlib
    child_key='foreground-v1-'+hashlib.sha256(request.idempotency_key.encode()).hexdigest()
    child=ImageGenerationRequest(provider='spark',prompt=prompt,idempotency_key=child_key,
        reference_image_data_urls=[data(crop),identity],**options)
    checkpoint=CreationMediaState(SimpleNamespace(model_dump_json=child.model_dump_json,idempotency_key=child_key,resume_task_id=''))
    cached=checkpoint.path.with_suffix('.foreground.png')
    raw=None
    if cached.exists() and cached.stat().st_size<=16*1024*1024:
        try:
            with Image.open(cached) as image:
                if image.size==(512,512):image.load();raw=cached.read_bytes()
        except OSError:pass
    if raw is None:
        try:
            with progress_scope(checkpoint.progress,background=background_enabled()):
                result=await foreground_client().generate(child,**({'resume_task_id':checkpoint.task_id} if checkpoint.task_id else {}))
            if len(result.images)!=1:raise invalid_foreground()
            item=result.images[0]
            value='data:'+item.mime_type+';base64,'+item.base64 if item.base64 else await load_image_url(item.url)
            raw,_=decode_image_data_url(value)
            with Image.open(BytesIO(raw)) as image:
                if image.size!=(512,512):raise invalid_foreground()
            save_private(cached,raw)
        except SparkProviderError as exc:
            # The child ID stays in its checkpoint. Returning it in the outer API
            # would cause Gateway to resume the wrong image as the final result.
            raise SparkProviderError('Foreground preparation did not finish',code=exc.code,
                idempotency_key=request.idempotency_key,http_status=exc.http_status,task_status=exc.task_status) from None
    with Image.open(BytesIO(raw)) as image:
        image=image.convert('RGB')
        array=np.asarray(image,dtype=float); score=key_score(array,key_name)
        if np.mean(score>120)<.15:raise invalid_foreground()
        measured=tuple(np.median(array[score>120],axis=0).round().astype(int))
        padded=Image.new('RGB',(512,512),measured)
        padded.paste(image.resize((320,320),Image.Resampling.LANCZOS),(96,96))
    emit_progress(stage='completing_foreground')
    prompt=('Edit this exact canvas. Keep the existing subject and its props at the current size and centered position; '
        'do not enlarge, zoom in or reframe. Keep the empty '+key_name+' margins on all four sides. '
        'Complete truncated tips, ears, limbs or prop ends using adjacent empty space, so the WHOLE subject and entire prop are contained. '
        'Preserve its identity, action, costume and lighting. Clean the background to flat uniform '+key_name+' chroma-key RGB'+str(rgb)+'. '
        'No ground, extra objects, new figures, sheet layout, border or text. Make only missing-edge corrections; '
        'the subject stays approximately the central 60 percent of the image.')
    return region,dict(options,prompt=prompt,reference_image_data_urls=[data(padded)])


def foreground_layer(raw, key_name):
    with Image.open(BytesIO(raw)) as image:
        if image.size!=(512,512):raise invalid_foreground()
        array=np.asarray(image.convert('RGB'),dtype=float)
    score=key_score(array,key_name)
    if np.mean(score>120)<.15:raise invalid_foreground()
    alpha=np.clip((100-score)/70,0,1)
    mask=alpha>.05; seen=np.zeros(mask.shape,bool); components=[]
    for y,x in zip(*np.where(mask)):
        if seen[y,x]:continue
        stack=[(int(y),int(x))];seen[y,x]=True;points=[]
        while stack:
            yy,xx=stack.pop();points.append((yy,xx))
            for ny,nx in ((yy-1,xx),(yy+1,xx),(yy,xx-1),(yy,xx+1)):
                if 0<=ny<512 and 0<=nx<512 and mask[ny,nx] and not seen[ny,nx]:seen[ny,nx]=True;stack.append((ny,nx))
        components.append(points)
    if not components:raise invalid_foreground()
    components.sort(key=len,reverse=True);points=components[0]
    positions=np.array(points);ys,xs=positions[:,0],positions[:,1]
    if len(points)<1000 or min(xs.min(),ys.min())<=1 or xs.max()>=510 or ys.max()>=510:raise invalid_foreground()
    # Do not silently discard a detached prop/limb/second figure. Only tiny
    # disconnected border/noise artifacts may be dropped.
    if any(len(c)>max(600,len(points)*.02) for c in components[1:]):raise invalid_foreground()
    keep=np.zeros(mask.shape,bool);keep[ys,xs]=True
    for _ in range(2):
        padded=np.pad(keep,1);keep=padded[1:-1,1:-1]|padded[:-2,1:-1]|padded[2:,1:-1]|padded[1:-1,:-2]|padded[1:-1,2:]
    alpha*=keep
    key=np.median(array[score>120],axis=0)
    foreground=np.clip((array-(1-alpha[:,:,None])*key)/np.maximum(alpha[:,:,None],.01),0,255)
    box=(int(xs.min())-2,int(ys.min())-2,int(xs.max())+3,int(ys.max())+3)
    return Image.fromarray(np.round(np.dstack([foreground,alpha*255])).astype('uint8')).crop(box)


def composite_foreground(region, raw):
    layer=foreground_layer(raw,region.key_name)
    p=region.placement;scene=region.scene
    height=round(scene.height*p.subject_height_percent/100);width=round(layer.width*height/layer.height)
    x=round(scene.width*p.center_x_percent/100-width/2);y=round(scene.height*p.center_y_percent/100-height/2)
    if x<0 or y<0 or x+width>scene.width or y+height>scene.height:raise invalid_foreground()
    layer=layer.resize((width,height),Image.Resampling.LANCZOS)
    final=scene.copy();final.paste(layer,(x,y),layer.getchannel('A'))
    return png_bytes(final)
