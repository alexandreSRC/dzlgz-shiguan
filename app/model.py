"""人物数据模型。

设计原则（保证"现有逻辑不变"）：
  * 人物记录仍然是普通 dict，JSON 结构一字不改，老存档 100% 兼容
  * 字段名集中在这里声明，消灭散落在视图里的魔法字符串
  * 迁移逻辑逐行照搬 v1，只做"位置搬迁"，不改判定

对外只暴露模块级函数，第一个参数统一是 people 字典，方便单测与快照比对。
"""
import logging
import re

from .theme import TIER_NAMES

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------- 字段定义

# 人物记录字段 → 默认值
FIELD_DEFAULTS = {
    "father": "",
    "mother": "",
    "color": "",
    "bg_color": "",
    "note": "",
    "gender": "男",
    "generation": 1,
    "historical": "否",
    "divine": "否",
    "birth": "",
    "death": "",
    "rank": 0,
    "spouses": None,        # list，用 None 占位（不能用可变默认值）
    "state_group": "",
    "state_name": "",
    "fief_title": "",
    "fief_gen": 0,
    "root_sort": 0,
    "bio": "",
}

# 列表类字段
LIST_FIELDS = ("spouses",)

# 表格视图列定义：(字段键, 表头, 宽度, 是否派生只读)
TABLE_COLUMNS = [
    ("__seq__",       "序号",        44,  True),
    ("__name__",      "姓名",        130, True),
    ("gender",        "性别",        46,  False),
    ("generation",    "代数",        44,  False),
    ("rank",          "排行",        44,  False),
    ("father",        "父亲",        80,  False),
    ("mother",        "母亲",        74,  False),
    ("spouses",       "配偶",        84,  False),
    ("fief_title",    "爵位",        48,  False),
    ("state_name",    "封国",        60,  False),
    ("fief_gen",      "君序",        48,  False),
    ("root_sort",     "祖序",        44,  False),
    ("note",          "尊号 · 谥号", 124, False),
    ("historical",    "史实",        46,  False),
    ("divine",        "神祖",        46,  False),
    ("__bio__",       "介绍",        56,  True),
    ("__life__",      "生年 / 卒年", 90,  True),
]


def new_person(**overrides):
    """按字段定义生成一条规范的人物记录。"""
    record = {}
    for key, default in FIELD_DEFAULTS.items():
        record[key] = list(default) if key in LIST_FIELDS and default is not None else default
    for key in LIST_FIELDS:
        if record.get(key) is None:
            record[key] = []
    record.update(overrides)
    return record


# ---------------------------------------------------------------- 关系查询

def get_children(people, person):
    """直接子嗣（父或母任一方命中）。"""
    return [name for name, info in people.items()
            if info.get("father") == person or info.get("mother") == person]


def get_descendants(people, person):
    """全部后裔（不含本人）。"""
    found = set()
    queue = [person]
    while queue:
        cur = queue.pop(0)
        for child in get_children(people, cur):
            if child not in found:
                found.add(child)
                queue.append(child)
    return found


def get_subtree(people, person):
    """本人 + 全部后裔。"""
    return {person} | get_descendants(people, person)


def root_ancestor(people, name):
    """一路向上找到所在宗支的始祖。"""
    cur = name
    guard = 0
    while cur in people and guard < len(people) + 1:
        guard += 1
        dad = people[cur].get("father", "")
        mom = people[cur].get("mother", "")
        if dad and dad in people:
            cur = dad
        elif mom and mom in people:
            cur = mom
        else:
            break
    return cur


def would_create_cycle(people, person, new_parent):
    """把 person 挂到 new_parent 下会不会成环。"""
    if not new_parent or person == new_parent:
        return person == new_parent
    return new_parent in get_descendants(people, person)


def all_roots(people):
    """没有有效父/母的人（布局用的"始祖候选"）。"""
    roots = []
    for name in people:
        dad = people[name].get("father", "")
        mom = people[name].get("mother", "")
        if (not dad or dad not in people) and (not mom or mom not in people):
            roots.append(name)
    return roots


def tier_of(people, name):
    """→ 爵位字（帝/王/公…）；未知或空爵位回落"无"。
    （docstring 原写「(爵位, 颜色key)」与返回值不符 —— 2026-09-26 审查订正。"""
    tier = people.get(name, {}).get("fief_title", "")
    if not tier or tier not in TIER_NAMES:
        return "无"
    return tier


