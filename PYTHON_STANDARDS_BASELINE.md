# Python standards baseline

Existing violations at `be7644752d914d489b9f31b3f9e306ad62a81f07` are baselined by exact authored file and rule. New files receive all enabled checks. Remove an exception when repairing its source. The tool configuration owns enforcement; this document records the rollout evidence and rationale.

## Ruff

Reason: preserve existing implementations during the standards rollout. Each row records the existing count and a representative required repair. No wildcard path or whole-rule ignores were added.

| File | Rule | Existing count | Required repair |
| --- | --- | ---: | --- |
| `.agents/github-actions/utility/publish-update/scripts/enrollment.py` | `ANN401` | 12 | Dynamically typed expressions (typing.Any) are disallowed in `api` |
| `.agents/github-actions/utility/publish-update/scripts/owner_setup.py` | `ANN401` | 9 | Dynamically typed expressions (typing.Any) are disallowed in `load_enrollment` |
| `.agents/github-actions/utility/publish-update/scripts/owner_setup.py` | `TID251` | 1 | `importlib.util.spec_from_file_location` is banned: Import the installed public API; do not load another checkout by path. |
| `.agents/tests/test_enrollment.py` | `ANN401` | 4 | Dynamically typed expressions (typing.Any) are disallowed in `api` |
| `.agents/tests/test_enrollment.py` | `PLR6301` | 4 | Method `call` could be a function, class method, or static method |
| `.agents/tests/test_enrollment.py` | `PT006` | 1 | Wrong type passed to first argument of `pytest.mark.parametrize`; expected `tuple` |
| `.agents/tests/test_enrollment.py` | `TID251` | 1 | `importlib.util.spec_from_file_location` is banned: Import the installed public API; do not load another checkout by path. |
| `.agents/tests/test_owner_setup.py` | `ANN401` | 10 | Dynamically typed expressions (typing.Any) are disallowed in `*args` |
| `.agents/tests/test_owner_setup.py` | `PT006` | 1 | Wrong type passed to first argument of `pytest.mark.parametrize`; expected `tuple` |
| `.agents/tests/test_owner_setup.py` | `PT011` | 1 | `pytest.raises(test_owner_setup.StopAfterProtectionError)` is too broad, set the `match` parameter or use a more specific exception |
| `.agents/tests/test_owner_setup.py` | `TID251` | 1 | `importlib.util.spec_from_file_location` is banned: Import the installed public API; do not load another checkout by path. |
| `.agents/tests/test_publish_generated.py` | `ANN401` | 9 | Dynamically typed expressions (typing.Any) are disallowed in `*_` |
| `.agents/tests/test_publish_generated.py` | `TID251` | 1 | `importlib.util.spec_from_file_location` is banned: Import the installed public API; do not load another checkout by path. |
| `.github/actions/publish-generated/publish_generated.py` | `PTH201` | 1 | Do not pass the current directory explicitly to `Path` |

## Custom checker

Reason: preserve exact pre-existing custom-checker findings during the standards rollout. Each entry maps to one authored path and rule; repair the stated design issue and remove its exception. No generated or vendored path is included.

| File | Rule | Existing count | Required repair |
| --- | --- | ---: | --- |
| .agents/github-actions/utility/merge-policy/scripts/merge_policy.py | PY001 | 1 | Rewrite the nested comprehension as named loops or one generator. |
| .agents/github-actions/utility/publish-update/scripts/enrollment.py | PY016 | 1 | Inject process state or confine the read to an entry-point main. |
| .agents/github-actions/utility/publish-update/scripts/owner_setup.py | PY016 | 2 | Inject process state or confine the read to an entry-point main. |
| .agents/github-actions/utility/scaffold/scripts/scaffold.py | PY001 | 1 | Rewrite the nested comprehension as named loops or one generator. |
| .agents/github-actions/utility/scaffold/templates/lint-workflows.py | PY016 | 1 | Inject process state or confine the read to an entry-point main. |
| .agents/tests/test_owner_setup.py | PY016 | 2 | Inject process state or confine the read to an entry-point main. |
| .agents/tests/test_scaffold.py | PY001 | 3 | Rewrite the nested comprehension as named loops or one generator. |
| .agents/tests/test_scaffold.py | PY016 | 4 | Inject process state or confine the read to an entry-point main. |
| .github/actions/publish-generated/publish_generated.py | PY001 | 1 | Rewrite the nested comprehension as named loops or one generator. |
| .github/actions/publish-generated/publish_generated.py | PY016 | 3 | Inject process state or confine the read to an entry-point main. |

## Expanded Python scope

