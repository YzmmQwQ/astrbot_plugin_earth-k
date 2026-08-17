from __future__ import annotations

import hashlib
import html
import os
import platform
import random
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


HELP_GROUPS = [
    (
        "已迁移功能",
        [
            ("/卜卦", "周易占卜，每日一卦"),
            ("/练习记忆力", "观察数字卡后，用 /我猜 <字母> 作答"),
            ("/今日运势", "查看今日运势"),
            ("/了解 <角色>", "发送本地角色资料图"),
            ("/大话骰规则", "发送大话骰规则图"),
            ("/土块状态", "查看 AstrBot 宿主进程和系统状态图"),
            ("/弹琴帮助", "查看音频演奏迁移说明"),
            ("/土块版本", "查看迁移版本"),
            ("/土块渲染测试", "管理员私聊测试本地 HTML 渲染"),
            ("/土块更新", "管理员调用 AstrBot 官方插件更新器"),
            ("/土块帮助", "查看当前已迁移命令"),
        ],
    ),
    (
        "迁移中的功能",
        [
            ("点歌、视频、小说、漫画", "正在替换 Yunzai 网络接口和消息段"),
            ("猜原神、猜语音、群小游戏", "正在迁移会话状态和群消息流程"),
            ("原史、角色资料、角色视频", "正在迁移数据接口和原有 HTML 模板"),
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
    def piano_help_text() -> str:
        return (
            "音频演奏说明\n"
            "原版支持：钢琴、八音盒、古筝、吉他、萨克斯、小提琴、吹箫、西域琴。\n"
            "音符支持 -1 到 -7、1 到 7、+1 到 +7；钢琴另支持 ++1 到 ++7。\n"
            "音符之间用空格或逗号分隔，末尾可用 |200 设置速度，例如：\n"
            "/钢琴 1 2 3 1 1 2 3 1|200\n\n"
            "当前状态：说明已迁移；音频合成仍在迁移，AstrBot 版本暂不会执行演奏命令。"
        )

    def character_image(self, character: str) -> Path | None:
        name = character.strip().replace("/", "").replace("\\", "")
        if not name or len(name) > 32:
            return None
        image = self.resources / "img" / "KnowAboutCharacter-IMG" / f"{name}.jpg"
        return image if image.is_file() else None

    def dice_rules_image(self) -> Path | None:
        image = self.resources / "img" / "骰子规则.jpg"
        return image if image.is_file() else None

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
            "host": [f"运行目录：{self.plugin_dir.parent}", f"解释器：{sys.executable}", "旧版 Yunzai Redis/Bot 数据：AstrBot 不提供，已移除"],
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
