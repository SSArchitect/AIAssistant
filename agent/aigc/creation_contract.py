"""Generation contracts rule out combinations the storage model cannot express.

The broad storage/patch models remain backwards compatible. These narrower
contracts are sent to the model; final ownership, graph and lock checks remain
mandatory even when a provider only supports JSON-object output.
"""
import copy


def node_schema(schema, kind, *, patch=False, ident=None, asset_ids=None):
    definitions = schema['$defs']
    node = copy.deepcopy(definitions['CreativeNodePatch' if patch else 'CreativeNode'])
    props = node['properties']
    props['kind'] = {'type': 'string', 'enum': [kind]}
    if ident is not None:
        props['id']['enum'] = [ident]
    if kind == 'text':
        props['content']['minLength'] = 1
        props['references']['maxItems'] = 0
        props['storyboard'] = {'type': 'null'}
        for field in ('asset_id', 'character_style', 'prompt'):
            props[field] = {'type': 'string', 'enum': ['']}
    else:
        branches = []
        for source in ('node_id', 'asset_id'):
            for timed in ([False, True] if kind == 'video' and source == 'node_id' else [False]):
                ref = copy.deepcopy(definitions['CreativeReference'])
                p = ref['properties']
                p[source]['minLength'] = 1
                if source == 'asset_id' and asset_ids:
                    p[source]['enum'] = list(asset_ids)
                p['asset_id' if source == 'node_id' else 'node_id'] = {'type': 'string', 'enum': ['']}
                if timed:
                    p['role'] = {'type': 'string', 'enum': ['reference']}
                else:
                    p['scene_intervals']['maxItems'] = 0
                ref['required'] = list(set(ref.get('required', [])) | {source})
                branches.append(ref)
        props['references']['items'] = {'anyOf': branches}
        if kind == 'image':
            props['references']['maxItems'] = 1
            props['storyboard'] = {'type': 'null'}
        else:
            props['asset_id'] = props['character_style'] = {'type': 'string', 'enum': ['']}
            props['count'] = {'type': 'integer', 'enum': [1]}
    return node


def planning_schema(model, request):
    schema = model.model_json_schema()
    patch = 'CreativePlanPatch' in schema.get('$defs', {})
    container = schema['$defs']['CreativePlanPatch' if patch else 'CreativePlan']
    variants = []
    assets = [a.id for a in request.assets if a.mime_type.startswith('image/')]
    existing = request.current_plan.get('nodes', []) if patch else []
    for kind in ('text', 'image', 'video'):
        ids = [n['id'] for n in existing if n['kind'] == kind and n['id'] not in request.locked_node_ids]
        if ids:
            variant = node_schema(schema, kind, patch=True, asset_ids=assets)
            variant['properties']['id']['enum'] = ids
            variants.append(variant)
        if request.repair and kind != 'image':
            continue  # Repair may add scene prerequisites, never new deliverables.
        variant = node_schema(schema, kind, patch=patch, asset_ids=assets)
        variant['required'] = list(dict.fromkeys(variant.get('required', []) + ['id', 'kind', 'title']))
        if request.repair:
            variant['properties']['purpose'] = {'type': 'string', 'enum': ['scene']}
            variant['properties']['count'] = {'type': 'integer', 'enum': [1]}
            variant['required'].append('purpose')
        variants.append(variant)
    container['properties']['nodes']['items'] = {'anyOf': variants}
    return schema
