"""Scene timelines connect reference nodes to clip time, including continuous shots."""
from fractions import Fraction
from agent.aigc.creation_shots import SHOT_PREFIX,shot_reference_rule

SCENE_PREFIX = "Environment timeline (creation): "


def validate_scene_intervals(node, nodes):
    scenes = [ref for ref in node.references if ref.node_id in nodes and nodes[ref.node_id].purpose == 'scene'
              and nodes[ref.node_id].kind == 'image' and ref.role in {'reference', 'first_frame'}]
    for ref in node.references:
        if ref.scene_intervals and ref not in scenes:
            raise ValueError('场景时段只能绑定本视频引用的场景图片节点：' + node.id)
    # Existing single-environment clips have an implicit full-clip binding.
    if len(scenes) <= 1 and not any(ref.scene_intervals for ref in scenes):
        return
    if any(not ref.scene_intervals for ref in scenes):
        raise ValueError('多场景视频必须为每张场景图填写scene_intervals，明确使用时段：' + node.id)
    intervals = sorted((Fraction(str(span.start_seconds)), Fraction(str(span.end_seconds)))
                       for ref in scenes for span in ref.scene_intervals)
    cursor, duration = Fraction(0), Fraction(node.duration_seconds)
    for start, end in intervals:
        if start != cursor or end <= start or end > duration:
            raise ValueError('场景时段必须从0秒起连续覆盖视频，不能重叠、空缺或越界：' + node.id)
        cursor = end
    if cursor != duration:
        raise ValueError('场景时段必须覆盖到视频结束：' + node.id)


def scene_timeline_rule(node):
    intervals = sorted((span.start_seconds, span.end_seconds, i)
        for i, ref in enumerate(node.references, 1) for span in ref.scene_intervals)
    shot_rule = shot_reference_rule(node)
    if not intervals:
        return shot_rule
    times = '; '.join(f'{start:g}-{end:g}s <Picture {i}>' for start, end, i in intervals)
    return SCENE_PREFIX + times + '. Use each environment only in its interval; preserve character identity across transitions.' + ('\n' + shot_rule if shot_rule else '')


def clean_scene_storyboard(storyboard):
    style = '\n'.join(line for line in storyboard.style.split('\n') if not line.startswith((SCENE_PREFIX,SHOT_PREFIX)))
    return storyboard.model_copy(update={'style': style})


def scene_storyboard(node):
    rule = scene_timeline_rule(node)
    storyboard = clean_scene_storyboard(node.storyboard)
    return storyboard.model_copy(update={'style': storyboard.style + '\n' + rule}) if rule else storyboard
