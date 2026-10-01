"""config.json 读写。

与 ai_recognizer 共用同一个 config.json：读取时容错 BOM，写入时整体回写，
不认识的键原样保留，避免互相覆盖。
"""
import json
import logging
import os

logger = logging.getLogger(__name__)

CONFIG_FILE = "config.json"

# 默认值：只在内存里补齐，不主动写盘（首次启动选完主题才会落盘）
DEFAULTS = {
    "current_save": "",     # 当前谱牒档（saves/<名>）
    "current_record": "",   # 当前实录槽（Save_All_N 所在目录）—— 双层来源各记各的
    # 从「存档」对话框里移除掉的实录槽（槽名数组）。
    # ★ 2026-09-21 使用者要求「实录槽也应该可以让我删除…让我删除脚本的记录也可以」。
    #   这里只记**名单**，磁盘上的槽目录一个字节都不动 —— 想真删自己删文件夹即可，
    #   取消的办法是把槽名从这个数组里删掉。
    "hidden_slots": [],
    "quick_chars": "",
    "theme": "",            # 空字符串 = 用户还没选过主题 → 首次启动弹风格选择
    "view": "person",       # person | tree | world | table（timeline 已并入 tree+mode，见 family_mode）
    "node_style": "classic",  # 画布节点版式 classic 经典版 | card 竖向卡片式
    "cloud_backup_dir": "",
    "doubao_api_key": "",
    "deepseek_api_key": "",
    "deepseek_model": "deepseek-chat",
    # ★ 2026-09-23 筛选状态持久化：四个选项（当前宗支/隐藏非史/隐藏逝者/仅显所选）
    #   勾选后切页、重载都保持，除非再点一次取消。
    # ⚠️ 这里只放**勾选态**（界面偏好，跨谱牒保持才合理）。
    #   「选定名单（focused_people）」与「按支系隐藏名单（hidden_non_historical）」
    #   **曾经也在这里，2026-09-24 已搬走** —— 它们是内容、跟哪本书有关，
    #   放全局会串档（实测一份 34 人名单横跨 4 本书）。现在存进各谱牒的
    #   family.json，见 `app/storage.py` 的 `CANVAS_KEYS` 与模块头说明。
    # ★ 2026-09-26 审查修复（M9）：补上 `enrolled`（此前写 5 键、这里只有 4 键，
    #   首次启动时靠调用方 `.get("enrolled", True)` 兜底，行为对但两处不同步）；
    #   并删掉 `sidebar_y` —— 四十三批起侧栏滚动位置已改为「会话内保持 +
    #   侧栏自己算默认」，不再读写 config，这个键是残留（老档里的旧值会把
    #   新默认顶掉，正是当年删它的理由）。
    "filter_state": {"branch": False, "nohist": False, "dead": False,
                     "focus": False, "enrolled": True},
    # ★ 2026-09-23 家谱页签的显示模式：gen 代际（原家谱）/ time 时间（原时间轴）
    "family_mode": "gen",
    # ★ 2026-09-24 人物页现场 —— 跨启动只需这两项（看的是哪张表、按哪列排）。
    #   「搜索词」与「两处滚动位置」**故意不落盘**：第二天开还带着一个莫名其妙
    #   的搜索词反而迷惑；它们只在会话内保持（见 `main._person_state`）。
    #   `person_sort` 形如 ["_p:智略", true]，键是表头内部键，null = 没手动排过。
    "person_family": "",
    "person_sort": None,
}


def load_config():
    """读取配置；文件不存在或损坏时返回默认值副本。"""
    cfg = dict(DEFAULTS)
    if os.path.exists(CONFIG_FILE):
        try:
            # utf-8-sig：兼容记事本等编辑器保存时带 BOM 的配置文件
            with open(CONFIG_FILE, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            if isinstance(data, dict):
                cfg.update(data)
            else:
                logger.error("配置文件不是 JSON 对象，已忽略")
        except Exception as e:
            logger.error(f"读取配置文件失败: {e}")
    return cfg


def save_config(config):
    """整体写回配置文件。"""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"保存配置文件失败: {e}")
        return False


def update_config(**kwargs):
    """读取 → 合并 → 写回，返回合并后的配置。"""
    cfg = load_config()
    cfg.update(kwargs)
    save_config(cfg)
    return cfg
