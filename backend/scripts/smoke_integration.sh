#!/usr/bin/env bash
# 后端联调冒烟脚本：CORS 预检 → healthz → upload(四条款) → analyze → align(可选 user_role) → matters → generate(确定性降级)。
# 逐字段断言（jq 优先，缺失时回退 python3），任一失败立即非零退出。
#
# 用法：
#   1) 先由联调方自起服务端（本脚本不启动服务）：
#      cd backend && CONTRACT_READER_LEGAL_CORPUS=data/legal_corpus.jsonl PYTHONPATH=. python3 serve.py
#      （未配置语料时 align 顶层 status 为 not_found，脚本视为通过并给出提示）
#   2) bash scripts/smoke_integration.sh
#      BASE_URL=http://127.0.0.1:9000 bash scripts/smoke_integration.sh
#
# 端点与字段契约见 backend/INTEGRATION.md（与 app/main.py::_route 一一对应）。

set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"

# macOS 系统代理（scutil，如 Clash 127.0.0.1:7890）会劫持对 127.0.0.1 的 curl 请求并返回 502；
# 强制直连，保证本脚本在带系统代理的机器上无人值守跑绿。
export no_proxy='*' NO_PROXY='*'

# --- 断言与 JSON 工具 -------------------------------------------------------

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

ok() {
  echo "  ok: $*"
}

expect_eq() { # expect_eq <描述> <实际> <期望>
  if [ "$2" != "$3" ]; then
    fail "$1: 期望 [$3]，实际 [$2]"
  fi
  ok "$1 = $3"
}

require_nonempty() { # require_nonempty <描述> <值>
  if [ -z "$2" ]; then
    fail "$1 为空"
  fi
  ok "$1 非空"
}

# request <METHOD> <URL> [curl 参数...]
# 结果写入全局 HTTP_CODE 与 BODY。
request() {
  local method=$1 url=$2 tmp
  shift 2
  tmp=$(mktemp)
  if ! HTTP_CODE=$(curl -sS --connect-timeout 5 --max-time 60 \
      -X "$method" -o "$tmp" -w '%{http_code}' "$@" "$url"); then
    rm -f "$tmp"
    fail "curl $method $url 请求失败（服务是否已在 $BASE_URL 启动？）"
  fi
  BODY=$(cat "$tmp")
  rm -f "$tmp"
}

# json_field <json> <路径> ：路径形如 .a.b[0].c；字符串原样输出，
# 布尔/数字/容器输出其 JSON 文本（与 jq -r 行为一致）。
json_field() {
  if command -v jq >/dev/null 2>&1; then
    printf '%s' "$1" | jq -r "$2"
    return
  fi
  command -v python3 >/dev/null 2>&1 || fail "断言需要 jq 或 python3，两者均未安装"
  printf '%s' "$1" | python3 -c '
import json, re, sys

data = json.load(sys.stdin)
path = sys.argv[1]
try:
    for m in re.finditer(r"\.([A-Za-z_][A-Za-z0-9_]*)|(\[([0-9]+)\])", path):
        if m.group(1) is not None:
            data = data[m.group(1)]
        else:
            data = data[int(m.group(3))]
except (KeyError, IndexError, TypeError):
    print("null")  # 与 jq -r 一致：缺失路径输出 null
    sys.exit(0)
if isinstance(data, str):
    print(data)
elif data is None:
    print("null")
else:
    print(json.dumps(data, ensure_ascii=False))
' "$2"
}

# json_count <json> <路径> ：数组/对象长度。
json_count() {
  if command -v jq >/dev/null 2>&1; then
    printf '%s' "$1" | jq "$2 | length"
    return
  fi
  printf '%s' "$1" | python3 -c '
import json, re, sys

data = json.load(sys.stdin)
path = sys.argv[1]
try:
    for m in re.finditer(r"\.([A-Za-z_][A-Za-z0-9_]*)|(\[([0-9]+)\])", path):
        if m.group(1) is not None:
            data = data[m.group(1)]
        else:
            data = data[int(m.group(3))]
    print(len(data))
except (KeyError, IndexError, TypeError) as exc:
    sys.stderr.write(f"json_count: 路径 {path} 无效: {exc}\n")
    sys.exit(1)
' "$2"
}

# --- 冒烟序列 ---------------------------------------------------------------

echo "== 冒烟目标: $BASE_URL =="

