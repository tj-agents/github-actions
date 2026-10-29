import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / ".agents/github-actions/skills/scaffold"
SPEC = importlib.util.spec_from_file_location("workflow_scaffold", SKILL / "scripts/scaffold.py")
scaffold = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scaffold)


def main():
    config = json.loads((SKILL / "examples/service.json").read_text(encoding="utf-8"))
    config["provider"]["oidc"] = True
    config["provider"]["ready"] = "vars.FOUNDATION_READY == 'true'"
    config["provider"]["phases"]["validate"]["matrix"] = {"root": ["foundation", "instance"]}
    config["provider"]["composites"] = {"provider-setup": {"description": "Initialize the neutral provider", "inputs": {"target": {"description": "Deployment target", "required": True}}, "steps": [{"name": "Initialize the target", "env": {"TARGET": "${{ inputs.target }}"}, "run": "printf '%s\\n' \"$TARGET\""}]}}
    config["provider"]["phases"]["setup"] = {"steps": [{"name": "Initialize the provider", "uses": "./.github/actions/provider-setup", "with": {"target": "${{ github.repository }}"}}]}
    config["verify"]["end-to-end"] = {"steps": [{"name": "Test the serving revision", "run": "python3 deploy.py test"}]}
    config["roots"] = ["src", "web"]
    for phase in ("deploy", "readiness", "destroy", "recover"):
        config["provider"]["phases"][phase]["roots"] = ["src", "web"]
    metadata = {"global.json": '{"sdk":{"version":"10.0.100"}}', "web/package.json": '{"engines":{"node":"24.x"},"packageManager":"pnpm@10.0.0"}', "web/pnpm-lock.yaml": "lockfileVersion: '9.0'"}
    with tempfile.TemporaryDirectory(prefix="workflow-writer-") as temporary:
        project = Path(temporary)
        scaffold.write_files(project, scaffold.render(config, metadata))
        variants = {name: copy.deepcopy(config) for name in ("no-build", "prod-off", "production-matrix", "oidc-build", "oidc-build-no-verify")}
        variants["no-build"].pop("build", None)
        variants["prod-off"]["prod-release"] = False
        variants["production-matrix"]["provider"]["environments"] = {"ci": "ci", "preview": "preview", "prod": ["east-prod", "west-prod"]}
        variants["oidc-build"]["build"]["oidc"] = True
        variants["oidc-build-no-verify"]["build"]["oidc"] = True
        variants["oidc-build-no-verify"]["verify"] = {}
        variants["oidc-build-no-verify"]["prod-release"] = False
        for name, variant in variants.items():
            for path, content in scaffold.render(variant, metadata).items():
                if path.startswith(".github/workflows/"):
                    (project / ".github/workflows" / f"{name}-{Path(path).name}").write_text(content, encoding="utf-8")
        (project / ".github/workflows/writer-check.yml").write_text((ROOT / ".github/workflows/workflow-writer.yml").read_text(encoding="utf-8"), encoding="utf-8")
        subprocess.run([sys.executable, "-B", str(project / ".github/scripts/lint-workflows.py")], cwd=project, check=True)
    print("Emitted full, no-build, prod-off, production-matrix and OIDC build workflows, composites and writer CI pass actionlint and zizmor.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
