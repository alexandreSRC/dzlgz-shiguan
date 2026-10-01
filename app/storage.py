"""存档存储层：saves/ 目录的读写与增删改。

存档目录结构 saves/<存档名>/family.json
文件结构：
    {
      "people": {...},
      "cutoff_person": ...,
      "source": {                    # ★ 新增（2026-09-21）
        "slot": "Save_All_1",        # 这份谱牒是从哪个实录槽抽出来的
        "slot_path": "D:\\DevCache\\dzlgz\\Save_All_1",
        "era": "秦末",               # 抽取时判定出的剧本
        "imported": "2026-09-21 10:40",
        "prune": "hist", "real_state_only": true,
      },
      "focused_people": [...],       # ★ 新增（2026-09-24）画布「选定」名单
      "hidden_non_historical": [...] # ★ 新增（2026-09-24）按支系隐藏非史的祖先
    }

★ 为什么要有 `source`（使用者第 7 问的落地）
--------------------------------------------------
使用者原话：「**实录和谱牒应该是一一对应的关系**，我不知道为什么我载入谱牒
《文王治岐》以后实录还是 Save_All_1，Save_All_1 应该就是读取的秦末起义的
存档数据归纳出来的，二者是统一的。」

问题在于：改之前 `family.json` 里**没有任何来源信息**，
所以「实录▾」不知道这份谱牒对应哪一槽，永远停在默认槽（Save_All_1）。
有了 `source.slot`，切谱牒时就能自动把实录切到对应的槽上。
这一层同时也是「**自动续谱机**」的接缝：将来「同步」按钮只要按
`source.slot` 重新拉一遍存档、重新抽取，就能把新增的人物续进谱里。

兼容：没有 `source` 的旧档照样读 —— `source` 缺省为空 dict。

★ 为什么「选定名单」也搬进这里（2026-09-24 使用者第 9 问）
----------------------------------------------------------
使用者问：「其他存档的选定人物和入谱是不是跟到我这个存档里来了？」
**选定名单串了，入谱没串** ——
  · `enrolled`（入谱标）本来就写在 `people` 里的每个人身上 → 天然按本隔离；
  · 而 `focused_people` / `hidden_non_historical` 原来存在**全局 config.json**，
    一本档选的名单会跟到下一本。实测那一份 34 人名单横跨 4 本书，
    还有 12 人属于早已删掉的《卫氏朝鲜》—— 换本新书就会「莫名已选定」。
经使用者拍板：**这两个名单跟「入谱」一样按谱牒存**（存这里）。
`cutoff_person`（截断显示）本来就在本文件里，语义上同属「画布状态」，
于是三者归位成一组。
"""
import json
import logging
import os
import re
import shutil

logger = logging.getLogger(__name__)

SAVES_DIR = "saves"
DATA_FILE = "family.json"

# 谱牒级的「画布状态」键（★ 2026-09-24）。原来它们住在全局 config.json 里，
# 一本档选的名单会跟到别的书里去 —— 见模块头说明。
CANVAS_KEYS = ("focused_people", "hidden_non_historical")

_INVALID_NAME_CHARS = re.compile(r'[\\/:*?"<>|]')


def ensure_saves_dir():
    if not os.path.exists(SAVES_DIR):
        os.makedirs(SAVES_DIR)
        logger.info(f"创建存档目录: {SAVES_DIR}")


def save_path(save_name):
    return os.path.join(SAVES_DIR, save_name, DATA_FILE)


def list_saves():
    """列出所有含 family.json 的存档目录（按名称排序）。"""
    if not os.path.exists(SAVES_DIR):
        return []
    saves = []
    for name in os.listdir(SAVES_DIR):
        save_dir = os.path.join(SAVES_DIR, name)
        if os.path.isdir(save_dir) and os.path.exists(os.path.join(save_dir, DATA_FILE)):
            saves.append(name)
    return sorted(saves)


def sanitize_name(name):
    return _INVALID_NAME_CHARS.sub("_", name or "").strip()


def load_save(save_name):
    """读取存档，返回 (people, cutoff_person)。文件缺失或损坏时返回 ({}, None)。"""
    people, cutoff, _src = load_save_full(save_name)
    return people, cutoff


