# Coverage ratchet (2026-11-12 Grok / Chief ruling)

The CI coverage gate is a ratchet. Overall 80% and domain-package 90% remain improvement goals, not blocking thresholds for O-CI1. The full backend test selection and coverage source remain unchanged. This ruling supersedes the old fixed coverage gate; it does not waive test failures or authorize skipping test groups.

The first trusted measurement is PR89 head `4c02a41ebbea1612da9c5cb53ec9a32b2342ee6f`, [CI43238057084](https://github.com/codeman840425-del/ashare-invest-assistant/actions/runs/43238057084):

| Scope | Covered / statements | Initial configured label |
|---|---:|---:|
| overall | 15571 / 22926 | 67 |
| domain | 113 / 172 | 65 |
| importing | 1092 / 1406 | 77 |
| signals | 353 / 436 | 81 |
| advice | 0 / 0 | N/A |
| llm | 0 / 0 | N/A |

Comparison uses integer fractions, not rounded displayed percentages. A one-line loss fails even if the integer label still passes. Every scope prints the current and base numerators/denominators and denominator delta. `353/436` is **80.9633%**, rounded to 81.0% in the old log: the specifically approved exact measurement is the initial signals floor; the configured 81 is its rounded label, not an extra one-line increase silently imposed on that approved baseline. Explicit later increases (for example 81 to 82) are strict. No ratio decrease from the exact trusted base is allowed.

The policy JSON preserves the reviewed bootstrap unchanged. Its minimum labels may only increase relative to the trusted base. A PR cannot lower a label or rewrite the bootstrap/test-selection manifest to choose its own easier baseline. `check_coverage.py` receives a separately frozen trusted base file, never the PR policy as its measured base.

For the first pre-ratchet main base `465e02046fa8d971897603742497444f884e89a2` only, the loader uses the approved CI counts above. This is an explicit bootstrap because that old run did not upload its raw coverage file. No other missing baseline resets to these counts. The base commit must be present in fetched history.

For later PRs, the base SHA comes from the GitHub event's base repository/main commit. For main pushes it is the actual previous main commit. The loader reads **completed main push** runs of `ci.yml` for that exact base SHA, selects the latest run/attempt and requires its unexpired matching coverage artifact. PR-head artifacts cannot supply the base. The artifact's commit/run/attempt, schema, full-selection manifest and successful ratchet result must all agree. Missing, expired, malformed, wrong-run or failed measurements stop the gate. The output of each successful gate becomes the next main commit's exact measured floor, so improvements cannot subsequently be lost.

A main-only manual dispatch compares the first parent; dispatching this gate on a topic branch is rejected. The standard workflow needs only read access to contents and Actions; the temporary GitHub token stays inside the baseline-fetch step and is never written into a receipt. Download redirects strip authorization on a host change. No repository write token or auto-commit is used.

For a scope with zero statements, output is N/A, never a claimed 100% measurement. Disappearance of a formerly measured scope fails. When advice/llm first acquire statements, they are measured and must meet at least the trusted overall coverage ratio until their own nonzero measurement becomes the next base; uncovered new packages do not inherit a fake 100% from 0/0.

A missing/empty coverage file, invalid integer counts or disagreement between file totals and coverage totals fails. Changing the declared full test-selection manifest also fails; changed or reduced execution is never absorbed by resetting the baseline. The ratchet does not replace the separate pytest execution/presence checks. Changes to test selection or bootstrap policy require an explicit new ruling, not a PR-local reset.

Only a successful coverage comparison uploads `coverage-ratchet-<run>-<attempt>` (90-day retention), containing the measurement, original coverage JSON and backend/selfcheck JUnit when produced. This also preserves complete measurement evidence when other backend tests fail. Later exact-base main artifacts must exist; an old/expired measurement requires explicit recovery rather than a default pass.

The former `--cov-fail-under=80` invocation and fixed 80/90 post-check are replaced by this dedicated ratchet gate. Pytest directories, coverage source, 30-minute job limit and all unrelated test assertions stay in place. Local authors must still report the same full pytest+coverage/vitest commands, actual isolated resource identity, results and gaps before a source push.
