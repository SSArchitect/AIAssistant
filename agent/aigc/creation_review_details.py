"""Show small subjects at readable resolution without changing review evidence."""
import base64
from io import BytesIO
import math

from PIL import Image, ImageOps
from agent.aigc.creation_review_geometry import Box
from agent.aigc.image_inputs import decode_image_data_url


def detail_previews(assets, candidate_ids, geometry):
    # Keep candidate treatment even and bound multimodal context growth.
    if len(candidate_ids) > 3:
        return [], []
    assets = {a.id:a for a in assets}
    measurements = {g.get('candidate_id'):g for g in geometry}
    parts, metadata = [], []
    for ident in candidate_ids:
        g, asset = measurements.get(ident, {}), assets.get(ident)
        if not asset or not g or g.get('uncertain', True):
            continue
        choices = []
        for subject in g.get('subjects', []):
            try:
                body = Box.model_validate(subject['body_box'])
                prop = Box.model_validate(subject['ridden_prop_box']) if subject.get('ridden_prop_box') else body
                box = (min(body.left,prop.left),min(body.top,prop.top),max(body.right,prop.right),max(body.bottom,prop.bottom))
                if 20 <= box[3]-box[1] <= 200:
                    choices.append((not bool(subject.get('ridden_prop_box')),box[3]-box[1],box))
            except (ValueError, KeyError, TypeError):
                continue
        if not choices:
            continue
        _, _, normalized = min(choices)
        try:
            raw, _ = decode_image_data_url(asset.data_url)
            with Image.open(BytesIO(raw)) as source:
                source = ImageOps.exif_transpose(source).convert('RGB')
                w,h = source.size
                left,top,right,bottom = [v*s/1000 for v,s in zip(normalized,(w,h,w,h))]
                if bottom-top < 12:
                    continue
                side = min(w,h,math.ceil(max(right-left,bottom-top)*1.4))
                x = max(0,min(w-side,round((left+right-side)/2)))
                y = max(0,min(h-side,round((top+bottom-side)/2)))
                box = [x,y,x+side,y+side]
                crop = source.crop(box).resize((512,512),Image.Resampling.LANCZOS)
                out = BytesIO();crop.save(out,format='PNG')
        except (ValueError, TypeError, OSError):
            continue  # The unchanged full-frame preview remains authoritative.
        metadata.append(dict(candidate_id=ident,box=box,full_width=w,full_height=h))
        parts.extend([{'type':'text','text':f'同一待审候选 {ident} 的原始像素局部放大，仅辅助辨认细节，不是另一张成品或身份参考；不能用于判断全图比例或位置。原全幅{w}x{h}，像素框{box}。全局数量、大小和场景关系仍按原全幅及独立定位核验。'},
            {'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(out.getvalue()).decode()}}])
    return parts, metadata
