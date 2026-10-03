# -*- coding: utf-8 -*-
"""剧本两档判定（上古 / 秦末）—— 唯一实现（代码改进 C1，2026-09-22）。

为什么必须有这个模块：此前 `main._detect_era`（进程内，吃 SaveSlot 的表行）与
`tools/import_from_game.detect_era`（子进程 CLI，直接读 json 文件）各持一份
同级判据，两边注释自己都写着「改一处要改两处，这条注释就是提醒」——
实测已经踩过「秦末档被判成上古」（秦宗庙是圣人阶段、邻国还是先民阶段）。

判据（按可靠度；采用原 import_from_game 版的超集，`Wang_Chao_Zhi_Du` 制度
这条是 main 旧版没有的）：
  1.  王朝纪元 `Wang_Chao_Jie_Duan`：郡县纪元 / 霸主纪元 → 秦末；
      推举纪元 / 诸侯纪元 / 礼法纪元 → 上古
  1b. 王朝制度 `Wang_Chao_Zhi_Du`：中央集权制 / 宗法分封制 → 秦末；方国共主制 → 上古
      ⚠️ 别只看「纪元」两个字 —— 「推举纪元」是上古的
  2.  玩家国分段起点 `King_Stage_Record[].Start_Time`：> 前 500 → 秦末，否则上古
  3.  **玩家国**的 `King_Stage`：圣人阶段 → 秦末；先民/方国/礼法 → 上古
      玩家是哪一国由**世传表**（`Shi_Zhuan_Controller.Play_Change_King_Map`）
      反查 `King_Code`；反查不到才退回旧约定 0。
  4.  兜底：全世界最高阶段（先民 < 方国 < 礼法 < 圣人）达到圣人 → 秦末

⚠️ 关键认知（实测踩过）：`Save_KingData` 是全世界 151 国的花名册，每国各带
自己的 `King_Stage` 且**同时代并存** —— 「有一国是先民 = 整档上古」是错的。

两类调用方各自把数据读成「行列表」再调 `era_of`：
  · main（SaveSlot 已载入）→ 传 slot.tables 里的表行
  · import_from_game（CLI / 子进程）→ 传 json 文件读出的行
本模块不依赖 tkinter，两边都能安全 import。
"""
import re


def parse_bc_year(text):
    """「公元前209年」/「-209」/杂串 → 整数年（公元前为负）；解析不出返回 None。

    调用方（main / import_from_game）拿到 None 就退回别的判据，不要抛。
    """
    if not text:
        return None
    m = re.search(r"公元前\s*(\d+)", str(text))
    if m:
        return -int(m.group(1))
    m = re.search(r"公元\s*(\d+)", str(text))
    if m:
        return int(m.group(1))
    m = re.search(r"(-?\d+)", str(text))
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    return None


# 全世界发展阶段的高低序（兜底用）
_STAGE_ORDER = ("先民阶段", "方国阶段", "礼法阶段", "圣人阶段")


def player_king_code(sz_rows, kd_rows):
    """世传表 + 国表 → **玩家（当前君主）那一国**的 `King_Code`；取不到返回 None。

    ★ 2026-10-02 修（一百零四批查实、一百零六批落地）：本模块原按
      「玩家国 `King_Code == 0`」判档。实测 `Save_All_101`：**0 是秦**，
      玩家是**楚（1）** —— 于是 #3 那条判据取的是**别国**的阶段。
      本档秦楚阶段恰好都判「秦末」故未暴雷；换成阶段不同的盘就判错。

    判据（唯一来源 = 游戏自己写的世传）：
      `Shi_Zhuan_Controller` 里的 `Play_Change_King_Map` 是**君主变更映射**
      （实测 `[{"key":"开始","value":"楚"}]`，value = 国名），取最后一条的
      `value` 当玩家国名，再到 `Save_KingData` 的花名册里按 `King_Name`
      找回 `King_Code`。任一步取不到就返回 None（调用方退回 0，兼容老档）。

    ⚠️ 实测结构：世传表**外面还套了一层** `Dang_Ju_Shi_Zhuan`
      （`Shi_Zhuan_Controller.json` 顶层只有这一个键），所以不能只看行顶层 ——
      行内一层字典值里的字段也要找（见 `_king_change_map`）。
    """
    m = _king_change_map(sz_rows)
    name = ""
    for it in (m or []):
        if isinstance(it, dict) and str(it.get("value") or "").strip():
            name = str(it["value"]).strip()      # 取最后一条 = 当前
    if not name:
        return None
    for r in (kd_rows or []):
        if not isinstance(r, dict):
            continue
        if str(r.get("King_Name") or "").strip() == name:
            kc = r.get("King_Code")
            if kc is not None and str(kc) != "":
                return str(kc)
    return None


def _king_change_map(rows):
    """行列表 → 君主变更映射（兼容「行顶层」与「行内一层字典」两种结构）。"""
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        cands = [r] + [v for v in r.values() if isinstance(v, dict)]
        for c in cands:
            m = c.get("Play_Change_King_Map")
            if isinstance(m, list):
                return m
    return None


def era_of(wc_rows, rec_rows, kd_rows, player_code=None):
    """行列表 → 「上古」/「秦末」。判据见模块头，按可靠度依次降级。

    `wc_rows`   Save_Wang_Chao_Data 的行（王朝纪元 / 制度）
    `rec_rows`  King_Stage_Record 的行（分段起点年）
    `kd_rows`   Save_KingData 的行（全世界 151 国，供 #3/#4）
    `player_code` 玩家国的 `King_Code`（`player_king_code()` 反查所得）。
                 None / 空 ⇒ 退回旧约定「0」（老档没有世传表时唯一能走的路）。
    """
    # 1 / 1b) 王朝纪元 → 王朝制度（同一行内先纪元后制度，逐行扫）
    for r in wc_rows or []:
        if not isinstance(r, dict):
            continue
        jd = str(r.get("Wang_Chao_Jie_Duan") or "")
        if jd in ("郡县纪元", "霸主纪元"):
            return "秦末"
        if jd in ("推举纪元", "诸侯纪元", "礼法纪元"):
            return "上古"
        zd = str(r.get("Wang_Chao_Zhi_Du") or "")
        if zd in ("中央集权制", "宗法分封制"):
            return "秦末"
        if zd == "方国共主制":
            return "上古"

    # 2) 分段起点年（存档自记）
    for r in rec_rows or []:
        y = parse_bc_year((r or {}).get("Start_Time"))
        if y is not None:
            return "秦末" if y > -500 else "上古"

    # 3) 玩家国自己的阶段（King_Code 由世传表反查；反查不到退回旧约定 0）
    pk = "0" if player_code in (None, "") else str(player_code)
    for r in kd_rows or []:
        if str(r.get("King_Code")) == pk:
            st = str(r.get("King_Stage") or "")
            if st == "圣人阶段":
                return "秦末"
            if st in ("先民阶段", "方国阶段", "礼法阶段"):
                return "上古"

    # 4) 兜底：全世界最高阶段
    best = -1
    for r in kd_rows or []:
        st = str(r.get("King_Stage") or "")
        if st in _STAGE_ORDER:
            best = max(best, _STAGE_ORDER.index(st))
    if best >= 3:
        return "秦末"
    return "上古"
