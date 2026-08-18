from __future__ import annotations

import asyncio
import base64
import hashlib
import html
import json
import os
import platform
import random
import re
import shutil
import sys
import time
from datetime import date
from pathlib import Path

import aiohttp

try:
    import psutil
except ImportError:  # pragma: no cover - requirements installs psutil in AstrBot
    psutil = None

from .earth_renderer import EarthRenderer


HOYOWIKI_API = "https://sg-wiki-api.hoyolab.com/hoyowiki/wapi"
HOYOWIKI_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/102 Safari/537.36",
    "Referer": "https://wiki.hoyolab.com",
    "x-rpc-language": "zh-cn",
}
HOYOWIKI_MENUS = {
    "角色": "2",
    "武器": "4",
    "圣遗物": "5",
    "敌人": "7",
    "物产": "9",
    "NPC": "10",
    "书籍": "12",
    "教程": "14",
    "动物": "15",
}


HELP_GROUPS = [
    (
        "已迁移功能",
        [
            ("/卜卦", "周易占卜，每日一卦"),
            ("/练习记忆力", "观察数字卡后，用 /我猜 <字母> 作答"),
            ("/今日运势", "查看今日运势"),
            ("/了解 <角色>", "发送本地角色资料图"),
            ("/角色语音汇总", "查看可用的原神角色语音"),
            ("/语音 <角色> [编号]", "播放角色中文语音"),
            ("/猜语音", "开始一轮原神猜语音"),
            ("/猜语音答案 <角色>", "回答当前猜语音"),
            ("/公布语音答案", "公布当前猜语音答案"),
            ("/重置语音分数", "管理员重置当前会话猜语音分数"),
            ("/原史 <名称>", "查询原神角色、武器、圣遗物等资料"),
            ("/原史目录 <分类>", "查看原神资料分类目录"),
            ("/猜原神", "开始一轮本地题库猜原神"),
            ("/猜原神答案 <名称>", "回答当前猜原神题目"),
            ("/猜原神提示", "获取当前猜原神提示"),
            ("/公布原神答案", "公布答案并结束当前回合"),
            ("/重置原神猜题分数", "仅管理员可用，重置当前会话分数"),
            ("/大话骰规则", "发送大话骰规则图"),
            ("/发起大话骰", "在当前群聊发起一局大话骰"),
            ("/加入大话骰", "加入当前会话的大话骰"),
            ("/开始大话骰", "房主开始游戏"),
            ("/我的骰子", "私聊查看自己的骰子"),
            ("/叫骰 <数量> <点数>", "进行大话骰叫骰"),
            ("/开蛊", "揭示骰子并结算本轮"),
            ("/结束大话骰", "房主结束游戏"),
            ("/土块状态", "查看 AstrBot 宿主进程和系统状态图"),
            ("/弹琴帮助", "查看音频演奏迁移说明"),
            ("/钢琴 <音符>", "使用本地音色演奏，其他乐器命令同理"),
            ("/土块表情列表", "查看可用的表情合成关键词"),
            ("/表情合成 <关键词> [文字]", "用当前消息附带的图片生成表情"),
            ("/土块版本", "查看迁移版本"),
            ("/土块渲染测试", "管理员私聊测试本地 HTML 渲染"),
            ("/土块更新", "管理员调用 AstrBot 官方插件更新器"),
            ("/土块帮助", "查看当前已迁移命令"),
        ],
    ),
    (
        "迁移中的功能",
        [
            ("点歌、视频、小说、漫画", "正在迁移网络接口和消息发送"),
            ("群小游戏", "正在迁移会话状态和群消息流程"),
            ("角色语音、角色视频", "正在迁移数据接口和消息发送"),
            ("AI 绘图", "单独评估配置、审核和外部服务，不随本批启用"),
        ],
    ),
]

TRIGRAMS = {
    "000": "乾金", "100": "兑金", "110": "震木", "001": "巽木",
    "011": "艮土", "111": "坤土", "101": "坎水", "010": "离火",
}

HEXAGRAM_NAMES = [
    "乾为天", "泽天夬", "火天大有", "雷天大壮", "风天小畜", "水天需", "山天大畜", "地天泰",
    "天泽履", "兑为泽", "火泽睽", "雷泽归妹", "风泽中孚", "水泽节", "山泽损", "地泽临",
    "天火同人", "泽火革", "离为火", "雷火丰", "风火家人", "水火既济", "山火贲", "地火明夷",
    "天雷无妄", "泽雷随", "火雷噬嗑", "震为雷", "风雷益", "水雷屯", "山雷颐", "地雷复",
    "天风姤", "泽风大过", "火风鼎", "雷风恒", "巽为风", "水风井", "山风蛊", "地风升",
    "天水讼", "泽水困", "火水未济", "雷水解", "风水涣", "坎为水", "山水蒙", "地水师",
    "天山遁", "泽山咸", "火山旅", "雷山小过", "风山渐", "水山蹇", "艮为山", "地山谦",
    "天地否", "泽地萃", "火地晋", "雷地豫", "风地观", "水地比", "山地剥", "坤为地",
]


