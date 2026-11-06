import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "workflows",
    [
        (".github/workflows/ci.yml",),
        (".github/workflows/ci.yaml",),
        (".github/workflows/ci.yml", ".github/actions/check/action.yaml"),
    ],
)
def test_stages_workflows_when_either_yaml_extension_is_absent(
    tmp_path: Path, workflows: tuple[str, ...]
) -> None:
    action = (ROOT / ".github/actions/update-pins/action.yml").read_text(
        encoding="utf-8"
    )
    paths = action.split("        add-paths: |\n", 1)[1].split(
        "        commit-message:", 1
    )[0]
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    for name in (*workflows, ".github/config.json", "README.md", "outside.yml"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("content\n", encoding="utf-8")
    staged = subprocess.run(
        ["git", "add", "--", *paths.split()],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert staged.returncode == 0, staged.stderr
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    assert set(result.stdout.splitlines()) == set(workflows)
