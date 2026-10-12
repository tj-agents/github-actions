#!/usr/bin/env python3
"""Generate a plugin repository's host discovery entries, marketplaces and installable payloads.

Vendored from the kit repository and pinned by `.agents/plugins/kit.json`: change it in kit, never here.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import shutil
import stat


KIT_VERSION = "1.2.1"
FRONTMATTER = re.compile(r"\A---\n(?P<header>.*?)\n---\n(?P<body>.*)\Z", re.DOTALL)
NAME = re.compile(r"^[a-z][a-z0-9-]*$")
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/([a-z][a-z0-9-]*)$")
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
URL_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
BARE_SKILL_REFERENCE = re.compile(r"`([a-z][a-z0-9-]+)`\s+skill(?:'s)?")
MARKDOWN_LINK = re.compile(r"\]\(([^)\s]+)\)")
SKILL_DIRECTORY_REFERENCE = re.compile(r"<skill-directory>/([^\s`'\")\]]+)")
REQUIRED_METADATA = ("name", "description", "kind", "domain", "profile", "applicability", "requires", "provenance")
REPOSITORY_TYPES = ("stack", "tool", "utility")
RESERVED_AGENT_DIRS = {"continuation", "plugins", "tiers", "tests", "hooks"}
IGNORED_PARTS = {"__pycache__"}
IGNORED_SUFFIXES = {".pyc"}
HOSTS = ("claude", "codex")
ADAPTER_ROOTS = {"claude": ".claude/skills", "codex": ".codex/skills"}
MANIFEST_ROOT = ".agents/plugins/manifests"
MARKETPLACE_OUTPUTS = {"claude": ".claude-plugin/marketplace.json", "codex": ".agents/plugins/marketplace.json"}
MARKETPLACE_FIELDS = {"claude": {"name", "description", "owner"}, "codex": {"name", "interface"}}
CODEX_POLICY = {"installation": "INSTALLED_BY_DEFAULT", "authentication": "ON_INSTALL"}
GENERATED_ROOTS = (
    ".claude/skills",
    ".codex/skills",
    "plugins",
    ".claude-plugin/marketplace.json",
    ".agents/plugins/marketplace.json",
    ".agents/INDEX.md",
)
TIER_MATCHERS = ("files", "globs", "content", "remote")
PAYLOAD_FIELDS = {"payloads", "dependencies", "compatibilitySkillAliases"}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def load(path: Path):
    try:
        return json.loads(read(path))
    except FileNotFoundError:
        raise ValueError(f"Missing {path.as_posix()}") from None


def dump(value) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def ignored(path: PurePosixPath | Path) -> bool:
    return bool(IGNORED_PARTS.intersection(path.parts)) or path.suffix in IGNORED_SUFFIXES


def is_link_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if is_junction is not None and is_junction():
        return True
    if os.name != "nt":
        return False
    try:
        attributes = path.lstat().st_file_attributes
    except FileNotFoundError:
        return False
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def load_config(root: Path) -> dict:
    config = load(root / ".agents/plugins/kit.json")
    if config.get("schema_version") != 1:
        raise ValueError(".agents/plugins/kit.json: schema_version must be 1")
    if config.get("kit") != KIT_VERSION:
        raise ValueError(
            f".agents/plugins/kit.json pins kit {config.get('kit')} but this generator is kit {KIT_VERSION}; "
            "run kit:update"
        )
    if config.get("type") not in REPOSITORY_TYPES:
        raise ValueError(f".agents/plugins/kit.json: type must be one of {', '.join(REPOSITORY_TYPES)}")
    match = REPOSITORY.fullmatch(str(config.get("repository", "")))
    if match is None:
        raise ValueError(".agents/plugins/kit.json: repository must be owner/name with a lowercase name")
    unknown = set(config) - {"schema_version", "kit", "type", "repository"}
    if unknown:
        raise ValueError(f".agents/plugins/kit.json: unknown fields {sorted(unknown)}")
    return {**config, "namespace": match.group(1)}


def metadata(body: str, source: str) -> dict[str, str]:
    match = FRONTMATTER.match(body)
    if match is None:
        raise ValueError(f"{source}: missing frontmatter")
    values: dict[str, str] = {}
    for line in match.group("header").splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            values[key.strip()] = value.strip()
    for field in REQUIRED_METADATA:
        if not values.get(field):
            raise ValueError(f"{source}: missing {field}")
    for field in ("name", "kind", "profile"):
        if not NAME.fullmatch(values[field]):
            raise ValueError(f"{source}: {field} must be a lowercase name")
    return values


def is_skill_folder(path: Path) -> bool:
    return path.is_dir() and not ignored(path) and not is_link_or_junction(path) and (path / "SKILL.md").is_file()


def load_skill(root: Path, plugin: str, kind: str, directory: Path, name: str, namespace: str) -> dict:
    path = directory / "SKILL.md"
    relative = path.relative_to(root).as_posix()
    raw = path.read_bytes()
    if b"\xef\xbb\xbf" in raw:
        raise ValueError(f"{relative}: embedded UTF-8 BOM")
    body = raw.decode("utf-8").replace("\r\n", "\n")
    values = metadata(body, relative)
    if values["name"] != name:
        raise ValueError(f"{relative}: name must be {name}, its folder path below the kind folder joined by hyphens")
    if values["kind"] != kind:
        raise ValueError(f"{relative}: kind must equal its kind folder")
    if values["domain"] != namespace:
        raise ValueError(f"{relative}: domain must be {namespace}")
    members = {item.name for item in directory.iterdir() if is_skill_folder(item)}
    files: list[str] = []
    for item in sorted(directory.rglob("*")):
        part = item.relative_to(directory)
        if ignored(part) or part.parts[0] in members:
            continue
        if is_link_or_junction(item):
            raise ValueError(f"{item.relative_to(root).as_posix()}: links are not shipped")
        if item.is_file() and item != path:
            files.append(part.as_posix())
    return {
        "plugin": plugin,
        "name": values["name"],
        "kind": kind,
        "body": body,
        "metadata": values,
        "directory": directory.relative_to(root).as_posix(),
        "files": files,
    }


def collect_skills(
    root: Path, plugin: str, kind: str, directory: Path, family: tuple[str, ...], namespace: str, skills: dict[str, dict]
) -> None:
    location = directory.relative_to(root).as_posix()
    if is_link_or_junction(directory):
        raise ValueError(f"{location}: links are not shipped")
    if not directory.is_dir() or not NAME.fullmatch(directory.name):
        raise ValueError(f"{location}: kind and family folders hold only skill folders and family folders")
    parts = (*family, directory.name)
    if (directory / "SKILL.md").is_file():
        skill = load_skill(root, plugin, kind, directory, "-".join(parts), namespace)
        if skill["name"] in skills:
            raise ValueError(f"{plugin}: duplicate skill {skill['name']}")
        skills[skill["name"]] = skill
        members = [item for item in sorted(directory.iterdir()) if is_skill_folder(item)]
    else:
        members = sorted(path for path in directory.iterdir() if not ignored(path))
        if not members:
            raise ValueError(f"{location}: a family folder holds skill folders")
    for member in members:
        collect_skills(root, plugin, kind, member, parts, namespace, skills)


def discover(root: Path, namespace: str) -> dict[str, dict[str, dict]]:
    agents = root / ".agents"
    plugins: dict[str, dict[str, dict]] = {}
    for plugin_dir in sorted(path for path in agents.iterdir() if path.is_dir() and not ignored(path)):
        if plugin_dir.name in RESERVED_AGENT_DIRS:
            continue
        plugin = plugin_dir.name
        if not NAME.fullmatch(plugin):
            raise ValueError(f".agents/{plugin}: a plugin folder must be a lowercase name")
        skills: dict[str, dict] = {}
        for kind_dir in sorted(path for path in plugin_dir.iterdir() if not ignored(path)):
            if not kind_dir.is_dir() or not NAME.fullmatch(kind_dir.name):
                raise ValueError(f".agents/{plugin}/{kind_dir.name}: only kind folders belong in a plugin folder")
            for entry in sorted(path for path in kind_dir.iterdir() if not ignored(path)):
                collect_skills(root, plugin, kind_dir.name, entry, (), namespace, skills)
        if not skills:
            raise ValueError(f".agents/{plugin}: a plugin folder needs at least one skill")
        plugins[plugin] = skills
    if not plugins:
        raise ValueError("No plugin folder with skills under .agents/")
    return plugins


def validate_payloads(payloads: dict, plugins: dict[str, dict[str, dict]]) -> None:
    unknown = set(payloads) - PAYLOAD_FIELDS
    if unknown:
        raise ValueError(f".agents/plugins/payloads.json: unknown fields {sorted(unknown)}")
    if payloads.get("payloads") != {plugin: [plugin] for plugin in plugins}:
        raise ValueError(
            ".agents/plugins/payloads.json: payloads must map each plugin folder to itself: "
            + ", ".join(sorted(plugins))
        )
    for plugin, needs in payloads.get("dependencies", {}).items():
        if plugin not in plugins or not isinstance(needs, list) or not all(isinstance(need, str) for need in needs) or len(needs) != len(set(needs)):
            raise ValueError(f".agents/plugins/payloads.json: invalid dependencies for {plugin}")
        for need in needs:
            if (need not in plugins and not re.fullmatch(r"[a-z0-9][a-z0-9-]*/[a-z0-9][a-z0-9-]*", need)) or need == plugin:
                raise ValueError(f".agents/plugins/payloads.json: {plugin} cannot depend on {need}")
    for plugin, aliases in payloads.get("compatibilitySkillAliases", {}).items():
        if plugin not in plugins or not isinstance(aliases, dict):
            raise ValueError(f".agents/plugins/payloads.json: invalid compatibility aliases for {plugin}")
        skills = plugins[plugin]
        for alias, declaration in aliases.items():
            if not isinstance(declaration, dict) or set(declaration) != {"replacedBy", "removeAfter"}:
                raise ValueError(f"{plugin}:{alias}: an alias declares exactly replacedBy and removeAfter")
            target = str(declaration["replacedBy"]).removeprefix(f"{plugin}:")
            if (
                alias not in skills
                or declaration["replacedBy"] != f"{plugin}:{target}"
                or target not in skills
                or target in aliases
            ):
                raise ValueError(f"{plugin}:{alias}: an alias must forward to another skill of the same plugin")
            if not DATE.fullmatch(str(declaration["removeAfter"])):
                raise ValueError(f"{plugin}:{alias}: removeAfter must be YYYY-MM-DD")
            if skills[alias]["metadata"]["profile"] != skills[target]["metadata"]["profile"]:
                raise ValueError(f"{plugin}:{alias}: an alias keeps its replacement's profile")


def validate_tiers(root: Path, plugins: dict, repository: str) -> None:
    tier_dir = root / ".agents/tiers"
    present = sorted(path.name for path in tier_dir.iterdir()) if tier_dir.is_dir() else []
    expected = sorted(f"{plugin}.json" for plugin in plugins)
    if present != expected:
        raise ValueError(f".agents/tiers must hold exactly {', '.join(expected)}")
    for plugin in plugins:
        source = f".agents/tiers/{plugin}.json"
        tier = load(root / source)
        if tier.get("schema_version") not in (1, 2, 3):
            raise ValueError(f"{source}: schema_version must be 1, 2 or 3")
        if tier.get("tier") != plugin:
            raise ValueError(f"{source}: tier must be {plugin}")
        owners = tier.get("owner_repository")
        owners = [owners] if isinstance(owners, str) else owners or []
        if repository.lower() not in {str(owner).lower() for owner in owners}:
            raise ValueError(f"{source}: owner_repository must name {repository}")
        detect = tier.get("detect")
        if tier.get("applies") == "always":
            if detect is not None:
                raise ValueError(f"{source}: an always-applicable tier declares no detect markers")
        elif tier.get("applies") == "stack-present":
            if tier.get("schema_version") == 3:
                if not isinstance(detect, dict) or not detect:
                    raise ValueError(f"{source}: a stack-present tier needs a detect predicate")
                continue
            if not isinstance(detect, dict) or not any(detect.get(field) for field in TIER_MATCHERS):
                raise ValueError(f"{source}: a stack-present tier needs at least one detect marker")
            if set(detect) - set(TIER_MATCHERS):
                raise ValueError(f"{source}: unknown detect matchers {sorted(set(detect) - set(TIER_MATCHERS))}")
        else:
            raise ValueError(f"{source}: applies must be always or stack-present")


def load_manifests(root: Path, plugins: dict, repository: str) -> tuple[dict, dict]:
    expected = sorted([f"{plugin}.json" for plugin in plugins] + ["marketplace.json"])
    manifests: dict[str, dict] = {}
    templates: dict[str, dict] = {}
    for host in HOSTS:
        host_dir = root / MANIFEST_ROOT / host
        present = sorted(path.name for path in host_dir.iterdir()) if host_dir.is_dir() else []
        if present != expected:
            raise ValueError(f"{MANIFEST_ROOT}/{host} must hold exactly {', '.join(expected)}")
        manifests[host] = {plugin: load(host_dir / f"{plugin}.json") for plugin in plugins}
        templates[host] = load(host_dir / "marketplace.json")
        if set(templates[host]) != MARKETPLACE_FIELDS[host]:
            raise ValueError(
                f"{MANIFEST_ROOT}/{host}/marketplace.json declares exactly {sorted(MARKETPLACE_FIELDS[host])}; "
                "its plugin entries are generated"
            )
    if not NAME.fullmatch(str(templates["claude"]["name"])) or templates["claude"]["name"] != templates["codex"]["name"]:
        raise ValueError("Claude and Codex marketplaces must share one lowercase name")
    if not templates["codex"]["interface"].get("displayName") or not templates["claude"]["owner"].get("name"):
        raise ValueError("Marketplaces need an owner name and a display name")
    for plugin in plugins:
        claude, codex = manifests["claude"][plugin], manifests["codex"][plugin]
        for field in ("name", "description", "author", "repository", "skills", "keywords"):
            if not codex.get(field) or codex.get(field) != claude.get(field):
                raise ValueError(f"{plugin}: Claude and Codex manifests disagree on {field}")
        if codex["name"] != plugin or codex["skills"] != "./skills/":
            raise ValueError(f"{plugin}: manifests must keep the {plugin} identity and the ./skills/ path")
        if codex["repository"] != f"https://github.com/{repository}":
            raise ValueError(f"{plugin}: manifest repository must be https://github.com/{repository}")
        if "version" in claude:
            raise ValueError(f"{plugin}: the Claude manifest stays commit-versioned and omits version")
        if not SEMVER.fullmatch(str(codex.get("version", ""))):
            raise ValueError(f"{plugin}: the Codex manifest declares a semantic version")
        interface = codex.get("interface") or {}
        if not claude.get("displayName") or claude["displayName"] != interface.get("displayName"):
            raise ValueError(f"{plugin}: Claude and Codex manifests disagree on display name")
        if not interface.get("category"):
            raise ValueError(f"{plugin}: the Codex manifest interface declares a category")
    return manifests, templates


def adapter_name(skill: dict, single_plugin: bool) -> str:
    return skill["name"] if single_plugin else f"{skill['plugin']}-{skill['name']}"


def adapter_body(skill: dict, adapter_dir: str) -> str:
    source = f"{skill['directory']}/SKILL.md"
    relative = posixpath.relpath(f"/{source}", f"/{adapter_dir}")
    match = FRONTMATTER.match(skill["body"])
    title = next((line for line in match.group("body").splitlines() if line.startswith("# ")), f"# {skill['name']}")
    return (
        f"---\n{match.group('header')}\n---\n\n{title}\n\n"
        f"Read and follow the [canonical definition]({relative}) in full.\n"
        "This discovery entry is generated; edit the referenced `.agents/` definition.\n"
    )


def references(body: str):
    for target in MARKDOWN_LINK.findall(body):
        if URL_SCHEME.match(target) or target.startswith(("#", "/")):
            continue
        target = target.split("#", 1)[0]
        if target:
            yield target
    for target in SKILL_DIRECTORY_REFERENCE.findall(body):
        yield target.rstrip(".,;:")


def validate_skill_references(plugins: dict[str, dict[str, dict]]) -> None:
    qualified = re.compile(
        r"(?<![-/\w])(" + "|".join(re.escape(plugin) for plugin in sorted(plugins)) + r"):(?!:)([a-z][a-z0-9-]+)"
    )
    for plugin, skills in plugins.items():
        for skill in skills.values():
            for namespace, name in qualified.findall(skill["body"]):
                if name not in plugins[namespace]:
                    raise ValueError(f"{plugin}:{skill['name']}: unknown skill reference {namespace}:{name}")
            for name in BARE_SKILL_REFERENCE.findall(skill["body"]):
                if name not in skills:
                    raise ValueError(f"{plugin}:{skill['name']}: unknown skill reference `{name}` skill")


def validate_file_references(root: Path, plugins: dict, locations: dict[tuple[str, str], list[str]], output: dict) -> None:
    def present(path: str) -> bool:
        return path in output or any(key.startswith(path + "/") for key in output)

    for plugin, skills in plugins.items():
        for skill in skills.values():
            for target in sorted(set(references(skill["body"]))):
                source = posixpath.normpath(posixpath.join(skill["directory"], target))
                if source.startswith("../") or not (root / source).exists():
                    raise ValueError(f"{plugin}:{skill['name']}: {target} does not resolve from {skill['directory']}")
                for base in locations[(plugin, skill["name"])]:
                    shipped = posixpath.normpath(posixpath.join(base, target))
                    if not present(shipped):
                        raise ValueError(f"{plugin}:{skill['name']}: {target} does not resolve from generated {base}")


def build(root: Path) -> dict[str, bytes]:
    config = load_config(root)
    namespace, repository = config["namespace"], config["repository"]
    plugins = discover(root, namespace)
    payloads = load(root / ".agents/plugins/payloads.json")
    validate_payloads(payloads, plugins)
    validate_tiers(root, plugins, repository)
    manifests, templates = load_manifests(root, plugins, repository)
    validate_skill_references(plugins)
    aliases = payloads.get("compatibilitySkillAliases", {})
    dependencies = payloads.get("dependencies", {})
    single_plugin = len(plugins) == 1

    output: dict[str, bytes] = {}
    locations: dict[tuple[str, str], list[str]] = {}

    def emit(relative: str, data: str | bytes) -> None:
        key = PurePosixPath(relative).as_posix()
        if key in output:
            raise ValueError(f"Duplicate generated output: {key}")
        output[key] = data.encode("utf-8") if isinstance(data, str) else data

    def emit_skill(directory: str, skill: dict, body: str) -> None:
        emit(f"{directory}/SKILL.md", body)
        for file in skill["files"]:
            emit(f"{directory}/{file}", (root / skill["directory"] / file).read_bytes())

    repository_index = [
        f"# {namespace} capabilities",
        "",
        "Generated from `.agents/<plugin>/<kind>/<family>/<member>/SKILL.md`; a skill's name is its folder path below "
        "the kind folder joined by hyphens.",
        "",
    ]
    for plugin, skills in plugins.items():
        ordered = sorted(skills.values(), key=lambda item: (item["kind"], item["name"]))
        plugin_aliases = aliases.get(plugin, {})
        for skill in ordered:
            package_dir = f"plugins/{plugin}/skills/{skill['name']}"
            emit_skill(package_dir, skill, skill["body"])
            locations[(plugin, skill["name"])] = [package_dir]
            for adapter_root in ADAPTER_ROOTS.values():
                adapter_dir = f"{adapter_root}/{adapter_name(skill, single_plugin)}"
                emit_skill(adapter_dir, skill, adapter_body(skill, adapter_dir))
                locations[(plugin, skill["name"])].append(adapter_dir)

        entries = [f"- `{skill['name']}` — {skill['kind']} — {skill['metadata']['profile']}" for skill in ordered]
        repository_index += [f"## {plugin}", ""]
        repository_index += [f"{entry} — `{skill['directory']}/SKILL.md`" for entry, skill in zip(entries, ordered)]
        repository_index.append("")
        emit(f"plugins/{plugin}/INDEX.md", "\n".join([f"# {plugin} package capabilities", "", *entries, ""]))

        profiles: dict[str, list[str]] = {}
        for skill in ordered:
            if skill["name"] not in plugin_aliases:
                profiles.setdefault(skill["metadata"]["profile"], []).append(skill["name"])
        selection = {
            "plugin": plugin,
            "dependencies": dependencies.get(plugin, []),
            "profiles": {profile: sorted(names) for profile, names in sorted(profiles.items())},
            "compatibilitySkillAliases": plugin_aliases,
            "skills": [
                {
                    "name": skill["name"],
                    "kind": skill["kind"],
                    "profile": skill["metadata"]["profile"],
                    "applicability": split_tags(skill["metadata"]["applicability"]),
                    "requires": split_tags(skill["metadata"]["requires"]),
                    "provenance": split_tags(skill["metadata"]["provenance"]),
                }
                for skill in sorted(ordered, key=lambda item: item["name"])
            ],
        }
        emit(f"plugins/{plugin}/selection.json", dump(selection))
        emit(f"plugins/{plugin}/tier.json", read(root / f".agents/tiers/{plugin}.json"))
        harness = root / MANIFEST_ROOT / "harness" / f"{plugin}.json"
        if harness.is_file():
            load(harness)
            emit(f"plugins/{plugin}/harness.json", read(harness))
        for host in HOSTS:
            emit(f"plugins/{plugin}/.{host}-plugin/plugin.json", read(root / MANIFEST_ROOT / host / f"{plugin}.json"))

    emit(".agents/INDEX.md", "\n".join(repository_index))
    claude_entries, codex_entries = [], []
    for plugin in plugins:
        claude, codex = manifests["claude"][plugin], manifests["codex"][plugin]
        category = codex["interface"]["category"]
        claude_entries.append(
            {
                "name": plugin,
                "source": f"./plugins/{plugin}",
                "description": claude["description"],
                "category": category,
                "keywords": claude["keywords"],
            }
        )
        codex_entries.append(
            {
                "name": plugin,
                "source": {"source": "local", "path": f"./plugins/{plugin}"},
                "policy": CODEX_POLICY,
                "category": category,
            }
        )
    emit(MARKETPLACE_OUTPUTS["claude"], dump({**templates["claude"], "plugins": claude_entries}))
    emit(MARKETPLACE_OUTPUTS["codex"], dump({**templates["codex"], "plugins": codex_entries}))
    validate_file_references(root, plugins, locations, output)
    return output


def split_tags(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def generated_root_paths(root: Path) -> list[Path]:
    resolved_root = root.resolve()
    result: list[Path] = []
    for value in GENERATED_ROOTS:
        relative = PurePosixPath(value)
        ancestor = resolved_root
        for part in relative.parts:
            ancestor = ancestor / part
            if is_link_or_junction(ancestor):
                raise ValueError(f"Generated root must not be or sit under a link or junction: {value}")
        path = resolved_root.joinpath(*relative.parts).resolve()
        if path == resolved_root or not path.is_relative_to(resolved_root):
            raise ValueError(f"Generated root escapes the repository: {value}")
        result.append(path)
    return result


def existing_files(root: Path) -> set[str]:
    result: set[str] = set()
    for value in GENERATED_ROOTS:
        path = root / value
        if path.is_dir():
            result.update(
                item.relative_to(root).as_posix()
                for item in path.rglob("*")
                if item.is_file() and not ignored(item.relative_to(root))
            )
        elif path.is_file():
            result.add(value)
    return result


def synchronize(root: Path, check: bool) -> int:
    output = build(root)
    expected = set(output)
    actual = existing_files(root)
    if check:
        stale = sorted(path for path in expected & actual if (root / path).read_bytes() != output[path])
        problems = [("MISSING", sorted(expected - actual)), ("STALE", stale), ("EXTRA", sorted(actual - expected))]
        for label, paths in problems:
            for path in paths:
                print(f"{label}: {path}")
        if any(paths for _, paths in problems):
            return 1
        print(f"generated outputs current: {len(expected)} files")
        return 0
    for path in generated_root_paths(root):
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    for relative, data in output.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    print(f"generated {len(expected)} files")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        return synchronize(args.root.resolve(), args.check)
    except ValueError as error:
        print(f"error: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
