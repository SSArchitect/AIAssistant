"""Convert successful media tool results into durable, typed chat artifacts."""
from __future__ import annotations

import re
from typing import Any

from agent.schemas.chat import ChatArtifact


def video_artifacts_from_result(tool_name: str, data: Any) -> list[ChatArtifact]:
    """Called only for completed tools, using URLs saved by our video client."""
    if tool_name != "generate_video" or not isinstance(data, dict):
        return []
    videos = data.get("videos")
    if not isinstance(videos, list):
        return []
    artifacts: dict[str, ChatArtifact] = {}
    for video in videos:
        if not isinstance(video, dict):
            continue
        url = video.get("url")
        if not isinstance(url, str) or not re.fullmatch(r"/static/generated/aigc/[\w-]+\.mp4", url):
            continue
        if video.get("mime_type", "video/mp4") != "video/mp4" or url in artifacts:
            continue
        artifacts[url] = ChatArtifact(
            type="video", item_id=url, name=url.rsplit("/", 1)[-1],
            title=f"AI 生视频 {len(artifacts) + 1}", url=url, mime_type="video/mp4",
            metadata={
                "source_tool": tool_name,
                "task_id": data.get("id", ""),
                "video": data.get("video") if isinstance(data.get("video"), dict) else {},
                "seed_text": data.get("seed_text"),
            },
        )
    return list(artifacts.values())
