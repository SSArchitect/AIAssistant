# Agent Input Protocol

Version: `agent_input.v1`

This protocol defines the structured packet every agent should receive at its
input boundary. It is especially important when one agent delegates to another:
the target agent needs the user's latest goal plus curated prior facts and stage
outputs, not a thin prompt fragment.

## Required Packet

```json
{
  "protocol_version": "agent_input.v1",
  "source_agent_id": "super_chat",
  "target_agent_id": "image_generation_v1",
  "reason": "intent",
  "forced": false,
  "conversation_id": "conv_...",
  "current_request": "latest user request",
  "mode_ids": ["research"],
  "mode_prompts": ["selected mode instruction"],
  "candidate_context_brief": "curated reusable or researched brief",
  "messages": [
    {
      "role": "assistant",
      "content": "facts that matter to the delegated task",
      "source": "persisted_context",
      "index": 1
    }
  ],
  "attachments": [
    {
      "name": "reference.png",
      "kind": "image",
      "mime_type": "image/png",
      "size": 128,
      "content_preview": "",
      "has_data_url": true,
      "truncated": false
    }
  ],
  "stage_contexts": [
    {
      "stage_id": "source_agent.routing",
      "status": "completed",
      "summary": "Super Chat delegated to image_generation_v1 by intent routing.",
      "content": "",
      "data": {
        "reason": "intent",
        "forced": false
      }
    }
  ],
  "constraints": [
    "Use current_request as the latest user goal.",
    "Do not invent unsupported facts, labels, numbers, dates, or source URLs."
  ],
  "metadata": {
    "context_block_count": 1,
    "candidate_context_chars": 1200
  }
}
```

## Rules

1. The target agent must treat `current_request` as the latest user intent.
2. If `candidate_context_brief` is present, it is the primary factual source.
3. `messages` are curated support context, not raw transcript dumps.
4. Low-signal assistant messages, previous image Markdown, and capability
   refusals should be filtered before handoff.
5. Attachment `data_url` payloads are not copied into trace events; only
   summaries and `has_data_url` are traced.
6. Each delegated run should emit `agent.input_context.built` so the Runs view
   can debug the exact transfer surface.

## Command Protocol

Agents that expose direct commands declare `metadata.command_protocol.version` as
`agent_command.v1`, plus `aliases`, `usage`, and `commands`. Super Chat accepts:

- `/agent <agent_id-or-alias> <command>`
- `/<agent-alias> <command>`
- `/<agent-alias>/<command>`

For `image_generation_v1`, supported commands are:

- `/generate <prompt>`
- `/refine <prompt>`
- `/reference <prompt>`
- `/help`

After command routing, the target agent still receives the normal
`agent_input.v1` packet. The parsed command is recorded as `target_agent.command`
stage context, so planning and prompt review see the cleaned user request plus
the command provenance.

## AI Image Generation

For `image_generation_v1`, the same packet is injected into planning, research,
and prompt review. Super Chat's routing decision is stored as
`source_agent.routing`; target-side planning is stored as
`target_agent.execution_planning`; context reuse or research output is stored as
`target_agent.context_reuse` or `target_agent.research_brief`. This prevents the
image prompt from being rebuilt from only the current user phrase after earlier
steps have already summarized or cropped conversation context.
