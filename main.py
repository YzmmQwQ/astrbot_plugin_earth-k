from __future__ import annotations

import asyncio
import random
from pathlib import Path
from typing import Any
from uuid import uuid4

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
        self.data_dir: Path | None = None
        self._divination_waiting: set[str] = set()
        self._memory_games: dict[str, dict[str, object]] = {}
        self._memory_scores: dict[tuple[str, str], int] = {}
        self._dice_games: dict[str, dict[str, object]] = {}
        self._voice_games: dict[str, dict[str, object]] = {}
        self._voice_scores: dict[str, dict[str, object]] = {}

    async def initialize(self) -> None:
        data_dir = Path(StarTools.get_data_dir(self.name))
        self.data_dir = data_dir
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

    @filter.command("了解")
    async def character_info(self, event: AstrMessageEvent, character: str = ""):
        event.stop_event()
        image = self.service.character_image(character)
        if not image:
            yield event.plain_result("该角色资料图正在筹备中，欸嘿")
            return
        yield event.image_result(str(image))

    @filter.command("角色语音汇总")
    async def voice_summary(self, event: AstrMessageEvent):
        event.stop_event()
        if not self.renderer:
            yield event.plain_result("本地 HTML 渲染器未启动")
            return
        try:
            entries = await self.service.genshin_character_entries()
            items = [{"name": str(entry["title"]), "content": str(entry.get("summary") or "")} for entry in entries]
            html = self.service.genshin_voice_list_html("角色", items)
            yield event.image_result(await self.renderer.render(html, viewport_width=1200))
        except Exception as error:
            logger.exception("Earth-K 角色语音汇总失败")
            yield event.plain_result(f"角色语音汇总获取失败：{error}")

    @filter.command("语音")
    async def voice_play(self, event: AstrMessageEvent, payload: str = ""):
        event.stop_event()
        parts = payload.strip().split()
        if not parts:
            yield event.plain_result("用法：/语音 <角色> [编号]，例如 /语音 胡桃 1；发送 /角色语音汇总查看角色名。")
            return
        index = None
        if parts[-1].isdigit():
            index = int(parts.pop()) - 1
        character = " ".join(parts).strip()
        if not character:
            yield event.plain_result("请提供角色名。")
            return
        try:
            entry, matches = await self.service.genshin_voice_entry(character)
            if entry is None:
                if matches:
                    names = "、".join(str(item.get("title") or "") for item in matches[:12])
                    yield event.plain_result(f"没有唯一匹配，请输入更完整的角色名：{names}")
                else:
                    yield event.plain_result("没有找到该角色的语音。")
                return
            items = entry["voice_items"]
            if not isinstance(items, list) or not items:
                yield event.plain_result("该角色没有可用语音。")
                return
            if index is None:
                index = random.randrange(len(items))
            if not 0 <= index < len(items):
                yield event.plain_result(f"语音编号范围为 1-{len(items)}。")
                return
            item = items[index]
            output_dir = self.data_dir or Path(StarTools.get_data_dir(self.name))
            output = output_dir / "voice" / f"earth-k-{uuid4().hex}.wav"
            await self.service.download_voice(str(item["audio_url"]), output)
            yield event.chain_result([
                Comp.Plain(text=f"{entry['title']}：{item['name']}\n{item['content']}"),
                Comp.Record.fromFileSystem(str(output)),
            ])
        except Exception as error:
            logger.exception("Earth-K 角色语音播放失败")
            yield event.plain_result(f"角色语音获取失败：{error}")

    @filter.command("猜语音")
    async def voice_quiz_start(self, event: AstrMessageEvent):
        event.stop_event()
        session = str(getattr(event, "unified_msg_origin", "") or event.get_sender_id())
        if session in self._voice_games:
            yield event.plain_result("当前已经有一轮猜语音，请发送 /猜语音答案 <角色> 或 /公布语音答案。")
            return
        try:
            entry, item = await self.service.genshin_random_voice()
            output_dir = self.data_dir or Path(StarTools.get_data_dir(self.name))
            output = output_dir / "voice" / f"earth-k-quiz-{uuid4().hex}.wav"
            await self.service.download_voice(str(item["audio_url"]), output)
            state = self._voice_scores.setdefault(session, {"round": 0, "scores": {}})
            state["round"] = int(state.get("round", 0)) + 1
            self._voice_games[session] = {
                "answer": str(entry["title"]),
                "round": int(state["round"]),
            }
            yield event.chain_result([
                Comp.Plain(text=f"猜语音第 {state['round']}/10 回合，请猜是哪位角色。\n发送 /猜语音答案 <角色> 作答。"),
                Comp.Record.fromFileSystem(str(output)),
            ])
        except Exception as error:
            logger.exception("Earth-K 猜语音开始失败")
            yield event.plain_result(f"猜语音开始失败：{error}")

    @filter.command("猜语音答案")
    async def voice_quiz_answer(self, event: AstrMessageEvent, answer: str = ""):
        event.stop_event()
        session = str(getattr(event, "unified_msg_origin", "") or event.get_sender_id())
        game = self._voice_games.get(session)
        if not game:
            yield event.plain_result("当前没有进行中的猜语音，请先发送 /猜语音。")
            return
        answer = answer.strip()
        if not answer:
            yield event.plain_result("用法：/猜语音答案 <角色>")
            return
        if self.service._history_normalize(answer) != self.service._history_normalize(str(game["answer"])):
            yield event.plain_result("回答不正确，可以继续猜，或发送 /公布语音答案。")
            return
        state = self._voice_scores.setdefault(session, {"round": int(game["round"]), "scores": {}})
        scores = state.setdefault("scores", {})
        sender = str(event.get_sender_id())
        scores[sender] = int(scores.get(sender, 0)) + 1
        round_number = int(game["round"])
        answer_name = str(game["answer"])
        self._voice_games.pop(session, None)
        if round_number >= 10:
            ranking = sorted(scores.items(), key=lambda item: item[1], reverse=True)
            result = "、".join(f"{user}：{score}分" for user, score in ranking) or "暂无得分"
            self._voice_scores.pop(session, None)
            yield event.plain_result(f"答对了！答案是{answer_name}。\n十回合结束，最终得分：{result}")
            return
        yield event.plain_result(
            f"答对了！答案是{answer_name}，你当前 {scores[sender]} 分。\n"
            f"发送 /猜语音 开始第 {round_number + 1}/10 回合。"
        )

    @filter.command("公布语音答案")
    async def voice_quiz_reveal(self, event: AstrMessageEvent):
        event.stop_event()
        session = str(getattr(event, "unified_msg_origin", "") or event.get_sender_id())
        game = self._voice_games.pop(session, None)
        if not game:
            yield event.plain_result("当前没有进行中的猜语音。")
            return
        yield event.plain_result(f"答案是：{game['answer']}。当前回合结束，请发送 /猜语音 继续。")

    @filter.command("重置语音分数")
    async def voice_quiz_reset(self, event: AstrMessageEvent):
        event.stop_event()
        if not event.is_admin():
            yield event.plain_result("该命令仅限管理员使用")
            return
        session = str(getattr(event, "unified_msg_origin", "") or event.get_sender_id())
        self._voice_games.pop(session, None)
        self._voice_scores.pop(session, None)
        yield event.plain_result("当前会话的猜语音分数已重置")

    @filter.command("原史目录")
    async def genshin_history_directory(self, event: AstrMessageEvent, category: str = ""):
        event.stop_event()
        if not self.renderer:
            yield event.plain_result("本地 HTML 渲染器未启动")
            return
        category = category.strip()
        if not category:
            yield event.plain_result("用法：/原史目录 <分类>，例如 /原史目录 角色")
            return
        try:
            catalog = await self.service.genshin_history_catalog()
            categories = sorted({str(item["category"]) for item in catalog})
            selected = [item for item in catalog if str(item["category"]) == category]
            if not selected:
                suggestions = "、".join(name for name in categories if category in name) or "、".join(categories[:12])
                yield event.plain_result(f"没有找到分类“{category}”。可用分类：{suggestions}")
                return
            html = self.service.genshin_history_directory_html(category, selected)
            yield event.image_result(await self.renderer.render(html, viewport_width=1200))
        except Exception as error:
            logger.exception("Earth-K 原史目录查询失败")
            yield event.plain_result(f"原史目录获取失败：{error}")

    @filter.command("原史")
    async def genshin_history(self, event: AstrMessageEvent, query: str = ""):
        event.stop_event()
        if not self.renderer:
            yield event.plain_result("本地 HTML 渲染器未启动")
            return
        query = query.strip()
        if not query:
            yield event.plain_result("用法：/原史 <名称>；发送 /原史目录 <分类> 查看分类目录")
            return
        try:
            entry, matches = await self.service.genshin_history_find(query)
            if entry is None:
                if matches:
                    names = "、".join(str(item["title"]) for item in matches[:12])
                    yield event.plain_result(f"找到多个条目，请输入更完整的名称：{names}")
                else:
                    yield event.plain_result("没有找到对应条目，请先使用 /原史目录 角色 查看目录。")
                return
            detail = await self.service.genshin_history_detail(entry)
            html = self.service.genshin_history_article_html(detail)
            yield event.image_result(await self.renderer.render(html, viewport_width=1200))
        except Exception as error:
            logger.exception("Earth-K 原史查询失败")
            yield event.plain_result(f"原史查询失败：{error}")

    @filter.command("大话骰规则")
    async def dice_rules(self, event: AstrMessageEvent):
        event.stop_event()
        image = self.service.dice_rules_image()
        if not image:
            yield event.plain_result("大话骰规则图片缺失")
            return
        yield event.image_result(str(image))

    @filter.command("发起大话骰")
    async def dice_create(self, event: AstrMessageEvent):
        event.stop_event()
        if event.is_private_chat():
            yield event.plain_result("请在群聊中发起大话骰。")
            return
        session = str(event.unified_msg_origin)
        if session in self._dice_games:
            yield event.plain_result("当前会话已经有一局大话骰。")
            return
        user_id = str(event.get_sender_id())
        self._dice_games[session] = {
            "host": user_id,
            "players": {user_id: self._dice_name(event)},
            "dice": {},
            "started": False,
            "turn": 0,
            "bid": None,
        }
        yield event.plain_result("大话骰已发起，发送 /加入大话骰 加入，至少两人后由房主发送 /开始大话骰。")

    @filter.command("加入大话骰")
    async def dice_join(self, event: AstrMessageEvent):
        event.stop_event()
        if event.is_private_chat():
            yield event.plain_result("请在发起游戏的群聊中加入大话骰。")
            return
        game = self._dice_games.get(str(event.unified_msg_origin))
        if not game:
            yield event.plain_result("当前会话还没有发起大话骰。")
            return
        if game["started"]:
            yield event.plain_result("游戏已经开始，不能中途加入。")
            return
        players = game["players"]
        user_id = str(event.get_sender_id())
        if user_id in players:
            yield event.plain_result("你已经加入这局游戏了。")
            return
        if len(players) >= 8:
            yield event.plain_result("当前游戏最多支持 8 名玩家。")
            return
        players[user_id] = self._dice_name(event)
        yield event.plain_result(f"{players[user_id]} 加入成功，当前 {len(players)} 人。")

    @filter.command("开始大话骰")
    async def dice_start(self, event: AstrMessageEvent):
        event.stop_event()
        session = str(event.unified_msg_origin)
        game = self._dice_games.get(session)
        if not game:
            yield event.plain_result("当前会话还没有发起大话骰。")
            return
        user_id = str(event.get_sender_id())
        if user_id != game["host"]:
            yield event.plain_result("只有房主可以开始游戏。")
            return
        players = game["players"]
        if len(players) < 2:
            yield event.plain_result("至少需要 2 名玩家。")
            return
        if game["started"]:
            yield event.plain_result("游戏已经开始了。")
            return
        game["started"] = True
        game["dice"] = {player: [random.randint(1, 6) for _ in range(5)] for player in players}
        game["turn"] = 0
        game["bid"] = None
        first = list(players.values())[0]
        yield event.plain_result(
            "大话骰开始！每位玩家私聊机器人发送 /我的骰子 查看自己的骰子。\n"
            f"当前轮到：{first}\n请发送 /叫骰 <数量> <点数>，例如 /叫骰 3 5。"
        )

    @filter.command("我的骰子")
    async def dice_private(self, event: AstrMessageEvent):
        event.stop_event()
        if not event.is_private_chat():
            yield event.plain_result("为了避免泄露骰子，请私聊机器人发送 /我的骰子。")
            return
        user_id = str(event.get_sender_id())
        matches = [game for game in self._dice_games.values() if game["started"] and user_id in game["players"]]
        if not matches:
            yield event.plain_result("你没有进行中的大话骰。")
            return
        if len(matches) > 1:
            yield event.plain_result("你同时参加了多局游戏，请先结束其他游戏后再查看骰子。")
            return
        dice = matches[0]["dice"].get(user_id, [])
        yield event.plain_result("你的骰子（仅私聊可见）：" + " ".join(map(str, dice)))

    @filter.command("叫骰")
    async def dice_bid(self, event: AstrMessageEvent, bid_text: str = ""):
        event.stop_event()
        game = self._dice_games.get(str(event.unified_msg_origin))
        if not game or not game["started"]:
            yield event.plain_result("当前会话没有进行中的大话骰。")
            return
        user_id = str(event.get_sender_id())
        players = list(game["players"])
        if user_id not in game["players"]:
            yield event.plain_result("你还没有加入这局游戏。")
            return
        if players[game["turn"]] != user_id:
            yield event.plain_result(f"还没轮到你，目前轮到：{game['players'][players[game['turn']]]}")
            return
        parts = bid_text.split()
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            yield event.plain_result("用法：/叫骰 <数量> <点数>，例如 /叫骰 3 5。")
            return
        count, face = map(int, parts)
        total_dice = sum(len(values) for values in game["dice"].values())
        if not 1 <= face <= 6 or not 1 <= count <= total_dice:
            yield event.plain_result(f"数量范围为 1-{total_dice}，点数范围为 1-6。")
            return
        previous = game["bid"]
        if previous and not (count > previous[0] or (count == previous[0] and face > previous[1])):
            yield event.plain_result(f"叫骰必须大于上一口 {previous[0]} 个 {previous[1]}。")
            return
        game["bid"] = (count, face)
        game["turn"] = (game["turn"] + 1) % len(players)
        next_player = players[game["turn"]]
        yield event.plain_result(
            f"{game['players'][user_id]} 叫了 {count} 个 {face}，下一位：{game['players'][next_player]}。\n"
            "下一位继续 /叫骰，或发送 /开蛊。"
        )

    @filter.command("开蛊")
    async def dice_open(self, event: AstrMessageEvent):
        event.stop_event()
        session = str(event.unified_msg_origin)
        game = self._dice_games.get(session)
        if not game or not game["started"]:
            yield event.plain_result("当前会话没有进行中的大话骰。")
            return
        user_id = str(event.get_sender_id())
        players = list(game["players"])
        if user_id not in game["players"]:
            yield event.plain_result("你还没有加入这局游戏。")
            return
        if players[game["turn"]] != user_id:
            yield event.plain_result(f"还没轮到你，目前轮到：{game['players'][players[game['turn']]]}")
            return
        bid = game["bid"]
        if not bid:
            yield event.plain_result("还没有人叫骰。")
            return
        count, face = bid
        actual = sum(values.count(face) for values in game["dice"].values())
        bidder = players[(game["turn"] - 1) % len(players)]
        loser = user_id if actual >= count else bidder
        reveal = "；".join(f"{game['players'][player]}：{' '.join(map(str, game['dice'][player]))}" for player in players)
        game["dice"][loser].pop()
        remaining = len(game["dice"][loser])
        if remaining == 0:
            winner = next(player for player in players if player != loser and game["dice"][player])
            self._dice_games.pop(session, None)
            yield event.plain_result(
                f"开蛊结果：{actual} 个 {face}。\n{reveal}\n"
                f"{game['players'][loser]} 的骰子已清空，{game['players'][winner]} 获胜！"
            )
            return
        game["turn"] = players.index(loser) % len(players)
        game["bid"] = None
        yield event.plain_result(
            f"开蛊结果：{actual} 个 {face}。\n{reveal}\n"
            f"{game['players'][loser]} 失去 1 颗骰子，剩余 {remaining} 颗。新一轮从 {game['players'][loser]} 开始。"
        )

    @filter.command("结束大话骰")
    async def dice_end(self, event: AstrMessageEvent):
        event.stop_event()
        session = str(event.unified_msg_origin)
        game = self._dice_games.get(session)
        if not game:
            yield event.plain_result("当前会话没有进行中的大话骰。")
            return
        if str(event.get_sender_id()) != game["host"]:
            yield event.plain_result("只有房主可以结束游戏。")
            return
        self._dice_games.pop(session, None)
        yield event.plain_result("大话骰已结束。")

    @staticmethod
    def _dice_name(event: AstrMessageEvent) -> str:
        return event.get_sender_name() or str(event.get_sender_id()) or "未知玩家"

    @filter.command("弹琴帮助")
    async def piano_help(self, event: AstrMessageEvent):
        event.stop_event()
        yield event.plain_result(self.service.piano_help_text())

    @filter.command("钢琴")
    @filter.command("八音盒")
    @filter.command("古筝")
    @filter.command("吉他")
    @filter.command("萨克斯")
    @filter.command("小提琴")
    @filter.command("吹箫")
    @filter.command("西域琴")
    async def piano_play(self, event: AstrMessageEvent, notation: str = ""):
        event.stop_event()
        raw = event.get_message_str().lstrip()
        instrument = next(
            (name for name in ("钢琴", "八音盒", "古筝", "吉他", "萨克斯", "小提琴", "吹箫", "西域琴")
             if raw.startswith(f"/{name}")),
            "钢琴",
        )
        output_dir = self.data_dir or Path(StarTools.get_data_dir(self.name))
        output = output_dir / "audio" / f"earth-k-{uuid4().hex}.mp3"
        result, error = await self.service.play_piano(instrument, notation, output)
        if error:
            yield event.plain_result(error)
            return
        yield event.chain_result([
            Comp.Plain(text=f"{instrument}演奏完成"),
            Comp.Record.fromFileSystem(str(result)),
        ])

    @filter.command("土块表情列表")
    async def meme_list(self, event: AstrMessageEvent):
        event.stop_event()
        try:
            image = await self.service.meme_list()
            yield event.chain_result([Comp.Image.fromBytes(image)])
        except Exception as error:
            logger.exception("Earth-K 表情列表获取失败")
            yield event.plain_result(f"表情列表获取失败：{error}")

    @filter.command("表情合成")
    async def meme_render(self, event: AstrMessageEvent, payload: str = ""):
        event.stop_event()
        parts = payload.strip().split()
        if not parts:
            yield event.plain_result("用法：/表情合成 <关键词> [文字]，图片请和命令一起发送。")
            return

        keyword, texts = parts[0], parts[1:]
        images = []
        for message in event.get_messages():
            if isinstance(message, Comp.Image):
                image = await self.service.message_image_bytes(message)
                if image:
                    images.append(image)
        result, error = await self.service.render_meme(
            keyword,
            texts,
            images,
            event.get_sender_name(),
        )
        if error:
            yield event.plain_result(error)
            return
        if result is None:
            yield event.plain_result("表情生成失败：服务没有返回图片。")
            return
        yield event.chain_result([Comp.Image.fromBytes(result)])

    @filter.command("土块状态")
    async def state(self, event: AstrMessageEvent):
        event.stop_event()
        if not self.renderer:
            yield event.plain_result("本地 HTML 渲染器未启动")
            return
        try:
            html = await asyncio.to_thread(self.service.state_html)
            yield event.image_result(await self.renderer.render(html, viewport_width=1200))
        except Exception as error:
            logger.exception("Earth-K 状态页渲染失败")
            yield event.plain_result(f"状态页渲染失败：{error}")

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