class EarthService:
    def __init__(self, plugin_dir: Path) -> None:
        self.plugin_dir = plugin_dir
        self.resources = plugin_dir / "resources"
        self.meme_url = "https://h.winterqkl.cn/memes/"
        self._meme_keywords: dict[str, dict[str, object]] = {}
        self._genshin_catalog: list[dict[str, object]] = []
        self._genshin_catalog_at = 0.0
        self._guess_aliases: dict[str, list[str]] = {}
        meme_file = self.resources / "bq.json"
        if meme_file.is_file():
            try:
                entries = json.loads(meme_file.read_text(encoding="utf-8"))
                for item in entries.values():
                    if not isinstance(item, dict):
                        continue
                    for keyword in item.get("keywords", []):
                        self._meme_keywords[str(keyword)] = item
            except (OSError, json.JSONDecodeError):
                pass
        guess_alias_file = self.resources / "json" / "mohu" / "mohu.json"
        if guess_alias_file.is_file():
            try:
                aliases = json.loads(guess_alias_file.read_text(encoding="utf-8"))
                if isinstance(aliases, dict):
                    self._guess_aliases = {
                        str(name): [str(alias) for alias in values if str(alias).strip()]
                        for name, values in aliases.items()
                        if isinstance(values, list)
                    }
            except (OSError, json.JSONDecodeError):
                pass

    def version_text(self) -> str:
        changelog = self.plugin_dir / "CHANGELOG.md"
        version = "2.0.0"
        if changelog.exists():
            for line in changelog.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.strip().startswith("##"):
                    version = line.lstrip("# ").strip()
                    break
        return f"Earth-K AstrBot 迁移版\n当前版本：{version}\n迁移状态：基础框架与本地 HTML 渲染已完成"

    @staticmethod
    def _guess_normalize(value: str) -> str:
        return re.sub(r"[\s·・「」【】『』（）()、,，.!！？:：\-_]", "", value).casefold()

    def new_genshin_guess(self) -> tuple[str, list[str]]:
        """Choose a local clue file and return its answer and remaining clues."""
        directory = self.resources / "txt" / "GuessGenshin"
        files = sorted(directory.glob("*.txt"))
        if not files:
            raise RuntimeError("猜原神题库为空")
        selected = random.choice(files)
        clues = [
            clue.replace("\\r", "").replace("\\n", "").replace("\r", "").replace("\n", "").strip()
            for clue in selected.read_text(encoding="utf-8", errors="ignore").split(",")
        ]
        clues = [clue for clue in clues if clue]
        if not clues:
            raise RuntimeError(f"题目“{selected.stem}”没有可用提示")
        return selected.stem, clues

    def resolve_genshin_guess(self, query: str, answer: str) -> bool:
        """Match the answer name or one of the legacy local aliases."""
        needle = self._guess_normalize(query)
        canonical = self._guess_normalize(answer)
        if not needle:
            return False
        if needle == canonical:
            return True
        return any(
            self._guess_normalize(alias) == needle
            for alias in self._guess_aliases.get(answer, [])
        )

    def genshin_guess_score_html(
        self,
        players: list[tuple[str, int]],
        round_number: int,
    ) -> str:
        css_path = self.resources / "html" / "GenshinSpeak" / "index.css"
        renderer = EarthRenderer(Path("."))
        css = renderer.inline_css(css_path.read_text(encoding="utf-8"), css_path)
        rows = "".join(
            f"<td>{html.escape(name)}-</td><td>{score}</td><tr>"
            for name, score in players
        )
        return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><style>
{css}
</style></head><body>
<div class="bt">第{round_number}回合</div>
<p class="nr">共十回合</p>
<div class="zhu"><table class="bg" border="0" width="650"><tbody>{rows}</tbody></table></div>
<p class="jw">Created By AstrBot &amp; Earth-K-Plugin</p>
</body></html>'''

    async def genshin_history_catalog(self, force: bool = False) -> list[dict[str, object]]:
        """Fetch the current HoYoWiki directories used by the old 原史 command."""
        if self._genshin_catalog and not force and time.monotonic() - self._genshin_catalog_at < 600:
            return self._genshin_catalog

        entries: list[dict[str, object]] = []
        try:
            for category, menu_id in HOYOWIKI_MENUS.items():
                page_num = 1
                total = None
                while total is None or len([item for item in entries if item["category"] == category]) < total:
                    payload = await self._hoyowiki_json(
                        "POST",
                        "/get_entry_page_list",
                        json_body={
                            "filters": [],
                            "menu_id": menu_id,
                            "page_num": page_num,
                            "page_size": 30,
                            "use_es": True,
                        },
                    )
                    data = ((payload.get("data") or {}) if isinstance(payload, dict) else {})
                    items = data.get("list") or []
                    total = int(data.get("total") or 0)
                    if not items:
                        break
                    for item in items:
                        if not isinstance(item, dict) or not item.get("entry_page_id") or not item.get("name"):
                            continue
                        entries.append({
                            "id": len(entries) + 1,
                            "category": category,
                            "content_id": str(item["entry_page_id"]),
                            "title": str(item["name"]).strip(),
                            "summary": str(item.get("desc") or "").strip(),
                            "icon": str(item.get("icon_url") or "").strip(),
                            "alias": "",
                        })
                    page_num += 1
                    if page_num > 100:
                        break
        except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError, ValueError, RuntimeError) as error:
            raise RuntimeError(f"原神资料目录获取失败：{error}") from error
        if not entries:
            raise RuntimeError("原神资料目录为空")
        self._genshin_catalog = entries
        self._genshin_catalog_at = time.monotonic()
        return entries

    async def _hoyowiki_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, object] | None = None,
        json_body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(headers=HOYOWIKI_HEADERS, timeout=timeout) as session:
            async with session.request(
                method,
                f"{HOYOWIKI_API}{path}",
                params=params,
                json=json_body,
            ) as response:
                response.raise_for_status()
                payload = await response.json(content_type=None)
        if not isinstance(payload, dict) or payload.get("retcode") != 0:
            message = payload.get("message") if isinstance(payload, dict) else "返回格式错误"
            raise RuntimeError(str(message))
        return payload

    @staticmethod
    def _history_normalize(value: str) -> str:
        return re.sub(r"[\s·・「」【】『』（）()、,，.!！？:：\-]", "", value).casefold()

    async def genshin_history_find(self, query: str) -> tuple[dict[str, object] | None, list[dict[str, object]]]:
        entries = self._genshin_catalog
        if not entries:
            try:
                payload = await self._hoyowiki_json("GET", "/search", params={"keyword": query})
                search_items = ((payload.get("data") or {}).get("list") or [])
                entries = [
                    self._hoyowiki_search_entry(item)
                    for item in search_items
                    if isinstance(item, dict) and self._hoyowiki_search_category(item)
                ]
            except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError, RuntimeError):
                entries = await self.genshin_history_catalog()
        needle = self._history_normalize(query)
        exact = [
            item for item in entries
            if needle and needle in {
                self._history_normalize(str(item.get("title") or "")),
                self._history_normalize(str(item.get("alias") or "")),
            }
        ]
        if len(exact) == 1:
            return exact[0], exact
        if len(exact) > 1:
            return None, exact
        partial = [
            item for item in entries
            if needle and needle in self._history_normalize(str(item.get("title") or ""))
        ]
        return (partial[0] if len(partial) == 1 else None), partial

    @staticmethod
    def _hoyowiki_search_category(item: dict[str, object]) -> str:
        menu = item.get("menu")
        if not isinstance(menu, dict):
            return ""
        submenu_items = menu.get("sub_menus") or []
        for submenu in submenu_items:
            if isinstance(submenu, dict):
                submenu_id = str(submenu.get("id") or "")
                for category, menu_id in HOYOWIKI_MENUS.items():
                    if submenu_id == menu_id:
                        return category
        return ""

    @classmethod
    def _hoyowiki_search_entry(cls, item: dict[str, object]) -> dict[str, object]:
        return {
            "id": str(item.get("entry_page_id") or ""),
            "category": cls._hoyowiki_search_category(item),
            "content_id": str(item.get("entry_page_id") or ""),
            "title": str(item.get("name") or "").strip(),
            "summary": str(item.get("desc") or "").strip(),
            "icon": str(item.get("icon_url") or "").strip(),
            "alias": "",
        }

    async def genshin_history_detail(self, entry: dict[str, object]) -> dict[str, object]:
        """Read a Wiki article and return safe text/image data for the local renderer."""
        title = str(entry.get("title") or "未知条目")
        summary = str(entry.get("summary") or "").strip()
        image = str(entry.get("icon") or "").strip()
        try:
            payload = await self._hoyowiki_json(
                "GET",
                "/entry_page",
                params={"entry_page_id": str(entry.get("content_id") or "")},
            )
            body, article_image = self._history_content_text(payload)
            image = article_image or image
            warning = ""
        except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError, RuntimeError) as error:
            warning = "正文接口暂时不可用"
            body = summary
            if not body:
                body = "当前只能获取到目录信息，请稍后重试。"
            body += f"\n\n（{warning}）"
        image = await self._history_image_uri(image)
        return {"title": title, "body": body or summary or "暂无资料正文。", "image": image, "warning": warning}

    async def genshin_character_entries(self) -> list[dict[str, object]]:
        """Return current character entries from HoYoWiki for voice lookup and quizzes."""
        entries: list[dict[str, object]] = []
        page_num = 1
        total = None
        while total is None or len(entries) < total:
            payload = await self._hoyowiki_json(
                "POST",
                "/get_entry_page_list",
                json_body={
                    "filters": [],
                    "menu_id": HOYOWIKI_MENUS["角色"],
                    "page_num": page_num,
                    "page_size": 30,
                    "use_es": True,
                },
            )
            data = ((payload.get("data") or {}) if isinstance(payload, dict) else {})
            items = data.get("list") or []
            total = int(data.get("total") or 0)
            if not items:
                break
            for item in items:
                if not isinstance(item, dict) or not item.get("entry_page_id") or not item.get("name"):
                    continue
                entries.append({
                    "id": str(item["entry_page_id"]),
                    "category": "角色",
                    "content_id": str(item["entry_page_id"]),
                    "title": str(item["name"]).strip(),
                    "summary": str(item.get("desc") or "").strip(),
                    "icon": str(item.get("icon_url") or "").strip(),
                    "alias": "",
                })
            page_num += 1
            if page_num > 100:
                break
        return entries

    async def genshin_voice_entry(self, query: str) -> tuple[dict[str, object] | None, list[dict[str, object]]]:
        entry, matches = await self.genshin_history_find(query)
        if entry is None:
            return None, matches
        payload = await self._hoyowiki_json(
            "GET",
            "/entry_page",
            params={"entry_page_id": str(entry["content_id"])},
        )
        voice_items = self._hoyowiki_voice_items(payload)
        if not voice_items:
            return None, [{"title": str(entry["title"]), "reason": "该角色没有可用语音"}]
        result = dict(entry)
        result["voice_items"] = voice_items
        return result, [result]

    async def genshin_random_voice(self) -> tuple[dict[str, object], dict[str, object]]:
        entries = await self.genshin_character_entries()
        random.shuffle(entries)
        for entry in entries[:30]:
            payload = await self._hoyowiki_json(
                "GET",
                "/entry_page",
                params={"entry_page_id": str(entry["content_id"])},
            )
            voice_items = self._hoyowiki_voice_items(payload)
            if voice_items:
                return entry, random.choice(voice_items)
        raise RuntimeError("暂时没有找到可用的角色语音")

    @staticmethod
    def _hoyowiki_voice_items(payload: object) -> list[dict[str, str]]:
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
            return []
        page = payload["data"].get("page")
        if not isinstance(page, dict):
            return []
        items: list[dict[str, str]] = []
        for module in page.get("modules") or []:
            if not isinstance(module, dict) or str(module.get("name") or "") != "语音":
                continue
            for component in module.get("components") or []:
                if not isinstance(component, dict):
                    continue
                raw_data = component.get("data")
                if not isinstance(raw_data, str):
                    continue
                try:
                    data = json.loads(raw_data)
                except json.JSONDecodeError:
                    continue
                for row in data.get("list") or []:
                    if not isinstance(row, dict) or not row.get("title"):
                        continue
                    audio_url = ""
                    for audio in row.get("audios") or []:
                        if isinstance(audio, dict) and str(audio.get("name") or "").upper() == "CN":
                            audio_url = str(audio.get("url") or "")
                            break
                    if audio_url:
                        items.append({
                            "name": str(row["title"]),
                            "content": str(row.get("desc") or ""),
                            "audio_url": audio_url,
                        })
        return items

    async def download_voice(self, url: str, output_path: Path) -> Path:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(headers=HOYOWIKI_HEADERS, timeout=timeout) as session:
            async with session.get(url) as response:
                response.raise_for_status()
                payload = await response.read()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(payload)
        return output_path

    def genshin_voice_list_html(self, character: str, items: list[dict[str, str]]) -> str:
        css_path = self.resources / "html" / "GenshinSpeak" / "index.css"
        css = EarthRenderer(Path(".")).inline_css(css_path.read_text(encoding="utf-8"), css_path)
        rows = "".join(
            f'<tr><td class="id">{index} - {html.escape(item["name"])}</td></tr>'
            f'<tr><td class="nei">{html.escape(item["content"])}</td></tr>'
            for index, item in enumerate(items, 1)
        )
        return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><style>{css}
body {{ width: auto; min-height: 100vh; }} .bg {{ width: 760px; }}
</style></head><body><div class="bt">{html.escape(character)}</div>
<p class="nr">以下为{html.escape(character)}语音列表，可发送 /语音 {html.escape(character)} 编号播放</p>
<div class="zhu"><table class="bg">{rows}</table></div>
<p class="jw">Created By AstrBot &amp; Earth-K-Plugin</p></body></html>'''

    @staticmethod
    def _history_content_text(payload: object) -> tuple[str, str]:
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
            return "", ""
        page = (payload["data"].get("page") or {})
        if not isinstance(page, dict):
            return "", ""
        sections: list[tuple[str, str]] = []
        modules = page.get("modules") or []
        preferred_modules = {"故事", "背景故事", "更多信息", "资料", "简介"}

        def collect_sections(value: object) -> None:
            if isinstance(value, dict):
                title = value.get("title")
                desc = value.get("desc")
                if isinstance(title, str) and isinstance(desc, str) and desc.strip():
                    sections.append((title.strip(), desc.strip()))
                for child in value.values():
                    if isinstance(child, (dict, list)):
                        collect_sections(child)
            elif isinstance(value, list):
                for child in value:
                    collect_sections(child)

        for module in modules:
            if not isinstance(module, dict):
                continue
            if str(module.get("name") or "") not in preferred_modules:
                continue
            for component in module.get("components") or []:
                if not isinstance(component, dict):
                    continue
                raw_data = component.get("data")
                if not isinstance(raw_data, str) or not raw_data.strip():
                    continue
                try:
                    collect_sections(json.loads(raw_data))
                except json.JSONDecodeError:
                    continue

        if not sections:
            desc = str(page.get("desc") or "").strip()
            if desc:
                sections.append(("简介", desc))
        text = "\n\n".join(
            f"【{title}】\n{EarthService._history_strip_html(desc)}"
            for title, desc in sections
        )
        return text, str(page.get("icon_url") or "")

    @staticmethod
    def _history_strip_html(value: str) -> str:
        value = html.unescape(value).replace("\\u003c", "<").replace("\\u003e", ">")
        value = re.sub(r"<(br|p|div|li|h[1-6])[^>]*>", "\n", value, flags=re.IGNORECASE)
        value = re.sub(r"<[^>]+>", "", value)
        value = html.unescape(value)
        value = re.sub(r"[ \t]+", " ", value)
        return re.sub(r"\n{3,}", "\n\n", value).strip()

    async def _history_image_uri(self, image: str) -> str:
        if not image or image.startswith("data:"):
            return image
        try:
            timeout = aiohttp.ClientTimeout(total=12)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(image) as response:
                    if response.status == 200:
                        content_type = response.headers.get("Content-Type", "image/png").split(";")[0]
                        payload = await response.read()
                        return f"data:{content_type};base64,{base64.b64encode(payload).decode('ascii')}"
        except (aiohttp.ClientError, asyncio.TimeoutError):
            pass
        return image

    def genshin_history_directory_html(self, category: str, entries: list[dict[str, object]]) -> str:
        css_path = self.resources / "html" / "GenshinHistory" / "ml.css"
        css = EarthRenderer(Path(".")).inline_css(css_path.read_text(encoding="utf-8"), css_path)
        rows = []
        for index, item in enumerate(entries, 1):
            rows.append(
                f'<tr><td class="id">{index}</td><td class="rw">'
                f'{html.escape(str(item.get("title") or ""))}'
                f'<small>#{item.get("id", "")}</small></td></tr>'
            )
        return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><style>{css}