These exact entries cover unchanged legacy diagnostics exposed when the root Python scope expanded. Repair each diagnostic and remove its matching baseline entry.

### Ruff

| File | Rule | Existing count | Required repair |
| --- | --- | ---: | --- |
| .agents/github-actions/utility/merge-policy/scripts/merge_policy.py | E501 | 18 | Repair the existing E501 diagnostic and remove this exact ignore. |
| .agents/github-actions/utility/merge-policy/scripts/merge_policy.py | I001 | 1 | Repair the existing I001 diagnostic and remove this exact ignore. |
| .agents/github-actions/utility/scaffold/scripts/scaffold.py | BLE001 | 1 | Repair the existing BLE001 diagnostic and remove this exact ignore. |
| .agents/github-actions/utility/scaffold/scripts/scaffold.py | E501 | 170 | Repair the existing E501 diagnostic and remove this exact ignore. |
| .agents/github-actions/utility/scaffold/scripts/scaffold.py | I001 | 1 | Repair the existing I001 diagnostic and remove this exact ignore. |
| .agents/github-actions/utility/scaffold/scripts/scaffold.py | PTH100 | 1 | Repair the existing PTH100 diagnostic and remove this exact ignore. |
| .agents/github-actions/utility/scaffold/scripts/scaffold.py | RUF005 | 1 | Repair the existing RUF005 diagnostic and remove this exact ignore. |
| .agents/github-actions/utility/scaffold/scripts/scaffold.py | TRY300 | 1 | Repair the existing TRY300 diagnostic and remove this exact ignore. |
| .agents/github-actions/utility/scaffold/templates/lint-workflows.py | E501 | 9 | Repair the existing E501 diagnostic and remove this exact ignore. |
| .agents/github-actions/utility/scaffold/templates/lint-workflows.py | I001 | 1 | Repair the existing I001 diagnostic and remove this exact ignore. |
| .agents/tests/test_lint_download.py | E501 | 7 | Repair the existing E501 diagnostic and remove this exact ignore. |
| .agents/tests/test_lint_download.py | I001 | 1 | Repair the existing I001 diagnostic and remove this exact ignore. |
| .agents/tests/test_lint_download.py | PT009 | 7 | Repair the existing PT009 diagnostic and remove this exact ignore. |
| .agents/tests/test_lint_download.py | SIM117 | 1 | Repair the existing SIM117 diagnostic and remove this exact ignore. |
| .agents/tests/test_lint_download.py | TID251 | 2 | Repair the existing TID251 diagnostic and remove this exact ignore. |
| .agents/tests/test_merge_policy.py | I001 | 1 | Repair the existing I001 diagnostic and remove this exact ignore. |
| .agents/tests/test_merge_policy.py | PLR6301 | 1 | Repair the existing PLR6301 diagnostic and remove this exact ignore. |
| .agents/tests/test_merge_policy.py | PT009 | 22 | Repair the existing PT009 diagnostic and remove this exact ignore. |
| .agents/tests/test_merge_policy.py | TID251 | 3 | Repair the existing TID251 diagnostic and remove this exact ignore. |
| .agents/tests/test_scaffold.py | B023 | 38 | Repair the existing B023 diagnostic and remove this exact ignore. |
| .agents/tests/test_scaffold.py | B905 | 2 | Repair the existing B905 diagnostic and remove this exact ignore. |
| .agents/tests/test_scaffold.py | E501 | 458 | Repair the existing E501 diagnostic and remove this exact ignore. |
| .agents/tests/test_scaffold.py | I001 | 1 | Repair the existing I001 diagnostic and remove this exact ignore. |
| .agents/tests/test_scaffold.py | PLR6301 | 5 | Repair the existing PLR6301 diagnostic and remove this exact ignore. |
| .agents/tests/test_scaffold.py | PT009 | 374 | Repair the existing PT009 diagnostic and remove this exact ignore. |
| .agents/tests/test_scaffold.py | TID251 | 7 | Repair the existing TID251 diagnostic and remove this exact ignore. |
| .agents/tests/verify_workflows.py | E501 | 12 | Repair the existing E501 diagnostic and remove this exact ignore. |
| .agents/tests/verify_workflows.py | I001 | 1 | Repair the existing I001 diagnostic and remove this exact ignore. |
| .agents/tests/verify_workflows.py | TID251 | 1 | Repair the existing TID251 diagnostic and remove this exact ignore. |

### Ruff format

