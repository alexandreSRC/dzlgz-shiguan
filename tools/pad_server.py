# -*- coding: utf-8 -*-
"""平板数据服务：给安卓 App（与浏览器原型）供数。

用法：
    python tools/pad_server.py            # 默认 0.0.0.0:8801
    python tools/pad_server.py 8801       # 指定端口

接口（全部返回 UTF-8 JSON，除 /proto.html）：
    GET /api/health   → {"ok":true,"ts":…}      探活，平板用来判断 PC 在不在
    GET /api/data     → 人物页全量数据（列/行/列宽/计数/分级/左栏…）
    GET /api/reload   → 强制重取后返回数据（改档 / 改数据后调）
    GET /proto.html   → 浏览器原型（对照用，已生成的静态页）

★ 数据源见 `tools/pad_data.py` —— 与 Tkinter **同源取数**，不是另算一套。
★ 只读：本服务绝不写 `saves/`（操作铁律：史馆开着时不改存档）。
"""
from __future__ import annotations

import io
import json
import os
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
os.chdir(ROOT)

from pad_data import PadData                      # noqa: E402

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PAD = PadData()
_LOCK = threading.Lock()           # 取数串行化（Tk 不并发）


def _local_ips():
    """列出本机局域网 IPv4 —— 平板要填的就是它。"""
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.append(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except Exception:
        pass
    return ips


class Handler(BaseHTTPRequestHandler):
    server_version = "ShiguanPad/1.0"

    def log_message(self, fmt, *args):
        print("  %s - %s" % (self.address_string(), fmt % args), flush=True)

    # ---- 工具 ----
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # 平板直连同一局域网：放开 CORS，方便浏览器调试
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False))

    # ---- 路由 ----
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/api/health", "/health"):
            self._json({"ok": True, "service": "shiguan-pad",
                        "ts": __import__("time").strftime("%Y-%m-%d %H:%M:%S")})
        elif path in ("/api/data", "/api/person", "/data"):
            try:
                with _LOCK:
                    self._json(PAD.payload())
            except Exception as e:                 # noqa: BLE001
                self._json({"error": str(e)}, 500)
        elif path == "/api/reload":
            try:
                with _LOCK:
                    self._json(PAD.reload())
            except Exception as e:                 # noqa: BLE001
                self._json({"error": str(e)}, 500)
        elif path in ("/proto.html", "/", "/index.html"):
            fp = os.path.join(ROOT, "_stats", "proto.html")
            if os.path.exists(fp):
                with open(fp, "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            else:
                self._send(404, "还没有 proto.html —— 先跑 _scratch/_build_mock.py",
                           "text/plain; charset=utf-8")
        else:
            self._send(404, json.dumps({"error": "no route", "path": path}),
                       "application/json; charset=utf-8")


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8801
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print("=" * 58)
    print("史馆 · 平板数据服务已启动")
    print("  监听端口: %d" % port)
    for ip in _local_ips():
        print("  平板填:   http://%s:%d     ← App 里的服务器地址" % (ip, port))
        print("  浏览器验: http://%s:%d/api/health" % (ip, port))
    print("  本地自测: http://127.0.0.1:%d/api/data" % port)
    print("  ⚠️ 只读服务，不写 saves/；数据与 Tkinter 同源")
    print("  Ctrl+C 停止")
    print("=" * 58, flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止", flush=True)
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
