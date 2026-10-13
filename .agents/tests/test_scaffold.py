import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / ".agents/github-actions/utility/scaffold"
SCRIPT = SKILL / "scripts/scaffold.py"
SPEC = importlib.util.spec_from_file_location("workflow_scaffold", SCRIPT)
scaffold = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scaffold)

if os.environ.get("REQUIRE_RELEASE_TESTS") == "true" and not shutil.which("node"):
    raise RuntimeError("CI must provide Node to execute the release assertion tests")


def fixture():
    return json.loads((SKILL / "examples/service.json").read_text(encoding="utf-8"))


def body(name):
    return scaffold.asset(name).split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]


class RenderingTests(unittest.TestCase):
    def test_plan_waits_for_successful_lint_and_validation_before_provider_setup(self):
        config = fixture()
        config["provider"]["oidc"] = True
        config["provider"]["ready"] = "vars.FOUNDATION_READY == 'true'"
        config["provider"]["phases"]["setup"] = {"steps": [{"name": "Sign in to the provider", "run": "echo login"}]}
        _, docs = scaffold.render_documents(config)
        plan = docs[".github/workflows/pr.yml"]["jobs"]["plan"]
        self.assertEqual(["lint", "validate"], plan["needs"])
        for condition in (scaffold.TRUSTED, "vars.FOUNDATION_READY == 'true'", "needs.lint.result == 'success'", "needs.validate.result == 'success'"):
            self.assertIn(condition, plan["if"])
        self.assertEqual("write", plan["permissions"]["id-token"])
        self.assertEqual("./.github/actions/cloud-setup", plan["steps"][-2]["uses"])
        self.assertEqual("Plan deployment", plan["steps"][-1]["name"])

    def test_distinct_joined_step_ids_and_references_are_preserved(self):
        config = fixture()
        config["build"]["steps"][0]["id"] = "package"
        phases = config["provider"]["phases"]
        phases["deploy"]["steps"][0]["id"] = "deployed"
        phases["readiness"]["steps"][0].update({"id": "serving", "env": {"REVISION": "${{ steps.deployed.outputs.revision }}"}})
        _, docs = scaffold.render_documents(config)
        deploy = docs[".github/workflows/deploy-environment.yml"]["jobs"]["deploy"]
        self.assertEqual(["deployed", "serving"], [step["id"] for step in deploy["steps"] if "id" in step])
        self.assertEqual("${{ steps.deployed.outputs.revision }}", deploy["steps"][-1]["env"]["REVISION"])
        for event in ("pr", "ci"):
            build = docs[f".github/workflows/{event}.yml"]["jobs"]["build"]
            self.assertEqual(["package", "artifact"], [step["id"] for step in build["steps"] if "id" in step])
            self.assertEqual("${{ steps.artifact.outputs.artifact-id }}", build["outputs"]["artifact-id"])

    def test_setup_and_plan_env_have_separate_scopes_and_step_override(self):
        config = fixture()
        phases = config["provider"]["phases"]
        phases["setup"] = {"env": {"MODE": "setup", "SETUP_ONLY": "true"}, "steps": [{"name": "Initialize the provider", "run": "echo setup"}, {"name": "Select setup mode", "run": "echo override", "env": {"MODE": "setup-step"}}]}
        phases["plan"]["env"] = {"MODE": "plan", "PLAN_ONLY": "true"}
        phases["plan"]["steps"].append({"name": "Inspect plan", "uses": "actions/github-script", "with": {"script": "return true;"}, "env": {"MODE": "plan-step"}})
        original = copy.deepcopy(config)
        _, docs = scaffold.render_documents(config)
        plan = docs[".github/workflows/pr.yml"]["jobs"]["plan"]
        invocation = next(step for step in plan["steps"] if step.get("uses") == "./.github/actions/cloud-setup")
        self.assertEqual({"MODE": "setup", "SETUP_ONLY": "true"}, invocation["env"])
        self.assertEqual({"MODE": "plan", "PLAN_ONLY": "true"}, plan["steps"][-2]["env"])
        self.assertEqual({"MODE": "plan-step", "PLAN_ONLY": "true"}, plan["steps"][-1]["env"])
        self.assertEqual({"DEPLOY_ENVIRONMENT": "preview", "PREVIEW_NUMBER": "${{ github.event.pull_request.number }}"}, plan["env"])
        self.assertNotIn("env", plan["steps"][0])
        setup = docs[".github/actions/cloud-setup/action.yml"]["runs"]["steps"]
        self.assertNotIn("env", setup[0])
        self.assertEqual({"MODE": "setup-step"}, setup[1]["env"])
        self.assertEqual(original, config)

    def test_deploy_and_readiness_env_have_separate_scopes_and_step_override(self):
        config = fixture()
        phases = config["provider"]["phases"]
        phases["deploy"]["env"] = {"MODE": "apply", "DEPLOY_ONLY": "true"}
        phases["readiness"]["env"] = {"MODE": "serving", "READINESS_ONLY": "true"}
        phases["readiness"]["steps"].append({"name": "Inspect serving revision", "run": "echo inspect", "env": {"MODE": "inspect"}})
        _, docs = scaffold.render_documents(config)
        job = docs[".github/workflows/deploy-environment.yml"]["jobs"]["deploy"]
        self.assertEqual({"MODE": "apply", "DEPLOY_ONLY": "true"}, job["steps"][-3]["env"])
        self.assertEqual({"MODE": "serving", "READINESS_ONLY": "true"}, job["steps"][-2]["env"])
        self.assertEqual({"MODE": "inspect", "READINESS_ONLY": "true"}, job["steps"][-1]["env"])
        self.assertEqual({"DEPLOY_ENVIRONMENT": "${{ inputs.environment }}", "PREVIEW_NUMBER": "${{ inputs.preview-number }}", "SOURCE_RUN_ID": "${{ inputs.source-run-id }}", "SOURCE_SHA": "${{ inputs.source-sha }}"}, job["env"])
        for step in job["steps"][:-3]:
            self.assertNotIn("env", step)

    def test_verify_validate_destroy_and_recovery_env_stay_on_their_steps(self):
        config = fixture()
        config["verify"]["end-to-end"] = {"steps": [{"name": "Verify serving", "run": "echo serving"}]}
        phases = config["provider"]["phases"]
        phases["setup"] = {"env": {"MODE": "setup", "SETUP_ONLY": "true"}, "steps": [{"name": "Initialize the provider", "run": "echo setup"}]}
        config["verify"]["unit"]["matrix"] = {"runtime": ["stable", "preview"]}
        scopes = [("pr", "verify-" + layer, val) for layer, val in config["verify"].items()]
        scopes.extend([("ci", "validate", phases["validate"]), ("pr", "recover-preview", phases["recover"]), ("destroy-preview", "destroy", phases["destroy"])])
        for _, key, val in scopes:
            val["env"] = {"MODE": key, "PHASE_ONLY": "true"}
            val["steps"].append({"name": "Inspect " + key, "run": "echo inspect", "env": {"MODE": "step"}})
        _, docs = scaffold.render_documents(config)
        for event, key, _ in scopes:
            with self.subTest(job=key):
                job = docs[f".github/workflows/{event}.yml"]["jobs"][key]
                self.assertEqual({"MODE": key, "PHASE_ONLY": "true"}, job["steps"][-2]["env"])
                self.assertEqual({"MODE": "step", "PHASE_ONLY": "true"}, job["steps"][-1]["env"])
                self.assertFalse({"MODE", "PHASE_ONLY", "SETUP_ONLY"} & job.get("env", {}).keys())
                for step in job["steps"][:-2]:
                    if step.get("uses") == "./.github/actions/cloud-setup":
                        self.assertEqual({"MODE": "setup", "SETUP_ONLY": "true"}, step["env"])
                    else:
                        self.assertNotIn("env", step)
        self.assertEqual({"fail-fast": False, "matrix": {"runtime": ["stable", "preview"]}}, docs[".github/workflows/pr.yml"]["jobs"]["verify-unit"]["strategy"])

    def test_cloud_build_setup_env_does_not_reach_build_or_upload(self):
        config = fixture()
        config["build"]["oidc"] = True
        config["build"]["steps"][0]["env"] = {"MODE": "build"}
        config["provider"]["phases"]["setup"] = {"env": {"MODE": "setup", "SETUP_ONLY": "true"}, "steps": [{"name": "Initialize the provider", "run": "echo setup"}]}
        _, docs = scaffold.render_documents(config)
        for event in ("pr", "ci"):
            job = docs[f".github/workflows/{event}.yml"]["jobs"]["build"]
            self.assertEqual({"MODE": "setup", "SETUP_ONLY": "true"}, job["steps"][-3]["env"])
            self.assertEqual({"MODE": "build"}, job["steps"][-2]["env"])
            self.assertNotIn("env", job["steps"][-1])
            self.assertEqual({"DEPLOY_ENVIRONMENT", "PREVIEW_NUMBER", "SOURCE_SHA", "SOURCE_RUN_ID"}, job["env"].keys())

    def test_cloud_phase_roots_install_declared_toolchains(self):
        config = fixture()
        config["provider"]["oidc"] = True
        for phase in ("deploy", "readiness", "destroy", "recover"):
            config["provider"]["phases"][phase]["roots"] = ["src/service"]
        _, docs = scaffold.render_documents(config, {"global.json": '{"sdk":{"version":"10.0.100"}}', "src/service/packages.lock.json": "{}"})
        jobs = [docs[".github/workflows/deploy-environment.yml"]["jobs"]["deploy"], docs[".github/workflows/destroy-preview.yml"]["jobs"]["destroy"], docs[".github/workflows/pr.yml"]["jobs"]["recover-preview"]]
        for job in jobs:
            installations = [step for step in job["steps"] if "setup-dotnet" in step.get("uses", "")]
            self.assertEqual(1, len(installations))
            self.assertEqual({"global-json-file": "global.json"}, installations[0]["with"])
            self.assertLess(job["steps"].index(installations[0]), len(job["steps"]) - 1)

    def test_complete_default_set_and_optional_release(self):
        config = fixture()
        files = scaffold.render(config)
        expected = {"pr.yml", "ci.yml", "prod.yml", "pr-closed.yml", "deploy-environment.yml", "destroy-preview.yml"}
        self.assertEqual(expected, {Path(path).name for path in files if path.startswith(".github/workflows/")})
        config["prod-release"] = False
        without_release = scaffold.render(config)
        self.assertEqual(set(files) - {".github/workflows/prod.yml"}, set(without_release))
        for path in set(without_release) - {".scaffold.github-actions.json"}:
            self.assertEqual(files[path], without_release[path])
        self.assertEqual({"prod-release": False}, json.loads(without_release[".scaffold.github-actions.json"])["options"])

    def test_provider_does_not_need_a_workload_artifact(self):
        config = fixture()
        del config["build"]
        _, docs = scaffold.render_documents(config)
        self.assertNotIn("build", docs[".github/workflows/ci.yml"]["jobs"])
        assertion = docs[".github/workflows/prod.yml"]["jobs"]["assert-release-commit"]
        self.assertEqual("false", assertion["steps"][0]["env"]["REQUIRE_ARTIFACT"])
        self.assertFalse(any("download-artifact" in step.get("uses", "") for step in docs[".github/workflows/deploy-environment.yml"]["jobs"]["deploy"]["steps"]))

    def test_graph_promotes_the_verified_artifact_without_a_second_build(self):
        _, docs = scaffold.render_documents(fixture())
        ci = docs[".github/workflows/ci.yml"]["jobs"]
        self.assertEqual(["verify-unit", "verify-integration", "lint", "validate"], ci["build"]["needs"])
        self.assertEqual("${{ needs.build.outputs.artifact-id }}", ci["deploy-ci"]["with"]["artifact-id"])
        deploy = docs[".github/workflows/deploy-environment.yml"]["jobs"]["deploy"]
        self.assertFalse(any(step["name"] == "Build the versioned package" for step in deploy["steps"]))
        download = next(step for step in deploy["steps"] if "download-artifact" in step.get("uses", ""))
        self.assertEqual("${{ inputs.artifact-id }}", download["with"]["artifact-ids"])
        self.assertEqual("${{ inputs.source-run-id }}", download["with"]["run-id"])
        directory_step = next(step for step in deploy["steps"] if step["name"] == "Set the verified artifact directory")
        self.assertLess(deploy["steps"].index(directory_step), deploy["steps"].index(download))
        self.assertIn('"$RUNNER_TEMP"', directory_step["run"])
        self.assertIn('"$GITHUB_ENV"', directory_step["run"])
        self.assertNotIn("ARTIFACT_DIRECTORY", deploy["env"])
        release = docs[".github/workflows/prod.yml"]["jobs"]["deploy-prod"]
        self.assertEqual(["assert-release-commit"], release["needs"])
        for key in ci["deploy-ci"]["needs"]:
            self.assertIn("needs." + key + ".result == 'success'", ci["deploy-ci"]["if"])
        self.assertEqual("${{ needs.assert-release-commit.outputs.artifact-id }}", release["with"]["artifact-id"])

    def test_security_timeouts_and_immutable_pins(self):
        _, docs = scaffold.render_documents(fixture())
        for path, doc in docs.items():
            if not path.startswith(".github/workflows/"):
                continue
            self.assertEqual({"contents": "read"}, doc["permissions"])
            self.assertIn("concurrency", doc)
            for job in doc["jobs"].values():
                if "uses" in job:
                    self.assertNotIn("timeout-minutes", job)
                else:
                    self.assertGreater(job["timeout-minutes"], 0)
                for step in job.get("steps", []):
                    if "uses" in step and not step["uses"].startswith("./"):
                        self.assertRegex(step["uses"], r"@[a-f0-9]{40} # v\d+\.\d+\.\d+$")
                    if "actions/checkout" in step.get("uses", ""):
                        self.assertIs(False, step["with"]["persist-credentials"])
        self.assertEqual({}, docs[".github/workflows/pr.yml"]["jobs"]["ci-complete"]["permissions"])

    def test_preview_trust_label_recovery_and_shared_teardown_group(self):
        config = fixture()
        config["provider"]["oidc"] = True
        config["provider"]["ready"] = "vars.FOUNDATION_READY == 'true'"
        _, docs = scaffold.render_documents(config)
        pr = docs[".github/workflows/pr.yml"]["jobs"]
        condition = pr["deploy-preview"]["if"]
        for value in (scaffold.TRUSTED, scaffold.PREVIEW, config["provider"]["ready"], "!cancelled()", "needs.plan.result == 'success'"):
            self.assertIn(value, condition)
        self.assertIn("cancelled()", pr["recover-preview"]["if"])
        self.assertEqual("${{ format('deploy-pr-{0}', github.event.pull_request.number) }}", pr["recover-preview"]["concurrency"]["group"])
        destroy = docs[".github/workflows/destroy-preview.yml"]
        deploy = docs[".github/workflows/deploy-environment.yml"]
        self.assertEqual("${{ format('deploy-pr-{0}', inputs.preview-number) }}", destroy["concurrency"]["group"])
        self.assertEqual("${{ inputs.preview-number != '' && format('deploy-pr-{0}', inputs.preview-number) || format('deploy-{0}', inputs.environment) }}", deploy["concurrency"]["group"])
        self.assertFalse(destroy["concurrency"]["cancel-in-progress"])
        self.assertIn(scaffold.TRUSTED, docs[".github/workflows/pr-closed.yml"]["jobs"]["destroy-preview"]["if"])

    def test_pr_readiness_does_not_block_main_foundation_bootstrap(self):
        config = fixture()
        config["provider"]["ready"] = "vars.FOUNDATION_READY == 'true'"
        config["provider"]["environments"] = {"ci": "shared", "preview": "ephemeral", "prod": "production"}
        config["build"]["oidc"] = True
        _, docs = scaffold.render_documents(config)
        ci = docs[".github/workflows/ci.yml"]["jobs"]
        pr = docs[".github/workflows/pr.yml"]["jobs"]
        self.assertNotIn("FOUNDATION_READY", ci["deploy-ci"]["if"])
        self.assertNotIn("FOUNDATION_READY", ci["build"]["if"])
        self.assertIn("FOUNDATION_READY", pr["plan"]["if"])
        self.assertNotIn("deploy-preview", pr["recover-preview"]["if"])
        self.assertEqual("ephemeral", pr["deploy-preview"]["with"]["environment"])
        self.assertEqual("production", docs[".github/workflows/prod.yml"]["jobs"]["deploy-prod"]["with"]["environment"])

    def test_removed_preview_label_does_not_prevent_trusted_ready_close_cleanup(self):
        config = fixture()
        config["provider"]["ready"] = "vars.FOUNDATION_READY == 'true'"
        _, docs = scaffold.render_documents(config)
        close = docs[".github/workflows/pr-closed.yml"]["jobs"]["destroy-preview"]
        self.assertIn(scaffold.TRUSTED, close["if"])
        self.assertIn("FOUNDATION_READY", close["if"])
        self.assertNotIn("labels", close["if"])
        self.assertNotIn("merged", close["if"])

    def test_region_targets_use_the_shared_deploy_matrix(self):
        config = fixture()
        config["provider"]["environments"] = {"prod": ["east-prod", "west-prod"]}
        _, docs = scaffold.render_documents(config)
        prod = docs[".github/workflows/prod.yml"]["jobs"]["deploy-prod"]
        self.assertEqual({"fail-fast": False, "matrix": {"environment": ["east-prod", "west-prod"]}}, prod["strategy"])
        self.assertEqual("${{ matrix.environment }}", prod["with"]["environment"])

    def test_npm_is_selected_after_node_without_duplicating_repository_version(self):
        metadata = {"package.json": '{"engines":{"node":"24.x"},"packageManager":"npm@11.0.0"}'}
        setup = scaffold.toolchains(["."], metadata)
        self.assertIn("setup-node", setup[0]["uses"])
        self.assertEqual("npm@11.0.0", setup[1]["env"]["PACKAGE_MANAGER"])
        self.assertNotIn("11.0.0", setup[1]["run"])

    def test_typed_provider_matrix_and_composite_envelopes(self):
        config = fixture()
        config["provider"]["phases"]["validate"]["matrix"] = {"root": ["foundation", "instance"]}
        config["provider"]["composites"] = {"provider-login": {"description": "Sign in to the provider", "inputs": {"client-id": {"description": "Federated client", "required": True}}, "steps": [{"name": "Sign in", "uses": "azure/login", "with": {"client-id": "${{ inputs.client-id }}", "tenant-id": "${{ vars.TENANT_ID }}", "subscription-id": "${{ vars.SUBSCRIPTION_ID }}"}}]}}
        config["provider"]["phases"]["setup"] = {"steps": [{"name": "Sign in to the provider", "uses": "./.github/actions/provider-login", "with": {"client-id": "${{ vars.CLIENT_ID }}"}}]}
        _, docs = scaffold.render_documents(config)
        self.assertEqual({"fail-fast": False, "matrix": {"root": ["foundation", "instance"]}}, docs[".github/workflows/ci.yml"]["jobs"]["validate"]["strategy"])
        action = docs[".github/actions/provider-login/action.yml"]
        self.assertEqual("composite", action["runs"]["using"])
        self.assertIn(scaffold.PINS["azure/login"][0], action["runs"]["steps"][0]["uses"])

    def test_toolchains_use_ancestor_and_prospective_repository_metadata(self):
        config = fixture()
        config["roots"] = ["src/api", "web"]
        metadata = {"global.json": '{"sdk":{"version":"10.0.100"}}', "web/package.json": '{"engines":{"node":"24.x"},"packageManager":"pnpm@10.0.0"}', "web/pnpm-lock.yaml": "lockfileVersion: '9.0'"}
        _, docs = scaffold.render_documents(config, metadata)
        steps = docs[".github/workflows/ci.yml"]["jobs"]["verify-unit"]["steps"]
        setup_dotnet = next(step for step in steps if "setup-dotnet" in step.get("uses", ""))
        self.assertEqual({"global-json-file": "global.json"}, setup_dotnet["with"])
        setup_node = next(step for step in steps if "setup-node" in step.get("uses", ""))
        self.assertEqual("web/package.json", setup_node["with"]["node-version-file"])
        self.assertEqual("pnpm", setup_node["with"]["cache"])
        self.assertEqual("web/pnpm-lock.yaml", setup_node["with"]["cache-dependency-path"])
        setup_pnpm = next(step for step in steps if "pnpm/action-setup" in step.get("uses", ""))
        self.assertNotIn("version", setup_pnpm["with"])
        self.assertEqual("web/package.json", setup_pnpm["with"]["package_json_file"])
        self.assertNotIn("dotnet-version", json.dumps(docs))

    def test_lint_and_dependabot_are_shipped(self):
        files = scaffold.render(fixture())
        self.assertIn(".github/scripts/lint-workflows.py", files)
        self.assertIn("actionlint", files[".github/scripts/lint-workflows.py"])
        self.assertIn("zizmor", files[".github/scripts/lint-workflows.py"])
        _, docs = scaffold.render_documents(fixture())
        update = docs[".github/dependabot.yml"]["updates"][0]
        self.assertEqual("weekly", update["schedule"]["interval"])
        self.assertEqual({"github-actions": {"patterns": ["*"]}}, update["groups"])


