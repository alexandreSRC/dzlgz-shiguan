"""大周列国志 · 史馆 —— 应用装配层（M1）。

左手翻实录，右手修谱牒，中间一座桥。

两层分工（规划 §一）：
  **实录层**（青绿 · 只读）—— 游戏存档直读，来自「存档阅览器」；
              saveload / labels / xref / catalog / relations / profiles
  **谱牒层**（橙金 · 可编辑）—— family.json 修谱台，来自「家族树 v2.0」；
              storage / history / model / layout / timeline / bio

本层只做**装配与业务编排**，不画界面细节：
  app.contract 五页签契约   app.theme 主题令牌   app.views.shell 外壳三段式
  app.views.person_view 人物页（实录）  app.views.world_view 世界页（实录）
  app.views.tree_view / timeline_view / table_view（谱牒）
"""
import ctypes
import logging
import os
import sys
import tkinter as tk


def _set_app_user_model_id():
    """Windows：显式声明进程的 AppUserModelID —— **任务栏图标靠它**。

    ★ 2026-09-30 使用者：「**打包后的 exe 怎么没在任务栏显示我给的那个图标？**」
      真因：`root.iconbitmap()` 只设**窗口图标**（标题栏左上角那个）；
      **任务栏**用的却是进程的 AppUserModelID —— 不声明的进程会被 Windows
      归到「python.exe」（或打包器的解包进程）那一组，任务栏便显示它们的图标，
      右键菜单还会出现"固定到任务栏"认不出自己人这类怪象。
      ⇒ 声明一个专属 ID，任务栏才用 exe 的图标、并且分组独立。

    ⚠️ 必须**尽早**调用（`tk.Tk()` 之前）—— 窗口一旦创建，归属就定了。
    """
    if os.name != "nt":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "Shiguan.DazhouLieguozhi.Shihguan.2")
    except Exception:                                  # noqa: BLE001
        pass          # 失败不致命：仅任务栏图标/分组退回系统默认，程序照常用

# ★ 2026-09-26 DPI 感知（使用者 150% 缩放实测发虚）：必须是**第一条** app 导入
#   —— theme/timeline/popcard 等模块的像素常量在导入时就按实测缩放系数换算，
#  晚于它们导入就吃不到 1.5× 了。详见 app/dpi.py 模块头。
from app import dpi as _dpi_mod
_dpi_mod.init()

from app import WINDOW_SIZE, WINDOW_TITLE, VIEW_KEYS
from app import bio as bio_mod
from app import model, storage
from app import saveload as S
from app.config import load_config, update_config
from app.contract import (APP_NAME, DEFAULT_VIEW, RECORD_BASES, VIEWS,
                          VIEW_LABEL)
from app.history import History
from app.theme import DEFAULT_THEME, get_theme
from app.views import shell as shell_mod
from app.views.person_view import PersonView
from app.views.table_view import TableView
from app.views.timeline_view import TimelineView
from app.views.tree_view import TreeView
from app.views.world_view import WorldView
from app.widgets import msgbox
from app.widgets.kit import apply_ttk_style

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
    RESOURCE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    RESOURCE_DIR = BASE_DIR
os.chdir(BASE_DIR)

LOG_FILE = "shiguan.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8", mode="w"),
              logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


def _clamp_geometry(geom_str):
    """把记忆的「WxH」或「WxH+x+y」钳到工作区内（显示器换过也不破屏）。"""
    wh = str(geom_str).split("+")[0]
    try:
        w, h = (int(x) for x in wh.lower().split("x"))
    except Exception:
        return _fit_geometry(WINDOW_SIZE)
    wa_w, wa_h = _dpi_mod.workarea()
    if wa_w > 0:
        w, h = min(w, wa_w), min(h, wa_h)
    w, h = max(w, 400), max(h, 300)
    return f"{w}x{h}"


def _fit_geometry(size_str):
    """「1440x860」→ 按系统缩放放大并钳到工作区内的 geometry 串。

    ★ 2026-09-26 DPI：默认窗口是 **100% 缩放下的逻辑尺寸**，150% 屏上若原样
      交给 geometry()，窗口物理上会小一圈（四周留白、字大框挤）。
      放大后若比工作区还大（小屏），宁可钳到工作区 —— 跟旧版「破屏也显示」
      相比，钳制是更安全的选择。取不到工作区（返回 0）就不钳。
    """
    try:
        w, h = (int(x) for x in str(size_str).lower().split("x"))
    except Exception:
        return str(size_str)
    w, h = _dpi_mod.px(w), _dpi_mod.px(h)
    wa_w, wa_h = _dpi_mod.workarea()
    if wa_w > 0:
        w, h = min(w, wa_w), min(h, wa_h)
    return f"{w}x{h}"


