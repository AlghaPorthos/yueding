#!/usr/bin/env bash
# 约定合同阅读器后端一键启动：法律语料 + 快速小模型（GLM）。
# 模型链：
#   主  glm-5.3-flash —— ZCode coding plan 的 Anthropic 兼容端点（key 取自 ~/.zcode/cli/config.json）
#   备  glm-4-flash   —— BigModel 开放平台 OpenAI 兼容端点（key 取自 ~/.zshrc 的 ZAI_API_KEY）
set -euo pipefail
BACKEND_DIR="$(cd "$(dirname "$0")" && pwd)"
export CONTRACT_READER_LEGAL_CORPUS="$BACKEND_DIR/data/legal_corpus.jsonl"
export CONTRACT_READER_LLM_TIMEOUT_SECONDS="${CONTRACT_READER_LLM_TIMEOUT_SECONDS:-90}"

if [[ -z "${ZAI_API_KEY:-}" ]]; then
  ZAI_API_KEY="$(zsh -ic 'printf %s "$ZAI_API_KEY"' 2>/dev/null || true)"
  export ZAI_API_KEY
fi
ZCODE_PLAN_KEY="$(python3 -c "
import json
try:
    cfg = json.load(open('$HOME/.zcode/cli/config.json'))
    print(cfg['provider']['builtin:bigmodel-coding-plan']['options']['apiKey'])
except Exception:
    print('')
")"

export CONTRACT_READER_LLM_PRIMARY_KIND="${CONTRACT_READER_LLM_PRIMARY_KIND:-anthropic}"
export CONTRACT_READER_LLM_PRIMARY_URL="${CONTRACT_READER_LLM_PRIMARY_URL:-https://open.bigmodel.cn/api/anthropic/v1/messages}"
export CONTRACT_READER_LLM_PRIMARY_MODEL="${CONTRACT_READER_LLM_PRIMARY_MODEL:-glm-5.3-flash}"
export CONTRACT_READER_LLM_PRIMARY_API_KEY="${CONTRACT_READER_LLM_PRIMARY_API_KEY:-$ZCODE_PLAN_KEY}"
export CONTRACT_READER_LLM_PRIMARY_THINKING="${CONTRACT_READER_LLM_PRIMARY_THINKING:-disabled}"

export CONTRACT_READER_LLM_FALLBACK_KIND="${CONTRACT_READER_LLM_FALLBACK_KIND:-openai}"
export CONTRACT_READER_LLM_FALLBACK_URL="${CONTRACT_READER_LLM_FALLBACK_URL:-https://open.bigmodel.cn/api/paas/v4/chat/completions}"
export CONTRACT_READER_LLM_FALLBACK_MODEL="${CONTRACT_READER_LLM_FALLBACK_MODEL:-glm-4-flash}"
export CONTRACT_READER_LLM_FALLBACK_API_KEY="${CONTRACT_READER_LLM_FALLBACK_API_KEY:-${ZAI_API_KEY:-}}"

cd "$BACKEND_DIR"
export CONTRACT_READER_CORS_ORIGINS="http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173,http://localhost:8080,http://127.0.0.1:8080,https://alghaporthos.github.io"
exec .venv/bin/python serve.py