def load_save_full(save_name):
    """读取存档，返回 (people, cutoff_person, source)。

    `source` 是这份谱牒的来源元数据（见模块头的说明）；旧档没有就返回 {}。
    """
    if not save_name:
        return {}, None, {}
    path = save_path(save_name)
    if not os.path.exists(path):
        logger.info(f"存档文件不存在: {path}")
        return {}, None, {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:
        logger.error(f"加载数据失败: {e}")
        raise
    if isinstance(raw, dict) and "people" in raw:
        return raw["people"], raw.get("cutoff_person", None), raw.get("source") or {}
    return raw, None, {}


def load_source(save_name):
    """只取来源元数据（切谱牒时用，避免白读整个 people）。"""
    try:
        return load_save_full(save_name)[2]
    except Exception:
        return {}


# 已故灰开关的按谱缓存 —— 渲染循环里会逐人问一次，不能每次都去读文件
_DEAD_SHADE_CACHE = {}


def hide_dead_shade(save_name) -> bool:
    """本谱是否声明「**不涂已故灰**」（`source.hide_dead_shade`）。

    ★ 2026-09-26 使用者裁定：《全史存档》跨 2500 年、**人人皆死**，
      已故灰不携带任何信息，全谱一律不涂 —— 家谱铭牌（两种版式）/ 时间轴铭牌 /
      表格页 / 人物页表格 **四处同规**（原来四处各写一份 `info["death"]` 判据，
      所以开关也做在这里、一处改四处生效）。

    机制与 `source.hide_cols` 同源：**谱牒自己声明**，界面读它；
    普通单剧本档没有这个键 → 保持原样（已故照样涂灰）。
    """
    name = str(save_name or "")
    if not name:
        return False
    if name in _DEAD_SHADE_CACHE:
        return _DEAD_SHADE_CACHE[name]
    val = False
    try:
        val = bool((load_source(name) or {}).get("hide_dead_shade"))
    except Exception:
        val = False
    _DEAD_SHADE_CACHE[name] = val
    return val


def load_canvas_state(save_name):
    """只取「画布状态」（选定名单 / 按支系隐藏名单）。

    ★ 2026-09-24：这两个名单原来是全局 config 键，会串到别的谱牒去。
      现在跟 `enrolled` 一样按谱牒存。返回的字典**保证两个键都在**（缺省空表），
      调用方不用再判 None。旧档没有这两个键 → 空表（等于「本档还没选过人」）。
    """
    out = {k: [] for k in CANVAS_KEYS}
    if not save_name:
        return out
    path = save_path(save_name)
    if not os.path.exists(path):
        return out
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:
        logger.warning(f"读取画布状态失败({save_name}): {e}")
        return out
    if isinstance(raw, dict):
        for k in CANVAS_KEYS:
            v = raw.get(k)
            if isinstance(v, list):
                out[k] = v
    return out


# ---------------------------------------------------------------- 原子写
# ★ 2026-09-26 审查修复（事故根因收口）：`write_save` 原来是裸 `open(path,"w")`
#   —— 无备份、非原子。七十一批的「18:22 合并成果被一次关窗口覆盖」事故、
#   以及「写一半崩溃 = 整本谱牒损坏」的风险，都出在这里。
#   现在统一走「备份 → 写 tmp → os.replace」，与 tools.import_from_game
#   的 write_atomic 同一套语义（app 侧不 import tools，这里自带一份轻实现）。

_MAX_BAKS = 10          # 与 tools.write_atomic 的 MAX_BAKS 保持一致


def _prune_baks(path, keep=_MAX_BAKS):
    d = os.path.dirname(path)
    base = os.path.basename(path)
    try:
        baks = sorted(f for f in os.listdir(d) if f.startswith(base + ".bak_"))
    except OSError:
        return
    for old in baks[:-keep] if len(baks) > keep else []:
        try:
            os.remove(os.path.join(d, old))
        except OSError:
            pass


def _atomic_write_json(path, payload, keep_backup=True):
    """备份 → 写 tmp → os.replace。返回备份路径（没备份则空串）。

    备份失败（磁盘只读等极罕见情形）只警告、不阻止保存 —— 宁可少一份备份，
    不能让人连保存都保存不了；正常路径下备份一定在。
    """
    import time
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = ""
    if keep_backup and os.path.exists(path):
        bak = f"{path}.bak_{ts}"
        try:
            shutil.copy2(path, bak)
            with open(bak, encoding="utf-8") as f:
                json.load(f)            # 备份必须能读回来，否则宁可不备
        except Exception as e:
            logger.warning(f"写前备份失败（继续保存，但本次无备份）：{e}")
            try:
                if os.path.exists(bak):
                    os.remove(bak)
            except OSError:
                pass
            bak = ""
    tmp = f"{path}.tmp_{ts}"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        raise
    _prune_baks(path)
    return bak


def write_save(save_name, people, cutoff_person, source=None, canvas=None):
    """写入存档；返回是否成功。

    ★ `source` 缺省时**保留文件里已有的那份**，不会被 None 抹掉 ——
    否则日常编辑（改个人名、加个备注）一保存就把来源信息冲没了。
    ★ `canvas`（选定名单 / 按支系隐藏名单）同款：缺省时从文件里读回已有的，
    免得「改个尊号」把画布上的选定名单顺手清空。
    ★ 2026-09-26：写盘改走 `_atomic_write_json`（写前自动 `.bak` + 原子替换，
    自动只留最近 10 份）—— 七十一批「关窗口把外部脚本成果覆盖掉」事故的
    根因收口；「史馆开着别用脚本改 saves/」的铁律从此多了一道保险。
    """
    if not save_name:
        logger.warning("未指定存档名，跳过保存")
        return False
    path = save_path(save_name)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if source is None:
            source = load_source(save_name)
        if canvas is None:
            canvas = load_canvas_state(save_name)
        payload = {"people": people, "cutoff_person": cutoff_person}
        if source:
            payload["source"] = source
        for k in CANVAS_KEYS:
            v = canvas.get(k) if isinstance(canvas, dict) else None
            if v:
                payload[k] = list(v)
        _atomic_write_json(path, payload, keep_backup=True)
        logger.info(f"成功保存 {len(people)} 个人物数据 → {path}")
        return True
    except Exception as e:
        logger.error(f"保存数据失败: {e}")
        raise


def set_source(save_name, **fields):
    """往存档的 `source` 里合并几个字段（不动 people）。

    给「从实录槽导入」用：导入完成后回填 slot / era / imported。
    """
    path = save_path(save_name)
    if not os.path.exists(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:
        logger.error(f"读取存档失败(写来源)：{e}")
        return False
    src = raw.get("source") or {}
    src.update({k: v for k, v in fields.items() if v is not None})
    raw["source"] = src
    try:
        # ★ 2026-09-26：同样走原子写 —— set_source 也是整文件重写，
        #   写一半崩了同样是整本谱牒损坏。
        _atomic_write_json(path, raw, keep_backup=True)
        logger.info(f"谱牒来源已记录：{save_name} ← {src.get('slot')}")
        return True
    except Exception as e:
        logger.error(f"写来源失败: {e}")
        return False


# ---------------------------------------------------------------- 保护档

def is_protected(save_name):
    """这部谱牒是不是「保护档」—— 自动续谱要绕开它。

    ★ 使用者 2026-09-21 拍板：《上古时代》《文王治岐》是他**手写的原始记录**，
      自动续谱不许覆盖。打上 `source.protected = true` 之后，自动流程遇到
      同一个剧本就跳过并提示；想强制续写，在「存档」对话框里把「保」摘掉即可。
    """
    return bool((load_source(save_name) or {}).get("protected"))


def set_protected(save_name, flag=True):
    """给谱牒打 / 摘「保护档」标记（写进 `source`，不动 people）。"""
    return set_source(save_name, protected=bool(flag))


def create_save(name):
    if os.path.exists(os.path.join(SAVES_DIR, name)):
        return False
    os.makedirs(os.path.join(SAVES_DIR, name))
    write_save(name, {}, None, source={})
    logger.info(f"新建存档: {name}")
    return True


def rename_save(old_name, new_name):
    src = os.path.join(SAVES_DIR, old_name)
    dst = os.path.join(SAVES_DIR, new_name)
    if os.path.exists(dst):
        return False
    os.rename(src, dst)
    logger.info(f"重命名存档: {old_name} → {new_name}")
    return True


def duplicate_save(name, new_name):
    dst = os.path.join(SAVES_DIR, new_name)
    if os.path.exists(dst):
        return False
    shutil.copytree(os.path.join(SAVES_DIR, name), dst)
    logger.info(f"复制存档: {name} → {new_name}")
    return True


def delete_save(name):
    shutil.rmtree(os.path.join(SAVES_DIR, name))
    logger.info(f"删除存档: {name}")


def export_save(save_name, file_path):
    """导出为独立 json 文件。"""
    shutil.copy2(save_path(save_name), file_path)
    logger.info(f"导出存档成功: {file_path}")


def import_save(file_path, save_name):
    """把外部 json 导入成新存档，返回人物数量。"""
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("无效的存档文件格式")
    save_dir = os.path.join(SAVES_DIR, save_name)
    if os.path.exists(save_dir):
        shutil.rmtree(save_dir)
    os.makedirs(save_dir, exist_ok=True)
    with open(os.path.join(save_dir, DATA_FILE), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"导入存档成功: {save_name}")
    return len(data.get("people", data))


# （`cloud_backup` 原在这里 —— 全项目无调用方，且把所有谱牒备份到同一个
#   `FamilyTree/family.json` 会互相覆盖。2026-09-26 审查删除；设置页的
#   `cloud_backup_dir` 配置键保留，将来真做云备份时按谱名分文件。）
