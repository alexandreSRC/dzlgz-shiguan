# -*- coding: utf-8 -*-
"""存档加载层 —— 把「一个存档槽目录」读成可浏览的表族集合。**纯只读。**

实测结论（`Save_All_1`：407 个 .json / 32MB）
------------------------------------------------
· **本地槽是纯明文 JSON**，全目录搜 crc/md5/check/sign/hash/version → 一个校验字段都没有
· **云端下载的槽是 Base64 + 加密**（熵 7.9987/8），没有密钥 → 直接拒绝并给出解法
· 顶层结构只有两种：
    列表 → 每条元素是一条记录（`Save_Ren_Data_0.json` = 100 个人）
    字典 → 文件本身就是**一条**记录（`Save_KingData_0.json` = 一个国家的 83 个字段）
  另外字典里若挂着「列表 + 元素是字典」，那是**子表**（如
  `Save_Res_Bank_Data.json` 的 `All_Res_Bank_Array` 有 3186 条）

每条记录都带一个精确的 `Src`（文件 + 取值路径），供「这条数据在哪个文件里」的溯源显示。

⚠️ v0.2 起本项目**只读**。所有写回能力（格式探测、预演、备份、落盘）已按需求整体移除，
   不再有任何写盘入口 —— 见 `工作日志.md` 的「只读化」一节。
"""
import json
import os
import re
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# 游戏在自己私有目录下的存档根（注意那个反斜杠是目录名的一部分，游戏自己的路径 bug）
# 实际拉取/扫描路径以 tools/sync_from_mumu.py 的 PACKAGES 为准
GAME_PKG = "com.xinlanzaoyi.ztz.mi"

IOT = r"[A-Za-z0-9+/=\r\n]"
SUFFIX_NUM = re.compile(r"_\d+$")


class CloudSaveError(Exception):
    """整个槽都是 .txt —— 那是游戏「云端下载」的加密档，解不了。"""

    def __init__(self, root: str = ""):
        super().__init__(
            "这是游戏『云端下载』的加密存档（Base64 + 加密，实测熵 7.9987/8）。"
            "没有密钥就解不开。解法：在游戏里【载入】它、过一个回合让它自动存档，"
            "游戏会把明文写回本地槽（.json），那时才能读。")
        self.root = root


# ==================================================================== 记录来源

@dataclass(frozen=True)
class Src:
    """一条记录在磁盘上的精确位置。"""
    file: str                    # 相对文件名
    path: Tuple = ()             # () 整个文件 | (idx,) 列表项 | (key, idx) 嵌套数组项

    def label(self) -> str:
        if not self.path:
            return f"{self.file}（整文件）"
        if len(self.path) == 1:
            return f"{self.file} · 第 {self.path[0]} 条"
        return f"{self.file} · {self.path[0]}[{self.path[1]}]"


@dataclass
class Table:
    """一个表族（同名前缀的所有文件合成一张表）。"""
    name: str
    label: str = ""
    srcs: List[Src] = field(default_factory=list)
    rows: List[dict] = field(default_factory=list)
    files: List[str] = field(default_factory=list)
    _fields: Optional[List[str]] = None

    def __len__(self):
        return len(self.rows)

    @property
    def fields(self) -> List[str]:
        """字段并集（保持首次出现顺序）—— 同族文件的结构可能不一样。"""
        if self._fields is None:
            seen = OrderedDict()
            for r in self.rows:
                for k in r:
                    seen.setdefault(k, None)
            self._fields = list(seen)
        return self._fields


# ==================================================================== 加载

