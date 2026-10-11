# -*- coding: utf-8 -*-
"""「上传版」路径脱敏过滤器（git clean / smudge）—— 本地真路径，推上去是占位符。

背景
----
本地源码里写的是**本机真路径**（本机缓存槽、桌面目录、模拟器安装目录、局域网 IP 等）。
这些不该出现在公开仓库里；但直接把源码改成占位符又会**改坏本机在跑的默认值**
（使用者裁定：「本地不要动，上传的弄上传版」）。

做法：用 git 自带的 `filter` ——
  · 提交 / 推送（clean）：真路径 → 占位符；
  · 检出 / 还原（smudge）：占位符 → 真路径。
⇒ **工作区文件一个字节都不动**，进仓库的都是脱敏版。

映射表**不入库**（否则等于把真路径又写进仓库）：放在 `tools/_public_filter.local.json`
（已加入 `.gitignore`，也可用环境变量 `SHIGUAN_PUBLIC_MAP` 指到别处），格式：

    {"pairs": [["D:\\\\Some\\\\Local\\\\Dir", "__YOUR_PLACEHOLDER__"],
               ["192.168.1.5",              "__YOUR_LAN_IP__"]]}

反斜杠有**两种写法**：裸文本里是单个，Python 字符串字面量里成对。两种各用一个占位符
变体（`_E` 后缀）分别记住 ⇒ 还原时**逐字节一致**（改一处必改 `_esc()`）。

一次性配置（本机；每个克隆都要配一次。`required=true` 保证过滤器失败时**报错**，
而不是悄悄把真路径提交上去）：

    git config filter.public.clean  "python tools/_public_filter.py --clean"
    git config filter.public.smudge "python tools/_public_filter.py --smudge"
    git config filter.public.required true

用法（由 git 调用，不手动跑）：
    python tools/_public_filter.py --clean   < 原始 > 脱敏
    python tools/_public_filter.py --smudge  < 脱敏 > 原始
"""
import json
import os
import re
import sys

MAP_ENV = "SHIGUAN_PUBLIC_MAP"
DEFAULT_MAP = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "_public_filter.local.json")


def load_pairs():
    """读本机映射表（长路径在前，保证「先长后短」）。读不到就**报错退出** —— 绝不放过。"""
    path = os.environ.get(MAP_ENV) or DEFAULT_MAP
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        pairs = [(str(a), str(b)) for a, b in data["pairs"]]
    except Exception as e:
        sys.stderr.write(
            "脱敏过滤器取不到映射表 %s：%r\n"
            "（该文件不入库，见 tools/_public_filter.py 的说明）\n" % (path, e))
        raise SystemExit(1)
    pairs.sort(key=lambda kv: -len(kv[0]))
    return pairs


def _rx(path, n):
    """把 `path` 编成正则：路径分隔的每个反斜杠恰好匹配 `n` 个反斜杠。"""
    parts = path.split("\\")
    pat = re.escape(parts[0])
    for p in parts[1:]:
        pat += re.escape("\\" * n) + re.escape(p)
    return re.compile(pat)


def _esc(ph):
    """占位符的「成对反斜杠」变体：`__X__` → `__X_E__`（两个变体互不为前缀）。"""
    return ph[:-2] + "_E__"


def clean(text, pairs):
    """真路径 → 占位符。先处理「成对反斜杠」（n=2），再处理「单个」（n=1）。"""
    for n in (2, 1):
        for path, ph in pairs:
            if n == 2 and "\\" not in path:
                continue                       # 无分隔符的（如 IP）只做一遍
            text = _rx(path, n).sub(_esc(ph) if n == 2 else ph, text)
    return text


def smudge(text, pairs):
    """占位符 → 真路径（还原成写入时的反斜杠写法，逐字节一致）。"""
    for path, ph in pairs:
        if "\\" in path:
            text = text.replace(_esc(ph), path.replace("\\", "\\\\"))
        text = text.replace(ph, path)
    return text


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    raw = sys.stdin.buffer.read()
    if b"\x00" in raw:                         # 二进制：原样通过
        sys.stdout.buffer.write(raw)
        return
    pairs = load_pairs()
    txt = raw.decode("utf-8", "surrogateescape")
    txt = clean(txt, pairs) if mode == "--clean" else smudge(txt, pairs)
    sys.stdout.buffer.write(txt.encode("utf-8", "surrogateescape"))


if __name__ == "__main__":
    main()