echo "[预检] OPTIONS $BASE_URL/v1/contracts（Origin: localhost:4173）"
preflight_headers=$(curl -s -o /dev/null -D - -X OPTIONS "$BASE_URL/v1/contracts" \
  -H "Origin: http://localhost:4173" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: content-type,x-user-id" | tr -d '\r') \
  || fail "CORS 预检请求失败（服务未启动？）"
echo "$preflight_headers" | grep -qi '^HTTP/[0-9.]* 204' \
  || fail "CORS 预检状态应 204，实际：$(echo "$preflight_headers" | head -1)"
ok "CORS 预检状态 = 204"
echo "$preflight_headers" | grep -qi '^Access-Control-Allow-Origin: http://localhost:4173' \
  || fail "CORS 预检缺少 Access-Control-Allow-Origin 回显（Origin 不在白名单？设置 CONTRACT_READER_CORS_ORIGINS）"
ok "CORS Allow-Origin 回显 = http://localhost:4173"

echo "[1/5] GET /healthz"
request GET "$BASE_URL/healthz"
expect_eq "healthz HTTP 状态" "$HTTP_CODE" "200"
expect_eq "healthz status" "$(json_field "$BODY" .status)" "ok"

echo "[2/5] POST /v1/contracts（multipart 四条款文本，字段名 file）"
contract_file=$(mktemp)
trap 'rm -f "$contract_file"' EXIT
cat >"$contract_file" <<'EOF'
押金为一个月租金，退租后七日内返还。
未经出租人书面同意，承租人不得改造房屋。
房屋及附属设施的日常维修由出租人负责。
承租人提前退租，应提前三十日通知并承担违约金。
EOF
request POST "$BASE_URL/v1/contracts" -F "file=@${contract_file};type=text/plain"
expect_eq "upload HTTP 状态" "$HTTP_CODE" "200"
CONTRACT_ID=$(json_field "$BODY" .contract_id)
VERSION_ID=$(json_field "$BODY" .version_id)
require_nonempty "upload contract_id" "$CONTRACT_ID"
require_nonempty "upload version_id" "$VERSION_ID"
expect_eq "upload quality_status" "$(json_field "$BODY" .quality_status)" "ready"
expect_eq "upload page_count" "$(json_field "$BODY" .page_count)" "1"
echo "  contract_id=$CONTRACT_ID version_id=$VERSION_ID"

echo "[3/5] POST /contracts/{cid}/versions/{vid}/analyze（注意：无 v1 前缀）"
request POST "$BASE_URL/contracts/$CONTRACT_ID/versions/$VERSION_ID/analyze"
expect_eq "analyze HTTP 状态" "$HTTP_CODE" "200"
expect_eq "analyze findings 数量" "$(json_count "$BODY" .findings)" "4"
expect_eq "analyze 固定顺序首条为 deposit" "$(json_field "$BODY" .findings[0].type)" "deposit"
expect_eq "analyze deposit 状态" "$(json_field "$BODY" .findings[0].status)" "confirmed"
expect_eq "analyze 质量状态" "$(json_field "$BODY" .quality_status)" "ready"

echo "[4/5] POST /v1/contracts/{cid}/versions/{vid}/align（user_role=承租人）"
request POST "$BASE_URL/v1/contracts/$CONTRACT_ID/versions/$VERSION_ID/align" \
  -H 'Content-Type: application/json' \
  -d '{"user_role": "承租人"}'
expect_eq "align HTTP 状态" "$HTTP_CODE" "200"
expect_eq "align findings 数量" "$(json_count "$BODY" .findings)" "4"
expect_eq "align user_role 回显" "$(json_field "$BODY" .findings[0].reasoning.user_role)" "承租人"
ALIGN_STATUS=$(json_field "$BODY" .status)
case "$ALIGN_STATUS" in
  matched|needs_review|not_found|ambiguous) ok "align 顶层 status = $ALIGN_STATUS" ;;
  *) fail "align 顶层 status 非法: [$ALIGN_STATUS]" ;;
esac
if [ "$ALIGN_STATUS" = "not_found" ]; then
  echo "  提示: 服务端未配置 CONTRACT_READER_LEGAL_CORPUS，legal_provisions 为空属预期；"
  echo "        如需完整链路，启动时加 CONTRACT_READER_LEGAL_CORPUS=data/legal_corpus.jsonl"
fi

echo "[5/5] POST /v1/contracts/{cid}/versions/{vid}/matters"
request POST "$BASE_URL/v1/contracts/$CONTRACT_ID/versions/$VERSION_ID/matters"
expect_eq "matters HTTP 状态" "$HTTP_CODE" "200"
expect_eq "matters contract_id 一致" "$(json_field "$BODY" .contract_id)" "$CONTRACT_ID"
expect_eq "matters drafts 恒为空" "$(json_field "$BODY" .drafts)" "[]"
ACTION_COUNT=$(json_count "$BODY" .actions)
if [ "$ACTION_COUNT" -lt 1 ]; then
  fail "matters actions 应至少 1 条（四条款 fixture 全部 confirmed），实际 $ACTION_COUNT"
fi
ok "matters actions 数量 = $ACTION_COUNT"
expect_eq "matters action.kind" "$(json_field "$BODY" .actions[0].kind)" "negotiate"
expect_eq "matters action.requires_user_approval" "$(json_field "$BODY" .actions[0].requires_user_approval)" "true"
FACT_COUNT=$(json_count "$BODY" .extracted_facts)
if [ "$FACT_COUNT" -lt 1 ]; then
  fail "matters extracted_facts 应至少 1 条，实际 $FACT_COUNT"
fi
ok "matters extracted_facts 数量 = $FACT_COUNT"
expect_eq "matters 首条事实状态" "$(json_field "$BODY" .extracted_facts[0].status)" "supported"

echo
echo "[加测] POST /v1/contracts/{cid}/versions/{vid}/generate（仅 v1 前缀；无 LLM 配置时确定性降级）"
request POST "$BASE_URL/v1/contracts/$CONTRACT_ID/versions/$VERSION_ID/generate" \
  -H 'Content-Type: application/json' \
  -d '{"task": "解释合同事实与法律对应"}'
expect_eq "generate HTTP 状态" "$HTTP_CODE" "200"
GEN_STATUS=$(json_field "$BODY" .generation_status)
case "$GEN_STATUS" in
  succeeded|failed) ok "generate generation_status = $GEN_STATUS" ;;
  *) fail "generate generation_status 应为 succeeded|failed，实际：$GEN_STATUS" ;;
esac

echo
echo "冒烟通过：CORS 预检 / healthz / upload / analyze / align / matters / generate 全部断言成功。"
