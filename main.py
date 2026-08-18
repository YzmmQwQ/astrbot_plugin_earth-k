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
from astrbot.core.star.filter.command import GreedyStr

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
        self._guess_games: dict[str, dict[str, object]] = {}
        self._guess_scores: dict[str, dict[str, int]] = {}
        self._guess_names: dict[str, dict[str, str]] = {}
        self._hit_games: dict[str, dict[str, str]] = {}
        self._hit_timeout_tasks: dict[str, asyncio.Task[None]] = {}
        self._you_say_games: dict[str, dict[str, object]] = {}
        self._draw_games: dict[str, dict[str, object]] = {}
        self._story_games: dict[str, dict[str, object]] = {}
        self._station_games: dict[str, dict[str, object]] = {}
        self._station_timeout_tasks: dict[str, asyncio.Task[None]] = {}
        self._marry_games: dict[str, list[dict[str, str]]] = {}
        self._game_sessions: dict[str, dict[str, object]] = {}
        self._history_choices: dict[str, list[dict[str, object]]] = {}

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
        for task in self._hit_timeout_tasks.values():
            task.cancel()
        self._hit_timeout_tasks.clear()
        self._hit_games.clear()
        self._you_say_games.clear()
        self._draw_games.clear()
        self._story_games.clear()
        for task in self._station_timeout_tasks.values():
            task.cancel()
        self._station_timeout_tasks.clear()
        self._station_games.clear()
        self._marry_games.clear()
        self._game_sessions.clear()
        self._history_choices.clear()
        if self.renderer:
            await self.renderer.stop()

    @filter.platform_adapter_type(filter.PlatformAdapterType.ALL)
    async def draw_image_message(self, event: AstrMessageEvent):
        """Accept a picture from the current drawer in an active game."""
        if not event.get_group_id():
            return
        session = str(event.unified_msg_origin)
        game = self._draw_games.get(session)
        if not game or not game.get("started"):
            return
        if not any(isinstance(message, Comp.Image) for message in event.get_messages()):
            return

        players = game["players"]
        current = players[int(game["turn"])]
        user_id = str(event.get_sender_id())
        if user_id != str(current["id"]):
            return

        game["image_received"] = True
        event.stop_event()
        yield event.chain_result([
            Comp.At(qq=user_id),
            Comp.Plain(text="已收到你的画作，其他玩家可以发送 /猜测 <答案>。"),
        ])

    @filter.command("土块更新")
    async def update_command(self, event: AstrMessageEvent):
        """Use AstrBot's official updater and reload the plugin."""
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

    @filter.command("测试智商")
    async def iq_test(self, event: AstrMessageEvent):
        event.stop_event()
        try:
            question = self.service.random_iq_question()
            yield event.plain_result(f"想测试自己是不是笨比吗？\n\n{question}")
        except Exception as error:
            logger.exception("Earth-K 智商题获取失败")
            yield event.plain_result(f"智商题获取失败：{error}")

    @filter.command("打我")
    async def hit_me(self, event: AstrMessageEvent):
        event.stop_event()
        if not event.get_group_id():
            yield event.plain_result("只能在群里被打")
            return
        session = str(event.unified_msg_origin)
        if session in self._hit_games:
            yield event.plain_result("我正在打别人，没空，你待会再挨打。")
            return
        await self._start_hit_game(session, str(event.get_sender_id()), event.get_sender_name())
        yield event.chain_result([
            Comp.At(qq=event.get_sender_id()),
            Comp.Plain(text="给你 20 秒，跟我来猜拳。赢了我就不打你，输了就寄！请发送 /石头、/剪刀 或 /布。"),
        ])

    @filter.command("打他")
    async def hit_other(self, event: AstrMessageEvent, target_id: str = ""):
        event.stop_event()
        if not event.get_group_id():
            yield event.plain_result("只能在群里发起群内猜拳")
            return
        if not event.is_admin():
            yield event.plain_result("该命令仅限管理员使用")
            return
        target_id = target_id.strip()
        if not target_id:
            yield event.plain_result("用法：/打他 <用户ID>，然后由对方发送 /石头、/剪刀 或 /布。")
            return
        session = str(event.unified_msg_origin)
        if session in self._hit_games:
            yield event.plain_result("当前群已经有一局猜拳，请先等本局结束。")
            return
        await self._start_hit_game(session, target_id, target_id)
        yield event.plain_result(
            f"已向用户 {target_id} 发起猜拳，对方有 20 秒发送 /石头、/剪刀 或 /布。"
        )

    @filter.command("石头")
    async def hit_rock(self, event: AstrMessageEvent):
        event.stop_event()
        yield event.plain_result(await self._play_hit_choice(event, "石头"))

    @filter.command("剪刀")
    async def hit_scissors(self, event: AstrMessageEvent):
        event.stop_event()
        yield event.plain_result(await self._play_hit_choice(event, "剪刀"))

    @filter.command("布")
    async def hit_paper(self, event: AstrMessageEvent):
        event.stop_event()
        yield event.plain_result(await self._play_hit_choice(event, "布"))

    async def _start_hit_game(self, session: str, target_id: str, target_name: str) -> None:
        self._hit_games[session] = {"target_id": target_id, "target_name": target_name or target_id}
        previous = self._hit_timeout_tasks.pop(session, None)
        if previous:
            previous.cancel()
        self._hit_timeout_tasks[session] = asyncio.create_task(self._hit_timeout(session, target_id))

    async def _hit_timeout(self, session: str, target_id: str) -> None:
        try:
            await asyncio.sleep(20)
            game = self._hit_games.get(session)
            if not game or game.get("target_id") != target_id:
                return
            self._hit_games.pop(session, None)
            await self.context.send_message(
                session,
                MessageChain([Comp.Plain(text=f"用户 {target_id} 20 秒没有出拳，本局猜拳结束。")]),
            )
        except asyncio.CancelledError:
            return
        except Exception as error:
            logger.error(f"Earth-K 打我超时消息发送失败: {error}")
        finally:
            self._hit_timeout_tasks.pop(session, None)

    async def _play_hit_choice(self, event: AstrMessageEvent, player_choice: str) -> str:
        if not event.get_group_id():
            return "只能在群里被打"
        session = str(event.unified_msg_origin)
        game = self._hit_games.get(session)
        if not game:
            return "当前没有进行中的猜拳，请先发送 /打我。"
        if str(game["target_id"]) != str(event.get_sender_id()):
            return "这局猜拳不是你的。"
        bot_choice = random.choice(("石头", "剪刀", "布"))
        self._hit_games.pop(session, None)
        timeout = self._hit_timeout_tasks.pop(session, None)
        if timeout:
            timeout.cancel()
        if player_choice == bot_choice:
            result = "平局，饶你一回。"
        elif (player_choice, bot_choice) in {("石头", "剪刀"), ("剪刀", "布"), ("布", "石头")}:
            result = "你赢了，这次不打你。"
        else:
            result = "你输了，但 AstrBot 不执行自动禁言。"
        return f"我出{bot_choice}，你出{player_choice}。{result}"

    @filter.command("挑选幸运儿")
    async def choose_lucky(self, event: AstrMessageEvent):
        event.stop_event()
        if not event.get_group_id():
            yield event.plain_result("只能在群里挑选幸运儿")
            return
        try:
            group = await event.get_group()
            members = list(getattr(group, "members", None) or []) if group else []
            members = [member for member in members if str(getattr(member, "user_id", "")) != str(event.get_self_id())]
            if not members:
                yield event.plain_result("暂时获取不到当前群成员列表")
                return
            lucky = random.choice(members)
            user_id = str(getattr(lucky, "user_id", ""))
            name = str(getattr(lucky, "nickname", "") or user_id)
            yield event.chain_result([
                Comp.At(qq=user_id),
                Comp.Plain(text=f"今天的幸运儿是 {name}（{user_id}）！"),
            ])
        except Exception as error:
            logger.exception("Earth-K 幸运儿选择失败")
            yield event.plain_result(f"选择幸运儿失败：{error}")

    @filter.command("发起你说我猜")
    async def you_say_start(self, event: AstrMessageEvent):
        event.stop_event()
        if not event.get_group_id():
            yield event.plain_result("你说我猜只能在群里发起")
            return
        session = str(event.unified_msg_origin)
        if session in self._you_say_games:
            yield event.plain_result("当前群已经发起过你说我猜了。")
            return
        self._you_say_games[session] = {
            "host": str(event.get_sender_id()),
            "players": [],
            "started": False,
        }
        yield event.plain_result("你说我猜已发起，发送 /加入你说我猜 报名。")

    @filter.command("加入你说我猜")
    async def you_say_join(self, event: AstrMessageEvent):
        event.stop_event()
        if not event.get_group_id():
            yield event.plain_result("你说我猜只能在群里加入")
            return
        session = str(event.unified_msg_origin)
        game = self._you_say_games.get(session)
        if not game:
            yield event.plain_result("游戏还没发起，请先发送 /发起你说我猜。")
            return
        if game.get("started"):
            yield event.plain_result("游戏已经开始了，不能再加入。")
            return
        players = game["players"]
        user_id = str(event.get_sender_id())
        if any(player["id"] == user_id for player in players):
            yield event.plain_result("你已经加入游戏了！")
            return
        players.append({"id": user_id, "name": event.get_sender_name() or user_id})
        yield event.chain_result([
            Comp.At(qq=user_id),
            Comp.Plain(text=f"加入游戏成功，当前人数 {len(players)} 人。"),
        ])

    @filter.command("开始你说我猜")
    async def you_say_begin(self, event: AstrMessageEvent):
        event.stop_event()
        session = str(event.unified_msg_origin)
        game = self._you_say_games.get(session)
        if not game:
            yield event.plain_result("游戏还没发起，请先发送 /发起你说我猜。")
            return
        if str(game.get("host")) != str(event.get_sender_id()):
            yield event.plain_result("只有发起者可以开始游戏。")
            return
        if game.get("started"):
            yield event.plain_result("游戏已经开始了。")
            return
        players = game["players"]
        if len(players) < 2:
            yield event.plain_result("至少需要两名玩家加入游戏。")
            return
        game.update({
            "started": True,
            "turn": 0,
            "turn_count": 0,
            "total_turns": len(players) * 2,
            "used": set(),
            "scores": {player["id"]: 0 for player in players},
            "score_names": {player["id"]: player["name"] for player in players},
            "answer": self.service.random_you_say_word(set()),
        })
        current = players[0]
        sent = await self._send_you_say_word(event, str(current["id"]), str(game["answer"]))
        private_note = "题词已私聊给当前描述者。" if sent else "无法私聊当前描述者，请检查平台私聊权限。"
        yield event.chain_result([
            Comp.At(qq=str(current["id"])),
            Comp.Plain(text=f"你说我猜已开始，请查看题词后描述。{private_note}"),
        ])

    @filter.command("猜测")
    async def you_say_guess(self, event: AstrMessageEvent, guess: str = ""):
        event.stop_event()
        if not event.get_group_id():
            yield event.plain_result("你说我猜或你画我猜只能在群里进行")
            return
        session = str(event.unified_msg_origin)
        if session in self._draw_games:
            async for result in self._draw_guess(event, guess):
                yield result
            return
        game = self._you_say_games.get(session)
        if not game or not game.get("started"):
            yield event.plain_result("当前没有进行中的你说我猜。")
            return
        guess = guess.strip()
        if not guess:
            yield event.plain_result("用法：/猜测 <答案>")
            return
        players = game["players"]
        current = players[int(game["turn"])]
        user_id = str(event.get_sender_id())
        if user_id == str(current["id"]):
            yield event.plain_result("当前是你的描述回合，请不要猜自己的题。")
            return
        if guess.casefold() != str(game["answer"]).casefold():
            yield event.plain_result("还没猜中，继续听描述。")
            return

        scores = game["scores"]
        score_names = game["score_names"]
        score_names[user_id] = event.get_sender_name() or user_id
        scores[user_id] = int(scores.get(user_id, 0)) + 1
        game["turn_count"] = int(game["turn_count"]) + 1
        ranking = sorted(
            ((str(name), int(scores.get(str(user_id), 0))) for user_id, name in score_names.items()),
            key=lambda item: item[1],
            reverse=True,
        )
        answer = str(game["answer"])
        if int(game["turn_count"]) >= int(game["total_turns"]):
            self._you_say_games.pop(session, None)
            if self.renderer:
                try:
                    image = await self.renderer.render(
                        self.service.group_game_score_html(
                            "你说我猜", ranking, int(game["turn_count"]), int(game["total_turns"])
                        ),
                        viewport_width=860,
                    )
                    yield event.image_result(image)
                except Exception as error:
                    logger.exception("Earth-K 你说我猜最终计分图渲染失败")
                    yield event.plain_result(f"最终计分图渲染失败：{error}")
            yield event.plain_result(f"恭喜答对！答案是：{answer}。你说我猜结束，最终得分：" + "、".join(f"{name}：{score}分" for name, score in ranking))
            return

        game["turn"] = (int(game["turn"]) + 1) % len(players)
        current = players[int(game["turn"])]
        used = game["used"]
        used.add(answer)
        game["answer"] = self.service.random_you_say_word(used)
        sent = await self._send_you_say_word(event, str(current["id"]), str(game["answer"]))
        if self.renderer:
            try:
                image = await self.renderer.render(
                    self.service.group_game_score_html(
                        "你说我猜", ranking, int(game["turn_count"]), int(game["total_turns"])
                    ),
                    viewport_width=860,
                )
                yield event.image_result(image)
            except Exception as error:
                logger.exception("Earth-K 你说我猜计分图渲染失败")
                yield event.plain_result(f"计分图渲染失败：{error}")
        note = "题词已私聊给下一位描述者。" if sent else "无法私聊下一位描述者，请检查平台私聊权限。"
        yield event.chain_result([
            Comp.At(qq=str(event.get_sender_id())),
            Comp.Plain(text=f"回答正确，答案是：{answer}。下一位描述者是 "),
            Comp.At(qq=str(current["id"])),
            Comp.Plain(text=f"。{note}"),
        ])

    async def _draw_guess(self, event: AstrMessageEvent, guess: str):
        game = self._draw_games.get(str(event.unified_msg_origin))
        if not game or not game.get("started"):
            yield event.plain_result("当前没有进行中的你画我猜。")
            return
        guess = guess.strip()
        if not guess:
            yield event.plain_result("用法：/猜测 <答案>")
            return
        players = game["players"]
        user_id = str(event.get_sender_id())
        player_ids = {str(player["id"]) for player in players}
        if user_id not in player_ids:
            yield event.plain_result("只有加入游戏的玩家可以猜测。")
            return
        current = players[int(game["turn"])]
        if user_id == str(current["id"]):
            yield event.plain_result("当前是你的作画回合，请等待其他玩家猜测。")
            return
        if not game.get("image_received"):
            yield event.plain_result("当前画手还没有发送画作，请稍等。")
            return
        if guess.casefold().strip() != str(game["answer"]).casefold().strip():
            yield event.plain_result("还没猜中，继续看画。")
            return

        scores = game["scores"]
        score_names = game["score_names"]
        scores[user_id] = int(scores.get(user_id, 0)) + 1
        score_names[user_id] = event.get_sender_name() or score_names.get(user_id, user_id)
        game["turn_count"] = int(game["turn_count"]) + 1
        ranking = sorted(
            ((str(name), int(scores.get(str(player_id), 0))) for player_id, name in score_names.items()),
            key=lambda item: item[1],
            reverse=True,
        )
        answer = str(game["answer"])
        if int(game["turn_count"]) >= int(game["total_turns"]):
            self._draw_games.pop(str(event.unified_msg_origin), None)
            if self.renderer:
                try:
                    image = await self.renderer.render(
                        self.service.group_game_score_html(
                            "你画我猜", ranking, int(game["turn_count"]), int(game["total_turns"])
                        ),
                        viewport_width=860,
                    )
                    yield event.image_result(image)
                except Exception as error:
                    logger.exception("Earth-K 你画我猜最终计分图渲染失败")
                    yield event.plain_result(f"最终计分图渲染失败：{error}")
            yield event.plain_result(
                f"恭喜答对！答案是：{answer}。你画我猜结束，最终得分："
                + "、".join(f"{name}：{score}分" for name, score in ranking)
            )
            return

        game["turn"] = (int(game["turn"]) + 1) % len(players)
        current = players[int(game["turn"])]
        game["used"].add(answer)
        game["answer"] = self.service.random_draw_word(game["used"])
        game["image_received"] = False
        sent = await self._send_draw_word(event, str(current["id"]), str(game["answer"]))
        if self.renderer:
            try:
                image = await self.renderer.render(
                    self.service.group_game_score_html(
                        "你画我猜", ranking, int(game["turn_count"]), int(game["total_turns"])
                    ),
                    viewport_width=860,
                )
                yield event.image_result(image)
            except Exception as error:
                logger.exception("Earth-K 你画我猜计分图渲染失败")
                yield event.plain_result(f"计分图渲染失败：{error}")
        note = "题目已私聊给下一位画手。" if sent else "无法私聊下一位画手，请检查平台私聊权限。"
        yield event.chain_result([
            Comp.At(qq=user_id),
            Comp.Plain(text=f"回答正确，答案是：{answer}。下一位画手是 "),
            Comp.At(qq=str(current["id"])),
            Comp.Plain(text=f"。请在群里发送画作。{note}"),
        ])

    @filter.command("结束你画我猜")
    async def draw_end(self, event: AstrMessageEvent):
        event.stop_event()
        session = str(event.unified_msg_origin)
        game = self._draw_games.get(session)
        if not game:
            yield event.plain_result("当前没有进行中的你画我猜。")
            return
        if str(game.get("host")) != str(event.get_sender_id()):
            yield event.plain_result("只有发起者可以结束游戏。")
            return
        self._draw_games.pop(session, None)
        yield event.plain_result("你画我猜已结束。")

    async def _send_draw_word(self, event: AstrMessageEvent, user_id: str, word: str) -> bool:
        private_umo = f"{event.get_platform_id()}:FriendMessage:{user_id}"
        try:
            await self.context.send_message(
                private_umo,
                MessageChain([Comp.Plain(text=f"你画我猜的题目是：{word}。请在群里画好后发送图片。")]),
            )
            return True
        except Exception as error:
            logger.error(f"Earth-K 你画我猜私聊题目失败: {error}")
            return False

    @filter.command("写答案")
    async def you_say_set_answer(self, event: AstrMessageEvent, answer: str = ""):
        event.stop_event()
        session = str(event.unified_msg_origin)
        game = self._you_say_games.get(session)
        if not game or not game.get("started"):
            yield event.plain_result("当前没有进行中的你说我猜。")
            return
        players = game["players"]
        current = players[int(game["turn"])]
        if str(current["id"]) != str(event.get_sender_id()):
            yield event.plain_result("只有当前描述者可以修改答案。")
            return
        answer = answer.strip()
        if not answer:
            yield event.plain_result("用法：/写答案 <答案>")
            return
        game["answer"] = answer
        yield event.plain_result(f"本轮答案已设置为：{answer}")

    @filter.command("结束你说我猜")
    async def you_say_end(self, event: AstrMessageEvent):
        event.stop_event()
        session = str(event.unified_msg_origin)
        game = self._you_say_games.get(session)
        if not game:
            yield event.plain_result("当前没有进行中的你说我猜。")
            return
        if str(game.get("host")) != str(event.get_sender_id()):
            yield event.plain_result("只有发起者可以结束游戏。")
            return
        self._you_say_games.pop(session, None)
        yield event.plain_result("你说我猜已结束。")

    @filter.command("发起你画我猜")
    async def draw_start(self, event: AstrMessageEvent):
        event.stop_event()
        if not event.get_group_id():
            yield event.plain_result("你画我猜只能在群里发起")
            return
        session = str(event.unified_msg_origin)
        if session in self._draw_games:
            yield event.plain_result("当前群已经发起过你画我猜了。")
            return
        if session in self._you_say_games:
            yield event.plain_result("当前群正在进行你说我猜，请先结束那局游戏。")
            return
        self._draw_games[session] = {
            "host": str(event.get_sender_id()),
            "players": [],
            "started": False,
        }
        yield event.plain_result("你画我猜已发起，发送 /加入你画我猜 报名。")

    @filter.command("加入你画我猜")
    async def draw_join(self, event: AstrMessageEvent):
        event.stop_event()
        if not event.get_group_id():
            yield event.plain_result("你画我猜只能在群里加入")
            return
        session = str(event.unified_msg_origin)
        game = self._draw_games.get(session)
        if not game:
            yield event.plain_result("游戏还没发起，请先发送 /发起你画我猜。")
            return
        if game.get("started"):
            yield event.plain_result("游戏已经开始了，不能再加入。")
            return
        players = game["players"]
        user_id = str(event.get_sender_id())
        if any(str(player["id"]) == user_id for player in players):
            yield event.plain_result("你已经加入游戏了！")
            return
        players.append({"id": user_id, "name": event.get_sender_name() or user_id})
        yield event.chain_result([
            Comp.At(qq=user_id),
            Comp.Plain(text=f"加入游戏成功，当前人数 {len(players)} 人。"),
        ])

    @filter.command("开始你画我猜")
    async def draw_begin(self, event: AstrMessageEvent):
        event.stop_event()
        if not event.get_group_id():
            yield event.plain_result("你画我猜只能在群里开始")
            return
        session = str(event.unified_msg_origin)
        game = self._draw_games.get(session)
        if not game:
            yield event.plain_result("游戏还没发起，请先发送 /发起你画我猜。")
            return
        if str(game.get("host")) != str(event.get_sender_id()):
            yield event.plain_result("只有发起者可以开始游戏。")
            return
        if game.get("started"):
            yield event.plain_result("游戏已经开始了。")
            return
        players = game["players"]
        if len(players) < 2:
            yield event.plain_result("至少需要两名玩家加入游戏。")
            return
        game.update({
            "started": True,
            "turn": 0,
            "turn_count": 0,
            "total_turns": len(players) * 2,
            "used": set(),
            "scores": {str(player["id"]): 0 for player in players},
            "score_names": {str(player["id"]): player["name"] for player in players},
            "answer": self.service.random_draw_word(set()),
            "image_received": False,
        })
        current = players[0]
        sent = await self._send_draw_word(event, str(current["id"]), str(game["answer"]))
        private_note = "题目已私聊给第一位画手。" if sent else "无法私聊第一位画手，请检查平台私聊权限。"
        yield event.chain_result([
            Comp.At(qq=str(current["id"])),
            Comp.Plain(text=f"你画我猜已开始，请在群里发送画作。{private_note}"),
        ])

    async def _send_you_say_word(self, event: AstrMessageEvent, user_id: str, word: str) -> bool:
        private_umo = f"{event.get_platform_id()}:FriendMessage:{user_id}"
        try:
            await self.context.send_message(
                private_umo,
                MessageChain([Comp.Plain(text=f"你说我猜的题词是：{word}。请在群里描述它，不要直接说出答案。")]),
            )
            return True
        except Exception as error:
            logger.error(f"Earth-K 你说我猜私聊题词失败: {error}")
            return False

    @filter.command("发起故事接龙")
    async def story_start(self, event: AstrMessageEvent):
        event.stop_event()
        if not event.get_group_id():
            yield event.plain_result("故事接龙只能在群里发起")
            return
        session = str(event.unified_msg_origin)
        if session in self._story_games:
            yield event.plain_result("当前群已经发起过故事接龙了。")
            return
        user_id = str(event.get_sender_id())
        self._story_games[session] = {
            "host": user_id,
            "players": [{"id": user_id, "name": event.get_sender_name() or user_id}],
            "started": False,
        }
        yield event.plain_result("故事接龙已发起，发起者已加入，发送 /加入故事接龙 报名。")

    @filter.command("加入故事接龙")
    async def story_join(self, event: AstrMessageEvent):
        event.stop_event()
        if not event.get_group_id():
            yield event.plain_result("故事接龙只能在群里加入")
            return
        session = str(event.unified_msg_origin)
        game = self._story_games.get(session)
        if not game:
            yield event.plain_result("游戏还没发起，请先发送 /发起故事接龙。")
            return
        if game.get("started"):
            yield event.plain_result("故事接龙已经开始，不能再加入。")
            return
        user_id = str(event.get_sender_id())
        players = game["players"]
        if any(str(player["id"]) == user_id for player in players):
            yield event.plain_result("你已经加入故事接龙了！")
            return
        players.append({"id": user_id, "name": event.get_sender_name() or user_id})
        yield event.chain_result([
            Comp.At(qq=user_id),
            Comp.Plain(text=f"加入故事接龙成功，当前人数 {len(players)} 人。"),
        ])

    @filter.command("开始故事接龙")
    async def story_begin(self, event: AstrMessageEvent):
        event.stop_event()
        if not event.get_group_id():
            yield event.plain_result("故事接龙只能在群里进行")
            return
        session = str(event.unified_msg_origin)
        game = self._story_games.get(session)
        if not game:
            yield event.plain_result("游戏还没发起，请先发送 /发起故事接龙。")
            return
        if str(game["host"]) != str(event.get_sender_id()):
            yield event.plain_result("只有发起者可以开始故事接龙。")
            return
        if game.get("started"):
            yield event.plain_result("故事接龙已经开始了。")
            return
        players = game["players"]
        if len(players) < 2:
            yield event.plain_result("至少需要两名玩家加入故事接龙。")
            return
        try:
            keyword = self.service.random_story_keyword(set())
        except Exception as error:
            logger.exception("Earth-K 故事接龙关键词获取失败")
            yield event.plain_result(f"故事接龙开始失败：{error}")
            return
        game.update({
            "started": True,
            "turn": 0,
            "turn_count": 0,
            "total_turns": len(players) * 2,
            "used_keywords": {keyword},
            "keyword": keyword,
            "history": [],
        })
        current = players[0]
        yield event.chain_result([
            Comp.Plain(text=f"故事接龙已开始，共 {game['total_turns']} 回合。\n"),
            Comp.At(qq=str(current["id"])),
            Comp.Plain(text=f" 请围绕关键词“{keyword}”描述故事开头。\n发送 /讲述 <内容> 续写。"),
        ])

    @filter.command("讲述")
    async def story_tell(self, event: AstrMessageEvent, content: GreedyStr = ""):
        event.stop_event()
        if not event.get_group_id():
            yield event.plain_result("故事接龙只能在群里进行")
            return
        session = str(event.unified_msg_origin)
        game = self._story_games.get(session)
        if not game or not game.get("started"):
            yield event.plain_result("当前没有进行中的故事接龙，请先发起并开始游戏。")
            return
        players = game["players"]
        current = players[int(game["turn"])]
        if str(current["id"]) != str(event.get_sender_id()):
            yield event.plain_result(f"还没轮到你，目前轮到：{current['name']}")
            return
        text = str(content).strip()
        if not text:
            yield event.plain_result("用法：/讲述 <故事内容>")
            return

        history = game["history"]
        history.append({
            "name": current["name"],
            "keyword": game["keyword"],
            "content": text,
        })
        game["turn_count"] = int(game["turn_count"]) + 1
        turn_count = int(game["turn_count"])
        total_turns = int(game["total_turns"])
        try:
            if self.renderer:
                image = await self.renderer.render(
                    self.service.story_game_html(history, turn_count, total_turns, "故事接龙"),
                    viewport_width=1100,
                )
                yield event.image_result(image)
        except Exception as error:
            logger.exception("Earth-K 故事接龙过程图渲染失败")
            yield event.plain_result(f"故事已记录，但过程图渲染失败：{error}")

        if turn_count >= total_turns:
            self._story_games.pop(session, None)
            yield event.plain_result("故事接龙游戏结束，以上为最终故事。")
            return

        game["turn"] = (int(game["turn"]) + 1) % len(players)
        try:
            used_keywords = game["used_keywords"]
            keyword = self.service.random_story_keyword(used_keywords)
            used_keywords.add(keyword)
            game["keyword"] = keyword
        except Exception as error:
            self._story_games.pop(session, None)
            logger.exception("Earth-K 故事接龙下一关键词获取失败")
            yield event.plain_result(f"故事接龙已结束，下一关键词获取失败：{error}")
            return
        next_player = players[int(game["turn"])]
        yield event.chain_result([
            Comp.Plain(text="本回合描述完毕，下一位："),
            Comp.At(qq=str(next_player["id"])),
            Comp.Plain(text=f"\n当前关键词：“{keyword}”\n请发送 /讲述 <内容>。"),
        ])

    @filter.command("结束故事接龙")
    async def story_end(self, event: AstrMessageEvent):
        event.stop_event()
        session = str(event.unified_msg_origin)
        game = self._story_games.get(session)
        if not game:
            yield event.plain_result("当前没有进行中的故事接龙。")
            return
        if str(game["host"]) != str(event.get_sender_id()):
            yield event.plain_result("只有发起者可以结束故事接龙。")
            return
        self._story_games.pop(session, None)
        yield event.plain_result("故事接龙已结束。")

    @filter.command("发起一站到底")
    async def station_start(self, event: AstrMessageEvent):
        event.stop_event()
        if not event.get_group_id():
            yield event.plain_result("一站到底只能在群里发起")
            return
        session = str(event.unified_msg_origin)
        if session in self._station_games:
            yield event.plain_result("当前群已经发起过一站到底了。")
            return
        user_id = str(event.get_sender_id())
        self._station_games[session] = {
            "host": user_id,
            "players": [{"id": user_id, "name": event.get_sender_name() or user_id}],
            "started": False,
        }
        yield event.plain_result("一站到底已发起，发起者已加入，发送 /加入一站到底 报名。")

    @filter.command("加入一站到底")
    async def station_join(self, event: AstrMessageEvent):
        event.stop_event()
        if not event.get_group_id():
            yield event.plain_result("一站到底只能在群里加入")
            return
        session = str(event.unified_msg_origin)
        game = self._station_games.get(session)
        if not game:
            yield event.plain_result("游戏还没发起，请先发送 /发起一站到底。")
            return
        if game.get("started"):
            yield event.plain_result("一站到底已经开始，不能再加入。")
            return
        user_id = str(event.get_sender_id())
        players = game["players"]
        if any(str(player["id"]) == user_id for player in players):
            yield event.plain_result("你已经加入一站到底了！")
            return
        players.append({"id": user_id, "name": event.get_sender_name() or user_id})
        yield event.chain_result([
            Comp.At(qq=user_id),
            Comp.Plain(text=f"加入一站到底成功，当前人数 {len(players)} 人。"),
        ])

    @filter.command("开始一站到底")
    async def station_begin(self, event: AstrMessageEvent):
        event.stop_event()
        if not event.get_group_id():
            yield event.plain_result("一站到底只能在群里进行")
            return
        session = str(event.unified_msg_origin)
        game = self._station_games.get(session)
        if not game:
            yield event.plain_result("游戏还没发起，请先发送 /发起一站到底。")
            return
        if str(game["host"]) != str(event.get_sender_id()):
            yield event.plain_result("只有发起者可以开始一站到底。")
            return
        if game.get("started"):
            yield event.plain_result("一站到底已经开始了。")
            return
        players = game["players"]
        if len(players) < 2:
            yield event.plain_result("至少需要两名玩家加入一站到底。")
            return
        try:
            question = await self.service.station_question()
        except Exception as error:
            logger.exception("Earth-K 一站到底开始失败")
            self._station_games.pop(session, None)
            yield event.plain_result(f"一站到底开始失败：{error}")
            return
        game.update({
            "started": True,
            "turn": 0,
            "round": 1,
            "question": question["question"],
            "options": question["options"],
            "answer": question["answer"],
        })
        self._schedule_station_timeout(session)
        yield event.chain_result(self._station_question_chain(game, "一站到底已开始"))

    @filter.command("答")
    async def station_answer(self, event: AstrMessageEvent, answer: GreedyStr = ""):
        event.stop_event()
        if not event.get_group_id():
            yield event.plain_result("一站到底只能在群里进行")
            return
        session = str(event.unified_msg_origin)
        game = self._station_games.get(session)
        if not game or not game.get("started"):
            yield event.plain_result("当前没有进行中的一站到底。")
            return
        players = game["players"]
        current = players[int(game["turn"])]
        if str(current["id"]) != str(event.get_sender_id()):
            yield event.plain_result(f"还没轮到你，目前轮到：{current['name']}")
            return
        answer = str(answer).strip()
        if not answer:
            yield event.plain_result("用法：/答 <答案>")
            return
        self._cancel_station_timeout(session)
        expected = str(game["answer"]).strip()
        if answer.casefold() == expected.casefold():
            game["round"] = int(game["round"]) + 1
            game["turn"] = (int(game["turn"]) + 1) % len(players)
            try:
                question = await self.service.station_question()
            except Exception as error:
                self._station_games.pop(session, None)
                yield event.plain_result(f"回答正确，但下一题获取失败，本局结束：{error}")
                return
            game.update({
                "question": question["question"],
                "options": question["options"],
                "answer": question["answer"],
            })
            self._schedule_station_timeout(session)
            yield event.chain_result(self._station_question_chain(game, "回答正确"))
            return

        players.pop(int(game["turn"]))
        if len(players) <= 1:
            winner = players[0] if players else None
            self._station_games.pop(session, None)
            if winner:
                yield event.chain_result([
                    Comp.Plain(text=f"回答错误，答案是“{expected}”。一站到底结束，"),
                    Comp.At(qq=str(winner["id"])),
                    Comp.Plain(text=" 是本轮站神！"),
                ])
            else:
                yield event.plain_result(f"回答错误，答案是“{expected}”。一站到底结束。")
            return
        game["turn"] = int(game["turn"]) % len(players)
        try:
            question = await self.service.station_question()
        except Exception as error:
            self._station_games.pop(session, None)
            yield event.plain_result(f"答错后下一题获取失败，本局结束：{error}")
            return
        game.update({
            "question": question["question"],
            "options": question["options"],
            "answer": question["answer"],
        })
        self._schedule_station_timeout(session)
        yield event.chain_result([
            Comp.Plain(text=f"回答错误，答案是“{expected}”，你被淘汰。\n"),
            *self._station_question_chain(game, "下一题"),
        ])

    @filter.command("结束一站到底")
    async def station_end(self, event: AstrMessageEvent):
        event.stop_event()
        session = str(event.unified_msg_origin)
        game = self._station_games.get(session)
        if not game:
            yield event.plain_result("当前没有进行中的一站到底。")
            return
        if str(game["host"]) != str(event.get_sender_id()):
            yield event.plain_result("只有发起者可以结束一站到底。")
            return
        self._cancel_station_timeout(session)
        self._station_games.pop(session, None)
        yield event.plain_result("一站到底已结束。")

    def _station_question_chain(self, game: dict[str, object], prefix: str) -> list[object]:
        players = game["players"]
        current = players[int(game["turn"])]
        options = str(game.get("options") or "")
        question_text = f"{game['question']}"
        if options:
            question_text += f"\n选项：{options}"
        return [
            Comp.Plain(text=f"{prefix}，第 {game['round']} 回合。\n"),
            Comp.At(qq=str(current["id"])),
            Comp.Plain(text=f" 请作答：\n{question_text}\n（20 秒未作答将被淘汰）"),
        ]

    def _schedule_station_timeout(self, session: str) -> None:
        self._cancel_station_timeout(session)
        self._station_timeout_tasks[session] = asyncio.create_task(self._station_timeout(session))

    def _cancel_station_timeout(self, session: str) -> None:
        task = self._station_timeout_tasks.pop(session, None)
        if task:
            task.cancel()

    async def _station_timeout(self, session: str) -> None:
        try:
            await asyncio.sleep(20)
            game = self._station_games.get(session)
            if not game or not game.get("started"):
                return
            players = game["players"]
            current = players[int(game["turn"])]
            expected = str(game["answer"])
            players.pop(int(game["turn"]))
            if len(players) <= 1:
                self._station_games.pop(session, None)
                if players:
                    message = MessageChain([
                        Comp.Plain(text=f"{current['name']} 超时未作答，答案是“{expected}”。一站到底结束，"),
                        Comp.At(qq=str(players[0]["id"])),
                        Comp.Plain(text=" 是本轮站神！"),
                    ])
                else:
                    message = MessageChain([Comp.Plain(text=f"{current['name']} 超时未作答，答案是“{expected}”。一站到底结束。")])
            else:
                game["turn"] = int(game["turn"]) % len(players)
                try:
                    question = await self.service.station_question()
                    game.update({
                        "round": int(game["round"]) + 1,
                        "question": question["question"],
                        "options": question["options"],
                        "answer": question["answer"],
                    })
                    self._station_timeout_tasks[session] = asyncio.create_task(self._station_timeout(session))
                    message = MessageChain([
                        Comp.Plain(text=f"{current['name']} 超时未作答，已被淘汰。\n"),
                        *self._station_question_chain(game, "下一题"),
                    ])
                except Exception as error:
                    self._station_games.pop(session, None)
                    message = MessageChain([Comp.Plain(text=f"超时淘汰后下一题获取失败，本局结束：{error}")])
            await self.context.send_message(session, message)
        except asyncio.CancelledError:
            return
        finally:
            current_task = self._station_timeout_tasks.get(session)
            if current_task is asyncio.current_task():
                self._station_timeout_tasks.pop(session, None)

    @filter.command("娶群友")
    async def marry_random(self, event: AstrMessageEvent):
        event.stop_event()
        if not event.get_group_id():
            yield event.plain_result("娶群友只能在群里进行")
            return
        session = str(event.unified_msg_origin)
        game = self._marry_games.setdefault(session, [])
        user_id = str(event.get_sender_id())
        if self._marry_find(game, user_id):
            yield event.plain_result("你今天已经有对象了，别三心二意。")
            return
        if random.randrange(100) < 30:
            yield event.plain_result("真可惜，娶对象失败了，嘤嘤嘤。")
            return
        try:
            candidates = await self._marry_members(event, game, user_id)
        except Exception as error:
            logger.exception("Earth-K 群成员获取失败")
            yield event.plain_result(f"暂时获取不到群成员：{error}")
            return
        if not candidates:
            yield event.plain_result("当前没有可配对的群友。")
            return
        target_id, target_name = random.choice(candidates)
        pair = {"man": user_id, "man_name": event.get_sender_name() or user_id,
                "woman": target_id, "woman_name": target_name}
        game.append(pair)
        yield event.chain_result([
            Comp.At(qq=user_id),
            Comp.Plain(text=f" 你今天的对象是 {target_name}（{target_id}），好好珍惜对方哦。"),
        ])

    @filter.command("强娶")
    async def marry_force(self, event: AstrMessageEvent, target_id: str = ""):
        event.stop_event()
        async for result in self._marry_add_target(event, target_id.strip(), "强娶", steal=False):
            yield result

    @filter.command("抢群友")
    async def marry_steal(self, event: AstrMessageEvent, target_id: str = ""):
        event.stop_event()
        async for result in self._marry_add_target(event, target_id.strip(), "抢群友", steal=True):
            yield result

    async def _marry_add_target(self, event: AstrMessageEvent, target_id: str, action: str, steal: bool):
        if not event.get_group_id():
            yield event.plain_result(f"{action}只能在群里进行")
            return
        if not target_id:
            yield event.plain_result(f"用法：/{action} <用户ID>")
            return
        user_id = str(event.get_sender_id())
        if target_id == user_id:
            yield event.plain_result("不能和自己结婚。")
            return
        session = str(event.unified_msg_origin)
        game = self._marry_games.setdefault(session, [])
        if self._marry_find(game, user_id):
            yield event.plain_result("你今天已经有对象了。")
            return
        target_pair = self._marry_find(game, target_id)
        if target_pair and not steal:
            yield event.plain_result("对方今天已经被娶走了。")
            return
        if steal and not target_pair:
            yield event.plain_result("对方还没有对象，直接使用 /强娶 <用户ID> 吧。")
            return
        if steal and random.randrange(100) >= 70:
            yield event.plain_result("没抢着，欸嘿。")
            return
        try:
            members = await self._marry_members(event, game, user_id, include_paired=True)
        except Exception:
            members = []
        target_name = next((name for member_id, name in members if member_id == target_id), target_id)
        if target_pair:
            target_name = target_pair["man_name"] if target_pair["man"] == target_id else target_pair["woman_name"]
            game.remove(target_pair)
        game.append({"man": user_id, "man_name": event.get_sender_name() or user_id,
                     "woman": target_id, "woman_name": target_name})
        yield event.chain_result([
            Comp.At(qq=user_id),
            Comp.Plain(text=f" 成功{action}了 {target_name}（{target_id}）。"),
        ])

    @filter.command("我对象呢")
    async def marry_current(self, event: AstrMessageEvent):
        event.stop_event()
        if not event.get_group_id():
            yield event.plain_result("这个命令只能在群里使用")
            return
        pair = self._marry_find(self._marry_games.get(str(event.unified_msg_origin), []), str(event.get_sender_id()))
        if not pair:
            yield event.plain_result("醒醒吧，你今天还没有对象。")
            return
        partner_id, partner_name = self._marry_partner(pair, str(event.get_sender_id()))
        yield event.chain_result([
            Comp.At(qq=str(event.get_sender_id())),
            Comp.Plain(text=f" 你今天的对象是 {partner_name}（{partner_id}）。"),
        ])

    @filter.command("闹离婚")
    async def marry_divorce(self, event: AstrMessageEvent):
        event.stop_event()
        if not event.get_group_id():
            yield event.plain_result("这个命令只能在群里使用")
            return
        game = self._marry_games.get(str(event.unified_msg_origin), [])
        pair = self._marry_find(game, str(event.get_sender_id()))
        if not pair:
            yield event.plain_result("你连对象都没有，跟谁离婚呢。")
            return
        game.remove(pair)
        yield event.plain_result("没想到你们走到了这一步，那就将来再会吧。")

    @filter.command("群对象列表")
    async def marry_list(self, event: AstrMessageEvent):
        event.stop_event()
        if not event.get_group_id():
            yield event.plain_result("群对象列表只能在群里查看")
            return
        pairs = self._marry_games.get(str(event.unified_msg_origin), [])
        if not self.renderer:
            yield event.plain_result("\n".join(f"{pair['man_name']} ♥ {pair['woman_name']}" for pair in pairs) or "当前还没有对象关系。")
            return
        try:
            page = self.service.marry_list_html(pairs)
            yield event.image_result(await self.renderer.render(page, viewport_width=1100))
        except Exception as error:
            logger.exception("Earth-K 群对象列表渲染失败")
            yield event.plain_result(f"群对象列表渲染失败：{error}")

    async def _marry_members(
        self,
        event: AstrMessageEvent,
        game: list[dict[str, str]],
        user_id: str,
        include_paired: bool = False,
    ) -> list[tuple[str, str]]:
        group = await event.get_group()
        raw_members = getattr(group, "members", None) if group else None
        members = list(raw_members.values()) if isinstance(raw_members, dict) else list(raw_members or [])
        paired_ids = {
            user
            for pair in game
            for user in (pair["man"], pair["woman"])
        }
        self_id = str(event.get_self_id())
        result = []
        for member in members:
            member_id = str(getattr(member, "user_id", ""))
            if not member_id or member_id in {user_id, self_id}:
                continue
            if not include_paired and member_id in paired_ids:
                continue
            result.append((member_id, str(getattr(member, "nickname", "") or member_id)))
        return result

    @staticmethod
    def _marry_find(game: list[dict[str, str]], user_id: str) -> dict[str, str] | None:
        return next((pair for pair in game if pair["man"] == user_id or pair["woman"] == user_id), None)

    @staticmethod
    def _marry_partner(pair: dict[str, str], user_id: str) -> tuple[str, str]:
        if pair["man"] == user_id:
            return pair["woman"], pair["woman_name"]
        return pair["man"], pair["man_name"]

    @filter.command("魔法目录")
    async def tag_catalog_command(self, event: AstrMessageEvent):
        event.stop_event()
        names = self.service.tag_catalog()
        if not names:
            yield event.plain_result("本地魔法目录为空。")
            return
        if not self.renderer:
            yield event.plain_result("本地 HTML 渲染器未启动")
            return
        try:
            page = self.service.tag_catalog_html(names)
            yield event.image_result(await self.renderer.render(page, viewport_width=1100))
        except Exception as error:
            logger.exception("Earth-K 魔法目录渲染失败")
            yield event.plain_result(f"魔法目录渲染失败：{error}")

    @filter.command("目录")
    async def tag_entries_command(self, event: AstrMessageEvent, name: GreedyStr = ""):
        event.stop_event()
        name = str(name).strip()
        if not name:
            yield event.plain_result("用法：/目录 <名称或编号>，例如 /目录 人物")
            return
        try:
            title, entries = self.service.tag_entries(name)
            if not self.renderer:
                yield event.plain_result(f"{title}\n" + "\n".join(entries))
                return
            page = self.service.tag_entries_html(title, entries)
            yield event.image_result(await self.renderer.render(page, viewport_width=1100))
        except Exception as error:
            logger.exception("Earth-K 魔法标签查询失败")
            yield event.plain_result(f"魔法目录查询失败：{error}")

    @filter.command("预览图")
    async def tag_preview(self, event: AstrMessageEvent, name: GreedyStr = ""):
        event.stop_event()
        name = str(name).strip()
        if not name:
            yield event.plain_result("用法：/预览图 <标签名称>")
            return
        if name not in self.service.tag_catalog():
            yield event.plain_result("没有找到该标签，请先发送 /魔法目录 查看可用名称。")
            return
        yield event.chain_result([
            Comp.Plain(text=f"{name}预览图："),
            Comp.Image.fromURL(self.service.tag_preview_url(name)),
        ])

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

    @filter.command("角色视频列表")
    async def genshin_character_video_list(self, event: AstrMessageEvent):
        event.stop_event()
        async for result in self._send_genshin_video_list(event, "角色视频"):
            yield result

    @filter.command("角色视频")
    async def genshin_character_video(self, event: AstrMessageEvent, index: str = ""):
        event.stop_event()
        async for result in self._send_genshin_video(event, "角色视频", index):
            yield result

    @filter.command("过场动画列表")
    async def genshin_cutscene_list(self, event: AstrMessageEvent):
        event.stop_event()
        async for result in self._send_genshin_video_list(event, "过场动画"):
            yield result

    @filter.command("过场动画")
    async def genshin_cutscene(self, event: AstrMessageEvent, index: str = ""):
        event.stop_event()
        async for result in self._send_genshin_video(event, "过场动画", index):
            yield result

    async def _send_genshin_video_list(self, event: AstrMessageEvent, category: str):
        try:
            catalog = await self.service.genshin_video_catalog(category)
            if self.renderer:
                page = self.service.genshin_history_directory_html(category, catalog)
                yield event.image_result(await self.renderer.render(page, viewport_width=1200))
            else:
                names = "\n".join(f"{item['id']}. {item['title']}" for item in catalog)
                yield event.plain_result(f"{category}目录：\n{names}")
        except Exception as error:
            logger.exception(f"Earth-K {category}目录获取失败")
            yield event.plain_result(f"{category}目录获取失败：{error}")

    async def _send_genshin_video(self, event: AstrMessageEvent, category: str, index: str):
        index = index.strip()
        if not index.isdigit() or int(index) < 1:
            yield event.plain_result(f"用法：/{category} <编号>，发送 /{category}列表 查看目录")
            return
        try:
            catalog = await self.service.genshin_video_catalog(category)
            position = int(index) - 1
            if position >= len(catalog):
                yield event.plain_result(f"编号范围为 1-{len(catalog)}。")
                return
            item = catalog[position]
            url = await self.service.genshin_video_url(str(item["content_id"]))
            output_dir = self.data_dir or Path(StarTools.get_data_dir(self.name))
            output = output_dir / "video" / f"earth-k-{uuid4().hex}.mp4"
            await self.service.download_video(url, output)
            yield event.chain_result([
                Comp.Plain(text=f"{item['title']}："),
                Comp.Video.fromFileSystem(str(output)),
            ])
        except Exception as error:
            logger.exception(f"Earth-K {category}播放失败")
            yield event.plain_result(f"{category}播放失败：{error}")

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
        session = str(event.unified_msg_origin)
        self._history_choices.pop(session, None)
        try:
            entry, matches = await self.service.genshin_history_find(query)
            if entry is None:
                if matches:
                    choices = matches[:12]
                    self._history_choices[session] = choices
                    lines = []
                    for index, item in enumerate(choices, 1):
                        title = str(item.get("title") or "未知条目")
                        category = str(item.get("category") or "未分类")
                        content_id = str(item.get("content_id") or item.get("id") or "未知")
                        lines.append(f"{index}. {title}（{category}，ID: {content_id}）")
                    yield event.plain_result(
                        "找到多个条目，请选择编号：\n"
                        + "\n".join(lines)
                        + "\n请发送：/原史选择 <编号>"
                    )
                else:
                    yield event.plain_result("没有找到对应条目，请先使用 /原史目录 角色 查看目录。")
                return
            detail = await self.service.genshin_history_detail(entry)
            html = self.service.genshin_history_article_html(detail)
            yield event.image_result(await self.renderer.render(html, viewport_width=1200))
        except Exception as error:
            logger.exception("Earth-K 原史查询失败")
            yield event.plain_result(f"原史查询失败：{error}")

    @filter.command("原史选择")
    async def genshin_history_choose(self, event: AstrMessageEvent, choice: str = ""):
        event.stop_event()
        if not self.renderer:
            yield event.plain_result("本地 HTML 渲染器未启动")
            return
        session = str(event.unified_msg_origin)
        choices = self._history_choices.get(session)
        if not choices:
            yield event.plain_result("当前没有待选择的原史条目，请先发送 /原史 <名称>。")
            return
        choice = choice.strip()
        if not choice.isdigit() or int(choice) < 1 or int(choice) > len(choices):
            yield event.plain_result(f"请输入 1-{len(choices)} 之间的编号：/原史选择 <编号>")
            return
        entry = choices[int(choice) - 1]
        self._history_choices.pop(session, None)
        try:
            detail = await self.service.genshin_history_detail(entry)
            html = self.service.genshin_history_article_html(detail)
            yield event.image_result(await self.renderer.render(html, viewport_width=1200))
        except Exception as error:
            logger.exception("Earth-K 原史条目选择失败")
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

    @filter.command("角色说")
    async def character_say(self, event: AstrMessageEvent, payload: GreedyStr = ""):
        event.stop_event()
        parts = payload.strip().split(maxsplit=1)
        if len(parts) < 2:
            yield event.plain_result("用法：/角色说 <角色> <文本>")
            return
        character, text = parts
        output_dir = self.data_dir or Path(StarTools.get_data_dir(self.name))
        output = output_dir / "audio" / f"earth-k-role-{uuid4().hex}.mp3"
        result, error = await self.service.character_speak(character, text, output)
        if error:
            yield event.plain_result(error)
            return
        yield event.chain_result([
            Comp.Plain(text=f"{character}：{text}"),
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

    @filter.command("发电榜")
    @filter.command("土块发电榜")
    async def donate_rank(self, event: AstrMessageEvent):
        event.stop_event()
        async for result in self._donate_rank_result(event, recent=False):
            yield result

    @filter.command("最近发电")
    async def recent_donate(self, event: AstrMessageEvent):
        event.stop_event()
        async for result in self._donate_rank_result(event, recent=True):
            yield result

    async def _donate_rank_result(self, event: AstrMessageEvent, recent: bool):
        try:
            sponsors = await self.service.donate_sponsors(recent=recent)
            if not sponsors:
                yield event.plain_result("暂时没有发电记录。")
                return
            if not self.renderer:
                title = "最近发电" if recent else "发电榜"
                yield event.plain_result(f"{title}：\n" + "\n".join(
                    f"{index}. {item['name']}" for index, item in enumerate(sponsors[:10], 1)
                ))
                return
            html_page = self.service.donate_rank_html(
                sponsors,
                "recent" if recent else "rank",
                10 if recent else 20,
            )
            yield event.image_result(await self.renderer.render(html_page, viewport_width=1000))
        except Exception as error:
            logger.exception("Earth-K 发电榜获取失败")
            yield event.plain_result(f"发电榜获取失败：{error}")

    @filter.command("点游戏")
    async def game_list(self, event: AstrMessageEvent, category: str = ""):
        event.stop_event()
        session = str(event.unified_msg_origin)
        selected = category.strip().lower()
        if selected not in {"fc", "街机", "gba"}:
            if selected:
                yield event.plain_result("用法：/点游戏 [fc|街机|gba]")
                return
            selected = "fc"
        async for result in self._game_catalog_result(event, session, selected, 1):
            yield result

    @filter.command("游戏下一页")
    async def game_next_page(self, event: AstrMessageEvent):
        event.stop_event()
        session = str(event.unified_msg_origin)
        state = self._game_sessions.get(session)
        if not state:
            yield event.plain_result("请先发送 /点游戏 [fc|街机|gba] 查看游戏目录。")
            return
        async for result in self._game_catalog_result(
            event, session, str(state["category"]), int(state["page"]) + 1
        ):
            yield result

    @filter.command("游戏上一页")
    async def game_previous_page(self, event: AstrMessageEvent):
        event.stop_event()
        session = str(event.unified_msg_origin)
        state = self._game_sessions.get(session)
        if not state:
            yield event.plain_result("请先发送 /点游戏 [fc|街机|gba] 查看游戏目录。")
            return
        page = max(1, int(state["page"]) - 1)
        async for result in self._game_catalog_result(
            event, session, str(state["category"]), page
        ):
            yield result

    @filter.command("玩游戏")
    async def play_game(self, event: AstrMessageEvent, index: str = ""):
        event.stop_event()
        session = str(event.unified_msg_origin)
        state = self._game_sessions.get(session)
        if not state:
            yield event.plain_result("请先发送 /点游戏 [fc|街机|gba] 查看游戏目录。")
            return
        if not index.strip().isdigit() or int(index.strip()) < 1:
            yield event.plain_result("用法：/玩游戏 <编号>")
            return
        items = state.get("items")
        position = int(index.strip()) - 1
        if not isinstance(items, list) or position >= len(items):
            yield event.plain_result("游戏编号超出当前目录范围，请重新查看目录。")
            return
        item = items[position]
        if not isinstance(item, dict) or not item.get("url"):
            yield event.plain_result("这个游戏暂时没有可用链接。")
            return
        message = [Comp.Plain(text=f"{item.get('name', '游戏')}\n{item['url']}")]
        if item.get("image"):
            message.insert(0, Comp.Image.fromURL(str(item["image"])))
        yield event.chain_result(message)

    async def _game_catalog_result(
        self,
        event: AstrMessageEvent,
        session: str,
        category: str,
        page: int,
    ):
        try:
            items = await self.service.game_catalog(category, page)
            self._game_sessions[session] = {
                "category": category,
                "page": page,
                "items": items,
            }
            if not self.renderer:
                names = "\n".join(
                    f"{index}. {item['name']}" for index, item in enumerate(items, 1)
                )
                yield event.plain_result(f"{category} 第 {page} 页：\n{names}\n发送 /玩游戏 <编号> 选择游戏。")
                return
            page_html = self.service.game_list_html(category, page, items)
            yield event.image_result(await self.renderer.render(page_html, viewport_width=1100))
        except Exception as error:
            logger.exception("Earth-K 在线游戏目录获取失败")
            yield event.plain_result(f"在线游戏目录获取失败：{error}")

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

    @filter.command("猜原神")
    async def genshin_guess_start(self, event: AstrMessageEvent, payload: str = ""):
        event.stop_event()
        session = str(getattr(event, "unified_msg_origin", "") or event.get_sender_id())
        if payload.strip():
            yield event.plain_result("请使用 /猜原神答案 <名称> 作答，/猜原神提示 获取提示。")
            return
        if session in self._guess_games:
            yield event.plain_result("当前已经有一轮猜原神，请先作答或发送 /公布原神答案。")
            return
        try:
            answer, clues = self.service.new_genshin_guess()
            first = random.randrange(len(clues))
            clue = clues.pop(first)
            scores = self._guess_scores.setdefault(session, {})
            round_number = sum(scores.values()) + 1
            self._guess_games[session] = {
                "answer": answer,
                "clues": clues,
                "round": round_number,
            }
            yield event.plain_result(f"猜原神第 {round_number}/10 回合\n提示：{clue}\n发送 /猜原神答案 <名称> 作答。")
        except Exception as error:
            logger.exception("Earth-K 猜原神开始失败")
            yield event.plain_result(f"猜原神开始失败：{error}")

    @filter.command("猜原神答案")
    async def genshin_guess_answer(self, event: AstrMessageEvent, answer: str = ""):
        event.stop_event()
        session = str(getattr(event, "unified_msg_origin", "") or event.get_sender_id())
        game = self._guess_games.get(session)
        if not game:
            yield event.plain_result("当前没有进行中的猜原神，请先发送 /猜原神。")
            return
        answer = answer.strip()
        if not answer:
            yield event.plain_result("用法：/猜原神答案 <名称>")
            return
        sender = str(event.get_sender_id())
        player_name = event.get_sender_name() or sender or "玩家"
        names = self._guess_names.setdefault(session, {})
        names[sender] = player_name
        if not self.service.resolve_genshin_guess(answer, str(game["answer"])):
            yield event.plain_result("回答不正确，可以继续猜。")
            return

        scores = self._guess_scores.setdefault(session, {})
        scores[sender] = scores.get(sender, 0) + 1
        round_number = int(game["round"])
        canonical_answer = str(game["answer"])
        self._guess_games.pop(session, None)
        ranking = sorted(
            ((name, scores.get(user_id, 0)) for user_id, name in names.items()),
            key=lambda item: item[1],
            reverse=True,
        )
        try:
            if self.renderer:
                image = await self.renderer.render(
                    self.service.genshin_guess_score_html(ranking, round_number),
                    viewport_width=860,
                )
                yield event.image_result(image)
        except Exception as error:
            logger.exception("Earth-K 猜原神计分图渲染失败")
            yield event.plain_result(f"计分图渲染失败：{error}")
        if round_number >= 10:
            final = "、".join(f"{name}：{score}分" for name, score in ranking) or "暂无得分"
            self._guess_scores.pop(session, None)
            self._guess_names.pop(session, None)
            yield event.plain_result(f"恭喜答对！答案是：{canonical_answer}\n十回合结束，最终得分：{final}")
        else:
            yield event.plain_result(
                f"恭喜答对！答案是：{canonical_answer}\n"
                f"发送 /猜原神 开始第 {round_number + 1}/10 回合。"
            )

    @filter.command("猜原神提示")
    async def genshin_guess_hint(self, event: AstrMessageEvent):
        event.stop_event()
        session = str(getattr(event, "unified_msg_origin", "") or event.get_sender_id())
        game = self._guess_games.get(session)
        if not game:
            yield event.plain_result("当前没有进行中的猜原神，请先发送 /猜原神。")
            return
        clues = game["clues"]
        if not clues:
            yield event.plain_result("我去，已经没有能提示的了。")
            return
        clue = clues.pop(random.randrange(len(clues)))
        yield event.plain_result(f"提示：{clue}")

    @filter.command("公布原神答案")
    async def genshin_guess_reveal(self, event: AstrMessageEvent):
        event.stop_event()
        session = str(getattr(event, "unified_msg_origin", "") or event.get_sender_id())
        game = self._guess_games.pop(session, None)
        if not game:
            yield event.plain_result("当前没有进行中的猜原神。")
            return
        yield event.plain_result(f"答案是：{game['answer']}。本回合结束，请发送 /猜原神 继续。")

    @filter.command("重置原神猜题分数")
    async def genshin_guess_reset(self, event: AstrMessageEvent):
        event.stop_event()
        if not event.is_admin():
            yield event.plain_result("该命令仅限管理员使用")
            return
        session = str(getattr(event, "unified_msg_origin", "") or event.get_sender_id())
        self._guess_games.pop(session, None)
        self._guess_scores.pop(session, None)
        self._guess_names.pop(session, None)
        yield event.plain_result("当前会话的猜原神分数已重置")

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
