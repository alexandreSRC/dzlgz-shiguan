# -*- coding: utf-8 -*-
"""史馆 · 验收总入口（M1）。

一次跑完三项，汇总成一份报告：
  1. 外壳      —— 五页签 × 三主题 × 双层来源选择器 × 状态栏双层计数
                 （含「默认页签非人物时实录层仍自动载入」冷启动回归）
  2. 双向桥    —— 查档（谱牒 → 实录）/ 入谱（实录 → 谱牒）/ 重复入谱防重
  3. 真 GUI    —— 真起窗口，逐页签逐主题带重绘，关窗保存

用法：
    python tools\\accept.py            # 全部
    python tools\\accept.py shell      # 只跑外壳
    python tools\\accept.py bridge gui # 跑指定几项

★ 所有子项都在无头模式（SHIGUAN_HEADLESS=1）下跑：
  没有 mainloop 时，`wait_window` 模态框会**永久挂死**进程（踩过，排查极痛苦）。
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable

SUITES = {
    "shell": ("tools/_m1_accept.py", "_stats/_m1_accept.txt", 300),
    "bridge": ("tools/_m1_bridge.py", "_stats/_m1_bridge.txt", 300),
    "gui": ("tools/_m1_gui.py", "_stats/_m1_gui.txt", 240),
}
LABEL = {"shell": "外壳（五页签 × 三主题）", "bridge": "双向桥（查档 / 入谱）",
         "gui": "真 GUI（窗口 × 重绘）"}


def main():
    want = [a for a in sys.argv[1:] if a in SUITES] or list(SUITES)
    rows = []
    for key in want:
        script, report, timeout = SUITES[key]
        path = os.path.join(ROOT, script)
        if not os.path.exists(path):
            rows.append((key, "—", f"找不到 {script}"))
            continue
        try:
            p = subprocess.run([PY, script], capture_output=True,
                               timeout=timeout, cwd=ROOT)
            tail = ""
            rp = os.path.join(ROOT, report)
            if os.path.exists(rp):
                with open(rp, encoding="utf-8") as f:
                    lines = [ln for ln in f.read().splitlines() if ln.strip()]
                tail = lines[-1] if lines else ""
            ok = (p.returncode == 0)
            rows.append((key, "通过 ✓" if ok else "失败 ✗",
                         tail or f"rc={p.returncode}"))
        except subprocess.TimeoutExpired:
            rows.append((key, "超时 ✗", f"超过 {timeout}s（可能是模态框挂死）"))

    lines = ["=" * 66, "史馆 · M1 验收总表", "=" * 66, ""]
    for key, verdict, note in rows:
        lines.append(f"  {LABEL.get(key, key):<24} {verdict:<8} {note}")
    lines.append("")
    allok = all(v == "通过 ✓" for _, v, _ in rows) and rows
    lines.append("总结论：" + ("全部通过 ✓" if allok else "有失败项 ✗"))
    out = "\n".join(lines)

    with open(os.path.join(ROOT, "_stats", "accept.txt"), "w", encoding="utf-8") as f:
        f.write(out)
    print(out)
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
