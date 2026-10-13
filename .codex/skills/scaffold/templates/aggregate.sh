set -euo pipefail
python3 - <<'PY'
import json
import os
import sys

results = json.loads(os.environ["GATE_RESULTS"])
failed = [name for name, info in results.items() if info["result"] != "success"]
if not results or failed:
    print("::error file=" + os.environ["WORKFLOW_FILE"] + "::required gates did not succeed: " + ", ".join(sorted(failed)), file=sys.stderr)
    sys.exit(1)
PY
