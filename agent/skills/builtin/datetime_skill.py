from datetime import datetime, timezone

from agent.skills.base import Skill, SkillMetadata, SkillParameter, SkillResult


class DateTimeSkill(Skill):
    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            name="datetime",
            description="获取当前日期和时间。可以按指定时区返回。",
            parameters=[
                SkillParameter(
                    name="timezone",
                    type="string",
                    description="时区名称，例如 Asia/Shanghai 或 US/Eastern。默认 UTC。",
                    required=False,
                    default="UTC",
                ),
                SkillParameter(
                    name="format",
                    type="string",
                    description="输出格式，例如 %Y-%m-%d %H:%M:%S。默认 ISO 格式。",
                    required=False,
                    default="iso",
                ),
            ],
            tags=["utility", "time"],
            domains=["utility", "time"],
            routing_keywords=["时间", "日期", "几点", "今天", "时区"],
            always_on=True,
            parallel_safe=True,
            idempotent=True,
        )

    async def execute(self, **kwargs) -> SkillResult:
        tz_name = kwargs.get("timezone", "UTC")
        fmt = kwargs.get("format", "iso")

        try:
            import zoneinfo
            tz = zoneinfo.ZoneInfo(tz_name)
        except Exception:
            return SkillResult(success=False, error=f"Unknown timezone: {tz_name}")

        now = datetime.now(tz)

        if fmt == "iso":
            formatted = now.isoformat()
        else:
            try:
                formatted = now.strftime(fmt)
            except Exception:
                formatted = now.isoformat()

        return SkillResult(
            success=True,
            data={
                "datetime": formatted,
                "timezone": tz_name,
                "timestamp": int(now.timestamp()),
            },
            display_text=f"Current time ({tz_name}): {formatted}",
        )
