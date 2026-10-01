"""人物介绍生成器。

逐逻辑照搬 v1 的 generate_bio_segments / _tag_custom_bio，
只做"位置搬迁"，不改句子结构和染色规则。

输出格式：[(文本段, tag), ...]，其中 tag 取值：
  None        无染色
  "tag_person" 人物名深红
  "tag_state"  封国名深绿
  "tag_note"   尊号深红
  "tag_<爵位>"   爵位取对应爵位色
"""
import logging

logger = logging.getLogger(__name__)

TIER_COLORS = {
    "帝": "#8B0000", "王": "#B8860B", "公": "#9B30FF", "侯": "#0044FF",
    "伯": "#006600", "子": "#007777", "卿": "#222222", "无": "#666666",
}
DIVINE_NAME_COLOR = "#CC0000"


_FIELD_DEFAULTS = {
    "gender": "男",
    "father": "",
    "mother": "",
    "fief_title": "",
    "state_name": "",
    "note": "",
    "fief_gen": 0,
    "rank": 0,
    "bio": "",
    "associate_of": "",
    "associate_type": "clan",
}


def _with_defaults(info):
    """只补缺失字段的默认值，**不丢弃任何原有字段**。

    注意：早期版本这里写成"只保留白名单字段"，把 father/mother 一起丢掉了，
    导致人物介绍里"某某之子也"整段消失 —— 回归指纹工具抓到了这个 bug。
    """
    merged = dict(_FIELD_DEFAULTS)
    merged.update(info)
    return merged


def _combo(state, tier):
    """「封国 + 爵位」的合写，如 state="巢" tier="伯" → "巢伯"。"""
    if tier and tier != "无":
        return (state or "") + tier
    return state or ""


def _ref_segments(info, name):
    """引用他人的固定写法：{封国}{爵位}{姓名}（{尊号}）。

    相比 v1 有三处行文改动（信息不变）：
      1. 尊号从「姓名之前」挪到「姓名之后并用全角括号括起」——
         v1 直接拼成 `风公东夷龙神巢皇风巢皇之伯子也`，尊号与姓名首尾同字时读成一串。
      2. 尊号若与「封国+爵位」完全重复（如 巢伯 / 凤鸿帝）则不再重复输出，
         v1 会写成 `巢伯巢伯巢亚居之伯子也`。
      3. 无爵位时不再重复封国名前缀（v1 会写成 `风风燧人`）。
    """
    tier = info.get("fief_title", "") or ""
    state = info.get("state_name", "") or ""
    note = info.get("note", "") or ""
    has_tier = bool(tier and tier != "无")
    if state and not has_tier and name.startswith(state):
        # 无爵位时封国名紧贴姓名会读成「风风燧人」，而姓名首字已含封国名，直接省掉
        state = ""
    segs = []
    if tier and tier != "无" and state:
        segs.append((state, "tag_state"))
        segs.append((tier, f"tag_{tier}"))
    elif tier and tier != "无":
        segs.append((tier, f"tag_{tier}"))
    elif state:
        segs.append((state, "tag_state"))
    segs.append((name, "tag_person"))
    if note and note != _combo(state, tier):
        segs.append((f"（{note}）", "tag_note"))
    return segs


