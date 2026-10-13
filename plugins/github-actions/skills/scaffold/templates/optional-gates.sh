set -euo pipefail
python3 - <<'PY'
import json
import os
import sys

results = json.loads(os.environ["GATE_RESULTS"])
failed = []
for name, info in results.items():
    expected = os.environ[name.upper().replace("-", "_")].lower() == "true"
    allowed = {"success"} if expected else {"skipped"}
    if info["result"] not in allowed:
        failed.append(name)
if not results or failed:
    print("::error::cloud gates failed or skipped unexpectedly: " + ", ".join(sorted(failed)), file=sys.stderr)
    sys.exit(1)
PY
