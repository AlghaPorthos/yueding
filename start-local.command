#!/bin/zsh
cd -- "${0:A:h}" || exit 1
local_url='http://127.0.0.1:8787'
node_bin="$(command -v node 2>/dev/null)"
if [[ -z "$node_bin" ]] || ! "$node_bin" -e 'const [a,b]=process.versions.node.split(".").map(Number);process.exit(a>22||(a===22&&b>=9)?0:1)' 2>/dev/null; then
  node_bin="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
fi
if [[ ! -x "$node_bin" ]]; then
  print '需要 Node.js 22.9 或更新版本。安装后重新打开此文件。'
  read '?按回车关闭…'; exit 1
fi
if curl --max-time 2 -fsS "$local_url/api/config" 2>/dev/null | "$node_bin" -e 'let s="";process.stdin.on("data",d=>s+=d);process.stdin.on("end",()=>{try{const j=JSON.parse(s);process.exit(j.localSetup===true&&j.scenarios?0:1)}catch{process.exit(1)}})'; then
  open "$local_url/"
  print '约定已经在运行，已打开体验页面。'; exit 0
fi
HOST=127.0.0.1 PORT=8787 LOCAL_SETUP=1 "$node_bin" --env-file-if-exists=.env server/index.mjs &
relay_pid=$!
trap 'kill "$relay_pid" 2>/dev/null' EXIT INT TERM
for attempt in {1..30}; do
  if ! kill -0 "$relay_pid" 2>/dev/null; then
    print '启动失败，请查看上方错误。如果 8787 端口被占用，请先关闭占用它的服务。'
    read '?按回车关闭…'; exit 1
  fi
  if curl --max-time 1 -fsS "$local_url/api/config" >/dev/null 2>&1; then
    open "$local_url/"
    print '约定已启动。首次使用请点击页面右上角“本机设置”。'
    print '请保持这个窗口打开；按 Ctrl+C 或关闭窗口即可停止服务。'
    wait "$relay_pid"
    exit $?
  fi
  sleep 0.2
done
print '服务未及时启动，请查看上方错误。'
read '?按回车关闭…'
exit 1