def generate_bio_segments(people, person):
    info = people.get(person, {})
    if not info:
        return [("", None)]
    info = _with_defaults(info)

    segments = []
    dad = info.get("father", "")
    mom = info.get("mother", "")
    tier = info.get("fief_title", "")
    state = info.get("state_name", "")
    fief_gen = info.get("fief_gen", 0)
    note = info.get("note", "")
    rank = info.get("rank", 0)

    segments.append((person, "tag_person"))
    has_dad = bool(dad and dad in people)
    has_mom = bool(mom and mom in people)

    kids = [n for n, i in people.items()
            if i.get("father") == person or i.get("mother") == person]
    kids.sort(key=lambda n: (people[n].get("rank", 0) or 999))
    sons = [n for n in kids if people[n].get("gender", "男") == "男"]
    daughters = [n for n in kids if people[n].get("gender", "男") == "女"]
    has_kids = bool(sons or daughters)
    child_label = "女" if info.get("gender", "男") == "女" else "子"

    is_layout_child = bool(info.get("associate_of", ""))

    if is_layout_child:
        assoc_type = info.get("associate_type", "clan")
        ref_name = info.get("associate_of", "")
        segments.append(("者，", None))
        if ref_name and ref_name in people:
            ref_info = _with_defaults(people[ref_name])
            gender = info.get("gender", "男")
            relation_map = {
                "spouse": "之妻也" if gender == "女" else "之夫也",
                "friend": "之友也",
                "clan": "之族人也",
            }
            relation_text = relation_map.get(assoc_type, "之族人也")
            segments.extend(_ref_segments(ref_info, ref_name))
            # v1 这里漏了句号，导致紧跟的「号曰…／受封于…」被读成同一句
            segments.append((relation_text + "。", None))
        else:
            segments.append(("同代人也。", None))
    elif has_dad:
        dad_info = _with_defaults(people[dad])

        all_brothers = [n for n, i in people.items()
                        if i.get("father") == dad and n in people
                        and people[n].get("gender", "男") == "男"]
        valid_ranks = [people[n].get("rank", 0) for n in all_brothers if people[n].get("rank", 0) > 0]
        max_rank = max(valid_ranks) if valid_ranks else 0

        rank_label = ""
        if rank >= 1 and child_label == "子":
            if rank == 1:
                rank_label = "伯子"
            elif rank == 2:
                rank_label = "仲子"
            elif max_rank > 2 and rank == max_rank:
                rank_label = "季子"
            elif rank >= 3:
                rank_label = "叔子"

        segments.append(("者，", None))
        segments.extend(_ref_segments(dad_info, dad))

        if has_mom:
            mom_info = _with_defaults(people[mom])
            segments.append(("与", None))
            segments.extend(_ref_segments(mom_info, mom))
            segments.append((f"之{child_label}也。", None))
        else:
            if rank_label:
                segments.append((f"之{rank_label}也。", None))
            else:
                segments.append((f"之{child_label}也。", None))
    elif has_mom:
        mom_info = _with_defaults(people[mom])
        segments.append(("者，", None))
        segments.extend(_ref_segments(mom_info, mom))
        segments.append((f"之{child_label}也。", None))
    else:
        segments.append(("者，古贤人也。", None))

    has_fief = tier and tier != "无"
    has_note = bool(note)
    clauses = []

    if has_fief:
        fief_clause = []
        if fief_gen == 1:
            if state:
                fief_clause.append(("受封于", None))
                fief_clause.append((state, "tag_state"))
                fief_clause.append(("，为第1代", None))
            else:
                fief_clause.append(("受封为第1代", None))
        elif fief_gen > 1:
            if state:
                fief_clause.append(("嗣", None))
                fief_clause.append((state, "tag_state"))
                fief_clause.append((f"，为第{fief_gen}代", None))
            else:
                fief_clause.append((f"嗣为第{fief_gen}代", None))
        else:
            if state:
                fief_clause.append(("为", None))
                fief_clause.append((state, "tag_state"))
            else:
                fief_clause.append(("为", None))
        fief_clause.append((tier, f"tag_{tier}"))
        clauses.append(fief_clause)

    # 尊号与「封国+爵位」完全重复时不再输出一遍（v1 会写成「为第1代帝，号曰凤鸿帝」）
    if has_note and note != _combo(state, tier):
        clauses.append([("号曰", None), (note, "tag_note")])

    if has_kids:
        kids_segments = []
        first_kid = True
        for child_name in sons:
            if first_kid:
                kids_segments.append(("生", None))
                first_kid = False
            else:
                kids_segments.append(("、", None))
            c_info = _with_defaults(people[child_name])
            c_tier = c_info.get("fief_title", "")
            c_state = c_info.get("state_name", "")
            if c_tier and c_tier != "无" and c_state:
                kids_segments.append((c_state, "tag_state"))
                kids_segments.append((c_tier, f"tag_{c_tier}"))
            kids_segments.append((child_name, "tag_person"))
        for child_name in daughters:
            if first_kid:
                kids_segments.append(("生女", None))
                first_kid = False
            else:
                kids_segments.append(("、", None))
            kids_segments.append((child_name, "tag_person"))
        clauses.append(kids_segments)

    if clauses:
        for i, cl in enumerate(clauses):
            if i > 0:
                segments.append(("，", None))
            for text, tag in cl:
                segments.append((text, tag))
        segments.append(("。", None))

    return segments


def bio_segments_for(people, person):
    """浮卡 / 介绍栏统一入口：有自定义介绍就回贴染色，否则用自动生成。"""
    info = people.get(person, {})
    custom = (info.get("bio") or "").strip()
    if custom:
        return _tag_custom_bio(people, person, custom)
    return generate_bio_segments(people, person)


def generate_bio(people, person):
    return "".join(text for text, _ in generate_bio_segments(people, person))


def _tag_custom_bio(people, person, text):
    """给自定义介绍文本回贴染色（尽力对齐自动生成的染色段）。与 v1 一致。"""
    if not person or person not in people:
        return [(text, None)]
    auto_segments = generate_bio_segments(people, person)
    auto_text = "".join(t for t, _ in auto_segments)
    if text == auto_text:
        return auto_segments
    char_tags = []
    for seg_text, tag in auto_segments:
        char_tags.extend([tag] * len(seg_text))
    result = []
    ai = 0
    ci = 0
    LOOKAHEAD = 50
    while ci < len(text):
        if ai < len(auto_text) and text[ci] == auto_text[ai]:
            tag = char_tags[ai] if ai < len(char_tags) else None
            if result and result[-1][1] == tag:
                result[-1] = (result[-1][0] + text[ci], tag)
            else:
                result.append((text[ci], tag))
            ai += 1
            ci += 1
        elif ai < len(auto_text):
            found = -1
            for k in range(ai + 1, min(ai + LOOKAHEAD, len(auto_text))):
                if auto_text[k] == text[ci]:
                    found = k
                    break
            if found >= 0:
                ai = found
            else:
                if result and result[-1][1] is None:
                    result[-1] = (result[-1][0] + text[ci], None)
                else:
                    result.append((text[ci], None))
                ci += 1
        else:
            if result and result[-1][1] is None:
                result[-1] = (result[-1][0] + text[ci], None)
            else:
                result.append((text[ci], None))
            ci += 1
    return result