def _read_json(path: str):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def sniff(path: str) -> str:
    """json | encrypted | unknown。"""
    with open(path, "rb") as f:
        head = f.read(4096)
    s = head.lstrip()
    if s[:1] in (b"{", b"["):
        return "json"
    try:
        head.decode("ascii")
    except UnicodeDecodeError:
        return "unknown"
    return "encrypted" if all(chr(c) in r"ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                              r"abcdefghijklmnopqrstuvwxyz0123456789+/=\r\n" for c in head) else "unknown"


class SaveSlot:
    """一个存档槽目录。`load()` 之后 tables 里就是全部可浏览的数据。"""

    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        self.tables: "OrderedDict[str, Table]" = OrderedDict()
        self.warnings: List[str] = []
        self.files_json: List[str] = []
        self.files_txt: List[str] = []
        self.total_bytes = 0

    # ---------------------------------------------------------------- 名字
    @property
    def name(self) -> str:
        return os.path.basename(self.root) or self.root

    # ---------------------------------------------------------------- 扫描
    def scan(self) -> bool:
        """只列文件、不解析。返回是否是「本地明文槽」。"""
        if not os.path.isdir(self.root):
            return False
        ents = sorted(os.listdir(self.root))
        self.files_json = [e for e in ents if e.lower().endswith(".json")]
        self.files_txt = [e for e in ents if e.lower().endswith(".txt")]
        self.total_bytes = sum(os.path.getsize(os.path.join(self.root, e))
                               for e in ents if os.path.isfile(os.path.join(self.root, e)))
        return bool(self.files_json)

    def load(self, progress=None) -> "SaveSlot":
        """读整个槽。`progress(done, total, name)` 用来更新界面。"""
        if not self.scan():
            if self.files_txt:
                raise CloudSaveError(self.root)
            raise FileNotFoundError(f"目录里没有 .json：{self.root}")
        total = len(self.files_json)
        for i, fn in enumerate(self.files_json):
            if progress:
                progress(i, total, fn)
            try:
                obj = _read_json(os.path.join(self.root, fn))
            except Exception as e:
                self.warnings.append(f"{fn} 解析失败：{e}")
                continue
            fam = SUFFIX_NUM.sub("", fn[:-5])
            if isinstance(obj, list):
                self._add(fam, fn, [(Src(fn, (j,)), it) for j, it in enumerate(obj)])
            elif isinstance(obj, dict):
                # 字典文件本身 = 一条记录（`Save_KingData_0.json` 就是一个国家）
                self._add(fam, fn, [(Src(fn), obj)])
                # 挂在字典里的「列表 + 字典元素」= 子表
                for k, v in obj.items():
                    if isinstance(v, list) and v and isinstance(v[0], dict):
                        self._add(f"{fam}/{k}", fn,
                                  [(Src(fn, (k, j)), it) for j, it in enumerate(v)])
            else:
                self.warnings.append(f"{fn} 顶层既不是列表也不是字典，已跳过")
        if progress:
            progress(total, total, "")
        return self

    def _add(self, fam: str, fn: str, items):
        t = self.tables.get(fam)
        if t is None:
            t = Table(name=fam)
            self.tables[fam] = t
        if fn not in t.files:
            t.files.append(fn)
        for src, obj in items:
            if not isinstance(obj, dict):
                obj = {"__value__": obj}       # 纯字符串/数字的列表项也留个位置
            t.rows.append(obj)
            t.srcs.append(src)

    # ---------------------------------------------------------------- 便捷
    def table(self, name: str) -> Optional[Table]:
        return self.tables.get(name)

    def find(self, *names: str) -> Optional[Table]:
        """按给定优先级取第一个存在的表（不同版本的表名会变）。"""
        for n in names:
            t = self.tables.get(n)
            if t is not None and len(t):
                return t
        return None

    def summary(self) -> str:
        return (f"{len(self.files_json)} 个 json / "
                f"{self.total_bytes / 1048576:.1f} MB / {len(self.tables)} 个表族")


# ==================================================================== 目录列举

def game_year(slot) -> Optional[int]:
    """这个存档「现在走到哪一年」（公元前为负）。

    ★ 2026-09-21 加 —— 时间轴「时代全览」原来右端写死公元 1000，
      春秋开局也一路画到隋唐（使用者：「时代全览中的时代也是变动的…战国秦汉
      则不存在」）。要做到随开局时间动态变化，就得先问存档：你走到哪年了。

    存档里的时间字段是 `年,月,?` 这种逗号串（实测 `-209,1,0`），
    表名各版本不一样，所以按可靠度依次试几张「一开局就该有记录」的表。
    都取不到就返回 None —— 调用方退回「最晚生年 + 余量」。
    """
    if slot is None:
        return None
    for fam, key in (("Save_Zhan_Zheng_Data", "Start_Time"),
                     ("Save_Wai_Jiao_Data", "War_Creat_Time"),
                     ("Save_Hui_Fang_Data", "Record_Time"),
                     ("Save_Ming_Fen_Data", "Start_Time"),
                     ("Save_KingData/King_Stage_Record", "Start_Time"),
                     ("Save_King_Death_Data", "Che_Di_Die_Time")):
        t = slot.table(fam)
        if not t:
            continue
        for r in t.rows:
            v = str(r.get(key) or "")
            if not v:
                continue
            head = v.split(",")[0].strip()
            try:
                y = int(head)
            except ValueError:
                continue
            if -4000 <= y <= 2000:
                return y
    return None


def is_slot_dir(path: str) -> bool:
    if not os.path.isdir(path):
        return False
    try:
        ents = os.listdir(path)
    except OSError:
        return False
    return any(e.lower().endswith((".json", ".txt")) for e in ents)


def list_slots(base: str) -> List[str]:
    """列出一个「存档根」下的所有槽目录（按名称自然序）。

    ★ 2026-09-21：排除 `Save_All_N.bak_<时间戳>` —— 那是拉档落位时把旧槽
      **改名**留下的备份（`sync_from_mumu` 故意的，随时能退回去），
      它不是槽，列进「实录槽」里只会多出一堆看着像存档的废项。
    """
    if not os.path.isdir(base):
        return []
    out = [os.path.join(base, e) for e in os.listdir(base)
           if ".bak_" not in e and is_slot_dir(os.path.join(base, e))]
    return sorted(out, key=lambda p: os.path.basename(p).lower())


