#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="/Users/xiexingyu/Documents/项目/Hackathon"
RIG_NAME="hackathon-dev"
SPEC="$PROJECT_ROOT/rig-hackathon.yaml"

cd "$PROJECT_ROOT"

if ! rig daemon status >/dev/null 2>&1; then
  rig daemon start
fi

RIG_ID="$(rig ps --json --fields rigId,name,status | python3 -c '
import json, sys
for row in json.load(sys.stdin).get("entries", []):
    if row.get("name") == "hackathon-dev":
        print(row["rigId"])
        break
')"

if [[ -z "$RIG_ID" ]]; then
  exec rig up "$SPEC" --cwd "$PROJECT_ROOT" --yes
fi

SEATS="$(rig ps --nodes --rig "$RIG_NAME" --json | python3 -c '
import json, sys
rows = json.load(sys.stdin)
print(",".join(row["logicalId"] for row in rows if row.get("logicalId")))
')"

if [[ -n "$SEATS" ]]; then
  rig launch "$RIG_ID" --seats "$SEATS"
fi

printf 'hackathon-dev ready: %s\n' "$RIG_ID"
rig ps --nodes --rig "$RIG_NAME"
