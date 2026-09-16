"""Recover video identity and attachment inputs from this owner's conversation only."""
import re


def recover_video_request(store, *, user_id, conversation_id, arguments):
    arguments = dict(arguments)
    # This value is internal; a model must never choose another provider task.
    arguments.pop('_resume_task_id', None)
    key = arguments.get('idempotency_key')
    if not key:
        return arguments, None
    frozen = store.get_video_request(user_id, conversation_id, key)
    if frozen is not None:
        arguments = frozen
    candidates = []
    cursor = ''
    while True:
        page = store.list_runs_page(user_id=user_id, conversation_id=conversation_id,
                                    limit=100, cursor=cursor)
        for run in page.runs:
            progress = [event.payload for event in run.events
                        if event.type == 'media.task.progress'
                        and event.payload.get('kind') == 'video'
                        and event.payload.get('idempotency_key') == key]
            if not progress:
                continue
            for item in reversed(progress):
                if item.get('task_id'):
                    return arguments, item['task_id']
            candidates.append(run)
        if not page.has_more:
            break
        cursor = page.next_cursor

    if frozen is not None:
        return arguments, None

    # Legacy traces have redacted prompts but retain the original selectors and
    # non-sensitive options. The first accepted local invocation defines replay;
    # later model turns must not reorder images or change duration/seed/mode.
    candidates.sort(key=lambda run: (run.started_at, run.run_id))
    replay_prompt = arguments.get('prompt')
    for run in candidates:
        started = {}
        for event in run.events:
            payload = event.payload
            if event.type == 'tool.started' and payload.get('name') == 'generate_video':
                started[event.step_id] = payload.get('arguments', {})
            if (event.type == 'tool.governance.allowed' and payload.get('tool_name') == 'generate_video'
                    and payload.get('arguments', {}).get('idempotency_key') == key):
                original = {**started.get(event.step_id, {}), **payload['arguments']}
                arguments = {k: v for k, v in original.items()
                             if not k.startswith('_') and v != '<redacted>'}
                arguments['prompt'] = original.get('prompt') if original.get('prompt') not in (None, '<redacted>') else replay_prompt
                candidates = [run]
                break
        else:
            continue
        break

    indices = arguments.get('reference_image_attachment_indices')
    single = arguments.get('image_attachment_index')
    if indices is None and single is None:
        return arguments, None
    selected = indices if indices is not None else [single]
    if (not isinstance(selected, list) or not 1 <= len(selected) <= 9
            or any(type(i) is not int or i < 1 for i in selected)
            or len(set(selected)) != len(selected)):
        raise ValueError('Select 1-9 distinct image attachment indices')
    for run in candidates:
        for event in run.events:
            if event.type != 'context.built':
                continue
            messages = event.payload.get('final_model_request', {}).get('messages', [])
            # Only the original turn's user message contains its attachment labels.
            message = next((m for m in reversed(messages) if m.get('role') == 'user'), {})
            content = message.get('content')
            if not isinstance(content, list):
                continue
            images = {}
            for label, part in zip(content, content[1:]):
                match = re.match(r'^Attachment (\d+): ', label.get('text', ''))
                url = part.get('image_url', {}).get('url', '')
                if match and part.get('type') == 'image_url' and url.startswith('data:image/'):
                    images[int(match[1])] = url
            if all(i in images for i in selected):
                if indices is not None:
                    if any(arguments.get(k) is not None for k in
                           ('reference_image_data_urls', 'reference_image_asset_ids', 'reference_image_urls')):
                        raise ValueError('Choose exactly one reference image source')
                    arguments.pop('reference_image_attachment_indices')
                    arguments['reference_image_data_urls'] = [images[i] for i in selected]
                else:
                    if any(arguments.get(k) is not None for k in ('first_frame_data_url', 'first_frame_asset_id')):
                        raise ValueError('Choose one image source')
                    arguments.pop('image_attachment_index')
                    arguments['first_frame_data_url'] = images[single]
                return arguments, None
    if candidates:
        raise ValueError('Original video attachments are unavailable; do not replace them under the same idempotency key')
    return arguments, None