class ShiguanApp:
    """史馆主控制器：装配外壳 + 编排两层。"""

    def __init__(self, root):
        logger.info("初始化大周列国志 · 史馆")
        self.root = root
        # ★ 2026-09-26 DPI：逻辑窗口 1440×860 按实测缩放放大（150% → 2160×1290
        #   物理像素），并**钳到工作区内** —— 小屏上宁可小一点也不许破屏；
        #   minsize 同理钳制（否则 minsize 比屏幕还大时窗口收不小）。
        self.root.geometry(_fit_geometry(WINDOW_SIZE))
        self.root.title(WINDOW_TITLE)
        _wa = _dpi_mod.workarea()
        self.root.minsize(min(_dpi_mod.px(1180), _wa[0] or _dpi_mod.px(1180)),
                          min(_dpi_mod.px(680), _wa[1] or _dpi_mod.px(680)))
        icon = os.path.join(RESOURCE_DIR, "app_icon.ico")
        if os.path.exists(icon):
            try:
                self.root.iconbitmap(icon)
            except Exception as e:
                logger.warning(f"加载图标失败: {e}")

        self.cfg = load_config()
        # ★ 2026-09-26 使用者要求「一打开默认就是我上次那么大」：记住上次窗口
        #   尺寸（win_geom），首次启动用默认 1440x860 逻辑尺寸；都要钳工作区。
        #   ⚠️ 必须在 cfg 装载**之后**（首版放 geometry 处，启动即 AttributeError）。
        saved_geom = str(self.cfg.get("win_geom") or "")
        if saved_geom:
            self.root.geometry(_clamp_geometry(saved_geom))

        # ★ 2026-09-23 老档迁移：`view: timeline`（独立时间轴页签）已取消，
        #   并入「家谱」页签 → 迁移成 view=tree + family_mode=time。
        #   `view=tree` 已是新格式，不动（family_mode 可能有它自己的值）。
        if self.cfg.get("view") == "timeline":
            self.cfg = update_config(view="tree", family_mode="time")
        self.family_mode = str(self.cfg.get("family_mode") or "gen")
        if self.family_mode not in ("gen", "time"):
            self.family_mode = "gen"

        # ---------------- 谱牒层状态（可编辑）----------------
        self.people = {}
        self.current_save = ""
        self.cutoff_person = None
        # ★ 2026-09-23 筛选状态持久化：从 config 恢复四个选项 + 仅显所选名单，
        #   勾选后切页/重载都保持，除非再点一次取消。
        # ★ 2026-09-24 使用者第 9 问：「其他存档的选定人物和入谱是不是跟到
        #   我这个存档里来了？」—— **选定名单串了**（原来存在全局 config.json，
        #   实测那份 34 人名单横跨 4 本书、还有 12 人属于已删掉的档）。
        #   经拍板改成**按谱牒存**（family.json，与「入谱」标同一处），
        #   所以这里只给个空壳，真值由 `load_data()` → `_load_canvas_state()` 填。
        self.hidden_non_historical = {}
        # ★ 2026-09-24 使用者报「勾了隐藏非史画布不变化、非史角色还存在」：
        #   原来「隐藏非史」只在**恰好选中了节点**时才动手（把该节点的始祖记进
        #   `hidden_non_historical`），没选中就什么都不发生，勾选态却照样持久化 ——
        #   读起来像全局开关，实际是「按当前选中者的始祖隐藏」。
        #   现在拆成两个各司其职的东西：
        #     `hide_nohist_all`      —— 侧栏「隐藏非史」勾选框 = **全局开关**
        #                               （勾上隐藏全部非史实人物，取消全部恢复）
        #     `hidden_non_historical` —— 右键菜单「隐藏非史实后裔」= 按支系的精细控制
        self.hide_nohist_all = bool((self.cfg.get("filter_state") or {})
                                    .get("nohist", False))
        self.hide_dead = bool((self.cfg.get("filter_state") or {}).get("dead", False))
        self._branch_only = bool((self.cfg.get("filter_state") or {}).get("branch", False))
        self.focused = []                 # 选定名单（按谱牒存，见上）
        self._focus_set_cache = None      # 高亮集合缓存（见 focus_set）
        self._focus_set_key = None        # 缓存对应的 people 身份（换档自动重算）
        self._enrolled_cache = None       # 「已入谱」集合缓存（见 enrolled_set）
        self._enrolled_key = None
        # ★ 2026-09-23 画布默认只画「点名过的人」（入谱 / 加入族谱），想全看就勾掉
        self.enrolled_only = bool((self.cfg.get("filter_state") or {})
                                  .get("enrolled", True))
        self.focus_only = bool((self.cfg.get("filter_state") or {}).get("focus", False))
        # ★ 2026-09-23 侧栏滚动位置改为「会话内保持」：启动时一律用侧栏自己
        #   算出的默认（「当前宗支」贴顶，见 Sidebar.default_scroll_y），
        #   切页时由 _clear_side 记住、重建后恢复；**不再从 config 读**，
        #   因为老档里存的是「滚到底部区」那个已废弃的默认值，读它会顶掉新默认。
        self._sidebar_y = None
        # ★ 2026-09-24 人物页现场：跨启动的两项（看哪张表 / 按哪列排）从 config
        #   起手，其余三项（搜索词、表格与导航的滚动）只在本会话内保持。
        #   切页时由 `_remember_view_state()` 存、`restore_person_view()` 恢复 ——
        #   照 `_sidebar_y` 的老办法（内存保持），因为 `_build_main_view` 会把
        #   主区控件整批销毁重建，人物页实例连同它的现场一起没了。
        self._person_state = {
            "family": str(self.cfg.get("person_family") or ""),
            "sort": self.cfg.get("person_sort") or None,
            "search": "",
            "table_y": 0.0,
            "nav_y": 0.0,
        }
        # ★ 2026-09-24 「从人物页双击跳来家谱页」的标记 —— 只有它为真时，家谱页
        #   才显示「← 返回人物页」。时间轴内部双击跳代际**不设**它（那不是从
        #   人物页来的，凭空冒出返回按钮反而莫名其妙）。
        self._return_to_person = False
        self.selected_node = None
        self.newly_added = set()
        self._updating = False
        self.detector = None
        self.quick_chars = self.cfg.get("quick_chars", "")
        self._saved_at = ""
        self._last_search = ""
        self._extend_last = {}         # 上一次续谱实际写到了哪部谱牒（对话框写回时引用）

        # ---------------- 实录层状态（只读）----------------
        self.record_slot = None        # saveload.SaveSlot | None
        self.record_slots = []         # 候选实录槽目录（给界面挑的，不含被「移除」的）
        self.all_record_slots = []     # 全部实录槽（含被「移除」的）—— 自动配对用这个
        self.record_rel = None         # relations.RelationGraph
        self.record_xref = None        # xref.XRef
        self.record_people = {}        # code → profiles.Profile（派生）
        self.record_hist = 0           # 其中史实人物数量（派生）
        self.record_era = "上古"       # 剧本（决定族域码表）
        self.record_derived = False    # 合并总表是否已推导过（重建视图时复用）

        storage.ensure_saves_dir()
        self._init_save_system()
        self.load_data()

        self.history = History(self._apply_history_state)
        self.history.record("初始化史馆", self.people, self.cutoff_person)

        self.theme = get_theme(self.cfg.get("theme") or DEFAULT_THEME)
        # ★ 实录层要**在视图之前**载入 —— 默认页签可能是表格/家谱，
        #   那些页不会建 PersonView，靠视图 `_autoload` 就永远载不进实录。
        self._autoload_record()
        self._build_ui()
        # ★ 快捷键交给 `_install_hotkeys` 统一装（在 `_build_main_view` 末尾，
        #   每次重建视图都重绑一遍）。原先这里只 bind 了 Ctrl+Z/Y 四条，
        #   只绑 root 一层会被输入框的 class binding 吃掉 —— 详见 HOTKEYS 注释。
        self._init_detector()
        self._refresh_all()
        self.root.protocol("WM_DELETE_WINDOW", self.quit_app)

        # 首启动不再弹主题框 —— 默认宣纸（DEFAULT_THEME），想换在「设置」里选，
        # 或用 Ctrl+T。弹窗只在第一次启动出现，反而像个拦路的门槛。
        logger.info("史馆初始化完成")

    def _slot_owner_map(self):
        """槽名 → 已经绑了它的谱牒名（读所有谱牒的 `source`）。

        ★ 用途：`_slot_for_save` 的兜底要尽量做到**一一对应** ——
          一个实录槽只配一部谱牒。已经名花有主的槽，除非就是本谱牒绑的，
          否则不当候选。
        """
        out = {}
        try:
            names = storage.list_saves()
        except Exception:
            return out
        for nm in names:
            try:
                src = storage.load_source(nm) or {}
            except Exception:
                continue
            for key in ("slot", "slot_path"):
                v = str(src.get(key) or "").strip()
                if v:
                    out.setdefault(os.path.basename(v), nm)
        return out

    def _slot_year(self, path):
        """槽 → 存档当前年份（只读两个小文件）。读不出返回 None。"""
        from tools import import_from_game as IM
        try:
            return IM.detect_start_year(path)
        except Exception:
            return None

    # ================================================================ 谱牒层
    def _slot_for_save(self, name):
        """★ 一份谱牒该配哪个实录槽 —— 「一一对应」的落地点（使用者第 7 问）。

        判据优先级：
          ① 谱牒自带的 `source.slot_path` / `source.slot`（导入时写进去的，
             最准 —— 这就是「这份谱是从哪一槽归纳出来的」）。
             槽被删掉又重拉、只要**槽名没变**，这里照样能对上；
             游戏写到别的槽号（槽名变了）就配不上了 —— 那时用「存档」对话框里的
             「绑定到选中槽」手动对一次即可，**不需要重新抽取**。
          ② **按剧本配**（★ 2026-09-21 拿到使用者的剧本表之后才做得成）：
             从谱牒名认出剧本（《秦末起义·史实》→ 秦末起义 = 前 209），
             再找存档年份落在该剧本区间内的槽；优先挑**还没被别的谱牒绑走**的。
          ③ 兜底：按两档粗判（上古 / 秦末）找第一个能读的槽。
          ④ 都没有 → 返回 ""，调用方保持当前槽不动（不硬猜）。

        返回槽目录绝对路径，或 ""。
        """
        if not name:
            return ""
        src = {}
        try:
            src = storage.load_source(name)
        except Exception:
            src = {}
        for key in ("slot_path", "slot"):
            v = (src.get(key) or "").strip()
            if not v:
                continue
            if os.path.isdir(v):
                return v
            # 只有槽名（"Save_All_1"）→ 到候选里找同名的
            for p in self.record_slots:
                if os.path.basename(p) == v:
                    return p

        # ② 按剧本配
        from app import scenarios as SC
        from tools import sync_from_mumu as SM
        scen = SC.match_name(name)
        start = SC.start_year_of(scen)
        if start is not None:
            nxt = min([s for _m, _g, _n, s in SC.SCENARIOS if s > start] or [10 ** 9])
            owners = self._slot_owner_map()
            hits, free = [], []
            # ★ 用**全量**槽（含被「移除」的）—— 移除只是不列给使用者挑，
            #   不代表这个槽不能配。用 `record_slots` 会漏配（实测踩过）。
            for p in (getattr(self, "all_record_slots", None) or self.record_slots):
                y = self._slot_year(p)
                if y is None or not (start <= y < nxt):
                    continue
                hits.append(p)
                if owners.get(os.path.basename(p), name) == name:
                    free.append(p)
            pick = free or hits
            if pick:
                # 同名槽里挑号最小的，结果稳定（不随目录扫描顺序变）
                return sorted(pick, key=lambda x: SM.slot_number(os.path.basename(x)))[0]

        # ③ 两档粗判兜底（老档没有 source 时走这条）
        want = ""
        if any(k in name for k in ("秦末", "楚汉", "起义", "始皇", "秦")):
            want = "秦末"
        elif any(k in name for k in ("上古", "先民", "文王", "方国", "三皇")):
            want = "上古"
        if want:
            # ★ 代码改进 B1（2026-09-22）：兜底不再整档解析 —— SaveSlot.load()
            #   0.6s/槽 × N 槽最坏要 6 秒；detect_era 只读两个小文件，判定同源同果。
            from tools import import_from_game as IM
            for p in (getattr(self, "all_record_slots", None) or self.record_slots):
                try:
                    if IM.detect_era(p) == want:
                        return p
                except Exception:
                    continue
        return ""

    def bind_save_to_record(self, name, force=False):
        """切谱牒时把实录层同步过去（一一对应）。

        `force=False` 时：若谱牒没带来源信息、也配不上，就**什么都不做**
        —— 宁可不同步，也不要随便把别人的实录换掉。
        """
        path = self._slot_for_save(name)
        if not path:
            return False
        cur = self.record_slot.root if self.record_slot is not None else ""
        if not force and cur and os.path.normcase(cur) == os.path.normcase(path):
            return False
        return self.open_record(path)

    def _autoload_record(self):
        """启动时自动载入**当前谱牒所对应**的实录槽（只读层）。

        顺序：先看当前谱牒带了哪一槽（`source`），其次用下面的兜底。
        找不到或读不了都**不报错、不弹窗** —— 谱牒层可以单独用。
        默认页签不是「人物」时，这一步是实录层唯一的载入时机。
        """
        # ① 当前谱牒自己记着的来源槽（最准）
        path = ""
        # ★ 先把候选槽扫出来 —— 原来只在「兜底找槽」那条分支里扫，
        #   走 ①（谱牒自带 source）时 `record_slots` 一直是空的，
        #   于是「存档」对话框里的实录槽列表空着。扫目录很便宜，一开始就扫。
        self.scan_record_slots()
        if self.current_save:
            path = self._slot_for_save(self.current_save)
        # ② 上次用过的槽
        if not (path and os.path.isdir(path)):
            p = self.cfg.get("current_record") or ""
            if p and os.path.isdir(p):
                path = p
        # ③ 第一个可用的槽
        if not path:
            slots = self.scan_record_slots()
            path = slots[0] if slots else ""
        if not path:
            logger.info("没有可用的实录槽 —— 只跑谱牒层")
            return False
        ok = self.open_record(path)
        if not ok:
            logger.warning(f"自动载入实录槽失败（跳过）：{path}")
        return ok

    def _init_save_system(self):
        last = self.cfg.get("current_save", "")
        if last and os.path.exists(storage.save_path(last)):
            self.current_save = last
        else:
            saves = storage.list_saves()
            self.current_save = saves[0] if saves else ""
        logger.info(f"当前谱牒档: {self.current_save or '(无)'}")

    def load_data(self):
        if not self.current_save:
            self.people = {}
            return
        try:
            people, cutoff = storage.load_save(self.current_save)
            self.people = people
            self.cutoff_person = cutoff
            self._load_followed()          # 续谱名单跟着谱牒走（存在 source.watch）
            self._load_canvas_state()      # ★ 选定名单 / 按支系隐藏名单也按谱牒走
            logger.info(f"谱牒档加载 {len(self.people)} 人 · "
                        f"续谱名单 {len(self.followed_codes())} 人 · "
                        f"选定名单 {len(self.focused)} 人")
            if model.normalize(self.people):
                logger.info("谱牒数据迁移完成，已保存")
                self.save_data()
        except Exception as e:
            logger.error(f"加载谱牒档失败: {e}")
            from app.widgets import msgbox as messagebox
            messagebox.showerror("错误", f"加载谱牒档失败：{e}")
            self.people = {}
        # ★ 换谱牒后重挂「谱牒总谱」：合并谱挂、非合并谱摘（见 _attach_book_table）
        self._attach_book_table()

    def _load_canvas_state(self):
        """从**当前谱牒**载入「选定名单」与「按支系隐藏名单」。

        ★ 2026-09-24：这两个名单原来是全局 config 键（换本书会串），
          现在跟「入谱」标一样存在本档的 family.json 里（见 storage 模块头）。
        ★ 顺手做一次自净：`focused` 里**不在本谱的人一律剔除** ——
          它们只可能来自以前「全局名单」时代别的书（实测那份 34 人名单里
          有 12 人属于早已删掉的《卫氏朝鲜》）。剔除后就不再有孤儿名字。
        """
        st = storage.load_canvas_state(self.current_save)
        self.focused = [n for n in (st.get("focused_people") or [])
                        if n in self.people]
        self.hidden_non_historical = {n: True
                                      for n in (st.get("hidden_non_historical") or [])
                                      if n in self.people}
        self._focus_set_cache = None

    def save_data(self):
        if not self.current_save:
            logger.warning("未设置谱牒档，跳过保存")
            return False
        try:
            storage.write_save(
                self.current_save, self.people, self.cutoff_person,
                canvas={"focused_people": list(self.focused),
                        "hidden_non_historical": [k for k, v in
                                                  self.hidden_non_historical.items() if v]})
            import time
            self._saved_at = time.strftime("%H:%M")
            return True
        except Exception as e:
            logger.error(f"保存谱牒档失败: {e}")
            return False

    def clear_all_states(self):
        """★ 2026-09-23 一键清除本谱牒档**所有人物**的封国信息。

        使用者原话：「这提取出来的信息已经乱了，给我出个一键清除存档所有人物
        封国信息的按钮」。封国（state_name / state_group / fief_gen）会混进
        「势力/出仕」（刘邦功臣 state_name=汉），清掉后重新续谱/抽取才会干净。
        只清封国相关字段，爵位（fief_title，手动锁定）与其他字段一律不动。
        危险批量动作 —— 先弹确认，再动笔。

        ★ 2026-09-24 使用者反馈：「只是把人物信息中的封国清空了，但是家谱里的
          世系框全部还留存着，需要同时把世系框清除」。查证：画布上的世系框是
          `layout._lineage_groups` 按 **`lineage_name`** 归组画的，清 `state_name`
          动不到它 —— 所以现在**连 `lineage_name` 一起清**，框才会跟着消失。
          （当年定「不清世系」是舍不得世系里的谥号，但谥号/尊号存在 `note`
          字段里，不在 `lineage_name` 里，清了不会丢。）
        """
        from app.widgets import msgbox as messagebox
        if not self.current_save:
            return False
        n = len(self.people)
        if not n:
            self.statusbar.set("hint", "谱牒无人，无可清除")
            return False
        if not messagebox.ask_danger(
                "清空封国",
                f"确定要清除《{self.current_save}》全部 {n} 个人的封国与世系吗？\n\n"
                "清除范围：封国 / 君序 / 世系（state_name、state_group、fief_gen、"
                "lineage_name）—— 家谱画布上的「X 世系」框会一并消失。\n"
                "爵位（手动设定的）与小传、尊号、族谱关系一律保留。\n"
                "清完可用「续谱」从实录槽重新抽取实证封国。",
                ok_text="清空", parent=self.root):
            return False
        self._record(f"清除全部封国（{n} 人）")
        cnt = 0
        for info in self.people.values():
            info["state_name"] = ""
            info["state_group"] = ""
            info["fief_gen"] = 0
            info["lineage_name"] = ""
            cnt += 1
        self.save_data()
        self._refresh_all()
        self.statusbar.set("hint", f"已清 {cnt} 人封国与世系（爵位与小传保留）")
        return True

    def switch_save(self, name):
        if not name or name == self.current_save:
            return
        self.current_save = name
        self.cfg = update_config(current_save=name)
        self.load_data()
        self.history.clear()
        self.history.record(f"切换谱牒档: {name}", self.people, self.cutoff_person)
        self.selected_node = None
        if getattr(self, "timeline", None) is not None:
            self.timeline.reset_scale()
        # ★ 谱牒 ↔ 实录 一一对应：换了谱牒，实录跟着换到它自己的来源槽。
        #   配不上就**保持不动**（宁缺勿猜），不硬塞一个别人的实录。
        synced = False
        try:
            synced = self.bind_save_to_record(name)
        except Exception as e:
            logger.warning(f"同步实录槽失败（不影响谱牒）: {e}")
        self._refresh_all()
        if synced and getattr(self, "statusbar", None) is not None:
            self.statusbar.set(
                "hint",
                f"已随谱牒《{name}》切到实录 {self.record_slot.name}"
                f"（剧本 {self.record_era}）")
        logger.info(f"切换到谱牒档: {name}" + ("（实录已同步）" if synced else ""))

    def quit_app(self):
        # ★ 2026-09-26：退出前记住窗口尺寸 + 侧栏拖拽位置
        try:
            sash = ""
            try:
                sash = int(self.pw.sash_coord(0)[0])
            except Exception:
                pass
            self.cfg = update_config(
                win_geom=self.root.geometry().split("+")[0],
                sidebar_sash=sash)
        except Exception:
            pass
        self.save_data()
        self.root.destroy()

    # ================================================================ 实录层
    def scan_record_slots(self):
        """扫描实录槽（只读）。找不到也不报错 —— 谱牒层可以单独用。

        ★ 2026-09-21：`hidden_slots` 里的槽**不列进 `record_slots`**（那是给界面挑的），
          但仍然收进 `all_record_slots` —— 「谱牒 ↔ 实录槽」的自动配对要用全量，
          否则使用者「移除」过某个槽之后，配对就再也找不到它了（实测踩过：
          5 个槽全被移除 → 存档对话框里一个槽都列不出来 → 切谱牒后实录不跟着换）。
        """
        from app import saveload as S
        hidden = {str(x) for x in (self.cfg.get("hidden_slots") or [])}
        self.record_slots = []
        self.all_record_slots = []
        for base in RECORD_BASES:
            for p in S.list_slots(base):
                if p not in self.all_record_slots:
                    self.all_record_slots.append(p)
                if os.path.basename(p) in hidden:
                    continue
                if p not in self.record_slots:
                    self.record_slots.append(p)

        def rank(p):
            try:
                n = len([f for f in os.listdir(p) if f.lower().endswith(".json")])
            except OSError:
                n = 0
            return (0 if n else 1, p.lower())

        self.record_slots.sort(key=rank)
        self.all_record_slots.sort(key=rank)
        return self.record_slots

    def hide_record_slot(self, path):
        """把一个实录槽从列表里移除（只记名单，不动磁盘）。

        使用者原话：「对于实录槽也应该可以让我删除，虽然可能删除不了实际游戏存档，
        但让我删除脚本的记录也可以」。所以这里删的是**脚本的记录**：
        槽名进 `config.json` 的 `hidden_slots`，之后 `scan_record_slots` 不再列它。
        想恢复：把槽名从 config.json 的 hidden_slots 里去掉。
        """
        name = os.path.basename(str(path or ""))
        if not name:
            return False
        hidden = [str(x) for x in (self.cfg.get("hidden_slots") or [])]
        if name not in hidden:
            hidden.append(name)
        self.cfg = update_config(hidden_slots=hidden)
        # 移除的正好是当前槽 → 顺手清掉记录，免得启动时又去载入它
        if self.record_slot is not None and \
                os.path.basename(self.record_slot.root) == name:
            self.record_slot = None
            self.cfg = update_config(current_record="")
        self.scan_record_slots()
        return True

    def delete_record_slot(self, path):
        """**彻底删除**一个实录槽：删掉本机缓存目录 + 从 hidden_slots 移除。

        与「移除选中槽」（只记名单、磁盘不动）相对 —— 使用者要求有删除就得有
        真正删文件的能力。只删**本机缓存**（`RECORD_BASES` 下的槽目录），
        **不动模拟器里的游戏存档**（那要进游戏自己删）。

        返回 (是否成功, 说明文字)。
        """
        import shutil
        name = os.path.basename(str(path or ""))
        # 只允许删 RECORD_BASES 下的槽目录，防止误删别的路径
        target = ""
        for base in RECORD_BASES:
            cand = os.path.join(base, name)
            if os.path.isdir(cand) and os.path.normcase(cand) == os.path.normcase(path):
                target = cand
                break
        if not target:
            return False, "没找到这个槽的本机缓存，没删任何东西。"
        try:
            shutil.rmtree(target)
        except Exception as e:
            return False, f"删缓存失败：{e}"
        # 删都删了，隐藏名单里也不留它
        hidden = [str(x) for x in (self.cfg.get("hidden_slots") or [])]
        if name in hidden:
            self.cfg = update_config(hidden_slots=[x for x in hidden if x != name])
        # 删的正好是当前槽 → 清掉记录
        if self.record_slot is not None and \
                os.path.basename(self.record_slot.root) == name:
            self.record_slot = None
            self.cfg = update_config(current_record="")
        self.scan_record_slots()
        return True, f"已彻底删除本机缓存 {name}（模拟器里的存档不受影响）"

    def unhide_record_slot(self, name):
        """把一个槽名从 `hidden_slots` 里放回来（重新拉取该槽后自动调）。

        ★ 为什么必须有这一步：`hidden_slots` 记的是**槽名**。使用者「移除」了
          Save_All_4001 之后，如果又从模拟器重新拉了一份同名的槽，
          它会被这条名单一直挡住、永远不出现 —— 于是「谱牒 ↔ 实录」的对应
          就断了（`_slot_for_save` 找不到同名槽，只能退化成「按剧本猜」）。
          所以**每次拉档落位之后**都要把它放回来。
        """
        name = os.path.basename(str(name or ""))
        if not name:
            return False
        hidden = [str(x) for x in (self.cfg.get("hidden_slots") or [])]
        if name not in hidden:
            return False
        hidden = [x for x in hidden if x != name]
        self.cfg = update_config(hidden_slots=hidden)
        self.scan_record_slots()
        return True

    def bind_save_slot(self, path):
        """把「当前谱牒」绑到指定的实录槽（只改 `source`，**不重抽、不合并**）。

        ★ 2026-09-21 使用者问：「删除存档槽以后，重新扫描模拟器得来的存档
          并不会跟原有的家谱存档一一对应，是这样的吗？是需要我点备份并写回才行的对吗？」
          答：对应关系记在谱牒的 `source.slot_path / slot` 里（槽名）。
          槽名没变 → 自动就对上了；槽名变了（游戏写到别的槽）→ 只能手动绑一次。
          **不需要「备份并写回」** —— 那是「重新抽取 + 合并」，会重写谱牒；
          这里只写两个来源字段，一个字节的人物数据都不动。
        """
        path = str(path or "")
        if not path or not os.path.isdir(path):
            return False
        if not self.current_save:
            return False
        ok = storage.set_source(self.current_save,
                                slot_path=path,
                                slot=os.path.basename(path))
        if not ok:
            return False
        self.cfg = update_config(current_record=path)
        self.open_record(path)
        return True

    def open_record(self, path):
        """载入一个实录槽（只读）。失败只影响实录层，不干扰谱牒层。"""
        from app import relations as R
        from app import saveload as S
        from app import xref as XR
        # 有状态栏就先挂个「载入中…」（启动早期状态栏还没建，跳过即可）
        sb = getattr(self, "statusbar", None)
        if sb is not None:
            sb.set("hint", f"载入中… {os.path.basename(path)}")
            # UI 改进 D16：update() 才会把「载入中…」真的画出来再进入阻塞
            # （update_idletasks 只处理几何，不重绘文字，提示等于没出）
            self.root.update()
        try:
            slot = S.SaveSlot(path).load()
        except Exception as e:
            self.record_slot = None
            logger.error(f"载入实录槽失败: {e}")
            return False
        self.record_slot = slot
        self.record_era = self._detect_era(slot)
        self.record_rel = R.RelationGraph.build(slot)
        self.record_xref = XR.XRef.build(slot)
        # ★ 派生表在**这里**推 —— 不依赖「人物」页被打开。
        #   默认页签是表格/家谱时，这一步是 record_people 唯一的来源。
        self.record_people, self.record_hist = self._derive(slot)
        self.record_derived = True
        self._attach_book_table()
        self.cfg = update_config(current_record=path)
        logger.info(f"实录槽载入：{slot.name} · {len(slot.tables)} 表族 · 剧本 {self.record_era}")
        return True

    def _merged_book(self):
        """磁盘上那部「全史总谱」（`source.merged = True` 的谱牒）→ (档名, people)。

        ★ 2026-09-29 使用者的新要求见 `_attach_book_table`。13.5k 人的解析
          只做一次，结果缓存在 `_merged_cache`。
        """
        if getattr(self, "_merged_cache", None) is not None:
            return self._merged_cache
        found = (None, None)
        for nm in storage.list_saves():
            try:
                if not (storage.load_source(nm) or {}).get("merged"):
                    continue
                people, _cut = storage.load_save(nm)
                if people:
                    found = (nm, people)
                    break
            except Exception as e:
                logger.warning(f"读合并谱 {nm} 失败（跳过）：{e}")
        self._merged_cache = found
        return found

    def _attach_book_table(self):
        """把「谱牒总谱」挂到人物页（当参考底本）。

        ★ 2026-09-25 使用者需求：总谱的一万多人要能在人物页查、看、跳家谱。
        ★ 2026-09-29 使用者：「**全谱就是作为参考文件的，是否可以始终显示在
          所有存档**以便于选定来做参考」—— 原逻辑只在**当前档本身是合并谱**
          （`source.merged`）时才挂，一切到《上古时代》这类普通谱就摘掉了。
          现在改成：**当前档不是合并谱时，改挂磁盘上那部全史总谱**，
          于是它在任何存档下都恒常可见，与当前档自己的「全部人物」并列，
          正好一左一右拿来对照。
          幂等：open_record / load_data 后都会调；确实找不到合并谱才摘掉。
        """
        from app import record_derive as RD
        src = {}
        if self.current_save:
            try:
                src = storage.load_source(self.current_save) or {}
            except Exception:
                src = {}
        # ① 当前档本身就是合并谱 → 挂它自己（原逻辑）
        own = bool(src.get("merged")) and bool(self.people)
        if own:
            book_save, book_people = self.current_save, self.people
        else:
            # ② 否则借全史总谱当参考底本（使用者 2026-09-29 要求恒常可见）
            nm, ppl = self._merged_book()
            if nm and ppl and nm != self.current_save:
                book_save, book_people = nm, ppl
            else:
                book_save, book_people = None, None
        if not book_people:
            if self.record_slot is not None:
                self.record_slot.tables.pop(RD.BOOK_NAME, None)
            self._rebuild_nav_after_book(RD.BOOK_NAME, keep=False)
            return
        # ★ 2026-09-26 使用者报「把实录槽删了，人物全没了」：谱牒总谱此前
        #   **搭在实录槽身上**，槽一删整页就空（谱牒数据本身好好的，家谱页
        #   照常）。现在无槽时造一个**只挂总谱**的轻量槽（root 只当显示名，
        #   不做任何磁盘操作；真实槽打开后自然被替换回去），人物页照常查总谱。
        created_shim = self.record_slot is None
        if created_shim:
            self.record_slot = S.SaveSlot("谱牒总谱（无实录）")
        RD.attach_book_table(self.record_slot, book_people,
                             label=book_save or "")
        # ★ 2026-09-26 使用者报「打开时间又变长了」：轻量槽下 record_people 为空
        #   —— 人物页每个单元格都现场 new 一个 Profile（13.5k 行 × 11 列 ≈ 15 万
        #   个对象），打开奇慢；列宽拟合也拿不到样本（塌成表头宽，生卒年被裁）。
        #   挂槽时把总谱 Profile **一次建好**，列宽/渲染/计数全走正轨。
        # ⚠️ 2026-09-29 起这个分支**不再只在轻量槽时走**：借全史总谱当参考时
        #   （`not own`）同样要预建，否则切到普通档后翻那一万多人会卡。
        if created_shim or not own:
            from app import profiles as PF
            try:
                era = (storage.load_source(book_save) or {}).get("era") \
                    or getattr(self, "record_era", None) or "上古"
            except Exception:
                era = getattr(self, "record_era", None) or "上古"
            rp = dict(self.record_people or {}) if not created_shim else {}
            # ⚠️ Profile 必须建在**总谱行**上（与单元格同源）—— 建在 family
            #   记录上会丢姓名（姓名在人名字典的键里，不在字段里）。
            for r in self.record_slot.tables[RD.BOOK_NAME].rows:
                code = str(r.get("Ren_Code") or "")
                if code and code not in rp:
                    rp[code] = PF.Profile(code, r, None, era)
            self.record_people = rp
            self.record_derived = True
        # ★ 2026-09-25 修：派生表变了，人物页导航必须跟着重建。
        #   原来不重建 —— 换到非合并谱后，导航里仍留着「谱牒总谱」那一行，
        #   表却已被摘掉，**点它直接 KeyError**。
        #   重建时**保住使用者的现场**：原表还在就留在原表，表没了才退回第一行。
        #   刚造的轻量槽 = 没有实录层，直接停到「谱牒总谱」上
        #   （否则会停在空的「合并总表」上，看起来像又全没了）。
        self._rebuild_nav_after_book(RD.BOOK_NAME,
                                     keep=bool(created_shim))

    def _rebuild_nav_after_book(self, book_name, keep=False):
        """挂完 / 摘完「谱牒总谱」后重建人物页导航，并保住使用者的现场。"""
        pv = getattr(self, "person_view", None)
        if pv is None or getattr(pv, "slot", None) is not self.record_slot:
            return
        want = book_name if keep else getattr(pv, "cur_family", None)
        pv._build_nav()
        hit = next((k for k, nm in pv._nav_index.items() if nm == want), None)
        if hit is not None:
            pv.nav.selection_set(hit)
        else:
            pv._select_first_family()

    def _derive(self, slot, followed=None):
        """推导人物派生视图（合并总表 + 史实筛分）。谱牒层关注世系也走这里。"""
        from app import record_derive as RD
        return RD.derive(slot, self.record_rel, self.record_xref,
                         self.record_era, followed=followed or set())
    def refresh_record_derive(self, followed=None):
        """关注世系变了 → 重推派生表（只动派生表，不重读存档）。"""
        if self.record_slot is None:
            return
        self.record_people, self.record_hist = self._derive(self.record_slot, followed)
        self.record_derived = True

    def followed_codes(self):
        """续谱名单（★ 点名要收的那些人）。

        ★ 落盘在谱牒的 `source.watch` 里 —— 存在 family.json 内，**重启不丢**，
        导出 / 复制谱牒时名单也跟着走。
        （原来只放内存 `self._followed`，关掉软件就清空，实测过。）
        """
        return set(getattr(self, "_followed", ()))

    def _load_followed(self):
        """从当前谱牒的 `source.watch` 读回名单（换谱牒 / 载入数据时调）。"""
        codes = set()
        if self.current_save:
            try:
                src = storage.load_source(self.current_save) or {}
                codes = {str(c) for c in (src.get("watch") or []) if str(c)}
            except Exception:
                codes = set()
        self._followed = codes
        return codes

    def set_followed_codes(self, codes):
        self._followed = {str(c) for c in codes if str(c)}
        if self.current_save:
            try:
                storage.set_source(self.current_save, watch=sorted(self._followed))
            except Exception as e:
                logger.warning(f"续谱名单落盘失败（不影响本次使用）：{e}")
        self.refresh_record_derive(self._followed)

    @staticmethod
    def _detect_era(slot):
        """判断存档属于哪个剧本 —— 决定 `Ren_Zu_Yu` 用哪套族域码表。

        ★ 代码改进 C1（2026-09-22）：判据唯一实现在 `app/era.py` —— 此前与本文件、
          `tools/import_from_game.detect_era` 各持一份，注释自认「改一处要改两处」。
          本方法只负责把 SaveSlot 的三张表读成行列表交给 `era_of`。
          关键认知（151 国阶段同时代并存、四级判据）见 era.py 模块头。
        """
        from app import era as ERA
        if slot is None:
            return "上古"
        wc = slot.table("Save_Wang_Chao_Data")
        rec = slot.table("Save_KingData/King_Stage_Record")
        kd = slot.table("Save_KingData")
        return ERA.era_of(
            wc.rows if wc else [],
            rec.rows if rec else [],
            kd.rows if kd else [],
        )

    def record_count(self):
        """实录层当前有多少人（状态栏用）。

        实录页视图会被切走 —— 切走后 `person_view` 是 None。
        所以先从视图问，问不到就退回主控制器缓存的 `record_people`
        （这样「实录 9106」这个数字在五个页签下都稳定显示）。
        """
        pv = getattr(self, "person_view", None)
        if pv is not None:
            n = pv.count_people()
            if n:
                return n
        return len(self.record_people) or None

    # ================================================================ 界面
    def _build_ui(self):
        theme = self.theme
        for child in self.root.winfo_children():
            if isinstance(child, tk.Toplevel):
                continue
            child.destroy()
        # ★ 2026-09-26 修（_m1_accept 抓到的存量 bug）：上面 destroy 之后，
        #   `self.statusbar` 仍指着**已销毁的旧状态栏**（Python 对象还在）。
        #   `_build_main_view` 里 `table.refresh() → counter_cb → _set_gen_stat`
        #   会对它 `.set()` ⇒ `TclError: invalid command name` —— 换主题必炸
        #   （89 批引入统计句后的 rebuild 场景没人验过）。置 None 让
        #   `_set_gen_stat` 的守卫真正生效；新状态栏在本函数末尾重建。
        self.statusbar = None
        self.root.configure(bg=theme.bg_app)
        apply_ttk_style(self.root, theme)
        # ★ 主题化弹窗（UI 改进 B5）：把主题挂在 root 上并注册兜底，
        #   msgbox 从任意控件链向上都能找到当前主题
        self.root._shiguan_theme = theme
        msgbox.bind(self.root, theme)

        callbacks = {
            "switch_view": self.switch_view,
            "open_archive": self.open_archive,
            "extend": self.extend_book,
            "settings": self.open_settings,
        }
        self.view_key = self.cfg.get("view", DEFAULT_VIEW)
        if self.view_key not in VIEW_KEYS:
            self.view_key = DEFAULT_VIEW
        self.topbar = shell_mod.TopBar(
            self.root, theme, callbacks, view=self.view_key,
            record_name=self.record_slot.name if self.record_slot else "",
            book_name=self.current_save,
            theme_name=theme.name)
        self.topbar.pack(fill=tk.X)

        body = tk.Frame(self.root, bg=theme.bg_app)
        body.pack(fill=tk.BOTH, expand=True)
        self.body = body

        # 侧栏随页签切换 —— 由各视图自己提供（实录页用阅览器那套卡片，
        # 谱牒页用家族树那套表单）。
        # ★ 2026-09-26 使用者要求侧栏边界**可拖拽**：定宽 Frame 换成
        #   水平 PanedWindow（拖中间分隔条调宽窄），位置记进 config。
        self.pw = tk.PanedWindow(
            body, orient=tk.HORIZONTAL, sashwidth=6, bg=theme.border_2,
            sashpad=0, sashrelief=tk.FLAT)
        self.pw.pack(fill=tk.BOTH, expand=True)
        self.side_host = tk.Frame(self.pw, bg=theme.bg_panel)
        self.main_area = tk.Frame(self.pw, bg=theme.bg_app)
        self.pw.add(self.side_host, minsize=230, width=theme.sidebar_w,
                    stretch="never")
        self.pw.add(self.main_area, minsize=420, stretch="always")
        # ★ 2026-09-28 使用者报「人物bar 左沿能不能跟代际对齐」——
        #   侧栏可拖拽 ⇒ 主区左缘 = 侧栏宽 + `sashwidth`，拖完要重新同步顶栏
        #   品牌区宽度，页签左缘才会一直贴着画布左缘。
        self.pw.bind("<ButtonRelease-1>",
                     lambda e: self._sync_brand_width(), add="+")
        # 窗口缩放 / 布局变化时也要重同步（PanedWindow 会重新分配宽度）
        self.root.bind("<Configure>",
                       lambda e: self._sync_brand_width(), add="+")
        self.side_host.pack_propagate(False)
        _saved_sash = self.cfg.get("sidebar_sash")
        if _saved_sash:
            try:
                self.pw.after(120, lambda: self.pw.sash_place(
                    0, int(_saved_sash), 0))
            except Exception:
                pass

        self._build_main_view()

        self.statusbar = shell_mod.StatusBar(self.root, theme)
        self.statusbar.pack(side=tk.BOTTOM, fill=tk.X)

    def _clear_side(self):
        # ★ 2026-09-23 切视图前记住侧边栏滚动位置（默认底部区，见 config.sidebar_y）
        sb = getattr(self, "sidebar", None)
        if sb is not None and hasattr(sb, "canvas"):
            try:
                self._sidebar_y = sb.canvas.yview()[0]
            except Exception:
                pass
        for w in self.side_host.winfo_children():
            w.destroy()

    # ---------------------------------------------------------------- 人物页现场
    def _remember_view_state(self):
        """切视图 / 重建之前，把人物页的现场记下来。

        ★ 2026-09-24：`_build_main_view` 会 `destroy()` 主区全部控件，人物页
          实例连同 `cur_family / search_var / sort_key / 两处滚动` 一起消失 ——
          这就是使用者说的「跳转打断现场」。照 `_sidebar_y` 的老办法：销毁前
          存进内存，重建后由 `restore_person_view()` 应用回去。
          「表族」与「排序」额外落 config（跨启动还停在上次那处）；搜索词与
          滚动位置**故意不落盘**（第二天开带着一个莫名其妙的搜索词更迷惑）。
        """
        pv = getattr(self, "person_view", None)
        if pv is None or self.view_key != "person":
            return
        st = self._person_state
        try:
            if pv.cur_family:
                # ★ 轻量谱牒槽不回写 person_family —— 别把使用者在真实槽上的
                #   停靠位置冲掉（无实录只是临时状态）。
                if "谱牒总谱（无实录）" in str(getattr(pv.slot, "root", "")):
                    return
                st["family"] = pv.cur_family
            st["sort"] = [pv.sort_key, bool(pv.sort_desc)] if pv.sort_key else None
            st["search"] = pv.search_var.get()
            st["table_y"] = float(pv.table.yview()[0])
            st["nav_y"] = float(pv.nav.yview()[0])
        except Exception:
            return
        self.cfg = update_config(person_family=st["family"], person_sort=st["sort"])

    def restore_person_view(self, pv):
        """人物页备好之后把现场应用回去；没存过就退回「选第一张表」。

        顺序有讲究：`nav.selection_set()` 会触发 `_on_nav`，而 `_on_nav` 自己
        会把排序清掉、搜索框清空 —— 所以**表族先切，排序与搜索后设**。
        """
        st = self._person_state or {}
        kids = pv.nav.get_children()
        if not kids:
            return
        want = str(st.get("family") or "")
        # ★ 2026-09-26 轻量「谱牒总谱」槽：无条件停总谱 —— 残留现场可能是
        #   空的「合并总表」，落上去像又全没了。
        if "谱牒总谱（无实录）" in str(getattr(pv.slot, "root", "")):
            want = "人物 · 谱牒总谱"
        target = None
        for kid in kids:
            if pv._nav_index.get(kid) == want:
                target = kid
                break
        if target is None:
            # ★ 2026-09-26 无实录槽（轻量「谱牒总谱」槽）时首选总谱 ——
            #   第一张是空的「合并总表」，落上去看着像又全没了。
            if "谱牒总谱（无实录）" in str(getattr(pv.slot, "root", "")):
                for kid in kids:
                    if pv._nav_index.get(kid) == "人物 · 谱牒总谱":
                        target = kid
                        break
        if target is None:
            target = kids[0]              # 没存过 / 存的表族不在本槽 → 第一张
        pv.nav.selection_set(target)
        pv.nav.see(target)
        if pv.cur_family is None:         # 同值选中不触发事件时兜底
            pv.cur_family = pv._nav_index.get(target)
        srt = st.get("sort")
        if srt:
            pv.sort_key, pv.sort_desc = srt[0], bool(srt[1])
        pv.search_var.set(str(st.get("search") or ""))
        pv._apply_filter()                # 上面几处 set 未必都触发 trace，补一次
        # 滚动位置要等控件真正布局过才吃得准，所以推迟到 idle 之后
        self.root.after_idle(lambda: self._apply_person_scroll(pv))

    def _apply_person_scroll(self, pv):
        """把人物页两处滚动位置挪回去（延迟执行，控件可能已被销毁）。"""
        if getattr(self, "person_view", None) is not pv:
            return
        st = self._person_state or {}
        for widget, key in ((pv.table, "table_y"), (pv.nav, "nav_y")):
            try:
                y = max(0.0, min(1.0, float(st.get(key) or 0.0)))
                widget.yview_moveto(y)
            except Exception:
                pass

    def book_name_of_code(self, code):
        """按存档编号在谱牒里反查人名 —— 跳转的锚点是 code，不是姓名。

        谱牒里的人名可能与实录不同（重名要加中文序数、使用者还会手改），
        所以一律走编号。找不到返回 None。
        """
        code = str(code or "")
        if not code:
            return None
        for name, rec in (self.people or {}).items():
            if str((rec or {}).get("code") or "") == code:
                return name
        return None

    def on_sidebar_ready(self, sidebar):
        """Sidebar 构建完成后调用：恢复四个筛选 chip 的选中态 + 侧边栏滚动位置。"""
        try:
            st = self.cfg.get("filter_state") or {}
            sidebar.chips.set_state("branch", bool(st.get("branch", self._branch_only)))
            sidebar.chips.set_state("nohist", bool(st.get("nohist", self.hide_nohist_all)))
            sidebar.chips.set_state("dead", bool(st.get("dead", self.hide_dead)))
            # ★ 2026-09-23「仅显入谱」与「仅显所选」已合并到**同一行同一个
            #   ChipRow**（`sidebar.chips_focus` 同时管两个键），所以两次
            #   set_state 都打在同一实例上。
            if hasattr(sidebar, "chips_focus"):
                sidebar.chips_focus.set_state(
                    "enrolled", bool(st.get("enrolled", True)))
                sidebar.chips_focus.set_state("focus", bool(st.get("focus", self.focus_only)))
                sidebar.set_focus_btn(self.focus_only)
            # 画布为空时给一句指引 —— 新档续谱后史实角色全都没有入谱标，
            # 一打开会看到空画布，不说明会以为坏了。
            if self.enrolled_only and not self.enrolled_set():
                self.statusbar.set(
                    "hint", "画布为空 · 人物页点「入谱」或「加入族谱」即上画布")
        except Exception:
            pass
        try:
            saved = getattr(self, "_sidebar_y", None)
            # ★ 2026-09-23 默认位置改成「『当前宗支』顶到侧栏最上沿」：
            #   没存过（首次启动）就让侧栏按实际布局自己算；存过（用户手动滚过）
            #   就照旧恢复。算默认值必须等布局就绪，所以放在 _go 里而不是这里。
            y = None if saved is None else max(0.0, min(1.0, saved))

            def _go(cv, yy, sb):
                try:
                    parts = cv.cget("scrollregion").split()
                    if len(parts) == 4 and float(parts[3]) > 10:
                        cv.yview_moveto(sb.default_scroll_y() if yy is None else yy)
                    else:
                        cv.after(80, lambda: _go(cv, yy, sb))
                except Exception:
                    pass
            sidebar.canvas.after(60, lambda: _go(sidebar.canvas, y, sidebar))
        except Exception:
            pass

    def _persist_filter_state(self):
        """把四个筛选**勾选态**写回 config（切页/重载后保持）。

        ★ 2026-09-24：这里**不再写**「选定名单 / 按支系隐藏名单」——
          那两个是**内容**（跟哪本书有关），已改成按谱牒存（`save_data`）。
          留在 config 里的只会串到别的书去（使用者第 9 问）。
          勾选态（开关本身）是界面偏好，跨书保持才合理，继续放 config。
        """
        try:
            self.cfg = update_config(
                filter_state={
                    "branch": bool(self._branch_only),
                    "nohist": bool(self.hide_nohist_all),
                    "dead": bool(self.hide_dead),
                    "focus": bool(self.focus_only),
                    "enrolled": bool(self.enrolled_only),
                },
            )
        except Exception as e:
            logger.warning(f"保存筛选状态失败: {e}")

    def _persist_canvas_state(self):
        """把「选定名单 / 按支系隐藏名单」写进**当前谱牒**（family.json）。

        只在名单真的变了时调 —— 写盘要序列化整本谱牒，别夹在勾选框点击里。
        """
        if not self.current_save:
            return
        self.save_data()

    def _build_main_view(self):
        # ★ 2026-09-24 销毁主区之前先记住人物页的现场（照 _sidebar_y 的老办法）。
        #   人物页实例马上要被 destroy 掉，这是它最后一次能被读到的时机。
        self._remember_view_state()
        for w in self.main_area.winfo_children():
            w.destroy()
        self._clear_side()
        # 统计句不用在这里清：它在**状态栏**（常驻），而 `_refresh_all` →
        # `_update_status` 每次都会按当前页重写 `gen` 格（★ 2026-09-26）。
        theme = self.theme
        self.view_key = self.cfg.get("view", DEFAULT_VIEW)
        holder = tk.Frame(self.main_area, bg=theme.bg_canvas)

        self.tree = self.table = self.timeline = None
        self.person_view = self.world_view = None
        key = self.view_key
        overflow = []                    # UI 改进 C11：低频命令收纳进「⋯」溢出菜单
        mode_seg = None                  # 家谱页两种模式的切换段（其余页签不显示）
        groups = []                      # 工具栏分组（组间竖线，组名不显示）

        if key == "person":
            self.person_view = PersonView(holder, self.side_host, theme, self)
            groups = self.person_view.toolbar_groups()
            self.sidebar = None          # 实录页侧栏由 PersonView 自己建、自己刷

        elif key == "world":
            self.world_view = WorldView(holder, self.side_host, theme, self)
            groups = self.world_view.toolbar_groups()
            self.sidebar = None

        elif key == "table":
            self.sidebar = shell_mod.Sidebar(self.side_host, theme, self)
            self.sidebar.pack(fill=tk.BOTH, expand=True)
            self.table = TableView(holder, theme, self)
            # ★ 2026-09-23 分组：视图（灰·看）→ 编辑（橙金·写谱牒）→ 危险（红·删）
            groups = [
                ("视图", [
                    ("expand", "展开", self.table.expand_all, "tool", "展开全部折叠的行"),
                    ("collapse", "折叠", self.table.collapse_all, "tool", "折叠所有有后代的行"),
                    ("drawer", self.table.drawer_label(), self.table.toggle_drawer, "tool",
                     "开合右侧档案抽屉（Ctrl+D）"),
                ]),
                ("编辑", [
                    ("new", "新增行", self.table.add_row, "edit", "新增一位始祖（谱牒层 · 可编辑）"),
                    ("paste", "从 Excel 粘贴", self.table.paste_from_clipboard, "edit",
                     "把 Excel 里复制的表格粘进谱牒"),
                    ("copy", "复制到 Excel", self.table.copy_selection, "edit",
                     "把选中行（缺省全部）复制出去"),
                ]),
            ]
            # ★ 2026-09-24 使用者要求：「清空封国」搬到**人物页**工具栏
            #   「重新载入」后面（见 person_view.toolbar_groups）。
            overflow = [("columns", "列设置", self.table.open_column_settings, "tool",
                         "列显示/隐藏与拖拽调序（规划中）")]

        elif key == "tree":
            # ★ 2026-09-23 家谱页签两种模式（原「家谱」/原「时间轴」合并）：
            #   family_mode=gen 代际（树形） / time 时间（时间轴）。上下文槽
            #   放一枚 Segmented「代际 | 时间」切换（与顶栏页签同款风格）。
            from app.contract import FAMILY_MODES, FAMILY_MODE_LABEL
            self.sidebar = shell_mod.Sidebar(self.side_host, theme, self)
            self.sidebar.pack(fill=tk.BOTH, expand=True)
            mode_seg = ([(m, FAMILY_MODE_LABEL[m], "") for m in FAMILY_MODES],
                        self.family_mode, self.switch_family_mode)
            if self.family_mode == "time":
                self.timeline = TimelineView(holder, theme, self)
                groups = [
                    ("缩放", [
                        ("zoomout", "－", lambda: self.timeline.zoom(-1), "tool", "缩小比例尺"),
                        ("zoom", "100%", lambda: self.timeline.zoom(0), "tool", "回到默认比例"),
                        ("zoomin", "＋", lambda: self.timeline.zoom(1), "tool", "放大比例尺"),
                    ]),
                    ("画布", [
                        ("fit", "适应", self.timeline.fit_to_window, "tool",
                         "把整个年份范围压进窗口高度"),
                        ("locate", "定位", self.locate_selected, "tool", "滚动到选中的人"),
                        ("plate", self.timeline.plate_label(), self.timeline.toggle_plate,
                         "tool", "铭牌方向：竖牌（姓名竖排，省横向）⇄ 横牌"),
                    ]),
                ]
                overflow = [
                    ("legend", "朝代图例", self.show_era_legend, "tool",
                     "各朝代的分段与年份区间"),
                    ("export", "导出图片", self.export_tree_image, "tool", "把画布存成 PNG"),
                ]
            else:
                self.tree = TreeView(holder, theme, self)
                groups = [
                    ("缩放", [
                        ("zoomout", "－", lambda: self.tree.zoom(-1), "tool", "缩小（10% 步进）"),
                        ("zoom", "100%", lambda: self.tree.zoom(0), "tool", "回到 100%"),
                        ("zoomin", "＋", lambda: self.tree.zoom(1), "tool", "放大（10% 步进）"),
                    ]),
                    ("画布", [
                        ("expand", "展开", self.expand_all, "tool", "取消隐藏与截断，显示全部"),
                        ("fit", "适应", self.fit_to_window, "tool", "把整棵树压进窗口宽度"),
                        ("locate", "定位", self.locate_selected, "tool", "滚动到选中的人"),
                    ]),
                    ("体检", [
                        ("refresh", "刷新体检", self.refresh_canvas_check, "edit",
                         "重画画布，并检查：男性角色的史实/男性后裔是否都已入谱（缺的补进）、"
                         "史实母亲是否都连了母线（缺的补/连）"),
                    ]),
                    ("搜索", [
                        ("hitprev", "◀ 命中", lambda: self.goto_search_hit(-1),
                         "tool", "上一个搜索命中"),
                        ("hitnext", "命中 ▶", lambda: self.goto_search_hit(1),
                         "tool", "下一个搜索命中"),
                        ("all", "显示全部", self.clear_cutoff, "tool", "取消截断显示"),
                    ]),
                ]
                overflow = [("export", "导出图片", self.export_tree_image, "tool",
                             "把画布存成 PNG")]

        # ★ 2026-09-24 从人物页双击跳来的话，工具栏最左给一条明确的回去的路。
        #   只在「家谱页 + 从人物页跳来」这个窗口内存在（见 _return_to_person）。
        if key == "tree" and self._return_to_person:
            groups = [("返回", [
                ("back", "← 返回人物页", self.back_to_person, "tool",
                 "回到人物页，搜索、排序、滚动位置原样恢复"),
            ])] + groups

        self.toolbar = shell_mod.ToolBar(self.main_area, theme, groups,
                                         overflow=overflow, mode_seg=mode_seg)
        self.toolbar.pack(fill=tk.X)
        holder.pack(fill=tk.BOTH, expand=True)

        if self.table is not None:
            # ★ 2026-09-26：表格页的统计句落到**状态栏 gen 格**（与家谱/时间轴同规）
            self.table.counter_cb = self._set_gen_stat
            self.table.refresh()

        self._install_hotkeys()
        # ★ 2026-09-28：顶栏页签左缘要对齐画布/工具条左缘 —— 品牌区宽度按
        #   **实际**侧栏宽同步。首帧尺寸还没定，所以推迟到 idle 再量。
        self.root.after_idle(self._sync_brand_width)
        if self.timeline is not None:
            self.timeline.canvas.after_idle(self._init_timeline)
        self._update_zoom_label()

    def _sync_brand_width(self):
        """让顶栏品牌区右缘 ≡ 主区左缘 ⇒ 页签外框左沿 ≡ 工具条最左控件左沿。

        ★ 2026-09-28（使用者：「这里的人物bar 能不能左沿跟代际对齐啊」）——
          第一版我按 `侧栏宽 + sashwidth` 算，**量出来还是不齐**：
          ```
          侧栏 476 · 品牌区 504（没更新）· 主区左缘 494 · 页签 515 · 模式段 494
          ```
          侧栏可拖、窗口缩放时 PanedWindow 还会再分配宽度，**任何"算出来"的
          公式都容易差几像素**（sash / padx / 边框各算一遍）。
          ⇒ 改成**直接量实测坐标**：`品牌区宽 = 主区左缘 − 顶栏左缘`。
          这样页签外框与工具条最左控件（家谱页是「代际|时间」段）永远同一条线。
        """
        try:
            delta = self.main_area.winfo_rootx() - self.topbar.winfo_rootx()
            self.topbar.set_brand_width(delta)
        except Exception:
            pass

    def _init_timeline(self):
        if self.timeline is None:
            return
        self.timeline.rerender(keep_scale=False)
        self.on_layout_changed()

    def switch_view(self, key):
        if key == self.view_key or key not in VIEW_KEYS:
            return
        # ★ 2026-09-24 一旦离开家谱页，「返回人物页」随即作废 —— 它只服务
        #   「从人物页跳来、还没离开家谱」这一个来回。
        if key != "tree":
            self._return_to_person = False
        self.cfg = update_config(view=key)
        self._build_main_view()
        self.topbar.set_view(key)
        self._refresh_all()
        logger.info(f"切换页签: {key}")

    def switch_family_mode(self, mode):
        """★ 2026-09-23 家谱页签模式切换：gen 代际 ⇄ time 时间。
        只换家谱页内部视图，页签仍停在「家谱」。
        """
        if mode not in ("gen", "time") or mode == self.family_mode:
            return
        self.family_mode = mode
        self.cfg = update_config(view="tree", family_mode=mode)
        self._build_main_view()
        self.topbar.set_view("tree")
        self._refresh_all()
        logger.info(f"家谱模式切换: {mode}")

    def apply_theme(self, key, save=True):
        self.theme = get_theme(key)
        if save:
            self.cfg = update_config(theme=key)
        self._build_ui()
        self._refresh_all()
        logger.info(f"应用主题: {self.theme.name}")

    def apply_node_style(self, key):
        self.cfg = update_config(node_style=key)
        if self.tree is not None:
            self.tree.rerender()
            self.on_layout_changed()

    def apply_timeline_plate(self, key):
        from app import timeline as T
        key = key if key in T.PLATES else "h"
        self.cfg = update_config(timeline_plate=key)
        if self.timeline is not None:
            self.timeline.plate = key
            self.timeline._cache.clear()
            self.timeline._user_zoomed = False
            self.timeline.rerender(keep_scale=False)
            self.on_layout_changed()
        btn = self.toolbar.buttons.get("plate") if self.toolbar else None
        if btn is not None:
            btn.set_text("铭牌 横排" if key == "h" else "铭牌 竖排")

    # ================================================================ 刷新
    def _refresh_all(self):
        # 侧栏只有谱牒页才由本层刷新（实录页自己管）
        # ★ 2026-09-23 时间轴已并入家谱（view_key=tree），这里不再单独列 timeline
        if self.view_key in ("tree", "table") and self.sidebar is not None:
            self.sidebar.card_filter.set_count(f"{len(self.people)} 人")
            tiers = sorted({i.get("fief_title", "") for i in self.people.values()} - {""})
            states = sorted({i.get("state_name", "") for i in self.people.values()} - {""})
            self.sidebar.refresh_filter_choices(tiers, states)
        if self.topbar is not None:
            self.topbar.set_archive(
                self.current_save,
                self.record_slot.name if self.record_slot else "",
                tip=f"{len(self.record_slots)} 个候选槽 · 只读")
        if self.tree is not None:
            self.tree.rerender()
            self.on_layout_changed()
        elif self.timeline is not None:
            self.timeline.rerender(keep_scale=True)
            self.on_layout_changed()
        elif self.table is not None:
            self.table.refresh()
        self._update_status()

    def _update_zoom_label(self):
        if self.toolbar is None:
            return
        btn = self.toolbar.buttons.get("zoom")
        if btn is None:
            return
        if self.tree is not None:
            btn.set_text(f"{self.tree.zoom_percent()}%")
        elif self.timeline is not None and self.timeline.lay is not None:
            btn.set_text(f"{self.timeline.scale:.2f} px/年")

    def on_layout_changed(self):
        # 统计句统一由 `_update_status` 写状态栏 `gen` 格（★ 2026-09-26）——
        # 这里只负责缩放标签与状态栏刷新，不再单独设计数（避免两个入口）。
        self._update_zoom_label()
        self._update_status()

    def _set_gen_stat(self, text):
        """把一句统计写进状态栏 `gen` 格（表格页 `counter_cb` 的落点）。

        ★ 2026-09-26：家谱 / 时间轴 / 表格三页的统计句统一落状态栏，
        这句永远完整显示 —— 不再出现「可见 1…」那种被工具栏挤断的半截数字。

        ⚠️ `_build_ui` 的顺序是「先 `_build_main_view()`（里面就 `table.refresh()`）
        → 后建状态栏」，所以**早期这一跳拿不到状态栏**（曾经直接 `self.statusbar.set`
        导致 `AttributeError`，程序一启动就闪退）—— 这里静默跳过，内容随后由
        `_update_status`（唯一权威填充口）按同一文案补齐。
        """
        sb = getattr(self, "statusbar", None)
        if sb is not None:
            sb.set("gen", text)

    def _update_status(self):
        sb = self.statusbar
        # ★ 左端常驻双层计数（规划 §四）
        sb.set_counts(record=self.record_count(), book=len(self.people))
        if self.selected_node and self.selected_node in self.people:
            sb.set("sel", f"选中 {self.selected_node}", accent=True)
        else:
            sb.set("sel", "未选中")
        # ★ 2026-09-26：这三条都是**完整统计句**（家谱 / 时间轴 / 表格）——
        #   使用者裁定落状态栏，就是因为它这一条放得下整句、不会被挤断。
        if self.tree is not None and self.tree.lay is not None:
            lay = self.tree.lay
            sb.set("gen", f"谱内 {len(self.people)} 人 · 根节点 {len(lay.roots)} · "
                          f"可见 {lay.min_depth}–{lay.max_depth} 代")
        elif self.timeline is not None and self.timeline.lay is not None:
            tl = self.timeline
            sb.set("gen", f"{tl.status_text()} · 连线 {len(tl.lay.link_pairs)} 条")
        elif self.table is not None:
            sb.set("gen", f"谱牒 {len(self.people)} 行 · 显示 {len(self.table.rows)} 行")
        else:
            sb.set("gen", self._view_gen_text())
        rec = self.record_slot.name if self.record_slot else "未载入"
        sb.set("source", f"实录槽 {rec} ｜ 谱牒档 {self.current_save or '（无）'}")
        # UI 改进 C12：「已保存 HH:MM」格已删（保存瞬间 hint 会报一次）
        sb.set("hint", f"已截断于 {self.cutoff_person}" if self.cutoff_person else "就绪")

    def _view_gen_text(self):
        """实录页的状态栏中段：人数与谱牒内计数。"""
        pv = getattr(self, "person_view", None) or getattr(self, "world_view", None)
        if pv is not None:
            return pv.status_gen_text()
        n = len(self.record_people)
        if n:
            return f"实录 {n} 人"
        return "未载入实录槽"

    # ================================================================ 选中
    def select_person(self, name):
        if name not in self.people:
            return
        self.selected_node = name
        if self.sidebar is not None and hasattr(self.sidebar, "fill_person"):
            self.sidebar.fill_person(self.people[name], name)
        if self.tree is not None:
            self.tree.selected = name
            self.tree.highlight_selection()
            self.tree._draw_popcard()
        if self.timeline is not None:
            self.timeline.select(name)
        if self.table is not None:
            self.table.select_name(name)
        self._update_status()

    def clear_selection(self):
        self.selected_node = None
        if self.sidebar is not None and hasattr(self.sidebar, "clear_person"):
            self.sidebar.clear_person()
        if self.tree is not None:
            self.tree.selected = None
            self.tree.highlight_selection()
            self.tree.hide_popcard()
        if self.timeline is not None:
            self.timeline.select(None)
        self._update_status()

    def goto_main_tree(self, name, from_person=False):
        # ★ 2026-09-23 「跳树」= 跳到代际模式（原家谱）。家谱模式是 time
        #   时没有 tree 实例，先切回代际再滚。
        # ★ 2026-09-24 加 from_person：人物页双击跳来时记下标记，家谱页据此
        #   显示「← 返回人物页」。时间轴内部双击跳代际**不走**这个标记。
        # ★ 2026-09-30 使用者：「**有时候**从人物表格页双击人物还是定位不到
        #   家谱的铭牌」——「有时候」= 勾着某层过滤时。
        #   目标在谱牒里、却被（隐藏非史 / 隐藏逝者 / 仅显入谱 / 画布截断）挡住，
        #   而 `scroll_to` 对不在画布上的人是静默 return ⇒ 看着像双击坏了。
        #   修法：**跳转目标钉进豁免名单**（`TreeView._pinned()` 读 `_jump_pin`），
        #   并且必须在 `switch_view` **之前**设 —— 切换过程就会重算布局。
        #   用独立属性而不是并进 `self.focused`：那是使用者的「选定」名单，
        #   跳一次就往里塞人会污染它（选定会影响筛选与高亮）。
        self._jump_pin = name
        if from_person:
            self._return_to_person = True
        if self.view_key != "tree":
            self.switch_view("tree")
        if self.family_mode != "gen":
            self.switch_family_mode("gen")
        # ★ 2026-09-24 「选中」必须放在切视图**之后** —— 切换会重建画布，在旧
        #   实例上设的 selected 会随旧控件一起丢掉。原来这里只有 scroll_to、
        #   没有选中：人滚过来了却没有高亮和浮卡，使用者不知道该看哪个框。
        self.select_person(name)
        if self.tree is not None:
            self.tree.scroll_to(name)
            # ★ 2026-09-26 跳过来顺带闪一圈 —— 画布人多，光居中找不着牌子
            if self.tree.lay is not None and name in self.tree.lay.positions:
                self.tree.flash_node(name)
            if self.tree.lay is not None and name not in self.tree.lay.positions:
                # 钉住了还是没画上？只剩「截断」或「根本不是画布上的人」这类
                # 兜底原因 —— 明说出来，别静默（与四十九批同一个教训）。
                self._hint_not_on_canvas(name)

    def export_chrome(self, hide):
        """整块导出专用：收起/恢复侧栏（PanedWindow 面板，不销毁控件）。"""
        pw, side = getattr(self, "pw", None), getattr(self, "side_host", None)
        if pw is None or side is None:
            return
        if hide:
            if side.winfo_manager():
                pw.remove(side)
        elif not side.winfo_manager():
            pw.add(side, minsize=230, width=self.theme.sidebar_w,
                   stretch="never")

    def locate_person(self):
        """家谱页侧栏「⌖ 定位人物」：把人居中并高亮闪一圈。

        ★ 2026-09-29 使用者报：「左上角我写的**陈朋**，定位了陈朋，怎么框的是
          **子曹圉**？」—— 原来这里**只读 `self.selected_node`（当前选中）**，
          压根不看侧栏的搜索框，所以搜索框里写谁都没用，框住的永远是上一次
          选中的人；而按钮又长在「过滤」卡片里、紧挨搜索框，任谁都会以为
          它是"按搜索词定位"。
          现在分两条路：
            ① **搜索框里有词** → 先在**画布上的人**里按名字找（先精确、后包含），
               命中就选中 + 居中 + 闪圈；找不到就**明说**没这人（不静默失败）。
            ② 搜索框空着 → 退回原行为：定位**当前选中**的人。
        """
        sb = getattr(self, "sidebar", None)
        query = ""
        if sb is not None:
            # ⚠️ 搜索框带**占位提示**（`attach_placeholder`），占位文字会被写进
            #   `var_search`，必须走 `entry_search.real_value()` 取真值 ——
            #   与 `Sidebar.current_filters()` 同一口径。
            try:
                real = getattr(getattr(sb, "entry_search", None), "real_value", None)
                if callable(real):
                    query = str(real() or "").strip()
                else:
                    query = str(sb.var_search.get() or "").strip()
            except Exception:
                query = ""

        if self.tree is None or self.tree.lay is None:
            return
        pos = self.tree.lay.positions

        if query:
            # ① 按搜索词找：精确 → 包含（画布上可能不止一人同名同姓）
            hit = query if query in pos else next(
                (n for n in pos if query in str(n)), None)
            if hit is None:
                self.statusbar.set(
                    "hint", f"画布上没有名字含「{query}」的人 —— "
                            f"可能被「隐藏非史 / 隐藏逝者 / 仅显入谱」筛掉了")
                return
            self.select_person(hit)
            self.tree.scroll_to(hit)
            self.tree.flash_node(hit)
            self.statusbar.set("hint", f"已按「{query}」定位到 {hit}")
            return

        # ② 搜索框空着 —— 定位当前选中
        name = self.selected_node
        if not name:
            self.statusbar.set("hint", "先选一个人（人物页点行 / 画布点铭牌），"
                                       "或在左上「过滤」里写下名字再点定位")
            return
        if name not in pos:
            self._hint_not_on_canvas(name)
            return
        self.tree.scroll_to(name)
        self.tree.flash_node(name)
        self.statusbar.set("hint", f"已定位 {name}")

    def _hint_not_on_canvas(self, name):
        """人进了谱牒却没出现在画布上时，说清是哪一层过滤挡住的。"""
        acts = []
        if getattr(self, "hide_nohist_all", False):
            acts.append("侧栏勾着「隐藏非史」")
        if getattr(self, "hide_dead", False):
            acts.append("侧栏勾着「隐藏逝者」")
        if getattr(self, "enrolled_only", False):
            acts.append("侧栏勾着「仅显入谱」")
        if getattr(self, "cutoff_person", None):
            acts.append(f"画布截断于「{self.cutoff_person}」")
        tail = "、".join(acts) if acts else "画布的显示范围没覆盖到他"
        self.statusbar.set("hint", f"「{name}」在谱牒里，但当前没画上画布 —— {tail}")

    def back_to_person(self):
        """家谱页的「← 返回人物页」—— 现场由 restore_person_view 恢复。"""
        self._return_to_person = False
        self.switch_view("person")


    def locate_selected(self):
        if self.selected_node is None:
            return
        if self.tree is not None:
            self.tree.scroll_to(self.selected_node)
        elif self.timeline is not None:
            self.timeline.scroll_to(self.selected_node)

    def show_era_legend(self):
        from app.widgets import msgbox as messagebox
        from app import timeline as tl

        def span(s, e):
            return f"前{-s} — 前{-e}" if e < 0 else \
                   (f"前{-s} — 公元{e}" if s < 0 else f"公元{s} — 公元{e}")

        lines = [f"{nm}　{span(s, e)}"
                 for nm, s, e in tl.era_segments(tl.YEAR_START_DEFAULT,
                                                 tl.YEAR_END_DEFAULT)]
        messagebox.showinfo(
            "朝代分段",
            "时间轴纵轴按真实历史分段，不受开局年份影响。\n"
            "前 2070 之前历史上没有朝代，标「上古」（原「传说时代」，2026-09-22 全改）。\n\n"
            + "\n".join(lines), parent=self.root)

    def fit_to_window(self):
        if self.tree is None:
            return
        vw = self.tree.canvas.winfo_width()
        if vw <= 1 or self.tree.lay is None:
            return
        from app.views.tree_view import BASE_SCALE, ZOOM_MAX, ZOOM_MIN
        target = vw / max(1.0, self.tree.lay.scroll_x)
        target = max(BASE_SCALE * ZOOM_MIN, min(BASE_SCALE * ZOOM_MAX, target))
        self.tree.scale = target
        self.tree.rerender()
        self.on_layout_changed()

    def preview_bio(self, name):
        info = self.people.get(name)
        if not info:
            return ""
        custom = info.get("bio", "")
        if custom:
            return custom
        text = bio_mod.generate_bio(self.people, name)
        return text[:80] + ("…" if len(text) > 80 else "")

    # ================================================================ 编辑
    def _record(self, action):
        self.history.record(action, self.people, self.cutoff_person)

    def _apply_history_state(self, people, cutoff):
        self.people = people
        self.cutoff_person = cutoff
        self.save_data()
        self.selected_node = None
        self._refresh_all()

    def undo(self):
        # UI 改进 D15：低价值告知改走状态栏 hint，不再弹窗打断
        if not self.history.undo():
            self.statusbar.set("hint", "无可撤回")

    def redo(self):
        if not self.history.redo():
            self.statusbar.set("hint", "无可恢复")

    # ================================================================ 快捷键
    # ★ 使用者第 1 问：「双击启动的快捷键都不能用」。
    #   实证：改造前全项目只绑了 4 条（Ctrl+Z / Ctrl+Y 及其大写变体），
    #   而且只用 `root.bind` 一层 —— Tk 的事件投递顺序是
    #       widget → class → toplevel → all
    #   焦点一进输入框 / 列表（Entry·Text·Treeview 自带 class binding），
    #   Ctrl+Z 就被控件内建的撤销吃掉并 break，永远传不到 root，
    #   观感就是「快捷键全都没接」。
    #   修法两层：`bind_all` 兜底 + 逐个控件 widget 级重绑（抢在内建之前）。
    HOTKEYS = (
        # 序列                  说明               方法名          输入框内放行
        ("<Control-f>",     "聚焦搜索框",       "_hk_search",   False),
        ("<Control-s>",     "保存谱牒",         "_hk_save",     False),
        ("<Control-o>",     "打开存档",         "_hk_archive",  False),
        ("<Control-p>",     "续谱",             "_hk_extend",   False),
        ("<Control-t>",     "换主题",           "_hk_theme",    False),
        ("<Control-comma>", "设置",             "_hk_settings", False),
        ("<Control-e>",     "导出图片",         "_hk_export",   False),
        ("<Control-g>",     "定位到选中",       "_hk_locate",   False),
        ("<Control-d>",     "档案抽屉开关",     "_hk_drawer",   False),
        ("<Control-q>",     "退出",             "_hk_quit",     False),
        ("<F5>",            "刷新重排",         "_hk_refresh",  False),
        ("<F1>",            "快捷键一览",       "_hk_help",     False),
        ("<Escape>",        "取消选择",         "_hk_escape",   False),
        # ★ 撤销/重做例外：焦点在输入框里时让它做「文本撤销」，
        #   不要抢来撤整个谱牒（否则改个名字按错键会丢一批改动）。
        ("<Control-z>",     "撤销",             "undo",         True),
        ("<Control-y>",     "重做",             "redo",         True),
        ("<Control-Z>",     "撤销",             "undo",         True),
        ("<Control-Y>",     "重做",             "redo",         True),
    )

    def _focus_in_editor(self):
        """焦点是否落在可编辑控件里（此时撤销 / 重做应让给控件自己）。"""
        try:
            w = self.root.focus_displayof()
        except Exception:
            return False
        if w is None:
            return False
        try:
            return w.winfo_class() in ("Entry", "Text", "TEntry", "Spinbox",
                                       "TSpinbox", "TCombobox")
        except Exception:
            return False

    def _make_hotkey(self, method, passthrough):
        def handler(event=None):
            if passthrough and self._focus_in_editor():
                return None
            try:
                getattr(self, method)()
            except Exception as e:
                logger.warning(f"快捷键 {method} 执行失败：{e}")
            return "break"
        return handler

    def _make_view_hotkey(self, key):
        def handler(event=None):
            self.switch_view(key)
            return "break"
        return handler

    def _install_hotkeys(self):
        """两层绑定：all（兜底） ＋ 逐个控件 widget 级（抢在内建 class 之前）。

        每次 `_build_main_view` 末尾都跑一遍 —— 换主题 / 切页签会重建控件，
        旧控件连同绑定一起没了，必须重绑。`bind` 默认是**替换**同序列绑定，
        重复跑不会叠加（不会按一次撤两步）。
        """
        spec = []
        for seq, _label, method, passthrough in self.HOTKEYS:
            spec.append((seq, self._make_hotkey(method, passthrough)))
        for i, (key, _label, _icon, _layer) in enumerate(VIEWS, start=1):
            spec.append((f"<Control-Key-{i}>", self._make_view_hotkey(key)))
        for seq, fn in spec:
            try:
                self.root.bind_all(seq, fn)
            except Exception:
                pass
        self._bind_widget_hotkeys(self.root, spec)

    def _bind_widget_hotkeys(self, widget, spec):
        for seq, fn in spec:
            try:
                widget.bind(seq, fn)
            except Exception:
                pass
        for child in widget.winfo_children():
            self._bind_widget_hotkeys(child, spec)

    def _hk_search(self):
        """聚焦当前页搜索框；本页没有搜索框就先跳到人物页。"""
        ent = (getattr(self.person_view, "search_entry", None)
               or getattr(self.world_view, "search_entry", None)
               or getattr(getattr(self, "sidebar", None), "entry_search", None))
        if ent is None:
            self.switch_view("person")
            ent = getattr(self.person_view, "search_entry", None)
        if ent is None:
            return
        ent.focus_set()
        try:
            ent.select_range(0, "end")
        except Exception:
            pass

    def _hk_save(self):
        if self.save_data():
            self._update_status()
            if getattr(self, "statusbar", None) is not None:
                self.statusbar.set("hint", f"已保存《{self.current_save}》{self._saved_at}")

    def _hk_archive(self):
        self.open_archive()

    def _hk_extend(self):
        self.extend_book()

    def _hk_theme(self):
        self.open_theme_picker()

    def _hk_settings(self):
        self.open_settings()

    def _hk_export(self):
        self.export_tree_image()

    def _hk_locate(self):
        self.locate_selected()

    def _hk_quit(self):
        self.quit_app()

    def _hk_refresh(self):
        self._refresh_all()

    def _hk_escape(self):
        self.clear_selection()

    def _hk_drawer(self):
        """表格页的档案抽屉开关；不在表格页就先切过去。"""
        if self.table is None:
            self.switch_view("table")
        if self.table is None:
            return
        self.table.toggle_drawer()
        if getattr(self, "toolbar", None) is not None:
            self.toolbar.set_button_text("drawer", self.table.drawer_label())

    def _hk_help(self):
        """F1 —— 快捷键一览。键位表就是 HOTKEYS，不会和实际绑定对不上。"""
        from app.widgets import msgbox as messagebox

        def human(seq):
            t = seq.strip("<>")
            parts = t.split("-")
            out = []
            for p in parts:
                if p == "Control":
                    out.append("Ctrl")
                elif p.lower() == "comma":
                    out.append(",")
                elif len(p) == 1 or p.isdigit():
                    out.append(p.upper())
                else:
                    out.append(p)
            return "+".join(out)

        lines = [f"{human(seq):<12}{label}"
                 for seq, label, _m, _p in self.HOTKEYS]
        lines.append("")
        for i, (key, label, _icon, _layer) in enumerate(VIEWS, start=1):
            lines.append(f"Ctrl+{i:<7}切到「{label}」页")
        messagebox.showinfo("快捷键一览", "\n".join(lines))

    # ---- 侧栏编辑回调（谱牒页；实录页不会触发）----
    # 实录页的 self.sidebar 是 None（那边侧栏归 PersonView 自己管），
    # 这些回调只有谱牒页的控件会调到，仍加一道 `sidebar is None` 兜底。
    def on_gender_change(self):
        if self._updating or not self.selected_node or self.sidebar is None:
            return
        self.people[self.selected_node]["gender"] = self.sidebar.var_gender.get()
        self._record(f"修改性别: {self.selected_node}")
        self.save_data()
        self._refresh_all()

    def on_historical_change(self):
        if self._updating or not self.selected_node or self.sidebar is None:
            return
        self.people[self.selected_node]["historical"] = self.sidebar.var_hist_person.get()
        self._record(f"修改史实: {self.selected_node}")
        self.save_data()
        self._refresh_all()

    def on_divine_change(self):
        if self._updating or not self.selected_node or self.sidebar is None:
            return
        self.people[self.selected_node]["divine"] = self.sidebar.var_divine.get()
        self._record(f"修改神祖: {self.selected_node}")
        self.save_data()
        self._refresh_all()

    def on_tier_change(self):
        if self._updating or not self.selected_node or self.sidebar is None:
            return
        tier = self.sidebar.var_tier_person.get()
        self.people[self.selected_node]["fief_title"] = tier
        if tier == "无":
            self.people[self.selected_node]["fief_gen"] = 0
            self.sidebar.var_fief_gen.set("")
        self._record(f"修改爵位: {self.selected_node} → {tier}")
        self.save_data()
        self._refresh_all()

    def on_root_sort_change(self):
        if self._updating or not self.selected_node or self.sidebar is None:
            return
        raw = self.sidebar.var_root_sort.get()
        try:
            new_sort = int(raw) if raw else 0
        except ValueError:
            new_sort = 0
        old_sort = self.people[self.selected_node].get("root_sort", 0)
        if new_sort == old_sort:
            return
        model.shift_root_sorts(self.people, new_sort, old_sort,
                               exclude_name=self.selected_node)
        self.people[self.selected_node]["root_sort"] = new_sort
        self._record(f"修改祖序: {self.selected_node} {old_sort} → {new_sort}")
        self.save_data()
        self._refresh_all()

    def remove_spouse(self):
        if not self.selected_node:
            return
        info = self.people[self.selected_node]
        spouses = info.get("spouses", [])
        if not spouses:
            return
        rem = spouses.pop()
        if rem in self.people:
            other = self.people[rem].get("spouses", [])
            if self.selected_node in other:
                other.remove(self.selected_node)
        self._record(f"移除配偶: {self.selected_node} × {rem}")
        self.save_data()
        self._refresh_all()
        self.select_person(self.selected_node)

    def save_modification(self):
        from app.dialogs import forms
        forms.save_person_modification(self)

    def delete_selected(self):
        from app.widgets import msgbox as messagebox
        if not self.selected_node:
            self.statusbar.set("hint", "请先选人")
            return
        name = self.selected_node
        children = model.get_children(self.people, name)
        # ★ 2026-09-23 危险确认框：红色主按钮 + 动词文案（原 askyesno「是/否」）
        if children and not messagebox.ask_danger(
                "删除人物", f"{name} 有 {len(children)} 名（直系）后代，\n是否连同全部后裔一起删除？",
                ok_text="全部删除", parent=self.root):
            return
        self._record(f"删除: {name}")
        gone = model.get_subtree(self.people, name)
        model.remove_people(self.people, gone)
        self.selected_node = None
        self.save_data()
        self._refresh_all()
        logger.info(f"删除 {name} 及 {len(gone) - 1} 个后代")

    # ================================================================ 搜索/过滤
    def do_search(self, text):
        text = (text or "").strip()
        if not text:
            self._clear_search_hits()
            self.statusbar.set("hint", "请输入姓名")
            return
        hits = [n for n in self.people if text in n]
        if not hits:
            self._clear_search_hits()
            self.statusbar.set("hint", f"无「{text}」")
            return
        same = (text == self._last_search)
        self._last_search = text
        if self.tree is not None:
            keep = self.tree.search_hits[self.tree.search_index] \
                if same and 0 <= self.tree.search_index < len(self.tree.search_hits) else None
            self.tree.set_search_hits(hits, current=keep)
            self.tree.rerender()
            self.tree.goto_hit(1 if same else 0)
        if self.table is not None:
            self.table.set_search(text)
            self.select_person(hits[0])
        elif self.timeline is not None:
            self.timeline.select(hits[0])
            self.timeline.scroll_to(hits[0])
            self.select_person(hits[0])
        self._set_search_hint(len(hits))

    def _clear_search_hits(self):
        self._last_search = ""
        if self.tree is not None:
            self.tree.clear_search_hits()

    def _set_search_hint(self, total):
        if self.tree is not None and self.tree.search_hits:
            idx = self.tree.search_index + 1
            self.statusbar.set("hint", f"命中 {total} 人 · 第 {idx} 个 · 回车下一个")
        else:
            self.statusbar.set("hint", f"命中 {total} 人 · 回车下一个")

    def goto_search_hit(self, step):
        if self.tree is None:
            return
        target = self.tree.goto_hit(step)
        if target is None:
            self.statusbar.set("hint", "尚无命中，请先搜索")
            return
        total = len(self.tree.search_hits)
        self.statusbar.set("hint",
                           f"命中 {total} 人 · 第 {self.tree.search_index + 1} 个 · {target}")

    def apply_filters(self):
        if self.table is not None:
            self.table.refresh()

    def on_chip_toggle(self, key, value):
        if key == "nohist":
            # ★ 2026-09-24 改成**真正的全局开关**（原来只在恰好选中节点时才
            #   把该节点的始祖记进隐藏名单，没选中就什么都不发生 ——
            #   使用者报「勾了隐藏非史画布不变化、非史角色还存在」就是这个）。
            self.hide_nohist_all = value
            if not value:
                # 取消 = 全部恢复：把旧版勾选框按支系留下的隐藏名单一起清掉
                # （想单独隐藏某一支，用右键「隐藏非史实后裔」）。
                if self.hidden_non_historical:
                    self.hidden_non_historical.clear()
                    self._persist_canvas_state()      # ★ 名单按谱牒存
            if value:
                self.statusbar.set("hint", "已隐藏全部非史实人物（取消勾选即恢复）")
        if key == "dead":
            self.hide_dead = value
        if key == "branch":
            self._branch_only = value          # 表格页「当前宗支」用它
        if key == "enrolled":
            # ★ 2026-09-23「仅显入谱」：画布默认只画点名过的人（入谱 / 加入族谱）
            self.enrolled_only = value
            if value and not self.enrolled_set():
                self.statusbar.set(
                    "hint", "尚无入谱者 —— 在人物页点「入谱」或「加入族谱」")
        if key == "focus":
            # 「仅显所选」：勾选启用过滤（名单=右键选定的人），取消只停用、名单保留
            self.focus_only = value
            if value and not self.focused:
                self.statusbar.set("hint", "尚未选定 —— 画布/表格右键「选定」")
            if self.sidebar is not None and hasattr(self.sidebar, "set_focus_btn"):
                self.sidebar.set_focus_btn(value)
        if self.tree is not None:
            self.tree.rerender()
            self.on_layout_changed()
        elif self.timeline is not None:
            self.timeline.rerender(keep_scale=True)
            self.on_layout_changed()
        if self.table is not None:
            self.table.refresh()
        self._persist_filter_state()

    def set_cutoff(self, person):
        self._record(f"截断显示: {person}")
        self.cutoff_person = person
        self.save_data()
        self.clear_selection()
        self._refresh_all()

    def clear_cutoff(self):
        if self.cutoff_person:
            self._record("取消截断显示")
        self.cutoff_person = None
        self.save_data()
        self.clear_selection()
        self._refresh_all()

    def expand_all(self):
        if (not self.hidden_non_historical and not self.cutoff_person
                and not self.hide_nohist_all):
            self.statusbar.set("hint", "已是完整显示")
            return
        if self.hidden_non_historical:
            self.hidden_non_historical.clear()
            self._persist_canvas_state()      # ★ 隐藏名单按谱牒存
        self.hide_nohist_all = False
        if self.sidebar is not None and hasattr(self.sidebar, "chips"):
            self.sidebar.chips.set_state("nohist", False)
        self._persist_filter_state()
        self.cutoff_person = None
        self._record("全部展开")
        self._refresh_all()

    def export_tree_image(self):
        from tkinter import filedialog
        from app.widgets import msgbox as messagebox
        view = self.tree if self.tree is not None else self.timeline
        if view is None:
            return
        who = "家谱(代际)" if self.tree is not None else "家谱(时间)"
        path = filedialog.asksaveasfilename(
            defaultextension=".png", filetypes=[("PNG 图片", "*.png")],
            initialfile=f"{self.current_save or '家谱'}_{who}.png",
            title=f"导出{who}图片", parent=self.root)
        if not path:
            return
        try:
            # ★ 2026-09-27 使用者要求：导出**整块画布**（含没显示的部分，
            #   代数标签/朝代带都在内），不再只截可视面板 —— 大画布自动
            #   分块成多个文件（每块 ≤10000px，逐屏截取拼接）。
            prefix = path[:-4] if path.lower().endswith(".png") else path
            files = view.export_full(prefix, on_progress=lambda d: (
                self.statusbar.set("hint", f"导出中… 已截 {d} 屏")))
            if len(files) == 1:
                f0, w0, h0 = files[0]
                messagebox.showinfo(
                    "导出成功", f"已导出整块画布 {w0}×{h0} 像素：\n{f0}")
            else:
                inner = "\n".join(f"{f}（{w}×{h}）" for f, w, h in files[:12])
                more = f"\n… 共 {len(files)} 个文件" if len(files) > 12 else ""
                messagebox.showinfo(
                    "导出成功",
                    f"整块画布较大，已分 {len(files)} 个文件：\n{inner}{more}")
        except Exception as e:
            logger.error(f"导出图片失败: {e}")
            messagebox.showerror("导出失败", f"导出图片失败：{e}")

    # ================================================================ 右键菜单
    def build_context_menu(self, person):
        from tkinter import Menu
        from app.dialogs import forms
        menu = Menu(self.root, tearoff=0,
                    font=(self.theme.font_ui_fallback, self.theme.fs_body),
                    bg=self.theme.bg_card, fg=self.theme.text,
                    activebackground=self.theme.edit, activeforeground=self.theme.edit_on)
        menu.add_command(label="添加子嗣", command=lambda: forms.add_child_dialog(self, person))
        menu.add_command(label="添加同代人", command=lambda: forms.add_associate_dialog(self, person))
        menu.add_command(label="修改尊号/谥号", command=lambda: self._edit_note(person))
        menu.add_command(label="编辑人物介绍", command=lambda: forms.bio_dialog(self, person))
        menu.add_separator()
        # ★ 2026-09-23「仅显所选」：右键「选定」把此人加进名单（可连续多选），
        #   再勾左侧「仅显所选」chip 只看名单人 + 其后裔。
        if person in self.focused:
            menu.add_command(label="✓ 已选定（再点取消）", command=lambda: self.toggle_focus(person))
        else:
            menu.add_command(label="选定（仅显所选）", command=lambda: self.toggle_focus(person))
        menu.add_separator()
        # ★ 桥：查档（谱牒 → 实录）
        menu.add_command(label="⌖ 查档（跳到实录层）", command=lambda: self.open_viewer(person))
        menu.add_separator()
        info = self.people.get(person, {})
        ancestor = model.root_ancestor(self.people, person)
        hidden = self.hidden_non_historical.get(ancestor, False)
        menu.add_command(label=("显示非史实后裔" if hidden else "隐藏非史实后裔"),
                         command=lambda: self._toggle_hide(ancestor))
        if self.cutoff_person:
            menu.add_command(label="显示全部（取消截断）", command=self.clear_cutoff)
        menu.add_command(label="从此人向下显示（隐藏以上）", command=lambda: self.set_cutoff(person))
        menu.add_separator()
        if not info.get("father") and not info.get("mother"):
            menu.add_command(label="转为同代人",
                             command=lambda: forms.convert_to_associate_dialog(self, person))
        menu.add_command(label="删除自己及所有后代", command=self.delete_selected)
        return menu

    def _toggle_hide(self, ancestor):
        self.hidden_non_historical[ancestor] = not self.hidden_non_historical.get(ancestor, False)
        self._persist_canvas_state()      # ★ 名单按谱牒存
        if self.tree is not None:
            self.tree.rerender()
            self.on_layout_changed()

    def focus_set(self):
        """「选定」高亮集合 = 手动选定的人 + 其**全部男性后裔**（纯父系谱系）。

        ★ 2026-09-23 使用者纠正：「选定（仅显所选）不是应该从被选定的人开始
          包含其所有男性后裔都被选定吗？毕竟我要看的是他的谱系啊」——
          高亮不该只标选定人本人，而要标出他这一支的**父系谱系**。
        只跟 `father` 边向下（不含女儿支），与「仅显所选」的过滤口径、
        与修谱/续谱的父系口径完全一致。结果按 (focused, people) 缓存，
        名单变化时由 `toggle_focus` 清空重算。
        """
        if self._focus_set_cache is None or self._focus_set_key != id(self.people):
            self._focus_set_key = id(self.people)
            kids = {}
            for n, v in self.people.items():
                d = (v or {}).get("father", "") or ""
                if d:
                    kids.setdefault(d, []).append(n)
            out = set(self.focused)
            stack = list(self.focused)
            while stack:
                cur = stack.pop()
                for c in kids.get(cur, ()):
                    if c not in out:
                        out.add(c)
                        stack.append(c)
            self._focus_set_cache = out
        return self._focus_set_cache

    def toggle_focus(self, person):
        """右键「选定/取消选定」：把某人加进/移出「仅显所选」名单（可多选）。"""
        if person not in self.people:
            # ★ 2026-09-26 二改（使用者报「我的选中功能没有了吗」）：实录层的
            #   人物也照选。原口径（09-23）对未入谱的人弹窗拦下 —— 在人物页对
            #   实录层的人点「选定」就像按钮坏了。现在照加名单：「仅显所选」
            #   在人物页按名字过滤照常可用；画布只画谱牒，实录层的人入谱后
            #   自然出现（提示语说明）。
            if person in self.focused:
                self.focused.remove(person)
                self.statusbar.set("hint",
                    f"已取消选定 {person}（余 {len(self.focused)} 人）")
            else:
                self.focused.append(person)
                self.statusbar.set(
                    "hint", f"已选定 {person}（实录层人物 · 共 "
                            f"{len(self.focused)} 人；画布需先入谱才显示）")
            self._focus_set_cache = None   # 名单变了，高亮集合缓存必须重算
            return
        if person in self.focused:
            self.focused.remove(person)
            self.statusbar.set("hint", f"已取消选定 {person}（余 {len(self.focused)} 人）")
        else:
            self.focused.append(person)
            # ★ 2026-09-23：若此人没入谱、而「仅显入谱」又勾着，光看画布会以为
            #   没选上（其实是被那层默认过滤挡了）。这里明说一句，避免反复点。
            extra = ""
            if (self.enrolled_only
                    and person not in self.enrolled_set()):
                extra = "；此人未入谱，画布上只显示他本人（其父系谱系需先入谱）"
            self.statusbar.set(
                "hint", f"已选定 {person}（共 {len(self.focused)} 人；勾「仅显所选」生效）{extra}")
        self._focus_set_cache = None      # 名单变了 → 高亮集合重算
        self._persist_canvas_state()      # ★ 名单按谱牒存（原来写 config 会串档）
        if self.focus_only:
            self._refresh_all()
        else:
            # 未启用过滤时只重画树/时间轴，把「✓已选定」菜单态刷出来
            if self.tree is not None:
                self.tree.rerender()
            if self.timeline is not None:
                self.timeline.rerender(keep_scale=True)
            # 人物页卡片上「选定人物」按钮态同步 —— 从右键菜单选定时卡片不会自己刷。
            # ★ 2026-09-28：原来调 `person_view._update_focus_btn`（刷新旧按钮条上
            #   那颗「✦ 选定」，随旧按钮一起删除）。现在卡片上的按钮态是**渲染时
            #   现算**的，所以这里直接让卡片重绘一次即可。
            pv = getattr(self, "person_view", None)
            if pv is not None:
                _idx = pv._selected_index()
                if _idx is not None:
                    pv._show_detail(_idx)
        self._persist_filter_state()

    def _edit_note(self, person):
        from tkinter import simpledialog
        old = self.people[person].get("note", "")
        new = simpledialog.askstring("修改尊号/谥号", f"请输入 {person} 的尊号/谥号：",
                                     initialvalue=old, parent=self.root)
        if new is None:
            return
        self.people[person]["note"] = new
        self._record(f"修改注释: {person}")
        self.save_data()
        self._refresh_all()
        self.select_person(person)

    # ================================================================ 对话框
    def open_add_ancestor(self):
        from app.dialogs import forms
        forms.add_ancestor_dialog(self)

    def open_add_child(self):
        from app.dialogs import forms
        if not self.selected_node:
            self.statusbar.set("hint", "请先选父或母，再添加子嗣")
            return
        forms.add_child_dialog(self, self.selected_node)

    def open_save_manager(self):
        from app.dialogs import forms
        forms.save_manager_dialog(self)

    # ================================================================ 桥
    def open_viewer_code(self, code):
        """`--goto 编号` 的入口：启动后直接跳到实录层这个人的档案。"""
        if self.view_key != "person":
            self.switch_view("person")
        pv = getattr(self, "person_view", None)
        if pv is not None:
            pv.locate_person(code=str(code))

    def open_viewer(self, person=None):
        """⌖ 查档（谱牒 → 实录）：切到「人物」页并定位此人的实录档案。

        M1 起两层同处一进程 —— 不再拉起外部程序：直接切页签、定位、选中。
        靠 people 记录里的 `code`（存档编号 Ren_Code）匹配；
        没有 code 的（手写老档）按姓名 + 性别 + 生年模糊匹配，再无则明说。
        """
        person = person or self.selected_node
        if not person:
            self.statusbar.set("hint", "请先选人，再查档")
            return
        if self.record_slot is None:
            self.statusbar.set("hint", "尚未载入实录槽 —— 请先在顶栏「存档」选槽")
            return
        info = self.people.get(person, {})
        code = str(info.get("code", "") or "").strip()
        if self.view_key != "person":
            self.switch_view("person")
        pv = self.person_view
        if pv is None:
            return
        hit = pv.locate_person(code=code, name=person, info=info)
        if not hit:
            # ★ 2026-09-26 审查修复：这里原来直接用 `messagebox` 却没有 import ——
            #   查档未命中（人在谱牒、实录槽里没有此人）时必抛 NameError，
            #   与四十一批修过的 delete_selected 同型，当时漏了这一处。
            from app.widgets import msgbox as messagebox
            messagebox.showinfo(
                "查档",
                f"实录层里没找到「{person}」。\n\n"
                + (f"编号 {code} 不在当前实录槽（{self.record_slot.name}）里。\n"
                   if code else
                   "这条谱牒记录没有存档编号，按姓名 + 性别 + 生年也没对上。\n")
                + "\n可以先在顶栏换一个实录槽再试；" 
                  "或从人物页选中同一人后点「⇱ 入谱」把编号补进谱牒。")
        logger.info(f"查档桥：{person}（code={code or '—'}）→ 实录层")

    def enrolled_set(self):
        """画布默认显示的集合 = **点过「入谱」的人** ∪ **「加入族谱」点名的人**。

        ★ 2026-09-23 使用者改规则：原来史实角色一续谱就全部上画布（两千多人
          看不过来），现在「只有点了入谱或续谱的人物才会绘制家族谱，就像现在
          的『仅显所选』一样」。抽取规则不变（仍全量抽进谱牒），只是画布默认
          筛掉没点名过的 —— 想全看时勾掉侧栏「仅显入谱」即可。
        带缓存，入谱/点名/换档时失效重算。
        """
        if (self._enrolled_cache is None
                or self._enrolled_key != id(self.people)):
            self._enrolled_key = id(self.people)
            out = {n for n, v in self.people.items()
                   if (v or {}).get("enrolled")}
            out |= set(self.followed_codes_names())
            self._enrolled_cache = out
        return self._enrolled_cache

    def followed_codes_names(self):
        """续谱名单在**谱牒里**对应的姓名（名单存的是编号）。"""
        codes = set(self.followed_codes())
        if not codes:
            return ()
        return [n for n, v in self.people.items()
                if str((v or {}).get("code", "")) in codes]

    def mark_enrolled(self, code, on=True):
        """给谱牒里编号为 code 的人打/撤「已入谱」标（决定上不上画布）。"""
        hit = 0
        for v in self.people.values():
            if str((v or {}).get("code", "")) == str(code):
                v["enrolled"] = bool(on)
                hit += 1
        if hit:
            self.save_data()
            self._enrolled_cache = None
        return hit

    def push_to_book(self, code, name=""):
        """⇱ 入谱（实录 → 谱牒）：把实录层某人写进当前谱牒档。

        M1 直接调 import_from_game 的单人入口，写的是 family.json，**不碰游戏存档**。

        ★ 2026-09-22 使用者要求「入谱后无需出现确认和成功的对话框」——
          点按钮就直接入，入完状态栏给一句反馈；不再弹确认/成功弹窗。
          只有真正失败才弹错误框（不能静默吞掉失败）。
        """
        import subprocess
        from app.widgets import msgbox as messagebox
        if not self.current_save:
            messagebox.showerror("入谱", "还没有谱牒档（saves/ 为空），先建一个。")
            return False
        if self.record_slot is None:
            messagebox.showerror("入谱", "还没有载入实录槽。")
            return False
        nm = name or code
        importer = os.path.join(BASE_DIR, "tools", "import_from_game.py")
        if not os.path.exists(importer):
            messagebox.showerror("入谱", f"找不到导入器：\n{importer}")
            return False
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        try:
            p = subprocess.run(
                [sys.executable, importer, "--src", self.record_slot.root,
                 "--save", self.current_save, "--person", str(code), "--lineage"],
                capture_output=True, timeout=180, cwd=BASE_DIR, env=env)
        except Exception as e:
            messagebox.showerror("入谱", f"启动导入器失败：{e}")
            return False
        out = (p.stdout or b"").decode("utf-8", "replace")
        err = (p.stderr or b"").decode("utf-8", "replace")
        tail = "\n".join(out.strip().splitlines()[-6:])
        if p.returncode == 0:
            self.load_data()          # 重新读谱牒，新入谱的人立刻可见
            # ★ 2026-09-23 打「已入谱」标 —— 画布默认只画点过入谱的人
            self.mark_enrolled(str(code))
            self._refresh_all()
            # ★ 2026-09-22：成功不再弹窗 —— 状态栏一句带过（成功是常态，弹窗是打扰）
            try:
                self.statusbar.set("hint", f"已入谱 {nm}（编号 {code}）")
            except Exception:
                pass
            return True
        messagebox.showerror("入谱失败", err.strip() or tail or f"退出码 {p.returncode}")
        return False

    # ================================================================ 刷新体检
    def refresh_canvas_check(self):
        """工具条「刷新体检」（使用者 2026-09-22）：重画画布，并做两项完整性
        检查、缺的当场补齐——
          ① 画布上男性角色的「史实后裔 + 男性后裔」是否都已入谱（缺的补进；
             纯父系下探，非史实女儿不入谱不下传——与入谱/续谱同一口径）；
          ② 每个角色按实录认出的「史实母亲」是否已入谱并连上母线
             （缺的补人，「媵妾」类占位不算）。
        手写谱（无编号）无法对实录溯源，自动跳过 —— 只体检带编号的角色。
        """
        if self.record_slot is None or self.record_rel is None:
            self.statusbar.set("hint", "刷新体检：尚未载入实录槽，请先在「存档」选槽")
            return
        if not self.current_save:
            self.statusbar.set("hint", "刷新体检：尚未载入谱牒档")
            return
        # 1) 重画画布
        if self.tree is not None:
            self.tree.rerender()
            self.on_layout_changed()
        elif self.timeline is not None:
            self.timeline.rerender(keep_scale=True)
            self.on_layout_changed()

        from app import profiles as PF
        from tools import import_from_game as IM
        rel = self.record_rel
        people = self.people
        book_codes = {str(v.get("code")): n for n, v in people.items() if v.get("code")}

        # 2) ① 男性角色的史实后裔 + 男性后裔（全局 seen 防重复下探/防环）
        need = set()
        seen = set()
        for root, v in people.items():
            if v.get("gender", "男") != "男" or not v.get("code"):
                continue
            stack = [str(v["code"])]
            while stack:
                c = stack.pop()
                if c in seen:
                    continue
                seen.add(c)
                for kid in rel.children_of(c):
                    kid = str(kid)
                    p = rel.get(kid)
                    female = (p is not None and p.sex == 1)
                    hist = PF.is_historical(kid)
                    # ★ 2026-09-26 审查修复：占位祖先空壳（编号带 父/祖/曾/高、
                    #   无性别记录）不是真人 —— 原来它 female=False、又不算
                    #   「史实女儿」，于是两头都不拦，被当成男性后裔补进谱
                    #   （五十六批刚清掉的东西从这里又回来了）。
                    #   判据与 tools.import_from_game._is_ph_code 同型。
                    if kid[-1:] in ("父", "祖", "曾", "高") and \
                            (p is None or p.sex is None):
                        continue
                    if female and not hist:
                        continue            # 非史实女儿：不入谱不下传
                    if kid not in book_codes:
                        need.add(kid)
                    if not female:
                        stack.append(kid)   # 男性后裔继续下探；史实女儿止步

        # 3) ② 史实母亲：没入谱的补人；已在谱但母线没连的记账
        mother_fix = []
        for n, v in people.items():
            c = str(v.get("code") or "")
            if not c:
                continue
            m = rel.mother.get(c)
            if not m:
                continue
            mc, _mn, placeholder = m
            if placeholder or not mc or not PF.is_historical(mc):
                continue                    # 媵妾/无名占位、非史实母亲：不管
            if mc not in book_codes:
                need.add(mc)
            else:
                mother_fix.append((n, mc))

        # 4) 补缺（一次读档批量并入，世代/母线逻辑与入谱同源）
        added = 0
        if need:
            rc, added, _u = IM.import_codes(self.record_slot.root, sorted(need),
                                            self.current_save)
            if rc != 0:
                from app.widgets import msgbox
                msgbox.showerror("刷新体检", "补全失败，明细见日志（shiguan.log）。")
                return
            self.load_data()

        # 5) 连母线（补入后名字才齐；book_codes 重算一遍）
        linked = 0
        people = self.people
        book_codes = {str(v.get("code")): n for n, v in people.items() if v.get("code")}
        for n, v in people.items():
            c = str(v.get("code") or "")
            if not c:
                continue
            m = rel.mother.get(c)
            if not m:
                continue
            mc, _mn, placeholder = m
            if placeholder or not mc or not PF.is_historical(mc):
                continue
            mother_name = book_codes.get(mc)
            if mother_name and v.get("mother") != mother_name:
                v["mother"] = mother_name
                linked += 1

        if added or linked:
            self._record(f"刷新体检：补 {added} 人 · 连母线 {linked} 条")
            self.save_data()
        self._refresh_all()

        msg = (f"刷新体检完成：补入史实后裔/男性后裔/史实母亲 {added} 人 · "
               f"连母线 {linked} 条。") if (added or linked) else \
              "刷新体检完成：史实/男性后裔齐备，史实母亲母线全连，无需修补。"
        self.statusbar.set("hint", msg)
        logger.info(f"刷新体检：{msg}")
        if added or linked:
            from app.widgets import msgbox
            msgbox.showinfo("刷新体检", msg + "\n\n画布已刷新。")

    # ================================================================ 续谱 / 存档
    def open_archive(self):
        """顶栏「存档」（Ctrl+O）：一个对话框管谱牒档（目的）与实录槽（来源）。"""
        from app.dialogs import forms
        forms.archive_dialog(self)

    def _local_era(self, slot):
        """本机缓存里若已有这个槽，读一下它的剧本 —— 只给槽列表当提示用。

        用 `import_from_game.detect_era` 而不是 `SaveSlot.load()`：
        后者要解析 400 多个文件（0.6s/槽），列 7 个槽就卡 4 秒；前者只读两个小文件。
        """
        from tools import import_from_game as IM
        for base in RECORD_BASES:
            p = os.path.join(base, slot)
            if os.path.isdir(p):
                try:
                    return IM.detect_era(p)
                except Exception:
                    return ""
        return ""

    def _local_scenario(self, path):
        """本机缓存槽 → 剧本标签（`秦末起义 · 前 209`），认不出返回空串。

        ★ 2026-09-21 使用者给了一份完整剧本表（33 本全局 + 10 本局部），
          于是槽列表不用再只写「秦末 / 上古」这种两档粗判，
          可以写出**具体剧本名 + 开局年**，一眼认出这是哪一盘。

        读年份走 `IM.detect_start_year`（只读两个小文件，0.6s/槽 那种整档解析是不做的），
        再拿「争霸类型 + 年份」去 `app/scenarios` 查表。
        """
        from tools import import_from_game as IM
        from tools import sync_from_mumu as SM
        from app import scenarios as SC
        try:
            year = IM.detect_start_year(path)
        except Exception:
            return ""
        if year is None:
            return ""
        return SC.label(year, SM.slot_mode(os.path.basename(path)))

    def local_slot_desc(self, path):
        """本机缓存槽的一行说明。返回 `(说明, 能不能读)`。

        一行 = `剧本名 · 开局年 · N 个表文件 · 游戏写入 MM-DD HH:MM`。
        ★ 2026-09-21 使用者要求「实录槽应该在每个存档后记录存档的现实时间，
          这个也是重要的判断依据」—— 存档 json 里**没有**这个字段
          （扫过 5 个槽全部 json 含嵌套数组，0 命中），所以改成**趁拉档那一刻
          从设备上取目录 mtime、落盘存进 `<槽根>/_shiguan_slots.json`**
          （见 `sync_from_mumu._merge_slot_meta`）。
          没拉过档的老槽读不到，退回显示「拉到本机 …」（目录 mtime）。
        """
        try:
            files = os.listdir(path)
        except Exception:
            return "（读不了）", False
        if not any(f.endswith(".json") for f in files):
            # 使用者原话：「加密就写加密就好，无需写读不了」
            return "加密", False
        bits = []
        # 剧本名优先（`秦末起义 · 前 209`）；认不出才退回两档粗判（上古/秦末）
        scen = self._local_scenario(path)
        if scen:
            bits.append(scen)
        else:
            era = self._local_era(os.path.basename(path))
            if era:
                bits.append(era)
        bits.append(f"{len(files)} 个表文件")
        dev = self._slot_device_mtime(path)
        if dev:
            bits.append(f"游戏写入 {dev}")
        else:
            mt = self._local_mtime(path)
            if mt:
                bits.append(f"拉到本机 {mt}")
        cur = self.record_slot.root if self.record_slot is not None else ""
        if cur and os.path.normcase(cur) == os.path.normcase(path):
            bits.append("← 当前")
        return " · ".join(bits), True

    @staticmethod
    def _fmt_device_mtime(raw):
        """设备目录时间 `Sep 21 23:25` → `09-21 23:25`；认不出原样返回。"""
        import re
        t = str(raw or "").strip()
        m = re.match(r"([A-Za-z]{3})\s+(\d{1,2})\s+(\d{1,2}:\d{2})", t)
        if not m:
            return t
        mon = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
               "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12
               }.get(m.group(1).title())
        if not mon:
            return t
        return f"{mon:02d}-{int(m.group(2)):02d} {m.group(3)}"

    def _slot_device_mtime_raw(self, path):
        """槽 → 拉档时落盘的 `device_mtime` **原串**（`2026-09-21 20:18`）；没有返回空串。"""
        p = os.path.normpath(path or "")
        slot, base = os.path.basename(p), os.path.dirname(p)
        if not slot or not base:
            return ""
        from tools import sync_from_mumu as SM
        try:
            import json as _json
            with open(os.path.join(base, SM.SLOT_META_FILE), encoding="utf-8") as f:
                data = _json.load(f) or {}
        except Exception:
            return ""
        return str((data.get(slot) or {}).get("device_mtime") or "")

    def _slot_device_mtime(self, path):
        """槽 → **游戏写入时间**（`09-21 23:25`）；没拉过档返回空串。

        读的是拉档时落盘的 `<槽根>/_shiguan_slots.json`（按槽名索引）。
        """
        return self._fmt_device_mtime(self._slot_device_mtime_raw(path))

    def _mmdd(self, s):
        """`2026-09-21 20:18` / `09-21 20:18` / `Sep 21 20:18` 都归一成 `09-21 20:18`。

        先过一遍 `_fmt_device_mtime`（它认得 `Sep 21 20:18` 那种 adb `ls -l` 格式），
        再砍掉四位年份 —— 两侧都用这一个函数，格式差就不会被误判成「缓存旧了」。
        """
        import re as _re
        t = self._fmt_device_mtime(s)
        m = _re.search(r"(\d{1,2}-\d{1,2} \d{1,2}:\d{2})$", t)
        if not m:
            return t
        d, tm = m.group(1).split(" ")
        mm, dd = d.split("-")
        return "%02d-%02d %s" % (int(mm), int(dd), tm)

    def _cache_stale(self, local, live_mtime):
        """本机缓存里那个**剧本名**是不是可能已经过期了？

        ★ 2026-09-22 修（B 批第 4 条）：槽列表里显示的剧本名读的是**本机缓存**
          （`_local_scenario`），而旁边的「游戏写入」时间读的是**设备实时** ——
          两者来源不同。若你在模拟器里又玩过、却没重新拉档，缓存里的剧本名
          可能已经换了一本，但列表上看着毫无异常。

        **判据**：设备目录时间（= 游戏最近一次写这个槽的时刻）与本机拉档时
        记下的 `device_mtime` 不一致 ⇒ 拉档之后游戏又写过 ⇒ 缓存旧了。
        资料不足（没拉过档 / 没记录）时返回 False —— **宁可不说，也不乱报**。
        """
        if not local or not live_mtime:
            return False
        snap = self._slot_device_mtime_raw(local)
        if not snap:
            return False
        return self._mmdd(snap) != self._mmdd(self._fmt_device_mtime(live_mtime))

    @staticmethod
    def _local_mtime(path):
        """目录 mtime → `MM-DD HH:MM`（这份缓存什么时候落到本机的）。"""
        import time as _t
        try:
            return _t.strftime("%m-%d %H:%M", _t.localtime(os.path.getmtime(path)))
        except Exception:
            return ""

    def local_slot_dir(self, slot):
        """槽名 → 本机缓存目录（`D:\\DevCache\\dzlgz\\Save_All_N`）；没有返回空串。

        ★ 拉档前先看本机有没有同名缓存：有就能立刻读出**具体剧本名**
          （`秦末起义 · 前 209`），也能直接当续谱的数据源；没有就得先拉档。
        """
        base_name = os.path.basename(str(slot or "").strip())
        if not base_name:
            return ""
        for base in RECORD_BASES:
            cand = os.path.join(base, base_name)
            if os.path.isdir(cand):
                return cand
        return ""

    def emulator_slot_rows(self, log=None):
        """扫模拟器上的存档槽 → `([(槽名, 说明, 可选, 本机目录)], 错误文本)`。

        加密槽给 `可选=False`，对话框会置灰并提示「在游戏里载入它、过一回合」。

        ★ `payload` 必须是**本机目录路径**，不能是槽名 ——
          对话框拿它去读剧本、定目标谱牒（`plan_extend_target` 里会 `isdir`）。
          2026-09-22 这里曾经错传槽名，于是「目标谱牒」永远显示
          「认不出这个槽是哪个剧本」，「先演习 / 备份并写回」两个按钮全灰 ——
          使用者报的就是这个（他以为是模拟器没 root，其实跟 root 无关）。
          本机还没拉过这个槽时 payload 是空串，对话框会走「先拉档再认」那条路。
        """
        def say(s):
            if log:
                log(s)
        try:
            from tools import sync_from_mumu as SM
        except Exception as e:
            return [], f"读不到同步脚本：{e}"
        adb = SM.find_adb()
        if not adb:
            return [], "找不到 adb —— 请确认 MuMu 模拟器 12 装着。"
        say("连接模拟器（要 root，约几秒）...")
        if not SM.connect(adb, root=True):
            return [], "连不上模拟器 —— 请确认 MuMu 正在运行，然后点「重扫模拟器」。"
        say("扫描存档槽 ...")
        slots = SM.list_slots(adb, with_meta=True)
        if not slots:
            return [], "模拟器里没扫到任何存档槽。"
        rows = []
        for label, folder, slot, meta in slots:
            enc = bool(meta.get("enc"))
            local = self.local_slot_dir(slot)
            bits = []
            if enc:
                bits.append("加密")     # 使用者：加密就写加密，无需写读不了
            else:
                # 本机缓存里若已有同名槽，就能读出**具体剧本名**（`秦末起义 · 前 209`）；
                # 还没拉下来的槽读不到（文件在模拟器里），退回两档粗判或干脆不写。
                scen = self._local_scenario(local) if local else ""
                if scen:
                    # ★ 2026-09-22 修（B 批第 4 条）：这个剧本名来自**本机缓存**，
                    #   而下面那行「游戏写入」来自**设备实时**。拉档之后你若又在
                    #   模拟器里玩过，缓存里的剧本名可能已经换了本，列表却看不出来。
                    #   两者时间不一致就把话说透，别让人把旧名字当成当前剧本。
                    if self._cache_stale(local, meta.get("mtime")):
                        bits.append(scen + "（按本机旧缓存，可能已变）")
                    else:
                        bits.append(scen)
                else:
                    era = self._local_era(slot)
                    if era:
                        bits.append(era)
                bits.append(f"{meta.get('files', '?')} 个表文件")
                if not local:
                    bits.append("还没拉到本机")
            if meta.get("mtime"):
                # 设备上的目录时间 = 游戏写这个档的时刻（`Sep 21 23:25` → `09-21 23:25`）
                bits.append("游戏写入 " + self._fmt_device_mtime(meta["mtime"]))
            rows.append((slot, " · ".join(bits), not enc, local))
        return rows, ""

    def extend_book(self):
        """顶栏「⟲ 续谱」（Ctrl+R）：拉档 → 抽取 → 增量合并写回谱牒。"""
        from app.dialogs import forms
        forms.extend_dialog(self)

    # ------------------------------------------------ 续谱：槽 → 目标谱牒
    def slot_book_name(self, slot_path):
        """实录槽 → `(目标谱牒名, 剧本名, 争霸类型)`。

        ★ 使用者 2026-09-21 拍板的核心诉求：**续谱不该要求谱牒先存在**。
          从槽里读出剧本（`detect_start_year` = 剧本开局年），
          目标谱牒名就是 `剧本名·争霸类型`（如《秦末起义·沙盒全局》）。
        认不出剧本时三个都返回空串，由调用方要求手动指定。
        """
        from app import scenarios as SC
        from tools import import_from_game as IM
        from tools import sync_from_mumu as SM
        base = os.path.basename(os.path.normpath(slot_path or ""))
        if not base:
            return "", "", ""
        mode = SM.slot_mode(base)
        try:
            year = IM.detect_start_year(slot_path)
        except Exception:
            year = None
        if year is None:
            return "", "", mode
        scen = SC.scenario_of(year, mode)
        if not scen:
            return "", "", mode
        return SC.book_name(year, mode), scen, mode

    def protected_owner_of_scenario(self, scen):
        """哪个**保护档**认得出同一个剧本 → 返回谱牒名（没有则空串）。

        按剧本名对而不是按谱牒名对 —— 保护档《文王治岐》不带「·沙盒全局」后缀，
        而自动推导出来的名字是《文王治岐·沙盒全局》，字符串比不中。
        """
        if not scen:
            return ""
        from app import scenarios as SC
        for nm in storage.list_saves():
            try:
                if storage.is_protected(nm) and SC.match_name(nm) == scen:
                    return nm
            except Exception:
                continue
        return ""

    def plan_extend_target(self, slot_path, manual="", force_new=False):
        """续谱该写到哪部谱牒 —— 核心诉求的落地点（对话框与验收脚本共用）。

        返回 dict：`action` / `name` / `scen` / `mode` / `note`
          new       目标谱牒不存在 → 整档新建
          extend    已存在且不是保护档 → 增量续写
          skip      命中保护档（《上古时代》《文王治岐》这种手写原始记录）→ 跳过
          conflict  同名谱牒已经绑在**别的**槽上 → 让使用者选续写它 / 另存新的
          none      认不出剧本且没手动指定 → 做不了
        """
        manual = (manual or "").strip()
        if manual:
            manual = storage.sanitize_name(manual)
        name, scen, mode = self.slot_book_name(slot_path)
        if manual:
            exists = os.path.exists(storage.save_path(manual))
            if not exists:
                return {"action": "new", "name": manual, "scen": scen, "mode": mode,
                        "note": f"手动指定：新建《{manual}》"}
            if storage.is_protected(manual) and not force_new:
                return {"action": "skip", "name": manual, "scen": scen, "mode": mode,
                        "note": f"《{manual}》是保护档 —— 自动续谱跳过它。"
                                "（点「① 先演习」可以先拉档看报告；要真写就先取消保护，"
                                "或换个谱牒名）"}
            return {"action": "extend", "name": manual, "scen": scen, "mode": mode,
                    "note": f"手动指定：续写《{manual}》"}
        if not name:
            return {"action": "none", "name": "", "scen": "", "mode": mode,
                    "note": "认不出这个槽是哪个剧本 —— 请勾「手动指定目标谱牒」。"}
        owner = self.protected_owner_of_scenario(scen)
        if owner and not force_new:
            return {"action": "skip", "name": owner, "scen": scen, "mode": mode,
                    "note": f"《{owner}》是你的手写原始记录（保护档），自动续谱跳过它。"
                            "（点「① 先演习」可以先拉档看报告；要真写就先取消它的保护，"
                            "或勾「手动指定目标谱牒」换一部）"}
        if not os.path.exists(storage.save_path(name)):
            return {"action": "new", "name": name, "scen": scen, "mode": mode,
                    "note": f"将自动新建《{name}》"}
        if force_new:
            return {"action": "new", "name": name, "scen": scen, "mode": mode,
                    "note": f"另存为新谱牒《{name}》"}
        # 已存在 —— 看它绑的是不是同一个槽
        try:
            src = storage.load_source(name) or {}
        except Exception:
            src = {}
        bound = os.path.basename(str(src.get("slot") or src.get("slot_path") or ""))
        cur = os.path.basename(os.path.normpath(slot_path or ""))
        if bound and cur and bound != cur:
            return {"action": "conflict", "name": name, "scen": scen, "mode": mode,
                    "note": f"《{name}》已经绑在 {bound} 上，这个槽却是 {cur}。"}
        return {"action": "extend", "name": name, "scen": scen, "mode": mode,
                "note": f"将续写《{name}》"}

    def free_book_name(self, name):
        """给「另存为新谱牒」找一个没被占用的名字（`X (2)`、`X (3)`…）。"""
        base = storage.sanitize_name(name) or "新谱牒"
        if not os.path.exists(os.path.join(storage.SAVES_DIR, base)):
            return base
        i = 2
        while os.path.exists(os.path.join(storage.SAVES_DIR, f"{base} ({i})")):
            i += 1
        return f"{base} ({i})"

    def extend_slot(self):
        """这份谱牒该配哪个实录槽 —— 续谱的数据源。配不上返回空串。"""
        if self.current_save:
            p = self._slot_for_save(self.current_save)
            if p:
                return p
        return self.record_slot.root if self.record_slot is not None else ""

    def extend_options(self, name=""):
        """续谱的抽取口径 —— **继承谱牒建档时的口径**（source.prune）。

        必须继承：秦末档建档用的是 hist（3233 人），若续谱用默认 anon，
        新抽会变成 9000+ 人，凭空多出几千个不相干的人物。
        没有或不合法就退回 hist（只收史实，最保守）。

        `name` 缺省用当前谱牒；自动续谱写到**别的**谱牒时传目标名，
        否则会拿错口径（新建的谱牒没有 source，会退回 hist，正好是对的）。
        """
        try:
            src = storage.load_source(name or self.current_save) or {}
        except Exception:
            src = {}
        prune = str(src.get("prune") or "")
        if prune not in ("none", "male-son", "anon", "hist"):
            prune = "hist"
        return prune, bool(src.get("real_state_only", True))

    def run_extend(self, apply=False, prune="", pull_slot="", log=None,
                   target="", create=False, slot_path="", real_state=None,
                   auto=False, manual="", progress=None, force=False):
        """续谱的实际干活函数（对话框与验收脚本共用，本身不弹窗）。

        顺序不能变：
          1. 先把内存里的改动落盘 —— 子进程读的是**文件**，不落盘就丢最近的编辑
          2. 从模拟器拉 `pull_slot` 那个槽并落位（失败不中断，继续用本机已有的档）
          3. 定目标谱牒：`auto` 或**这次真拉了档** → 按槽里现在的剧本重推一遍
          4. 子进程跑 import_from_game.py：
               create=False → `--merge [--apply]`（增量续写已有的谱牒）
               create=True  → 整档导入：演习不带 `--save`（只出统计、不落盘），
                              写回带 `--save <目标名>`（**自动新建**这部谱牒）
          5. 写盘成功后切到目标谱牒 → load_data() → _record(...) → _refresh_all()
             （`_record` 的约定是**改完再记**，撤销才一步回到续谱前）

        返回 (ok, 文本)。`log` 是可选回调，把进度实时贴进对话框；
        `progress` 是可选回调 `(第几步, 文案)`，给进度条用。

        `auto=True`：目标谱牒**先不定**，等拉完档再按槽里的剧本推
        （槽还没拉到本机时读不出剧本，只能这么办）。

        ★ 2026-09-22 使用者：「脚本从模拟器拉取存档的时候，经常把剧本读成别的剧本」。
          真根因之一就在这里：本机缓存是**旧**的时候，目标谱牒是用旧缓存算好的，
          拉档把本机文件换成新的之后却仍按旧目标写 —— **写错谱牒**。
          所以现在只要**这次真拉了档**（`pulled`），就按新档重推一遍目标。
          `manual` 是「手动指定目标谱牒」的名字：给了它就以它为准，
          重推也只是把它再过一遍 `plan_extend_target`（结论一致，顺带重查一次存在性）。

        定下来的目标会记进 `self._extend_last`，供对话框写回时引用。
        """
        import re as _re

        def say(s):
            logger.info(s)
            if log:
                log(s)

        def step(n, text):
            if progress:
                try:
                    progress(n, text)
                except Exception:
                    pass

        if not self.current_save and not target:
            return False, "还没有谱牒档（saves/ 为空），先建一个。"

        # 1. 内存 → 磁盘
        step(1, "保存当前谱牒 ...")
        if not self.save_data():
            return False, "保存谱牒失败，已中止（不动任何文件）。"

        slot = slot_path or self.local_slot_dir(pull_slot) or self.extend_slot()
        out_dir = (os.path.dirname(slot) if slot
                   else (RECORD_BASES[0] if RECORD_BASES else ""))

        # 2. 拉档（续谱的第一步；失败不中断）
        pulled = False
        if pull_slot:
            sync_py = os.path.join(BASE_DIR, "tools", "sync_from_mumu.py")
            if os.path.exists(sync_py):
                step(2, f"从模拟器拉取 {pull_slot} ...")
                say(f"── 从模拟器拉取 {pull_slot} ──")
                rc, out = self._run_child(
                    [sys.executable, sync_py, "--pkg", "mi", "--overwrite",
                     "--out", out_dir, "--only-slot", pull_slot], 900)
                say(out)
                if rc != 0:
                    say("（拉档失败或模拟器没开 —— 继续用本机已有的存档续谱）")
                else:
                    # ★ 拉档落位成功 → 把这个槽名从「已移除」名单里放回来。
                    #   否则使用者「移除」过 Save_All_N 之后重新拉一份同名档，
                    #   会被 hidden_slots 一直挡着，谱牒 ↔ 实录 的对应就断了。
                    if self.unhide_record_slot(pull_slot):
                        say(f"（{pull_slot} 曾被移除，已自动放回列表）")
                    self.scan_record_slots()
                    newp = os.path.join(out_dir, pull_slot)
                    if os.path.isdir(newp):
                        slot = newp
                        self.open_record(newp)
                        pulled = True

        if not slot or not os.path.isdir(slot):
            return False, ("没有可用的实录槽。\n"
                           "请在上面选一个槽，或先在「存档」里整档导入一次。")

        # 3. 定目标谱牒 + 抽取口径
        if auto or pulled:
            # 槽刚拉到本机（或刚被新档覆盖）——现在读得出**这一份**的剧本，按它定目标。
            plan = self.plan_extend_target(slot, manual)
            if plan["action"] not in ("new", "extend"):
                return False, plan["note"] or "这个槽认不出对应的剧本，请勾「手动指定目标谱牒」。"
            new_target, new_create = plan["name"], plan["action"] == "new"
            if auto:
                say(f"── 按槽里的剧本定下目标谱牒：《{new_target}》"
                    + ("（新建）" if new_create else "（续写）"))
            elif manual:
                say(f"── 按你指定的名字定下目标谱牒：《{new_target}》"
                    + ("（新建）" if new_create else "（续写）"))
            elif (new_target, new_create) != (target, create):
                # 旧缓存与新档不是同一盘 —— 明说改成了哪一部，别让人以为还是原来那个
                say(f"── 拉档后重新认定：目标谱牒改为《{new_target}》"
                    + ("（新建）" if new_create else "（续写）")
                    + "　（本机原来那份是别的剧本）")
            target, create = new_target, new_create
        if not target:
            target = self.current_save
            create = False
        self._extend_last = {"target": target, "create": create}
        if prune:
            real_state = True if real_state is None else bool(real_state)
        else:
            prune, inherit_real = self.extend_options("" if create else target)
            if real_state is None:
                real_state = inherit_real

        importer = os.path.join(BASE_DIR, "tools", "import_from_game.py")
        if not os.path.exists(importer):
            return False, f"找不到抽取脚本：\n{importer}"
        cmd = [sys.executable, importer, "--src", slot, "--prune", prune]
        if create:
            # 整档导入：演习**不给 --save** → 脚本只统计不落盘；
            # 写回才给 --save → 自动新建这部谱牒（source 由脚本写全）。
            if apply:
                cmd += ["--save", target]
        else:
            cmd += ["--save", target, "--merge"]
            if apply:
                cmd.append("--apply")
            # ★ 2026-09-24 使用者报「让游戏自动跑了一会，续不上存档了」：
            #   脚本有个人数比保险（新抽 / 谱牒 > 2 倍或 < 0.5 就拦，防口径不一致
            #   灌进几千个路人）。但**世界正常长大**也会触发它（实测续谱名单的
            #   父系后裔链从 ~98 人涨到 402 人 → 483 vs 116 = 4.16 倍）。
            #   原来这道闸在 GUI 里**无路可走** —— 脚本只回一句「请在命令行加
            #   --force」，对话框上没有可点的入口。现在对话框给「强行继续」勾选，
            #   勾了就把 --force 透传给脚本（演习与写回都传，两趟口径一致）。
            if force:
                cmd.append("--force")
        if real_state:
            cmd.append("--real-state-only")
        watch = sorted(self.followed_codes())
        if watch:
            cmd += ["--watch", ",".join(watch)]
        step(3, ("抽取人物各表 + 定世代 + 宗庙爵位 ..." if not create
                 else f"读人物各表并汇总《{target}》..."))
        say("── " + ("整档新建" if create else "增量续写") + "《" + target + "》"
            + ("· 写回" if apply else "· 演习") + " ──")
        rc, out = self._run_child(cmd, 900)
        say(out)
        if rc == 2:
            return False, (out + "\n\n（人数比闸门拦下：新抽与谱牒相差 2 倍以上。\n"
                                 "  核对上面的报告无误后，勾上「强行继续」再点「① 先演习」。）")
        if rc != 0:
            return False, out

        # 4. 写回成功后重读 + 进撤销栈
        if apply:
            step(4, "刷新界面 ...")
            m = _re.search(r"新增\s+(\d+)\s+人", out)
            m2 = _re.search(r"更新\s+(\d+)\s+人", out)
            add = m.group(1) if m else "?"
            upd = m2.group(1) if m2 else "?"
            if create:
                mt = _re.search(r"人物总数\s+(\d+)", out)
                add = mt.group(1) if mt else "?"
                upd = "0"
            if target != self.current_save:
                self.switch_save(target)     # 内部会 load_data + _refresh_all
                self.history.record(f"自动续谱：新建《{target}》{add} 人"
                                    if create else f"自动续谱：{target} 新增 {add} 更新 {upd}",
                                    self.people, self.cutoff_person)
            else:
                self.load_data()
                self._record(("自动续谱（整档新建）：%s 人" % add) if create
                             else f"自动续谱：新增 {add} 更新 {upd}")
                self._refresh_all()
            step(5, "完成")
        return True, out

    @staticmethod
    def _run_child(cmd, timeout):
        """跑子进程并回传 (退出码, 合并后的输出文本)。"""
        import subprocess
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        try:
            p = subprocess.run(cmd, capture_output=True, timeout=timeout,
                               cwd=BASE_DIR, env=env)
        except Exception as e:
            return 1, f"启动失败：{e}"
        out = (p.stdout or b"").decode("utf-8", "replace")
        err = (p.stderr or b"").decode("utf-8", "replace")
        if err.strip():
            out += "\n[stderr]\n" + err
        return p.returncode, out

    def open_settings(self):
        from app.dialogs import forms
        forms.settings_dialog(self)

    def open_theme_picker(self):
        from app.dialogs import forms
        forms.theme_picker_dialog(self)

    def ai_recognize(self):
        from app.dialogs import forms
        forms.ai_dialog(self)

    def _init_detector(self):
        try:
            from ai_recognizer import AIDetector, DOUBAO_VISION_MODEL
        except Exception as e:
            logger.info(f"AI 模块不可用: {e}")
            self.detector = None
            return
        cfg = load_config()
        key = cfg.get("doubao_api_key", "")
        if key:
            self.detector = AIDetector(api_key=key, model=DOUBAO_VISION_MODEL, provider="doubao")
            return
        # ★ 代码改进 A14：deepseek-chat 不支持图像输入，那条装配路径必报错，
        #   删除（DeepSeek Key 仍留在 config 里不影响其他功能）。
        self.detector = None