| File | Existing count | Required repair |
| --- | ---: | --- |
| .agents/github-actions/utility/merge-policy/scripts/merge_policy.py | 1 | Format this existing file and remove this exact exclusion. |
| .agents/github-actions/utility/scaffold/scripts/scaffold.py | 1 | Format this existing file and remove this exact exclusion. |
| .agents/github-actions/utility/scaffold/templates/lint-workflows.py | 1 | Format this existing file and remove this exact exclusion. |
| .agents/tests/test_lint_download.py | 1 | Format this existing file and remove this exact exclusion. |
| .agents/tests/test_scaffold.py | 1 | Format this existing file and remove this exact exclusion. |
| .agents/tests/verify_workflows.py | 1 | Format this existing file and remove this exact exclusion. |

### Mypy

| Module | Rule | Existing count | Required repair |
| --- | --- | ---: | --- |
| lint-workflows | no-any-return | 1 | Repair the existing no-any-return diagnostic and remove this exact override. |
| lint-workflows | union-attr | 2 | Repair the existing union-attr diagnostic and remove this exact override. |
| merge_policy | no-untyped-call | 11 | Repair the existing no-untyped-call diagnostic and remove this exact override. |
| merge_policy | no-untyped-def | 9 | Repair the existing no-untyped-def diagnostic and remove this exact override. |
| merge_policy | var-annotated | 1 | Repair the existing var-annotated diagnostic and remove this exact override. |
| scaffold | arg-type | 2 | Repair the existing arg-type diagnostic and remove this exact override. |
| scaffold | assignment | 4 | Repair the existing assignment diagnostic and remove this exact override. |
| scaffold | dict-item | 3 | Repair the existing dict-item diagnostic and remove this exact override. |
| scaffold | index | 1 | Repair the existing index diagnostic and remove this exact override. |
| scaffold | list-item | 1 | Repair the existing list-item diagnostic and remove this exact override. |
| scaffold | no-any-return | 2 | Repair the existing no-any-return diagnostic and remove this exact override. |
| scaffold | no-untyped-def | 2 | Repair the existing no-untyped-def diagnostic and remove this exact override. |
| scaffold | type-arg | 27 | Repair the existing type-arg diagnostic and remove this exact override. |
| scaffold | unreachable | 1 | Repair the existing unreachable diagnostic and remove this exact override. |
| scaffold | var-annotated | 2 | Repair the existing var-annotated diagnostic and remove this exact override. |
| test_lint_download | arg-type | 3 | Repair the existing arg-type diagnostic and remove this exact override. |
| test_lint_download | no-untyped-def | 1 | Repair the existing no-untyped-def diagnostic and remove this exact override. |
| test_lint_download | union-attr | 3 | Repair the existing union-attr diagnostic and remove this exact override. |
| test_merge_policy | arg-type | 1 | Repair the existing arg-type diagnostic and remove this exact override. |
| test_merge_policy | no-untyped-call | 16 | Repair the existing no-untyped-call diagnostic and remove this exact override. |
| test_merge_policy | no-untyped-def | 16 | Repair the existing no-untyped-def diagnostic and remove this exact override. |
| test_merge_policy | union-attr | 2 | Repair the existing union-attr diagnostic and remove this exact override. |
| test_scaffold | arg-type | 1 | Repair the existing arg-type diagnostic and remove this exact override. |
| test_scaffold | assignment | 2 | Repair the existing assignment diagnostic and remove this exact override. |
| test_scaffold | attr-defined | 5 | Repair the existing attr-defined diagnostic and remove this exact override. |
| test_scaffold | dict-item | 2 | Repair the existing dict-item diagnostic and remove this exact override. |
| test_scaffold | index | 4 | Repair the existing index diagnostic and remove this exact override. |
| test_scaffold | list-item | 3 | Repair the existing list-item diagnostic and remove this exact override. |
| test_scaffold | no-untyped-call | 123 | Repair the existing no-untyped-call diagnostic and remove this exact override. |
| test_scaffold | no-untyped-def | 143 | Repair the existing no-untyped-def diagnostic and remove this exact override. |
| test_scaffold | union-attr | 2 | Repair the existing union-attr diagnostic and remove this exact override. |
| test_scaffold | var-annotated | 3 | Repair the existing var-annotated diagnostic and remove this exact override. |
| verify_workflows | arg-type | 1 | Repair the existing arg-type diagnostic and remove this exact override. |
| verify_workflows | no-untyped-call | 1 | Repair the existing no-untyped-call diagnostic and remove this exact override. |
| verify_workflows | no-untyped-def | 1 | Repair the existing no-untyped-def diagnostic and remove this exact override. |
| verify_workflows | union-attr | 2 | Repair the existing union-attr diagnostic and remove this exact override. |
