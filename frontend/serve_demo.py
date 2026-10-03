#!/usr/bin/env python3
"""约定合同阅读器 · 演示静态服务器（单端口方案）。

同一个端口上完成三件事：
  1. 托管 frontend/dist 静态文件（SPA 回退到 index.html）
  2. 把后端 API（/v1/、/contracts/、/healthz、/readyz）反向代理到本机后端
  3. 向 index.html 注入 window.YUEDING_BACKEND_CONFIG={baseUrl:location.origin}，
     让前端 API 调用与页面同源——公网 IP、SSH 隧道、VNC 本机打开均可，无 CORS 问题。

用法（远端演示的典型形态：前端 8000，后端 8001）：
  python3 serve_demo.py                     # 默认 0.0.0.0:8000 → 127.0.0.1:8001
环境变量：HOST / PORT / BACKEND_HOST / BACKEND_PORT
"""

import mimetypes
import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DIST = Path(__file__).resolve().parent / "dist"
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))
BACKEND = "http://{}:{}".format(
    os.environ.get("BACKEND_HOST", "127.0.0.1"), os.environ.get("BACKEND_PORT", "8001")
)
BACKEND_TIMEOUT = float(os.environ.get("BACKEND_TIMEOUT", "300"))

API_PREFIXES = ("/v1/", "/contracts/", "/legal/", "/kb/")
API_EXACT = ("/healthz", "/readyz")
# 逐跳头不转发；Content-Length 由本服务器按转发后的 body 重写
HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length",
}

# index.html 内置脚本用 Object.assign(target, window.YUEDING_BACKEND_CONFIG || {})
# 合并，预置值优先级更高，所以提前注入即可覆盖“非 localhost 即纯本地模式”的默认。
INJECT = "<script>window.YUEDING_BACKEND_CONFIG={baseUrl:location.origin,timeout:120000}</script>"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "YuedingDemo/1.0"

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if self._is_api(path):
            self._proxy()
        else:
            self._static(path, send_body=True)

    def do_HEAD(self):
        path = self.path.split("?", 1)[0]
        if self._is_api(path):
            self._proxy()
        else:
            self._static(path, send_body=False)

    def do_POST(self):
        self._proxy()

    def do_PUT(self):
        self._proxy()

    def do_PATCH(self):
        self._proxy()

    def do_DELETE(self):
        self._proxy()

    def do_OPTIONS(self):
        self._proxy()

    @staticmethod
    def _is_api(path):
        return path in API_EXACT or path.startswith(API_PREFIXES)

    # ── 反向代理 ────────────────────────────────────────────────
    def _proxy(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        req = urllib.request.Request(BACKEND + self.path, data=body, method=self.command)
        for key, value in self.headers.items():
            if key.lower() not in HOP_HEADERS:
                req.add_header(key, value)
        try:
            resp = urllib.request.urlopen(req, timeout=BACKEND_TIMEOUT)
        except urllib.error.HTTPError as err:
            resp = err
        except Exception as exc:  # 后端未启动/连接失败
            payload = '{{"error":{{"message":"demo proxy: {}"}}}}'.format(exc).encode("utf-8")
            self._respond(502, [("Content-Type", "application/json")], payload)
            return
        with resp:
            payload = resp.read()
            headers = [
                (key, value)
                for key, value in resp.headers.items()
                if key.lower() not in HOP_HEADERS
            ]
            self._respond(resp.status if hasattr(resp, "status") else resp.code, headers, payload)

    # ── 静态文件 ────────────────────────────────────────────────
    def _static(self, path, send_body):
        if path in ("/", ""):
            path = "/index.html"
        parts = [p for p in path.split("/") if p and p not in (".", "..")]
        target = DIST.joinpath(*parts) if parts else None
        if target and target.is_file():
            self._send_file(target, send_body)
            return
        if "." in path.rsplit("/", 1)[-1]:  # 带扩展名的资源缺失 → 404，不回退
            self._respond(404, [("Content-Type", "text/plain; charset=utf-8")], b"not found")
            return
        self._send_file(DIST / "index.html", send_body)  # SPA 回退

    def _send_file(self, file, send_body):
        payload = file.read_bytes()
        if file.name == "index.html":
            payload = payload.decode("utf-8").replace("</head>", INJECT + "</head>", 1).encode("utf-8")
        ctype = "text/html; charset=utf-8" if file.name == "index.html" else (
            mimetypes.guess_type(file.name)[0] or "application/octet-stream"
        )
        self._respond(200, [("Content-Type", ctype)], payload, send_body)

    def _respond(self, status, headers, payload, send_body=True):
        self.send_response(status)
        for key, value in headers:
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if send_body:
            self.wfile.write(payload)


def main():
    if not (DIST / "index.html").is_file():
        raise SystemExit("dist/index.html 不存在，请先在 frontend/ 执行 npm run build")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    print("demo frontend on http://{}:{} | api proxied to {}".format(HOST, PORT, BACKEND))
    server.serve_forever()


if __name__ == "__main__":
    main()
