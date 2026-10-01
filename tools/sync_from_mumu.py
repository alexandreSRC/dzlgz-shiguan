# -*- coding: utf-8 -*-
"""从 MuMu 模拟器直接同步《大周列国志》存档到本地。

    python tools/sync_from_mumu.py            # 同步（默认小米版 Save_All_1/100/2/3/4）
    python tools/sync_from_mumu.py --list     # 只列模拟器里有哪些槽，不拉取
    python tools/sync_from_mumu.py --dry-run  # 显示会做什么，不实际写盘

为什么能这么干（踩过的坑都写在下面）：

1. **存档在应用私有目录**，不在 /sdcard
   - 小米版：`/data/data/com.xinlanzaoyi.ztz.mi/files/2023011702767223_Save_Files\\Save_All_N`
   - 普通版：`/data/data/com.xinlanzaoyi.ztz/files/17346581644_Save_Files\\Save_All_N`
   - 注意那个 **反斜杠是目录名的一部分**（游戏故意写的），不是路径分隔符。
     用 `?` 通配符能匹配到它，直接写 `\\` 会被 shell 吃掉。

2. **必须 root**：读 /data/data 需要。MuMu 12 的 adb 可以直接 `adb root`。
   （实测：`adb root` 后 `id` = uid=0(root)，KernelSU 也在但用不上。）

3. **PowerShell 每次调用 adb 都会重启 daemon**，设备连接随之丢失，
   表现为 `adb: device 'xxx' not found`。所以每一步都要
   `start-server → connect → (root) → connect` 连在一起做。

4. **adb pull 的目标路径不能带中文** —— adb 按 GBK 解释 argv，
   中文目录会让它报 `cannot create file/directory`。必须先 cd 到纯英文目录
   再用相对路径。

5. **存档文件是 UTF-8**。用 GBK 读会乱码（"苗" 会变成 "鑻?"）。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# ---- MuMu 相关常量 ---------------------------------------------------------
MUMU_ROOT = r"D:\Program Files\Netease\MuMu Player 12"
ADB_CANDS = [
    os.path.join(MUMU_ROOT, "shell", "adb.exe"),
    os.path.join(MUMU_ROOT, "nx_main", "adb.exe"),
    os.path.join(MUMU_ROOT, "nx_device", "15.0", "shell", "adb.exe"),
    os.path.join(MUMU_ROOT, "nx_device", "12.0", "shell", "adb.exe"),
]
ADB_PORT = 16416          # MuMu 12 默认实例的 adb 端口（可用 mumu_info() 查）

# 两个包：小米版优先（存档多），普通版只有 Save_All_1
PACKAGES = [
    ("com.xinlanzaoyi.ztz.mi", "2023011702767223_Save_Files", "小米版"),
    ("com.xinlanzaoyi.ztz", "17346581644_Save_Files", "普通版"),
]

# 本地存档根（GUI 的 DEFAULT_BASES 第一项）
LOCAL_BASE = r"D:\DevCache\dzlgz"

# ---- 争霸类型 ←→ 存档号段 ---------------------------------------------------
# 游戏里 4 种争霸类型 × 5 个存档位 = 20 个槽，靠号段区分。
#
# ★ 2026-09-22 使用者纠正：**1000 段与 5000 段原先判反了**。
#   他给的实机截图（游戏里逐个页签点开看的）：
#     「争霸模式」页签 → 荆楚吴越 · 周 · 公元前771年 · 2026-09-21 20:27 → Save_All_1001
#     「家族模式」页签 → 世代替缨 · 博陆侯 · 公元前86年 · 2026-09-21 20:29 → Save_All_5001
#   原表拿「国家数 / 四表人数」猜（1001 只有 3 国 122 人 → 猜成家族模式），
#   猜反了：**国家少恰恰是争霸模式**（局部几国争霸），家族模式反而是大世界里的一个家族。
#
#   槽              剧本     国家数  四表人数   判定
#   Save_All_1      秦末      151     8972     沙盒全局（全世界都在这盘里）
#   Save_All_1001   荆楚吴越    3      122     争霸模式（使用者实机截图确认）
#   Save_All_4001   卫氏朝鲜    7     2579     沙盒局部（卫氏朝鲜）
#   Save_All_5001   世代替缨   76     9360     家族模式（使用者实机截图确认）
#
# 每类占一个千位段；表里没有的号段一律归「未识别模式」，照样列出来、不隐藏。
MODE_RANGES = (
    (1, 999, "沙盒全局"),
    (1000, 1999, "争霸模式"),
    (4000, 4999, "沙盒局部"),
    (5000, 5999, "家族模式"),
)
MODE_UNKNOWN = "未识别模式"
MODE_ORDER = ("沙盒全局", "沙盒局部", "家族模式", "争霸模式", MODE_UNKNOWN)


def slot_mode(slot):
    """存档槽 → 争霸类型。表里没有的号段归「未识别模式」。"""
    m = re.search(r"Save_All_(\d+)", str(slot or ""))
    if not m:
        return MODE_UNKNOWN
    n = int(m.group(1))
    for lo, hi, name in MODE_RANGES:
        if lo <= n <= hi:
            return name
    return MODE_UNKNOWN


def slot_number(slot):
    m = re.search(r"Save_All_(\d+)", str(slot or ""))
    return int(m.group(1)) if m else 0


def find_adb():
    for p in ADB_CANDS:
        if os.path.isfile(p):
            return p
    return None


def run(adb, args, timeout=120):
    """跑一次 adb。返回 (ok, stdout)。"""
    try:
        r = subprocess.run([adb] + args, capture_output=True, timeout=timeout)
        out = (r.stdout or b"").decode("utf-8", "replace")
        err = (r.stderr or b"").decode("utf-8", "replace")
        return r.returncode == 0, (out + err)
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as e:
        return False, str(e)


SERIAL = f"127.0.0.1:{ADB_PORT}"


def run_dev(adb, args, timeout=120):
    """带 -s 的 adb 调用。

    ⚠️ 必须带 -s：模拟器里往往同时挂着两个设备（`127.0.0.1:16416` 和
    `emulator-5556`），不带 -s 会报 "more than one device/emulator"。
    """
    return run(adb, ["-s", SERIAL] + args, timeout=timeout)


def connect(adb, root=False):
    """连上模拟器。root=True 时顺带 adb root。

    **每次 adb 调用都要重连** —— 会话一换，daemon 就重启，连接丢失。
    """
    run(adb, ["start-server"], timeout=30)
    time.sleep(0.4)
    ok, msg = run(adb, ["connect", SERIAL], timeout=30)
    time.sleep(0.6)
    if root:
        run_dev(adb, ["root"], timeout=30)
        time.sleep(0.8)
        run(adb, ["connect", SERIAL], timeout=30)
        time.sleep(0.4)
    return ok


def adb_shell(adb, cmd, root=True, timeout=120):
    connect(adb, root=root)
    return run_dev(adb, ["shell", cmd], timeout=timeout)


def list_slots(adb, with_meta=False):
    """列出模拟器里实际存在的存档槽。

    返回 `[(pkg_label, folder, slot, meta), ...]`，按号段排序。
    `meta = {"files": n, "mtime": "MM-DD HH:MM", "enc": bool}`；
    `with_meta=False` 时 meta 为空 dict（老行为，只列名字）。

    ★ 为什么一次 shell 调用拿全部：`adb_shell` 每次都做一遍
      `start-server → connect → root → connect` 的连接舞（实测很慢），
      20 个槽逐个查会慢到没法用，所以用一个 for 循环在远端一次问完。
    """
    found = []
    for pkg, folder, label in PACKAGES:
        base = f"/data/data/{pkg}/files"
        # 用 ? 通配那个反斜杠目录名（游戏自己的路径 bug）
        if not with_meta:
            ok, out = adb_shell(adb, f"ls -d {base}/{folder}?Save_All_* 2>/dev/null")
            for line in out.splitlines():
                line = line.strip()
                if not line.endswith("/") and "Save_All_" in line:
                    slot = line.rsplit("Save_All_", 1)[-1]
                    if slot.isdigit():
                        found.append((label, folder, f"Save_All_{slot}", {}))
            continue
        cmd = ("for d in " + base + "/" + folder + "?Save_All_*; do "
               "n=$(ls \"$d\" 2>/dev/null | wc -l); "
               "t=$(ls -ld \"$d\" 2>/dev/null | awk '{print $6\" \"$7}'); "
               "e=$(ls \"$d\" 2>/dev/null | head -1); "
               "echo \"$d|$n|$t|$e\"; done")
        ok, out = adb_shell(adb, cmd)
        for line in out.splitlines():
            line = line.strip()
            if line.count("|") != 3 or "Save_All_" not in line:
                continue
            path, n, t, first = line.split("|")
            slot = path.rsplit("Save_All_", 1)[-1]
            if not slot.isdigit():
                continue
            try:
                n = int(n)
            except ValueError:
                n = 0
            meta = {"files": n, "mtime": t.strip(),
                    # 明文槽是 .json，加密（云端下载）槽是 .txt
                    "enc": bool(first) and not first.endswith(".json")}
            found.append((label, folder, f"Save_All_{slot}", meta))
    found.sort(key=lambda x: (x[0] != "小米版", slot_number(x[2])))
    return found


def main():
    ap = argparse.ArgumentParser(description="从 MuMu 模拟器同步大周列国志存档")
    ap.add_argument("--list", action="store_true", help="只列存档槽，不拉取")
    ap.add_argument("--dry-run", action="store_true", help="只显示计划")
    ap.add_argument("--pkg", choices=["mi", "std", "both"], default="both",
                    help="拉哪个包（默认 both）")
    ap.add_argument("--out", default=LOCAL_BASE, help=f"本地存档根（默认 {LOCAL_BASE}）")
    ap.add_argument("--only-slot", default="",
                    help="只拉指定的槽，可逗号分隔（如 Save_All_4001,Save_All_1001）。"
                         "不给则拉 --pkg 下的全部。")
    ap.add_argument("--overwrite", action="store_true",
                    help="拉完直接把槽**落位**到 --out（覆盖同名槽）。"
                         "被覆盖的旧槽先改名成 <槽>.bak_<时间戳>，随时可回退。"
                         "不加这个开关时行为完全不变：只拉到暂存目录，等你手动搬。")
    args = ap.parse_args()

    adb = find_adb()
    if not adb:
        print("找不到 adb，请确认 MuMu 模拟器 12 装在某处。")
        print("试过这些位置：")
        for p in ADB_CANDS:
            print("  " + p)
        return 2
    print(f"adb: {adb}")

    print("连接模拟器 ...")
    if not connect(adb, root=True):
        print("连接失败。请确认 MuMu 模拟器正在运行。")
        return 3
    ok, ident = adb_shell(adb, "id")
    if "uid=0" not in ident:
        print("警告：没拿到 root，读 /data/data 可能失败。")
        print("  id 输出：" + ident.strip()[:120])
    else:
        print("  root OK")

    print("扫描存档槽 ...")
    slots = list_slots(adb, with_meta=True)
    if not slots:
        print("没找到任何存档槽。确认游戏至少存过一次档。")
        return 4

    print(f"\n发现 {len(slots)} 个槽（按争霸类型分组）：")
    for mode in MODE_ORDER:
        group = [s for s in slots if slot_mode(s[2]) == mode]
        if not group:
            continue
        print(f"  【{mode}】")
        for label, folder, slot, meta in group:
            note = meta.get("mtime") or ""
            if meta.get("enc"):
                desc = f"加密 · 读不了 · {note}"
            else:
                desc = f"{meta.get('files', '?')} 个表文件 · {note}"
            print(f"    [{label}] {slot:<18s} {desc}")

    if args.list:
        return 0

    # 过滤包
    if args.pkg == "mi":
        slots = [s for s in slots if s[0] == "小米版"]
    elif args.pkg == "std":
        slots = [s for s in slots if s[0] == "普通版"]

    # 只拉指定槽（可逗号分隔）
    if args.only_slot:
        want = {s.strip() for s in args.only_slot.split(",") if s.strip()}
        slots = [s for s in slots if s[2] in want]
        if not slots:
            print(f"\n× 模拟器里没有这些槽：{'、'.join(sorted(want))}")
            return 6

    if args.dry_run:
        print("\n[dry-run] 会把上面这些槽拉到：")
        print("  " + args.out)
        return 0

    # 拉取：adb pull 的目标路径必须纯英文，所以先 cd 到 out（可能含中文）
    # 用 os.chdir 不行（自己也可能在中文路径下），改用临时英文目录周转。
    tmp = r"D:\DevCache\_mumu_sync_tmp"
    if os.path.isdir(tmp):
        shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)
    os.makedirs(args.out, exist_ok=True)

    cwd = os.getcwd()
    n_ok = 0
    try:
        os.chdir(tmp)                       # 切到纯英文目录
        for label, folder, slot, _meta in slots:
            src = f"/data/data/{pkg_for(label)}/files/{folder}\\{slot}"
            dst = f"./{folder}__{slot}"
            print(f"\n拉取 [{label}] {slot} ...", flush=True)
            connect(adb, root=True)
            ok, out = run_dev(adb, ["pull", src, dst], timeout=600)
            if ok and ("files pulled" in out or "file pulled" in out):
                cnt = sum(len(f) for _, _, f in os.walk(dst))
                print(f"  OK  {cnt} 个文件")
                n_ok += 1
            else:
                print("  FAIL " + out.strip()[:200])
    finally:
        os.chdir(cwd)

    print(f"\n完成：{n_ok}/{len(slots)} 个槽拉取成功")
    print(f"暂存目录：{tmp}")
    print(f"目标目录：{args.out}")

    if not args.overwrite:
        print("（把暂存目录里的槽移动过去覆盖即可；本脚本不自动覆盖，避免误伤）")
        return 0 if n_ok == len(slots) else 5

    # ---- 落位：暂存目录 → --out（同名槽先改名备份，再搬过去）----
    # 使用者要的「自动续谱」闭环第一步就是这里：拉完必须真的落到
    # D:\DevCache\dzlgz\Save_All_N，否则后面抽取读到的还是旧档。
    print("\n落位（覆盖本机缓存槽）...")
    ts = time.strftime("%Y%m%d_%H%M%S")
    n_land = 0
    landed = {}
    for label, folder, slot, _meta in slots:
        src_dir = os.path.join(tmp, f"{folder}__{slot}")
        if not os.path.isdir(src_dir):
            continue
        dst_dir = os.path.join(args.out, slot)
        if os.path.isdir(dst_dir):
            bak = f"{dst_dir}.bak_{ts}"
            try:
                if os.path.isdir(bak):
                    shutil.rmtree(bak)
                os.replace(dst_dir, bak)      # 改名而不是删 —— 随时能退回去
                print(f"  {slot} 旧槽已备份 → {os.path.basename(bak)}")
            except Exception as e:
                print(f"  {slot} 旧槽备份失败，跳过落位：{e}")
                continue
        try:
            shutil.move(src_dir, dst_dir)
        except Exception as e:
            print(f"  {slot} 落位失败：{e}")
            continue
        cnt = sum(len(f) for _, _, f in os.walk(dst_dir))
        mt = time.strftime("%Y-%m-%d %H:%M",
                           time.localtime(os.path.getmtime(dst_dir)))
        print(f"  {slot} 已落位：{cnt} 个文件 · 目录时间 {mt}")
        landed[slot] = {
            # ★ 设备上的目录时间 = **游戏自己写这个档的时刻**（`ls -ld` 的月-日 时:分）。
            #   使用者原话：「实录槽应该在每个存档后记录存档的现实时间，
            #   这个也是重要的判断依据」。存档 json 里没有这个字段（扫过，0 命中），
            #   只能趁拉档这一刻从设备上取，落盘存下来。
            "device_mtime": (_meta or {}).get("mtime") or "",
            "pulled_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "files": cnt,
            "enc": bool((_meta or {}).get("enc")),
        }
        n_land += 1
    _merge_slot_meta(args.out, landed)
    print(f"落位完成：{n_land}/{len(slots)} 个槽")
    return 0 if n_ok == len(slots) else 5


SLOT_META_FILE = "_shiguan_slots.json"


def _merge_slot_meta(out_dir, landed):
    """把这次拉到的槽时间并进 `<out>/_shiguan_slots.json`。

    ★ 为什么放在**槽目录外面**：槽目录里多一个 json 会让
      `import_from_game.check_slot` / `load_tables` 的 `*.json` 通配
      多看到一个不相干的文件（明文槽判据、文件计数都会飘）。
      放在 `--out` 根下按槽名索引，谁也不干扰。

    结构：`{"Save_All_1": {"device_mtime": "Sep 21 23:25",
                          "pulled_at": "2026-09-21 23:40:11", "files": 408}}`
    """
    if not landed:
        return
    path = os.path.join(out_dir, SLOT_META_FILE)
    data = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f) or {}
        except Exception:
            data = {}
    data.update(landed)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"（写入槽时间记录失败，不影响存档：{e}）")


def pkg_for(label):
    for pkg, _folder, lbl in PACKAGES:
        if lbl == label:
            return pkg
    return PACKAGES[0][0]


if __name__ == "__main__":
    sys.exit(main())
