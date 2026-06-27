from __future__ import annotations

from agent.search import SearchService
from agent.skills.base import Skill, SkillMetadata, SkillParameter, SkillResult


class OpenURLSkill(Skill):
    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            name="open_url",
            description=(
                "打开一个公开 HTTP/HTTPS 网页并提取可读正文。适合在 search 返回 URL 后，"
                "继续读取网页详情、核验标题摘要、获取页面正文中的具体信息。"
            ),
            parameters=[
                SkillParameter(
                    name="url",
                    type="string",
                    description="要打开的公开网页 URL，仅支持 http 或 https。",
                    required=True,
                ),
                SkillParameter(
                    name="max_chars",
                    type="integer",
                    description="返回正文最大字符数，默认 6000，最多 12000。",
                    required=False,
                    default=6000,
                ),
            ],
            tags=["web", "reader", "retrieval"],
            source="builtin",
        )

    async def execute(self, **kwargs) -> SkillResult:
        url = str(kwargs.get("url") or "").strip()
        if not url:
            return SkillResult(success=False, error="url is required")

        try:
            max_chars = int(kwargs.get("max_chars") or 6000)
        except (TypeError, ValueError):
            max_chars = 6000
        max_chars = max(500, min(max_chars, 12000))

        try:
            page = await SearchService().open_url(url, max_chars=max_chars)
        except Exception as e:
            return SkillResult(
                success=False,
                error=f"Open URL failed: {e}",
                data={"url": url},
            )

        title = page.title or page.final_url or page.url
        display_parts = [title]
        if page.final_url and page.final_url != page.url:
            display_parts.append(page.final_url)
        if page.content:
            display_parts.append(page.content[:800])

        return SkillResult(
            success=True,
            data={"page": page.model_dump(mode="json")},
            display_text="\n\n".join(display_parts),
        )
