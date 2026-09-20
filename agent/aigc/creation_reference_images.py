"""Compile a shot's ordered image responsibilities; style never imports identity."""
import re
from agent.aigc.creation_image_context import ImageReferenceContext, style_only_prompt
from agent.aigc.creation_pose_context import pose_only_guide
from agent.aigc.creation_image_prompt import fit_image_prompt
from agent.aigc.creation_identity_context import isolated_identity_view

RULES = {
    'identity': 'Preserve only this subject identity, proportions, clothing and owned props. Do not copy sheet layout, labels, background or unrelated people.',
    'environment': 'Use this environment, spatial structure and lighting. Do not import people or character identity from it.',
    'composition': 'Use only framing, camera angle and pose layout. Character identity comes from the identity references.',
    'reference': 'Use only the explicitly described visual contribution.',
}

async def prepare_reference_image(request, *, resume=False):
    prompt = request.prompt
    refs = request.image_references or [ImageReferenceContext(role='reference') for _ in request.input_images]
    isolate_pose = request.image_purpose == 'shot_reference' and any(ref.role == 'environment' for ref in refs)
    images, rules, mapping = [], [], {}
    for index, (data, ref) in enumerate(zip(request.input_images, refs), 1):
        if ref.role == 'style':
            mapping[index] = 'the extracted rendering style'
            if not resume:
                prompt = await style_only_prompt(prompt, data, ref, request.idempotency_key + ':style:' + str(index))
            continue
        if ref.role == 'composition' and isolate_pose:
            # A different shot's VAE conditioning copies its scenery even when
            # the prompt says "pose only". Keep only requested pose semantics.
            mapping[index] = 'the extracted pose guide'
            if not resume:
                guide = await pose_only_guide(data, ref, request.prompt, request.idempotency_key + ':pose:' + str(index))
                if guide:
                    rules.append('Pose guide (no source pixels, identity or scenery): '+guide)
            continue
        if not resume and request.image_purpose in {'shot_reference','character'} and ref.role=='identity':
            data=await isolated_identity_view(data,ref,request.prompt,request.idempotency_key+':'+str(index))
        images.append(data)
        mapping[index] = f'Picture {len(images)}'
        rules.append(f'Picture {len(images)}: {RULES[ref.role]} {ref.note}')
    # Provider image labels differ from the video protocol's <Picture N>.
    prompt = re.sub(r'<?Picture\s+([1-9]\d*)>?', lambda m: mapping.get(int(m[1]), m[0]), prompt)
    if resume:
        # This is a lookup of an accepted task, not a new provider submission.
        # Do not let later prompt assembly prevent retrieving its saved output.
        return dict(prompt=request.prompt,mode='reference_to_image',reference_image_data_urls=images) if images else dict(prompt=request.prompt,mode='text_to_image')
    if not images:
        return dict(prompt=prompt, mode='text_to_image')
    guide = 'Create one single continuous scene on a new canvas, not a collage, grid or reference sheet. The target brief controls the action and explicit changes.\n'
    if request.image_purpose == 'scene':
        guide += 'Unpopulated environment establishing shot. Use only the referenced environment and spatial structure; do not import or add characters.\n'
    suffix='\n'+'\n'.join(rules)
    prompt=await fit_image_prompt(prompt,4000-len(guide)-len(suffix),request.idempotency_key)
    compiled = guide + prompt + suffix
    return dict(prompt=compiled, mode='reference_to_image', reference_image_data_urls=images)