small {{ margin-left: 12px; opacity: .65; font-size: 14px; }}</style></head><body>
<div class="kqtp"><div class="bt">原 史 目 录 · {html.escape(category)}</div></div>
<table class="bg1"><tbody>{"".join(rows)}</tbody></table>
<p class="jw">Created By AstrBot &amp; Earth-K-Plugin</p></body></html>'''

    def genshin_history_article_html(self, detail: dict[str, object]) -> str:
        css_path = self.resources / "html" / "GenshinHistory" / "gs.css"
        css = EarthRenderer(Path(".")).inline_css(css_path.read_text(encoding="utf-8"), css_path)
        image = str(detail.get("image") or "")
        image_html = f'<img class="history-image" src="{html.escape(image, quote=True)}" />' if image else ""
        paragraphs = "".join(
            f'<div class="lb">{html.escape(line)}</div>'
            for line in str(detail.get("body") or "暂无资料正文。" ).splitlines()
            if line.strip()
        )
        return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><style>{css}
.history-image {{ max-width: 60%; max-height: 520px; object-fit: contain; }}
.lb {{ white-space: pre-wrap; }}
</style></head><body><div class="kqtp">{image_html}<div>{html.escape(str(detail.get("title") or "未知条目"))}</div></div>
{paragraphs}<p class="jw">Created By AstrBot &amp; Earth-K-Plugin</p></body></html>'''

    @staticmethod
    def piano_help_text() -> str:
        return (
            "音频演奏说明\n"
            "原版支持：钢琴、八音盒、古筝、吉他、萨克斯、小提琴、吹箫、西域琴。\n"
            "音符支持 -1 到 -7、1 到 7、+1 到 +7；钢琴另支持 ++1 到 ++7。\n"
            "音符之间用空格或逗号分隔，末尾可用 |200 设置速度，例如：\n"
            "/钢琴 1 2 3 1 1 2 3 1|200\n\n"
            "当前状态：音频合成已迁移；宿主需要安装 FFmpeg 才能发送演奏结果。"
        )

    async def play_piano(
        self,
        instrument: str,
        notation: str,
        output_path: Path,
    ) -> tuple[Path | None, str | None]:
        instrument_dirs = {
            "钢琴": "gangqin",
            "八音盒": "ba",
            "古筝": "gu",
            "吉他": "jita",
            "萨克斯": "sa",
            "小提琴": "ti",
            "吹箫": "xiao",
            "西域琴": "xiyu",
        }
        directory = self.resources / "tanqin" / instrument_dirs.get(instrument, "gangqin")
        parsed, error = self._parse_piano_notation(notation, directory)
        if error:
            return None, error
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return None, "未找到 FFmpeg，无法合成音频。请先安装 FFmpeg 并加入系统 PATH。"

        output_path.parent.mkdir(parents=True, exist_ok=True)
        filters = []
        labels = []
        elapsed = 0.0
        for index, (note_path, duration) in enumerate(parsed):
            filters.append(f"[{index}:a]adelay={round(elapsed)}:all=1[a{index}]")
            labels.append(f"[a{index}]")
            elapsed += duration
        filters.append(
            f"{''.join(labels)}amix=inputs={len(parsed)}:dropout_transition=0:normalize=0[a]"
        )
        command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-threads", "4"]
        for note_path, _ in parsed:
            command.extend(["-i", str(note_path)])
        command.extend([
            "-filter_complex", ";".join(filters),
            "-map", "[a]", "-codec:a", "libmp3lame", str(output_path),
        ])
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(
                process.communicate(), timeout=max(30, elapsed / 1000 + 20)
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return None, "音频合成超时，请缩短曲谱后重试。"
        except OSError as error:
            return None, f"启动 FFmpeg 失败：{error}"
        if process.returncode != 0 or not output_path.is_file():
            detail = stderr.decode("utf-8", errors="ignore").strip() if stderr else "未知错误"
            return None, f"音频合成失败：{detail}"
        return output_path, None

    @staticmethod
    def _parse_piano_notation(
        notation: str,
        directory: Path,
    ) -> tuple[list[tuple[Path, float]], str | None]:
        score, _, tempo_text = notation.partition("|")
        tempo = 100
        if tempo_text.strip():
            try:
                tempo = int(tempo_text.strip())
            except ValueError:
                return [], "速度必须是数字，例如：|100。"
            if not 30 <= tempo <= 300:
                return [], "速度范围为 30 到 300。"
        tokens = score.replace("，", " ").replace(",", " ").split()
        if not tokens:
            return [], "请输入音符，例如：/钢琴 1 2 3 1。"
        if len(tokens) > 128:
            return [], "一次最多演奏 128 个音符。"

        result = []
        beat = 60000 / tempo
        for token in tokens:
            match = re.fullmatch(r"(\+{0,2}|-)?[0-7](_{0,3})", token)
            if not match:
                return [], f"无法识别音符：{token}。请使用 -7 到 +7，并用下划线表示短音。"
            note = token.replace("_", "")
            path = directory / f"{note}.mp3"
            if not path.is_file():
                return [], f"音色资源缺失：{note}.mp3。"
            duration = beat * ({0: 1, 1: 0.5, 2: 0.25, 3: 0.125}[len(match.group(2))])
            result.append((path, duration))
        return result, None

    def character_image(self, character: str) -> Path | None:
        name = character.strip().replace("/", "").replace("\\", "")
        if not name or len(name) > 32:
            return None
        image = self.resources / "img" / "KnowAboutCharacter-IMG" / f"{name}.jpg"
        return image if image.is_file() else None

    def dice_rules_image(self) -> Path | None:
        image = self.resources / "img" / "骰子规则.jpg"
        return image if image.is_file() else None

    async def meme_list(self) -> bytes:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(f"{self.meme_url}render_list") as response:
                response.raise_for_status()
                return await response.read()

    async def render_meme(
        self,
        keyword: str,
        texts: list[str],
        images: list[bytes],
        sender_name: str,
    ) -> tuple[bytes | None, str | None]:
        item = self._meme_keywords.get(keyword.strip())
        if not item:
            return None, "找不到这个表情关键词，请先发送 /土块表情列表 查看支持的关键词。"

        params = item.get("params_type") or {}
        min_images = int(params.get("min_images", 0))
        max_images = int(params.get("max_images", min_images))
        min_texts = int(params.get("min_texts", 0))
        max_texts = int(params.get("max_texts", min_texts))
        if not min_images <= len(images) <= max_images:
            return None, f"该表情需要 {min_images} 到 {max_images} 张图片，当前收到 {len(images)} 张。"
        if not min_texts <= len(texts) <= max_texts:
            return None, f"该表情需要 {min_texts} 到 {max_texts} 段文字，当前收到 {len(texts)} 段。"

        args = self._meme_args(str(item.get("key", "")), texts, sender_name)
        form = aiohttp.FormData()
        for index, image in enumerate(images):
            form.add_field(
                "images",
                image,
                filename=f"earth-k-{index}.jpg",
                content_type="application/octet-stream",
            )
        for text_value in texts:
            form.add_field("texts", text_value)
        if args:
            form.add_field("args", args)

        timeout = aiohttp.ClientTimeout(total=30)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(f"{self.meme_url}{item['key']}/", data=form) as response:
                    if response.status >= 300:
                        return None, f"表情服务返回错误（HTTP {response.status}），请稍后重试。"
                    return await response.read(), None
        except (aiohttp.ClientError, asyncio.TimeoutError) as error:
            return None, f"表情服务暂时不可用：{error}"

    @staticmethod
    def _meme_args(key: str, texts: list[str], sender_name: str) -> str:
        value = texts[0].strip() if texts else ""
        args: dict[str, object] = {
            "user_infos": [{"name": sender_name or "", "gender": "unknown"}]
        }
        if key == "look_flat":
            args["ratio"] = int(value) if value.isdigit() else 2
        elif key == "crawl":
            args["number"] = int(value) if value.isdigit() else random.randint(1, 92)
        elif key == "symmetric":
            args["direction"] = {"左": "left", "右": "right", "上": "top", "下": "bottom"}.get(value, "left")
        elif key in {"petpet", "jiji_king", "kirby_hammer"}:
            args["circle"] = value.startswith("圆")
        elif key == "my_friend":
            args["name"] = value or sender_name
        elif key == "looklook":
            args["mirror"] = value == "翻转"
        elif key == "always":
            args["mode"] = {"": "normal", "循环": "loop", "套娃": "circle"}.get(value, "normal")
        elif key in {"gun", "bubble_tea"}:
            args["position"] = {"左": "left", "右": "right", "两边": "both"}.get(value, "right")
        return json.dumps(args, ensure_ascii=False)

    @staticmethod
    async def message_image_bytes(message: object) -> bytes | None:
        """Read an image component from the current AstrBot message."""
        source = getattr(message, "url", None) or getattr(message, "file", None)
        if not source:
            return None
        if str(source).startswith("base64://"):
            try:
                return base64.b64decode(str(source)[9:])
            except (ValueError, TypeError):
                return None
        if str(source).startswith(("http://", "https://")):
            timeout = aiohttp.ClientTimeout(total=15)
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(str(source)) as response:
                        if response.status < 300:
                            return await response.read()
            except aiohttp.ClientError:
                return None
            return None
        path = Path(str(source).removeprefix("file:///"))
        try:
            return path.read_bytes() if path.is_file() else None
        except OSError:
            return None

    def state_html(self) -> str:
        """Build the original status layout from AstrBot host metrics."""
        state_dir = self.resources / "html" / "state"
        css_path = state_dir / "lyr.css"
        renderer = EarthRenderer(Path("."))
        css = renderer.inline_css(css_path.read_text(encoding="utf-8"), css_path)
        background = self._asset_uri(self.resources / "help" / "theme" / "default" / "bg.jpg")
        icon_dir = state_dir / "zt"

        def icon(name: str) -> str:
            return self._asset_uri(icon_dir / name)

        def text(value: object) -> str:
            return html.escape(str(value))

        metrics = self._host_metrics()
        visual = metrics["visual"]
        bot = metrics["bot"]
        stat_rows = "".join(
            f'''<td class="biaoge"><img src="{icon(name)}" class="bgtu"><br>{text(value)}</td>'''
            for name, value in (
                ("收.png", bot["received"]),
                ("发.png", bot["sent"]),
                ("图片.png", "AstrBot"),
                ("人.png", "当前会话"),
                ("人群.png", "当前会话"),
            )
        )
        visual_cells = "".join(
            f'''<td class="biaoge3"><img src="{icon(item["icon"])}" class="bgtu3"><br>
<a class="bfb">{text(item["inner"])}</a><br><br>{text(item["info"][0])}<br>
{text(item["info"][1])}<br>{text(item["info"][2])}</td>'''
            for item in visual
        )
        disks = "".join(
            f'''<div class="HardDisk_li"><div class="progress">
<div class="word">{text(item["mount"])}   {text(item["use"])}%    {text(item["used"])} / {text(item["size"])}</div>
<div class="current" style="width:{item["use"]}%;background:{item["color"]}"></div>
</div></div>'''
            for item in metrics["disks"]
        )
        other_rows = "".join(
            f'<tr><td><div class="biao1">{text(first)}</div></td>'
            f'<td><div class="biao2">{text(last)}</div></td></tr>'
            for first, last in metrics["other"]
        )
        host_rows = "".join(f'<tr><td><div class="biao3">{text(row)}</div></td></tr>' for row in metrics["host"])
        bot_name = text(bot["name"])
        return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><style>
{css}
body {{ background-image:url("{background}"); }}
.state-avatar {{ object-fit:contain; background:rgba(255,255,255,.12); padding:22px; }}
</style></head><body><div class="box"><br>
<div class="nbox"><div class="zt1"><img class="zt state-avatar" src="{icon("机器人_o.png")}" width="200" height="200"></div>
<h1 class="name">{bot_name}</h1>
<div class="zhuangtai"><img src="{icon("状态.png")}" class="ztd">- AstrBot Python 插件</div>
<table class="bg"><tbody><tr>{stat_rows}</tr></tbody></table></div>
<div class="nbox"><table class="bg2"><tbody>
<tr><th class="biaoge2"><img src="{icon("机器人_o.png")}" class="bgtu2"></th><td class="biaoge2">{text(bot["platform"])}</td></tr>
<tr><th class="biaoge2"><img src="{icon("电脑.png")}" class="bgtu2"></th><td class="biaoge2">{text(metrics["uptime"])}</td></tr>
<tr><th class="biaoge2"><img src="{icon("设置.png")}" class="bgtu2"></th><td class="biaoge2">{text(metrics["runtime"])}</td></tr>
<tr><th class="biaoge2"></th><td class="biaoge22">{text(metrics["time"])}</td></tr>
</tbody></table><table class="bg3"><tbody><tr>{visual_cells}</tr></tbody></table></div>
<div class="nbox2"><div class="memory"><ul>{disks}</ul></div></div>
<div class="nbox"><table class="bg4">{other_rows}</table></div>
<div class="nbox"><table class="bg4">{host_rows}</table></div>
</div><br></body></html>'''

    def _host_metrics(self) -> dict[str, object]:
        now = time.time()
        if psutil is None:
            return self._fallback_metrics(now)

        cpu = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        process = psutil.Process(os.getpid())
        process_memory = process.memory_info().rss
        disks = []
        seen: set[tuple[int, int]] = set()
        for partition in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(partition.mountpoint)
            except (OSError, PermissionError):
                continue
            key = (usage.total, usage.used)
            if key in seen or not usage.total:
                continue
            seen.add(key)
            percent = round(usage.percent)
            color = "var(--low-color)" if percent < 70 else "var(--medium-color)" if percent < 90 else "var(--high-color)"
            disks.append({
                "mount": partition.mountpoint,
                "use": percent,
                "used": self._file_size(usage.used),
                "size": self._file_size(usage.total),
                "color": color,
            })

        network = psutil.net_io_counters(pernic=True)
        active = [(name, item) for name, item in network.items() if not name.lower().startswith(("lo", "loopback"))]
        active.sort(key=lambda pair: pair[1].bytes_sent + pair[1].bytes_recv, reverse=True)
        if active:
            interface, counter = active[0]
            network_text = f"{interface} ↑{self._file_size(counter.bytes_sent, False, False)} | ↓{self._file_size(counter.bytes_recv, False, False)}"
        else:
            network_text = "无可用网络接口"

        plugin_root = self.plugin_dir.parent
        plugin_count = sum(1 for item in plugin_root.iterdir() if item.is_dir()) if plugin_root.is_dir() else 1
        return {
            "bot": {
                "name": "AstrBot",
                "platform": f"AstrBot Python {platform.python_version()}",
                "received": "当前进程",
                "sent": f"{plugin_count} plugins",
            },
            "uptime": f"系统运行 {self._duration(now - psutil.boot_time())}",
            "runtime": f"AstrBot 进程 {self._duration(process.create_time() and now - process.create_time())}",
            "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
            "visual": [
                {"icon": "CPU.png", "inner": f"{round(cpu)}%", "info": [f"{platform.processor() or '未知 CPU'} {psutil.cpu_count() or 0}核", f"系统 {platform.system()} {platform.release()}", f"负载 {round(cpu, 1)}%"]},
                {"icon": "内存.png", "inner": f"{round(memory.percent)}%", "info": [f"总共 {self._file_size(memory.total)}", f"已用 {self._file_size(memory.used)}", f"空闲 {self._file_size(memory.available)}"]},
                {"icon": "设置.png", "inner": f"{self._file_size(process_memory, False, False)}", "info": ["当前插件进程", f"Python {platform.python_version()}", f"PID {process.pid}"]},
            ],
            "disks": disks,
            "other": [("系统", platform.platform()), ("网络", network_text), ("插件", f"{plugin_count} 个 AstrBot 插件")],
            "host": [f"运行目录：{self.plugin_dir.parent}", f"解释器：{sys.executable}", "旧版运行时数据：AstrBot 不提供，已移除"],
        }

    def _fallback_metrics(self, now: float) -> dict[str, object]:
        return {
            "bot": {"name": "AstrBot", "platform": "AstrBot Python", "received": "未知", "sent": "未知"},
            "uptime": "系统运行时间不可用", "runtime": "AstrBot 进程运行时间不可用",
            "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
            "visual": [
                {"icon": "CPU.png", "inner": "未知", "info": ["psutil 未安装", "请安装 requirements.txt", ""]},
                {"icon": "内存.png", "inner": "未知", "info": ["psutil 未安装", "请安装 requirements.txt", ""]},
                {"icon": "设置.png", "inner": "未知", "info": ["AstrBot 进程", "Python", ""]},
            ], "disks": [], "other": [("系统", platform.platform()), ("网络", "未知")], "host": [],
        }

    @staticmethod
    def _duration(seconds: float) -> str:
        seconds = max(0, int(seconds))
        days, seconds = divmod(seconds, 86400)
        hours, seconds = divmod(seconds, 3600)
        minutes, seconds = divmod(seconds, 60)
        return f"{days}天{hours:02d}小时{minutes:02d}分{seconds:02d}秒"

    @staticmethod
    def _file_size(size: int | float, is_byte: bool = True, suffix: bool = True) -> str:
        if size is None:
            return "0"
        units = ["B", "Kb", "Mb", "Gb", "Tb"]
        value = float(size)
        index = 0
        while value >= 1024 and index < len(units) - 1:
            value /= 1024
            index += 1
        if not is_byte and index == 0:
            return f"{value:.2f}"
        return f"{value:.2f}{units[index] if suffix else units[index].replace('b', '')}"

    @staticmethod
    def _asset_uri(path: Path) -> str:
        return EarthRenderer(Path(".")).inline_file(path) if path.is_file() else ""

    async def daily_fortune(self, user_id: str) -> dict[str, str]:
        """Fetch the old service when available, with a deterministic local fallback."""
        url = f"https://api.fanlisky.cn/api/qr-fortune/get/{user_id}"
        try:
            timeout = aiohttp.ClientTimeout(total=8)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        payload = await response.json(content_type=None)
                        data = payload.get("data") or payload
                        if isinstance(data, dict) and data.get("fortuneSummary"):
                            return {
                                "summary": str(data.get("fortuneSummary", "平稳")),
                                "star": str(data.get("luckyStar", "三星")),
                                "review": str(data.get("signText", "保持平常心，稳步前进。")),
                                "detail": str(data.get("unSignText", "今日宜脚踏实地，忌急于求成。")),
                                "source": "在线运势服务",
                            }
        except Exception:
            pass

        options = [
            ("大吉", "五星", "今日状态上佳，适合推进重要计划。", "把握机会，也记得给自己留出休息时间。"),
            ("小吉", "四星", "小事顺利，积累会带来不错的结果。", "先完成最重要的一件事，再处理其他安排。"),
            ("平稳", "三星", "平稳度日，耐心会比速度更有价值。", "避免冲动决定，按自己的节奏完成今天的事。"),
            ("待时", "二星", "今天适合整理和准备，不必强求立刻见效。", "把基础工作做好，合适的时机自然会出现。"),
        ]
        seed = hashlib.sha256(f"{date.today().isoformat()}:{user_id}".encode()).digest()
        summary, star, review, detail = options[int.from_bytes(seed[:2], "big") % len(options)]
        return {"summary": summary, "star": star, "review": review, "detail": detail, "source": "本地备用结果"}

    def help_html(self) -> str:
        groups = []
        for title, items in HELP_GROUPS:
            rows = "".join(
                f'<div class="help-item"><strong>{command}</strong><span>{description}</span></div>'
                for command, description in items
            )
            groups.append(f'<section><h2>{title}</h2><div class="help-grid">{rows}</div></section>')
        return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><style>
* {{ box-sizing: border-box; }}
@font-face {{ font-family: earth; src: url('{self._font_uri()}'); }}
body {{ margin: 0; width: 860px; padding: 42px; color: #eee; font-family: earth, sans-serif;
  background: #1e2730 url('{self._help_background_uri()}') center/cover fixed; }}
.panel {{ padding: 30px; border-radius: 16px; background: rgba(27, 35, 44, .78);
  box-shadow: 0 8px 24px rgba(0,0,0,.3); backdrop-filter: blur(5px); }}
h1 {{ margin: 0; color: #ceb78b; font-size: 42px; }}
.subtitle {{ margin: 8px 0 28px; color: #b9c2ca; font-size: 16px; }}
section {{ margin-top: 20px; overflow: hidden; border-radius: 12px; background: rgba(6,21,31,.4); }}
h2 {{ margin: 0; padding: 14px 18px; color: #ceb78b; font-size: 20px; }}
.help-grid {{ display: grid; grid-template-columns: 1fr 1fr; }}
.help-item {{ min-height: 76px; padding: 12px 18px; border-top: 1px solid rgba(255,255,255,.08); }}
.help-item strong {{ display: block; color: #d3bc8e; font-size: 17px; }}
.help-item span {{ display: block; margin-top: 5px; color: #eee; font-size: 14px; }}
</style></head><body><main class="panel"><h1>土块帮助</h1>
<div class="subtitle">AstrBot & Earth-K-Plugin · 仅使用 / 命令</div>{''.join(groups)}</main></body></html>"""

    def divination_html(self) -> str:
        return self.divination_card(self.draw_divination())

    def draw_divination(self) -> tuple[tuple[str, str], tuple[str, str], tuple[str, str]]:
        return self._draw_hexagram(), self._draw_hexagram(), self._draw_hexagram()

    def divination_card(self, result: tuple[tuple[str, str], tuple[str, str], tuple[str, str]]) -> str:
        css_path = self.resources / "html" / "Divination" / "zy.css"
        renderer = EarthRenderer(Path("."))
        css = renderer.inline_css(css_path.read_text(encoding="utf-8"), css_path)
        bg = renderer.inline_file(self.resources / "html" / "Divination" / "bg.png")
        return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><style>
{css}
body {{ background-image: url('{bg}'); }}
.earth-title {{ color: #d3bc8e; text-align: center; font-size: 26px; margin: 12px; }}
</style></head><body><div class="earth-title">周易占卜</div>
<div class="lb2">{result[0][0]}</div><div class="lb3">{result[0][1]}</div>
<div class="lb">变爻：{result[2][0]} · {result[2][1]}</div>
<div class="lb2">{result[1][0]}</div><div class="lb3">{result[1][1]}</div>
<p class="jw">Created By AstrBot & Earth-K-Plugin</p></body></html>"""

    @staticmethod
    def _draw_hexagram() -> tuple[str, str]:
        number = random.randrange(64)
        bits = f"{number:06b}"
        name = HEXAGRAM_NAMES[number]
        upper = TRIGRAMS[bits[:3]]
        lower = TRIGRAMS[bits[3:]]
        return name, f"上卦{upper}，下卦{lower}。顺势而为，守正待时。"

    def memory_card(
        self,
        positions: list[tuple[int, int]],
        labels: list[str],
        highlighted: int = -1,
    ) -> str:
        css_path = self.resources / "html" / "Memory" / "html.css"
        renderer = EarthRenderer(Path("."))
        css = renderer.inline_css(css_path.read_text(encoding="utf-8"), css_path)
        items = []
        for index, ((left, top), label) in enumerate(zip(positions, labels)):
            background = "background-color:rgb(255 0 0 / 70%);" if index == highlighted else ""
            items.append(
                f'<span class="jw" style="left:{left}px;top:{top}px;{background}">{label}</span>'
            )
        return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><style>
{css}
body {{ position: relative; margin: 0; background: #f5f1e8; }}
.jw {{ position: absolute; }}
.js {{ position: absolute; }}
</style></head><body>{''.join(items)}
<div class="js">发送 /我猜 + 字母回答</div>
<p class="js" style="top:960px">Created By AstrBot & Earth-K-Plugin</p>
</body></html>"""

    @staticmethod
    def new_memory_round() -> dict[str, object]:
        positions = [(random.randint(100, 900), random.randint(100, 900)) for _ in range(9)]
        labels = list("abcdefghi")
        random.shuffle(labels)
        target = random.randrange(9)
        return {"positions": positions, "labels": labels, "target": target}

    def _font_uri(self) -> str:
        font = self.resources / "font" / "jty.OTF"
        return EarthRenderer(Path(".")).inline_file(font) if font.exists() else ""

    def _help_background_uri(self) -> str:
        bg = self.resources / "help" / "theme" / "default" / "bg.jpg"
        return EarthRenderer(Path(".")).inline_file(bg) if bg.exists() else ""
