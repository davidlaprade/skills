---
name: audit-code-quality
description: Audit a codebase for verified maintainability and test quality problems, then produce a detailed report by default. Use when Codex is asked to review code quality, find code smells or technical debt, assess complexity, identify large or deeply nested code, inspect typing or documentation gaps, evaluate hard coded data, find weak test coverage or mock heavy tests, or prepare a ranked code quality report without changing the code.
---

# Audit code quality

Audit the repository and return a detailed Markdown report in the response. Do
not change code unless the user separately asks for fixes.

## Set the scope

1. Read the repository instructions and build files.
2. Identify source, test, generated, vendored, migration, fixture, and example
   files. Exclude generated and vendored code. Report any other material
   exclusions.
3. Read the project's lint, type, test, and coverage settings. Respect explicit
   local conventions.
4. Check the working tree. Treat existing changes as user work.

Read [references/checks.md](references/checks.md) before running the audit. Use
its definitions, thresholds, and cautions. Read
[references/report-template.md](references/report-template.md) and follow it
for the default response.

## Gather evidence

Use several evidence sources. Do not treat one tool as a complete audit.

1. Run the repository's existing lint and static type commands when they are
   safe and read only.
2. Run the existing test command when its cost is reasonable.
3. Use an existing coverage command or coverage artifact when available. Do not
   install a coverage tool or change project settings unless the user asks.
4. For Python, run:

```bash
python3 <skill-directory>/scripts/audit_python.py <repository> \
  --format json --output /tmp/code-quality-audit.json
```

5. To collect hard coded literal candidates, run a second pass:

```bash
python3 <skill-directory>/scripts/audit_python.py <repository> \
  --format json --include-literals \
  --output /tmp/code-quality-literals.json
```

6. For other languages, use the repository's existing tools first. Then use
   language aware parsing or careful source inspection. Use raw line searches
   only to find candidates.
7. Inspect the highest risk files and functions in full. Trace their callers,
   dependencies, error paths, and tests as needed.
8. Search for duplication, dead code, broad error handling, hidden state,
   boundary violations, and weak tests that automated metrics cannot establish.

## Verify every finding

Open the cited code and confirm the claim in context. A metric is evidence, not
an explanation of harm.

For each proposed finding:

1. Confirm the exact file and smallest useful line range.
2. Explain the concrete maintenance, testing, or defect risk.
3. Check whether local conventions or framework requirements justify it.
4. Remove speculative findings that lack source evidence.
5. Downgrade uncertain evidence to a review candidate. Do not present it as a
   verified defect.

Do not claim that a file is untested from its name or from a missing matching
test file. Use executed line or branch coverage, or trace tests to the behavior.
If no valid measurement exists, state that coverage is unknown.

Do not call every literal a problem. Distinguish a magic value from a local
value whose meaning is clear. Constants are useful when they name a domain
concept, centralize a shared value, or prevent inconsistent changes. Moving a
literal to a constant without one of those benefits adds indirection.

## Write the report

Return the full report by default. Do not wait for the user to ask for details.
Do not replace the report with a short summary.

Lead with major verified findings, ordered by severity and then confidence.
After those findings, include a dedicated section named "Requested checks".
Cover every check in this order:

1. Files over 1,000 source lines.
2. Classes over 500 source lines.
3. Functions over 300 source lines.
4. Control flow nested more than 2 levels.
5. Hard coded data.
6. Undocumented functions.
7. Functions with untyped arguments.
8. Functions with 10 or more arguments.
9. Coverage gaps and untested files.
10. Tests that rely mainly on mocks.

Do not omit a check when there are no findings. Mark it as "none found". Mark
it as "unknown" when the audit could not measure it. Explain why it is unknown
and what evidence is needed.

Report every size threshold crossing. A threshold crossing may be a measured
concern rather than a verified defect. Keep that distinction clear, but do not
bury it in a general candidate list.

For documentation and typing, give the total count and group results by file.
List every material item. If there are many minor items, show the most important
examples and a complete per file count.

Never report missing docstrings for Pydantic validator methods, Protocol
properties, or methods on private prepared-change classes whose names start
with `_Prepared`. Exclude them from documentation counts and examples. Their
decorators, types, and class role already state the relevant contract.

Within the control-flow-nesting check, sort items by decreasing measured depth.
Use path and line number as deterministic tie breakers.

For coverage, name files or branches as untested only when executed coverage or
direct test tracing proves it. If coverage was not measured, make the lack of a
measurement prominent. Do not turn a filename match into a coverage claim.

For mock use, state what behavior the test checks, what it mocks, and whether it
asserts outcomes or only interactions. A mock count alone is not a finding.

Follow the exact order and field requirements in
[references/report-template.md](references/report-template.md).

Use these priorities:

* P0 means an immediate correctness, data loss, or severe security risk.
* P1 means a likely defect source or a major barrier to safe changes.
* P2 means a material maintainability or test weakness.
* P3 means a local improvement with limited effect.

If there are no verified findings, say so. Still include the complete requested
checks section and state what was not measured.
