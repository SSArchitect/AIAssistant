"""Stable storyboard-image bindings, compiled to the video's local picture order."""
import re

SHOT_PREFIX='Shot image bindings (creation): '


def validate_shot_ids(node):
    if node.shot_ids:
        if not node.storyboard or len(node.shot_ids)!=len(node.storyboard.shots) or len(set(node.shot_ids))!=len(node.shot_ids):
            raise ValueError('镜头ID需唯一并与视频分镜逐一对应：'+node.id)
        if any(not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}',ident) for ident in node.shot_ids):
            raise ValueError('镜头ID格式无效：'+node.id)


def validate_shot_bindings(node,nodes):
    validate_shot_ids(node)
    bindings=0
    for ref in node.references:
        source=nodes.get(ref.node_id)
        shot=source is not None and source.kind=='image' and source.purpose=='shot_reference'
        if ref.shot_ids:
            if not shot or ref.role!='reference' or len(set(ref.shot_ids))!=len(ref.shot_ids) or any(ident not in node.shot_ids for ident in ref.shot_ids):
                raise ValueError('分镜图绑定必须指向本视频真实镜头：'+node.id)
            if source.aspect_ratio!=node.aspect_ratio:
                raise ValueError('分镜图与视频画幅不一致：'+node.id)
            bindings+=1
        elif shot and node.shot_ids:
            raise ValueError('分镜图缺少镜头绑定：'+node.id)
    if node.shot_ids and not bindings:
        raise ValueError('新视频需准备至少一张关键分镜图并绑定镜头：'+node.id)


def shot_reference_rule(node):
    # Compilation also runs before complete-graph validation (e.g. compaction).
    # Malformed drafts must enter the normal ValueError repair path, not crash.
    validate_shot_ids(node)
    bindings=[]
    for picture,ref in enumerate(node.references,1):
        for ident in ref.shot_ids:
            if ident not in node.shot_ids:
                raise ValueError('分镜图绑定了未知镜头：'+ident)
            index=node.shot_ids.index(ident)
            start=node.storyboard.shots[index].start_seconds
            end=node.storyboard.shots[index+1].start_seconds if index+1<len(node.storyboard.shots) else node.duration_seconds
            bindings.append(f'<Picture {picture}> -> [Shot {index+1}] ({ident}, {start:g}-{end:g}s)')
    if not bindings:return ''
    return SHOT_PREFIX+'; '.join(bindings)+'. Composition and action anchors only; preserve approved character identities and environments. Not exact first frames.'