class ValidationTests(unittest.TestCase):
    def test_setup_uses_writer_env_and_rejects_all_inputs_context_spellings(self):
        for expression in ("${{ inputs.target }}", "${{ inputs['target'] }}", "${{ InPuTs [ 'target' ] }}", "${{ inputs }}", "${{ toJSON(INPUTS) }}"):
            with self.subTest(expression=expression):
                config = fixture()
                config["provider"]["phases"]["setup"] = {"steps": [{"name": "Initialize provider", "run": "echo setup", "env": {"TARGET": expression}}]}
                with self.assertRaisesRegex(scaffold.InputError, "provider.setup uses writer env data"):
                    scaffold.render(config)
        config = fixture()
        config["provider"]["phases"]["setup"] = {"env": {"LABEL": "${{ 'inputs.target' }}", "PLAIN": "inputs.target", "TARGET": "${{ env.DEPLOY_ENVIRONMENT }}"}, "steps": [{"name": "Read inputs.target label", "run": "echo inputs.target"}]}
        scaffold.render(config)

    def test_secret_context_spellings_are_rejected_outside_step_env(self):
        expressions = [
            "${{ secrets.PASSWORD }}",
            "${{ secrets['PASSWORD'] }}",
            "${{ SeCrEtS [ 'PASSWORD' ] }}",
            "${{ secrets }}",
            "${{ toJSON(Secrets) }}",
            "${{ secrets[vars.KEY] }}",
            "${{ format('{0}', secrets['PASSWORD']) }}",
            "${{ secrets.* }}",
        ]
        for expression in expressions:
            for destination in ("phase", "run", "script", "with"):
                with self.subTest(expression=expression, destination=destination):
                    config = fixture()
                    if destination == "phase":
                        config["provider"]["phases"]["deploy"]["env"] = {"PASSWORD": expression}
                    elif destination == "run":
                        config["verify"]["unit"]["steps"][0]["run"] = "echo " + expression
                    else:
                        settings = {"script": "return true;"}
                        settings["script" if destination == "script" else "credential"] = expression
                        config["verify"]["unit"]["steps"][0] = {"name": "Inspect context", "uses": "actions/github-script", "with": settings}
                    with self.assertRaises(scaffold.InputError):
                        scaffold.render(config)

    def test_untrusted_context_spellings_are_rejected_in_commands_and_scripts(self):
        expressions = [
            "${{ github.event.pull_request.title }}",
            "${{ github['event']['pull_request']['title'] }}",
            "${{ GiThUb [ 'EvEnT' ] . pull_request.title }}",
            "${{ github . head_ref }}",
            "${{ GITHUB['HEAD_REF'] }}",
            "${{ inputs.target }}",
            "${{ InPuTs [ 'target' ] }}",
            "${{ toJSON(github.event) }}",
            "${{ toJSON(github) }}",
            "${{ toJSON(inputs) }}",
            "${{ github[vars.CONTEXT_KEY] }}",
            "${{ github[format('{0}', 'event')] }}",
            "${{ github.* }}",
            "${{ (github).event }}",
            "${{ format('{0}', github['event']) }}",
        ]
        for expression in expressions:
            for destination in ("run", "script"):
                with self.subTest(expression=expression, destination=destination):
                    config = fixture()
                    if destination == "run":
                        config["verify"]["unit"]["steps"][0]["run"] = "echo " + expression
                    else:
                        config["verify"]["unit"]["steps"][0] = {"name": "Inspect context", "uses": "actions/github-script", "with": {"script": "return " + expression + ";"}}
                    with self.assertRaises(scaffold.InputError):
                        scaffold.render(config)

    def test_context_values_are_allowed_through_consuming_step_env(self):
        values = {"PASSWORD": "${{ SeCrEtS['PASSWORD'] }}", "TITLE": "${{ github['event']['pull_request']['title'] }}", "TARGET": "${{ inputs['target'] }}"}
        config = fixture()
        config["verify"]["unit"]["steps"] = [
            {"name": "Consume context", "run": "printf '%s' \"$TITLE\"", "env": values},
            {"name": "Read context", "uses": "actions/github-script", "with": {"script": "return process.env.TITLE;"}, "env": values},
        ]
        _, docs = scaffold.render_documents(config)
        job = docs[".github/workflows/pr.yml"]["jobs"]["verify-unit"]
        self.assertNotIn("env", job)
        for step in job["steps"][-2:]:
            self.assertEqual(values, step["env"])

    def test_trusted_metadata_and_quoted_context_words_are_allowed(self):
        expressions = [
            "${{ github.sha }}",
            "${{ GiThUb [ 'repository' ] }}",
            "${{ github . run_id }}",
            "${{ vars['inputs'] }}",
            "${{ vars.secrets }}",
            "${{ 'secrets.PASSWORD github.event inputs.target' }}",
            "${{ 'it''s github.head_ref and secrets' }}",
            "${{ format('}} inputs {0}', github['sha']) }}",
            "${{ format('{0}', '${{ secrets.PASSWORD }}') }}",
        ]
        for expression in expressions:
            with self.subTest(expression=expression):
                config = fixture()
                config["verify"]["unit"]["steps"] = [
                    {"name": "Print metadata", "run": "echo " + expression},
                    {"name": "Read metadata", "uses": "actions/github-script", "with": {"script": "return " + expression + ";"}},
                ]
                config["provider"]["phases"]["deploy"]["env"] = {"LABEL": "${{ 'secrets.PASSWORD' }}", "PLAIN": "secrets.PASSWORD"}
                scaffold.render(config)

    def test_build_step_id_cannot_collide_with_writer_artifact_step(self):
        for oidc in (False, True):
            with self.subTest(oidc=oidc):
                config = fixture()
                config["build"]["oidc"] = oidc
                config["build"]["steps"][0]["id"] = "artifact"
                with self.assertRaisesRegex(scaffold.InputError, "Build the deployment artifact: repeated step id artifact"):
                    scaffold.render(config)

    def test_joined_deploy_and_readiness_step_ids_must_be_distinct(self):
        config = fixture()
        for key in ("deploy", "readiness"):
            config["provider"]["phases"][key]["steps"][0]["id"] = "revision"
        with self.assertRaisesRegex(scaffold.InputError, "Deploy and verify the serving environment: repeated step id revision"):
            scaffold.render(config)

    def test_malformed_provider_and_config_inputs_fail_before_rendering(self):
        mutations = [
            lambda c: c.update({"jobs": {}}),
            lambda c: c.update({"prod-release": "false"}),
            lambda c: c.update({"schema_version": True}),
            lambda c: c.update({"roots": ["../escape"]}),
            lambda c: c["provider"].update({"jobs": {}}),
            lambda c: c["provider"].update({"ready": "github.event.pull_request.title"}),
            lambda c: c["provider"]["phases"].pop("recover"),
            lambda c: c["provider"]["phases"]["deploy"].update({"permissions": {"contents": "write"}}),
            lambda c: c["verify"]["unit"]["steps"][0].update({"run": "echo ${{ github.event.pull_request.title }}"}),
            lambda c: c["verify"]["unit"]["steps"][0].update({"uses": "actions/checkout@main"}),
            lambda c: c["provider"]["phases"]["plan"].update({"matrix": {"root": []}}),
            lambda c: c["provider"]["phases"]["deploy"].update({"env": {"PASSWORD": "${{ secrets.PASSWORD }}"}}),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                config = fixture()
                mutate(config)
                with self.assertRaises(scaffold.InputError):
                    scaffold.render(config)

    def test_missing_toolchain_metadata_and_invalid_repository_json(self):
        for metadata in ({"package.json": "{}"}, {"global.json": "bad-json"}, {"global.json": '{"sdk":{"version":42}}'}, {"package.json": '{"engines":{"node":"24"},"packageManager":"pnpm@latest"}'}, {"../outside": "x"}):
            with self.subTest(metadata=metadata), self.assertRaises(scaffold.InputError):
                scaffold.render(fixture(), metadata)

    def test_untrusted_values_are_allowed_in_step_env(self):
        config = fixture()
        config["verify"]["unit"]["steps"][0] = {"name": "Read the title", "env": {"TITLE": "${{ github.event.pull_request.title }}"}, "run": "printf '%s\\n' \"$TITLE\""}
        scaffold.render(config)

    def test_multiline_bash_gets_strict_mode(self):
        config = fixture()
        config["verify"]["unit"]["steps"][0]["run"] = "echo one\necho two"
        _, docs = scaffold.render_documents(config)
        self.assertEqual("set -euo pipefail", docs[".github/workflows/pr.yml"]["jobs"]["verify-unit"]["steps"][-1]["run"].splitlines()[0])


class AtomicCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name) / "project"
        self.project.mkdir()
        self.config = Path(self.temporary.name) / "config.json"
        self.config.write_text(json.dumps(fixture()), encoding="utf-8")

    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-B", str(SCRIPT), *args], capture_output=True, text=True)

    def test_dry_run_is_json_and_writes_nothing(self):
        result = self.run_cli("new", "--config", str(self.config), "--project", str(self.project), "--dry-run")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn(".github/workflows/prod.yml", json.loads(result.stdout)["files"])
        self.assertEqual([], list(self.project.iterdir()))

    def test_cli_render_overlay_and_override(self):
        overlay = Path(self.temporary.name) / "files.json"
        overlay.write_text('{"global.json":"{\\"sdk\\":{\\"version\\":\\"10.0.100\\"}}"}', encoding="utf-8")
        result = self.run_cli("render", "--config", str(self.config), "--repository-files", str(overlay), "--set", "prod-release=false")
        self.assertEqual(0, result.returncode, result.stderr)
        files = json.loads(result.stdout)
        self.assertNotIn(".github/workflows/prod.yml", files)
        self.assertIn("global-json-file", files[".github/workflows/pr.yml"])

    def test_write_and_collision_are_no_overwrite(self):
        result = self.run_cli("new", "--config", str(self.config), "--project", str(self.project))
        self.assertEqual(0, result.returncode, result.stderr)
        existing = {p.relative_to(self.project).as_posix(): p.read_bytes() for p in self.project.rglob("*") if p.is_file()}
        collision = self.run_cli("new", "--config", str(self.config), "--project", str(self.project))
        self.assertEqual(1, collision.returncode)
        self.assertIn("already exists", collision.stderr)
        self.assertEqual(existing, {p.relative_to(self.project).as_posix(): p.read_bytes() for p in self.project.rglob("*") if p.is_file()})
        self.assertTrue(all(b"\r\n" not in content for content in existing.values()))

    def test_validation_exit_two_writes_nothing(self):
        config = fixture()
        config["provider"]["jobs"] = {}
        self.config.write_text(json.dumps(config), encoding="utf-8")
        result = self.run_cli("new", "--config", str(self.config), "--project", str(self.project))
        self.assertEqual(2, result.returncode)
        self.assertEqual([], list(self.project.iterdir()))

    def test_joined_step_id_collision_exits_two_before_writing(self):
        config = fixture()
        config["build"]["steps"][0]["id"] = "artifact"
        self.config.write_text(json.dumps(config), encoding="utf-8")
        result = self.run_cli("new", "--config", str(self.config), "--project", str(self.project))
        self.assertEqual(2, result.returncode)
        self.assertIn("repeated step id artifact", result.stderr)
        self.assertEqual([], list(self.project.iterdir()))

    def test_context_validation_exits_two_before_writing(self):
        for destination in ("phase", "run", "script"):
            with self.subTest(destination=destination):
                config = fixture()
                if destination == "phase":
                    config["provider"]["phases"]["deploy"]["env"] = {"PASSWORD": "${{ secrets['PASSWORD'] }}"}
                elif destination == "run":
                    config["verify"]["unit"]["steps"][0]["run"] = "echo ${{ github['event']['pull_request']['title'] }}"
                else:
                    config["verify"]["unit"]["steps"][0] = {"name": "Inspect context", "uses": "actions/github-script", "with": {"script": "return ${{ inputs['target'] }};"}}
                self.config.write_text(json.dumps(config), encoding="utf-8")
                result = self.run_cli("new", "--config", str(self.config), "--project", str(self.project))
                self.assertEqual(2, result.returncode)
                self.assertEqual([], list(self.project.iterdir()))

    def test_partial_write_failure_rolls_back_and_preserves_existing_files(self):
        keep = self.project / "keep.txt"
        keep.write_text("keep", encoding="utf-8")
        original = Path.open
        def fail(path, mode="r", *args, **kwargs):
            if path.name == "second.yml" and mode == "xb":
                raise OSError("injected disk failure")
            return original(path, mode, *args, **kwargs)
        with patch.object(Path, "open", fail), self.assertRaises(scaffold.WriteError):
            scaffold.write_files(self.project, {"new/first.yml": "first\n", "new/second.yml": "second\n"})
        self.assertEqual([keep], list(self.project.iterdir()))
        self.assertEqual("keep", keep.read_text(encoding="utf-8"))

    def test_paths_and_file_parent_conflicts_are_rejected(self):
        for path in ("../escape", "/absolute", "C:/outside", "a/../b", "a\\b", "a./b"):
            with self.subTest(path=path), self.assertRaises(scaffold.InputError):
                scaffold.write_files(self.project, {path: "x"})
        (self.project / "new").write_text("existing", encoding="utf-8")
        with self.assertRaises(scaffold.WriteError):
            scaffold.write_files(self.project, {"new/file": "x"})
        self.assertEqual("existing", (self.project / "new").read_text(encoding="utf-8"))


