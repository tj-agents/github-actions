import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "updater_staging", ROOT / ".github/actions/update-pins/update_pins.py"
)
assert SPEC is not None and SPEC.loader is not None
updater = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(updater)


@pytest.mark.parametrize(
    "workflows",
    [
        (".github/workflows/ci.yml",),
        (".github/workflows/ci.yaml",),
        (".github/workflows/ci.yml", ".github/actions/check/action.yaml"),
    ],
)
def test_stages_workflows_when_either_yaml_extension_is_absent(
    tmp_path: Path, workflows: tuple[str, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    action = (ROOT / ".github/actions/update-pins/action.yml").read_text(
        encoding="utf-8"
    )
    assert "add-paths: ${{ steps.update.outputs.add-paths }}" in action
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    unrelated = (
        ".github/config.json",
        ".github/workflows/extra.yxml",
        ".github/workflows/extra.ykml",
        ".github/workflows/extra.yamml",
        "README.md",
        "outside.yml",
    )
    original = "uses: neutral/actions@" + "a" * 40 + "\n"
    for name in (*workflows, *unrelated):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(original, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    summary = updater.update(
        tmp_path,
        ["neutral/actions"],
        resolver=lambda _: "b" * 40,
        comparer=lambda *_: None,
        content_comparer=lambda *_: True,
    )
    output = tmp_path / "outputs"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    updater.write_outputs(summary)
    outputs = dict(
        line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines()
    )
    paths = outputs["add-paths"].split(",")
    assert set(paths) == {f".github/**/*{Path(name).suffix}" for name in workflows}
    subprocess.run(["git", "read-tree", "--empty"], cwd=tmp_path, check=True)
    staged = subprocess.run(
        ["git", "add", "--", *paths],
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
    for name in unrelated:
        assert (tmp_path / name).read_text(encoding="utf-8") == original