def num_to_chinese(n):
    """1→一 … 与 v1 完全一致；**100 起逐位读**（一〇〇 / 一〇一 / 一〇二）。

    ★ 2026-09-26 使用者要求：「代际家谱到 100 代写『一〇〇代』，101 写
      『一〇一代』，以此类推，不要阿拉伯数字」。原实现在 n ≥ 100 时直接
      `return str(n)`（画布上出现「100代」这种半土半洋的写法）。
    逐位读还有个好处：谱轴上一眼看得出「百位同段」（一〇〇…一〇九），
    而「一百零八」这种进位读法反而要心算。
    """
    chinese_nums = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]
    if n <= 10:
        return chinese_nums[n] if n > 0 else ""
    if n < 20:
        return "十" + chinese_nums[n - 10]
    if n < 100:
        return chinese_nums[n // 10] + "十" + (chinese_nums[n % 10] if n % 10 != 0 else "")
    # 逐位读（〇 用「〇」，不用「零」—— 谱轴上的习惯写法）
    digits = "〇一二三四五六七八九"
    return "".join(digits[int(ch)] for ch in str(n))


# ---------------------------------------------------------------- 变更操作

def cascade_state_change(people, person, state_name, state_group):
    """把封国信息级联给全部后裔，返回受影响人数。

    ★ 2026-09-23 联动：`lineage_name`（世系 = 君族）一并同步 —— 世系框认它。
    清空封国时不动世系（使用者：「世系中的谥号是很好的材料」）。
    """
    queue = get_children(people, person)
    count = 0
    while queue:
        child = queue.pop(0)
        if child in people:
            people[child]["state_name"] = state_name
            people[child]["state_group"] = state_group
            if state_name:
                people[child]["lineage_name"] = state_name
            queue.extend(get_children(people, child))
            count += 1
    if count:
        logger.info(f"封国信息级联更新: {person} → {count} 个后裔")
    return count


def shift_root_sorts(people, new_sort, old_sort=0, exclude_name=None):
    """祖序插入/移动时的自动位移（与 v1 一致）。"""
    if new_sort <= 0:
        return
    for name, info in people.items():
        if exclude_name and name == exclude_name:
            continue
        rs = info.get("root_sort", 0)
        if rs <= 0:
            continue
        if old_sort == 0:
            if rs >= new_sort:
                info["root_sort"] = rs + 1
        elif new_sort < old_sort:
            if new_sort <= rs < old_sort:
                info["root_sort"] = rs + 1
        elif new_sort > old_sort:
            if old_sort < rs <= new_sort:
                info["root_sort"] = rs - 1


def remove_people(people, names):
    """删除一批人物，并清理幸存者配偶列表里对他们的引用。"""
    gone = set(names)
    for name in gone:
        people.pop(name, None)
    for info in people.values():
        spouses = info.get("spouses", [])
        if any(s in gone for s in spouses):
            info["spouses"] = [s for s in spouses if s not in gone]


def rename_person(people, old_name, new_name):
    """把 old_name 改名为 new_name，并同步所有引用（父/母/配偶/同代人）。"""
    if old_name == new_name or new_name in people:
        return False
    for info in people.values():
        if info.get("father") == old_name:
            info["father"] = new_name
        if info.get("mother") == old_name:
            info["mother"] = new_name
        if info.get("associate_of") == old_name:
            info["associate_of"] = new_name
    for info in people.values():
        spouses = info.get("spouses", [])
        if old_name in spouses:
            info["spouses"] = [new_name if s == old_name else s for s in spouses]
    return True


# ---------------------------------------------------------------- 迁移

def normalize(people):
    """载入时的数据规范化/迁移。

    逐行照搬 v1 的 _migrate_old_data，只把 self.people 换成参数。
    返回 True 表示数据被改动过（调用方据此决定是否落盘）。
    """
    needs_save = False

    for name, info in people.items():
        changed = False

        # 同代人标记指向自己属于无效数据，会导致树上多出"友"字标记
        if info.get("associate_of") == name:
            info["associate_of"] = ""
            changed = True

        if info.get("state_name") is None:
            sg = info.get("state_group", "")
            if sg:
                tier = info.get("fief_title", "")
                if tier and sg.endswith(tier):
                    info["state_name"] = sg[:-len(tier)]
                else:
                    info["state_name"] = sg
                changed = True

        note = info.get("note", "")
        if note:
            m = re.search(r'^([\u4e00-\u9fff]+?)([公侯伯子男王卿无])([一二三四五六七八九十\d]+)代$', note)
            if m:
                state_name = m.group(1)
                tier = m.group(2)
                gen_str = m.group(3)
                if gen_str.isdigit():
                    gen = int(gen_str)
                else:
                    chn = "零一二三四五六七八九十"
                    gen = chn.index(gen_str) if gen_str in chn else 0
                if not info.get("fief_title"):
                    info["fief_title"] = tier
                    changed = True
                if not info.get("fief_gen") or info.get("fief_gen") == 0:
                    info["fief_gen"] = gen
                    changed = True
                if not info.get("state_name"):
                    info["state_name"] = state_name
                    changed = True
                info["note"] = note[m.end():].strip()
                changed = True
                logger.info(f"迁移: {name} 解析为 封国={state_name} 爵位={tier} 代数={gen} "
                            f"注释精简为'{info['note']}'")

            m2 = re.search(r'^([\u4e00-\u9fff]+?)国(伯|侯|公|王) ', note)
            if m2 and not info.get("state_name"):
                info["state_name"] = m2.group(1) + "国"
                info["fief_title"] = m2.group(2)
                changed = True
                info["note"] = note[m2.end():].strip()
                logger.info(f"迁移: {name} 解析 state_name={info['state_name']}")

        if info.get("state_name") and info.get("fief_title") and not info.get("state_group"):
            info["state_group"] = info["state_name"] + info["fief_title"]
            changed = True

        if changed:
            needs_save = True

    for info in people.values():
        if "birth_death" in info:
            val = info.pop("birth_death")
            if val:
                parts = val.split("--")
                info["birth"] = parts[0]
                info["death"] = parts[1] if len(parts) > 1 else ""
            else:
                info["birth"] = ""
                info["death"] = ""
            needs_save = True

    for info in people.values():
        if "root_sort" not in info:
            info["root_sort"] = 0
            needs_save = True

    for info in people.values():
        if "bio" not in info:
            info["bio"] = ""
            needs_save = True

    for name, info in people.items():
        if "spouses" not in info:
            if "spouse" in info:
                old_spouse = info.pop("spouse", "")
                info["spouses"] = [old_spouse] if old_spouse else []
            else:
                info["spouses"] = []
            needs_save = True
        elif isinstance(info.get("spouses"), str):
            info["spouses"] = [info["spouses"]] if info["spouses"] else []
            needs_save = True

        # 清除指向不存在人物的配偶引用（旧版本会把多配偶拼接成一条字符串写入）
        spouses = info.get("spouses", [])
        valid_spouses = [s for s in spouses if s in people]
        if valid_spouses != spouses:
            logger.info(f"迁移: {name} 移除无效配偶引用 "
                        f"{[s for s in spouses if s not in people]}")
            info["spouses"] = valid_spouses
            needs_save = True

    # 祖序重复时，按现有显示顺序重排为连续的 1..N（显示顺序不变，只让序号唯一）
    ranked = [(info.get("root_sort", 0), idx, name)
              for idx, (name, info) in enumerate(people.items())
              if info.get("root_sort", 0) > 0]
    if ranked:
        ordered = sorted(ranked, key=lambda item: (item[0], item[1]))
        if len({item[0] for item in ordered}) != len(ordered):
            logger.info(f"迁移: 祖序存在重复 {[item[0] for item in ordered]}，"
                        f"按显示顺序重排为 1..{len(ordered)}")
            for new_sort, (_, _, name) in enumerate(ordered, 1):
                people[name]["root_sort"] = new_sort
            needs_save = True

    if needs_save:
        # 封国名向下继承：父有封国而子无，则子继承
        # ★ 代码改进 B6（2026-09-22）：原实现对每个有封国的人**全表扫一遍**
        #   找亲子（O(n²)，八千人档白转几十万圈）；预建 father→children 索引后
        #   BFS，语义不变（子仍按 people 字典顺序入队）。
        kids_of = {}
        for _n, _info in people.items():
            _f = _info.get("father", "")
            if _f:
                kids_of.setdefault(_f, []).append(_n)
        queue = list(people.keys())
        while queue:
            cur = queue.pop(0)
            sn = people[cur].get("state_name", "")
            if sn:
                for p in kids_of.get(cur, ()):
                    if not people[p].get("state_name"):
                        people[p]["state_name"] = sn
                        queue.append(p)
                        logger.info(f"迁移: 子嗣 {p} 继承封国名 {sn}")

    return needs_save