def _log_tk_exception(exc_type, exc, tb):
    """Tk 回调异常落日志 —— 画布「卡住/不加载」类问题以前被 Tk 静默吞掉，
    现在会在 shiguan.log 里看到完整堆栈（2026-09-26 加）。"""
    logger.error("Tk 回调异常", exc_info=(exc_type, exc, tb))


def main():
    # ★ 2026-09-30（任务栏图标）：必须在建窗口**之前** —— 见函数说明
    _set_app_user_model_id()
    root = tk.Tk()
    root.report_callback_exception = _log_tk_exception
    app = ShiguanApp(root)
    # ★ 2026-09-30 使用者要求「**脚本默认全屏**」。
    #   用 `state("zoomed")`（最大化）而不是 `-fullscreen`：保留标题栏与
    #   还原按钮，桌面工具这样才好用（真全屏要按 Esc 才出得来，容易以为死机）。
    #   ⚠️ 必须放在 `ShiguanApp(root)` **之后** —— 构造里会按 config 恢复
    #   上次的窗口几何，先 zoomed 会被它覆盖掉。
    try:
        root.state("zoomed")
    except tk.TclError:
        pass          # 非 Windows / 某些 WM 不支持 —— 保持构造里设的尺寸
    argv = sys.argv[1:]
    # --goto 编号：启动后直接跳到实录层这个人的档案（M0 桥的 CLI 约定保留）
    if "--goto" in argv:
        try:
            code = argv[argv.index("--goto") + 1]
        except IndexError:
            code = ""
        if code:
            root.after(400, lambda: app.open_viewer_code(code))
    root.mainloop()


if __name__ == "__main__":
    main()
