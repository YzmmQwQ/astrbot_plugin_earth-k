from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import astrbot.api.message_components as Comp
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools, register
from astrbot.core.message.message_event_result import MessageChain

from .earth_renderer import EarthRenderer
from .earth_service import HELP_GROUPS, EarthService


@register(
    "astrbot_plugin_earth_k",
    "Yzmm",
    "Earth-K 原生 AstrBot 迁移版，保留原有 HTML/CSS 资源",
    "0.1.0",
    repo="https://github.com/YzmmQwQ/astrbot_plugin_earth-k",
)
class EarthKPlugin(Star):
    def __init__(self, context: Context, config: dict[str, Any] | None = None) -> None:
        super().__init__(context)
        self.config = config or {}
        self.plugin_dir = Path(__file__).parent
        self.service = EarthService(self.plugin_dir)
        self.renderer: EarthRenderer | None = None
        self._divination_waiting: set[str] = set()
        self._memory_games: dict[str, dict[str, object]] = {}
        self._memory_scores: dict[tuple[str, str], int] = {}

    async def initialize(self) -> None:
        data_dir = Path(StarTools.get_data_dir(self.name))
        self.renderer = EarthRenderer(data_dir / "renders")
        try:
            await self.renderer.start()
        except Exception as error:
            self.renderer = None
            logger.error(f"Earth-K 本地 HTML 渲染器启动失败: {error}")
        logger.info("Earth-K AstrBot 迁移版已加载")

    async def terminate(self) -> None:
        if self.renderer:
            await self.renderer.stop()

    @filter.command("土块更新")
    async def update_command(self, event: AstrMessageEvent):
        """Use AstrBot's updater instead of the old Yunzai update script."""
        event.stop_event()
        if not event.is_admin():
            yield event.plain_result("该命令仅限管理员使用")
            return

        manager = getattr(self.context, "_star_manager", None)
        session = str(getattr(event, "unified_msg_origin", "") or "")
        if manager is None or not session:
            yield event.plain_result("无法访问 AstrBot 更新器，请在 AstrBot 管理面板中更新 Earth-K")
            return

        asyncio.create_task(self._run_update(manager, session))
        yield event.plain_result("已开始通过 AstrBot 更新 Earth-K，更新完成后插件会自动重载。")

    async def _run_update(self, manager: Any, session: str) -> None:
        try:
            await manager.update_plugin(self.name)
            message = "Earth-K 更新完成，AstrBot 已重新加载插件。"
        except Exception as error:
            logger.exception("Earth-K 插件更新失败")
            message = f"Earth-K 更新失败，请改用 AstrBot 管理面板：{error}"
        try:
            await self.context.send_message(session, MessageChain([Comp.Plain(text=message)]))
        except Exception as error:
            logger.error(f"Earth-K 更新结果发送失败: {error}")

    @filter.command("土块帮助")
    async def help_command(self, event: AstrMessageEvent):
        event.stop_event()
        lines = ["Earth-K 已切换为 AstrBot 命令。", "发送 /土块渲染测试 检查本地 HTML 渲染。", ""]
        lines.extend(f"{command}：{description}" for _, items in HELP_GROUPS for command, description in items)
        yield event.plain_result("\n".join(lines))

    @filter.command("土块版本")
    async def version_command(self, event: AstrMessageEvent):
        event.stop_event()
        yield event.plain_result(self.service.version_text())

    @filter.command("今日运势")
    async def fortune(self, event: AstrMessageEvent):
        event.stop_event()
        try:
            result = await self.service.daily_fortune(str(event.get_sender_id()))
            yield event.plain_result(
                f"今日运势：{result['summary']}\n"
                f"星级：{result['star']}\n"
                f"点评：{result['review']}\n"
                f"解读：{result['detail']}\n"
                f"来源：{result['source']}"
            )
        except Exception as error:
            logger.exception("Earth-K 运势查询失败")
            yield event.plain_result(f"运势查询失败：{error}")

    @filter.command("卜卦")
    async def divination(self, event: AstrMessageEvent):
        event.stop_event()
        user_id = str(event.get_sender_id())
        if user_id not in self._divination_waiting:
            self._divination_waiting.add(user_id)
            yield event.plain_result(
                "周易占卜原则\n一卦一事，请集中意念，不要反复占卜。\n请再次发送 /卜卦 开始起卦。"
            )
            return
        if not self.renderer:
            yield event.plain_result("本地 HTML 渲染器未启动")
            return
        self._divination_waiting.discard(user_id)
        try:
            image = await self.renderer.render(self.service.divination_card(self.service.draw_divination()))
            yield event.image_result(image)
        except Exception as error:
            logger.exception("Earth-K 占卜失败")
            yield event.plain_result(f"占卜失败：{error}")

    @filter.command("练习记忆力")
    async def memory_start(self, event: AstrMessageEvent):
        event.stop_event()
        if not self.renderer:
            yield event.plain_result("本地 HTML 渲染器未启动")
            return
        session = str(getattr(event, "unified_msg_origin", "") or event.get_sender_id())
        if session in self._memory_games:
            yield event.plain_result("当前已经有一轮记忆力练习，请先回答上一轮。")
            return
        game = self.service.new_memory_round()
        self._memory_games[session] = game
        positions = game["positions"]
        target = int(game["target"])
        renderer = self.renderer
        try:
            numeric = [str(index) for index in range(9)]
            yield event.image_result(await renderer.render(self.service.memory_card(positions, numeric)))
            yield event.plain_result("请观察数字卡 10 秒，随后回答目标数字对应的字母。")
            await asyncio.sleep(10)
            yield event.image_result(await renderer.render(self.service.memory_card(positions, list(game["labels"]))))
            yield event.plain_result(f"请回答数字 {target} 对应的字母，例如：/我猜 a")
        except Exception as error:
            self._memory_games.pop(session, None)
            logger.exception("Earth-K 记忆力练习失败")
            yield event.plain_result(f"记忆力练习失败：{error}")

    @filter.command("我猜")
    async def memory_answer(self, event: AstrMessageEvent, answer: str = ""):
        event.stop_event()
        session = str(getattr(event, "unified_msg_origin", "") or event.get_sender_id())
        game = self._memory_games.pop(session, None)
        if not game:
            yield event.plain_result("当前没有进行中的记忆力练习，请先发送 /练习记忆力。")
            return
        labels = list(game["labels"])
        target = int(game["target"])
        expected = labels[target]
        if answer.strip().lower() != expected:
            yield event.plain_result(f"回答错误，数字 {target} 对应的字母是 {expected}。")
            return
        sender = str(event.get_sender_id())
        score_key = (session, sender)
        self._memory_scores[score_key] = self._memory_scores.get(score_key, 0) + 1
        positions = list(game["positions"])
        try:
            if self.renderer:
                numeric = [str(index) for index in range(9)]
                image = await self.renderer.render(self.service.memory_card(positions, numeric, target))
                yield event.image_result(image)
            yield event.plain_result(
                f"恭喜你回答正确！本轮得分：{self._memory_scores[score_key]}"
            )
        except Exception as error:
            logger.exception("Earth-K 记忆力结果渲染失败")
            yield event.plain_result(f"回答正确，但结果图片渲染失败：{error}")

    @filter.command("重置记忆分数")
    async def memory_reset(self, event: AstrMessageEvent):
        event.stop_event()
        if not event.is_admin():
            yield event.plain_result("该命令仅限管理员使用")
            return
        session = str(getattr(event, "unified_msg_origin", "") or event.get_sender_id())
        for key in [key for key in self._memory_scores if key[0] == session]:
            self._memory_scores.pop(key, None)
        self._memory_games.pop(session, None)
        yield event.plain_result("当前会话的记忆力分数已重置")

    @filter.command("土块渲染测试")
    async def render_test(self, event: AstrMessageEvent):
        event.stop_event()
        if not event.is_admin() or not event.is_private_chat():
            yield event.plain_result("该命令仅限管理员私聊使用")
            return
        if not self.renderer:
            yield event.plain_result("本地 HTML 渲染器未启动")
            return
        try:
            image = await self.renderer.render(self.service.divination_html())
            yield event.image_result(image)
        except Exception as error:
            logger.exception("Earth-K 渲染测试失败")
            yield event.plain_result(f"渲染失败：{error}")
