# -*- coding: utf-8 -*-
"""生成「大周列国志 · 史馆」快捷方式（.lnk）。

★ 2026-09-21 改法（重要）：.lnk **直接指向 pythonw.exe**，不再经过 Start.vbs。
  为什么：使用者机器上双击 .vbs 报「Windows 无法访问指定设备、路径或文件」——
  实测（对照实验）：
    · 用 ShellExecute（＝双击）启动**任何** .vbs 都返回 Access is denied，
      连放到纯英文路径 D:\\DevCache 下也一样；
    · 同一个 .vbs 用 cscript 跑完全正常；
    · .vbs 关联正常、文件没有被标记为「下载文件」、路径里的「·」GBK 也能表示。
  → 结论：**这台机器上 wscript.exe 被安全软件 / 组策略拦了**，
    与脚本内容、编码、路径都无关。所以启动器彻底不依赖 wscript。
  pythonw.exe 无控制台、无黑框，双击即开，比 .vbs 更干净。

为什么需要它：
  Start.bat / Start.vbs 仍保留做兜底（cmd.exe 没被拦），但它们是脚本文件，
  放桌面上图标是「脚本」图标。快捷方式自带工作目录与图标，双击即开。

用法（双击不弹参数时默认生成到本脚本所在的项目根目录）：
    python tools/make_shortcut.py                 # 生成到项目根目录
    python tools/make_shortcut.py 桌面             # 生成到当前用户的桌面
    python tools/make_shortcut.py D:\\某文件夹       # 生成到指定目录

★ 不写注册表、不改系统设置，只落一个 .lnk 文件。
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME = "大周列国志 · 史馆.lnk"
MAIN = "main.py"


def pythonw():
    """无控制台的 Python 解释器 —— .lnk 的目标。找不到就退回 python.exe。"""
    exe = sys.executable or ""
    cand = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.isfile(cand):
        return cand
    return exe


def python_icon():
    """图标借 python.exe 的第 0 号图标（pythonw.exe 没有自己的图标）。"""
    exe = sys.executable or ""
    return exe if os.path.isfile(exe) else ""


def _desktop():
    """当前用户的**真实**桌面目录。

    ★ 必须读注册表，不能猜：这台机器的桌面被重定向到了 `D:\\Desktop`，
      而 `C:\\Users\\Administrator\\Desktop` 这个目录**仍然存在**（空壳），
      按「哪个存在用哪个」会稳稳地挑错那个 —— 快捷方式就落到没人看的地方了。
    """
    ps = (
        "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;"
        "(Get-ItemProperty 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion"
        "\\Explorer\\User Shell Folders' -Name Desktop).Desktop"
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        val = (r.stdout or "").strip()
        if val:
            val = os.path.expandvars(val)          # 注册表里可能写着 %USERPROFILE%
            if os.path.isdir(val):
                return val
    except Exception:
        pass
    home = os.path.expanduser("~")
    for cand in (os.path.join(home, "Desktop"),
                 os.path.join(home, "OneDrive", "Desktop"),
                 os.path.join(os.environ.get("USERPROFILE", home), "Desktop")):
        if os.path.isdir(cand):
            return cand
    return home


def make_shortcut(dest_dir):
    """在 dest_dir 下建 .lnk，返回 lnk 绝对路径。"""
    target = pythonw()
    if not target or not os.path.isfile(target):
        raise SystemExit(f"找不到 pythonw.exe（sys.executable={sys.executable}）")
    if not os.path.isfile(os.path.join(HERE, MAIN)):
        raise SystemExit(f"找不到主程序：{os.path.join(HERE, MAIN)}")
    os.makedirs(dest_dir, exist_ok=True)
    lnk = os.path.join(dest_dir, NAME)
    icon = python_icon()

    # ★ PowerShell 里塞中文路径：用 -Command 加单引号，整段一次执行。
    #   写成多行脚本文件会被 GBK/UTF-8 编码问题咬到，单行 -Command 最稳。
    ps = (
        "$s=New-Object -ComObject WScript.Shell;"
        f"$l=$s.CreateShortcut('{lnk}');"
        f"$l.TargetPath='{target}';"
        f"$l.Arguments='{MAIN}';"
        f"$l.WorkingDirectory='{HERE}';"
        f"$l.Description='{NAME[:-4]}';"
        + (f"$l.IconLocation='{icon},0';" if icon else "")
        + "$l.Save()"
    )
    r = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0 or not os.path.isfile(lnk):
        raise SystemExit(f"创建快捷方式失败（rc={r.returncode}）：{r.stderr or r.stdout}")
    return lnk


def verify(lnk):
    """读回 .lnk 的目标 / 参数 / 工作目录，确认指向正确。"""
    # ★ 中文路径两道坎：① 控制台输出默认是 GBK，Python 按 utf-8 读会乱成问号，
    #   所以先把它切成 UTF-8；② 一条 -Command 写完，别落成 .ps1 文件（编码坑）。
    ps = (
        "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;"
        "$s=New-Object -ComObject WScript.Shell;"
        f"$l=$s.CreateShortcut('{lnk}');"
        "Write-Output $l.TargetPath;"
        "Write-Output $l.Arguments;"
        "Write-Output $l.WorkingDirectory"
    )
    r = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    return [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg in ("桌面", "desktop", "Desktop"):
        dest = _desktop()
    elif arg:
        dest = arg
    else:
        dest = HERE

    try:
        lnk = make_shortcut(dest)
    except SystemExit as e:
        print(f"[FAIL] {e}")
        sys.exit(1)

    info = verify(lnk)
    print(f"已生成：{lnk}")
    print(f"  目标      ：{info[0] if info else '（读回失败）'}")
    print(f"  参数      ：{info[1] if len(info) > 1 else '（读回失败）'}")
    print(f"  工作目录  ：{info[2] if len(info) > 2 else '（读回失败）'}")
    ok = (bool(info) and info[0].lower().endswith("pythonw.exe")
          and (len(info) > 1 and info[1] == MAIN))
    print("  校验      ：" + ("通过 ✓" if ok else "目标不对 ✗"))
    sys.exit(0 if ok else 1)
