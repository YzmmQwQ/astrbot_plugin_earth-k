from __future__ import annotations

import random
from pathlib import Path

from .earth_renderer import EarthRenderer


HELP_GROUPS = [
    (
        "已迁移功能",
        [
            ("/卜卦", "周易占卜，每日一卦"),
            ("/练习记忆力", "观察数字卡后，用 /我猜 <字母> 作答"),
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