class GateBehaviorTests(unittest.TestCase):
    def run_gate(self, template, results, extra=None):
        return subprocess.run([sys.executable, "-c", body(template)], env={**os.environ, "GATE_RESULTS": json.dumps(results), "WORKFLOW_FILE": ".github/workflows/pr.yml", **(extra or {})}, capture_output=True, text=True)

    def test_mandatory_gate_requires_every_success(self):
        self.assertEqual(0, self.run_gate("aggregate.sh", {"unit": {"result": "success"}}).returncode)
        for status in ("skipped", "failure", "cancelled"):
            self.assertEqual(1, self.run_gate("aggregate.sh", {"unit": {"result": status}}).returncode)
        self.assertEqual(1, self.run_gate("aggregate.sh", {}).returncode)

    def test_optional_cloud_gate_allows_only_expected_skips(self):
        for selected, status, code in (("true", "success", 0), ("false", "skipped", 0), ("true", "skipped", 1), ("false", "success", 1), ("false", "failure", 1), ("true", "cancelled", 1)):
            with self.subTest(selected=selected, status=status):
                result = self.run_gate("optional-gates.sh", {"deploy-preview": {"result": status}}, {"DEPLOY_PREVIEW": selected})
                self.assertEqual(code, result.returncode)


@unittest.skipUnless(shutil.which("node"), "Node is required to execute the mocked GitHub API assertion")
class ReleaseBehaviorTests(unittest.TestCase):
    def assert_release(self, case):
        script = scaffold.asset("assert-release.js")
        harness = """
const input = JSON.parse(process.argv[1]);
const outputs = {};
const context = {repo: {owner: 'neutral', repo: 'service'}};
const core = {setOutput: (key, value) => { outputs[key] = value; }};
const github = {rest: {git: {
 getRef: async () => ({data: {object: input.target || {type: 'commit', sha: 'verified'}}}),
 getTag: async () => ({data: {object: {type: 'commit', sha: input.tagSha || 'verified'}}}),
}, actions: {
 listWorkflowRuns: async (args) => { if (args.event !== 'push' || args.branch !== 'main' || args.status !== 'success') throw Error('incorrect query'); return {data: {workflow_runs: input.noRun ? [] : [{id: 123, head_sha: input.runSha || 'verified'}]}}; },
 listWorkflowRunArtifacts: () => {},
}}, paginate: async () => input.artifacts || []};
(async () => {
SCRIPT
})().then(() => process.stdout.write(JSON.stringify(outputs))).catch(e => { process.stderr.write(e.message); process.exitCode = 1; });
""".replace("SCRIPT", script)
        return subprocess.run([shutil.which("node"), "-e", harness, json.dumps(case)], env={**os.environ, "TAG_NAME": case.get("tag", "v1.2.3"), "REQUIRE_ARTIFACT": str(case.get("require", False)).lower()}, capture_output=True, text=True)

    def test_lightweight_and_annotated_tags_resolve_verified_run(self):
        for target in ({"type": "commit", "sha": "verified"}, {"type": "tag", "sha": "annotation"}):
            result = self.assert_release({"target": target})
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual({"source-sha": "verified", "source-run-id": "123", "artifact-id": ""}, json.loads(result.stdout))

    def test_rejects_wrong_commit_missing_ci_and_nonsemver_tag(self):
        for case in ({"runSha": "different"}, {"noRun": True}, {"tag": "v1.2.3-injected"}, {"target": {"type": "tree", "sha": "verified"}}):
            with self.subTest(case=case):
                self.assertEqual(1, self.assert_release(case).returncode)

    def test_artifact_promotion_requires_unique_retained_digest_from_that_run(self):
        artifact = {"id": 42, "name": "deployment", "expired": False, "digest": "sha256:" + "a" * 64}
        result = self.assert_release({"require": True, "artifacts": [artifact]})
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("42", json.loads(result.stdout)["artifact-id"])
        for artifacts in ([], [{**artifact, "expired": True}], [artifact, artifact], [{**artifact, "digest": ""}]):
            with self.subTest(artifacts=artifacts):
                self.assertEqual(1, self.assert_release({"require": True, "artifacts": artifacts}).returncode)


if __name__ == "__main__":
    unittest.main()
