---
name: write-pr-description
description: Draft high-signal pull request descriptions from the current branch's commits, diff, repository context, and active conversation. Use when asked to write, draft, revise, or prepare a pull request or PR description, summary, body, overview, or reviewer notes for a Git branch.
---

# Write Pull Request Descriptions

## Goal

Write a reviewer-facing account of the branch's purpose, impact, and important implementation choices. Treat the active conversation and Git history as complementary evidence: the thread explains intent and tradeoffs, while the committed branch proves what shipped.

Do not create or update a pull request unless the user explicitly asks. Otherwise, return only paste-ready Markdown for the PR body.

## Use the Deterministic Helper

Resolve this skill's directory from the loaded `SKILL.md`, then run `scripts/pr_evidence.py` with Python 3.12 or newer. Use the helper for repository discovery, comparison-range metadata, commit extraction, changed-file metadata, diffs, file line numbers, and GitHub permalinks. Do not reconstruct those results manually when the helper supports them.

Run the inspection command first:

```bash
python3 <skill-dir>/scripts/pr_evidence.py inspect --repo <repository> [--base <base-ref>] [--remote <remote>]
```

Use a base named by the user, established in the thread, or returned by existing PR metadata. Pass it with `--base`. Otherwise, let the helper use the configured remote's default branch; if it reports ambiguous candidates, ask the user which base is correct.

Inspect the complete committed diff, or narrow it to a relevant path:

```bash
python3 <skill-dir>/scripts/pr_evidence.py diff --repo <repository> [--base <base-ref>]
python3 <skill-dir>/scripts/pr_evidence.py diff --repo <repository> [--base <base-ref>] --path <repo-relative-path>
```

Display exact file lines at any revision when needed:

```bash
python3 <skill-dir>/scripts/pr_evidence.py show --repo <repository> --path <repo-relative-path> --start <line> --end <line>
```

Generate and validate each immutable Markdown link instead of composing it by hand:

```bash
python3 <skill-dir>/scripts/pr_evidence.py link --repo <repository> --path <repo-relative-path> --start <line> [--end <line>] [--label <label>]
```

For deleted behavior, pass `--revision <merge-base-sha>` to `show` and `link`. The helper rejects unknown revisions, paths absent at the chosen revision, binary files, invalid line ranges, non-GitHub remotes, and ambiguous base branches.

## Gather Evidence

1. Re-read the active conversation for the original problem, motivation, constraints, decisions, rejected approaches, and discoveries made during implementation. Exclude plans or claims that the final branch does not implement.
2. Run `inspect`. Treat its `merge_base_sha..head_sha` range as the PR contents. Describe committed branch changes only; ignore the reported uncommitted worktree entries unless the user explicitly includes them.
3. Read every commit subject and body, the changed-file list, and the diff. Inspect final versions of important files and their pre-change versions when the replacement is not clear from the diff.
4. Build a private change map organized by reviewer concern, not by commit or file. For each candidate item, record:
   - the outcome or behavior that changed;
   - what existed before or what it replaced;
   - the defect, limitation, risk, or cost that motivated the change;
   - the concrete gain;
   - supporting files and exact final line numbers;
   - whether a repository-familiar engineer could find it surprising or controversial.
5. Verify material claims against final code, tests, schemas, or documentation. Use the thread and commit bodies to explain intent, but do not present aspirations as shipped behavior or invent motives, benchmarks, or guarantees.

Resolve a material conflict between the conversation and the committed branch before drafting.

## Select the Signal

- Cover every key behavior, contract, architecture, workflow, dependency, configuration, data, performance, or operational change.
- Combine related changes into one reviewer concern. Never produce a commit-by-commit or file-by-file transcript.
- Rank items by reviewer impact and risk.
- Omit routine tests, formatting, generated files, lockfile churn, refactors with no meaningful review implication, and implementation trivia. Mention testing only when the testing system, contract, matrix, or strategy is itself a substantive change.
- Keep at most 10 bullets. If the branch has more than 10 key changes, group closely related changes without hiding important independent risks.
- Prefix an affected bullet with `:warning:` when it describes a surprising or controversial choice. Examples include deleting or splitting a major package, breaking a public contract, changing persisted data, replacing a core dependency, removing compatibility, or accepting a non-obvious tradeoff. State the consequence plainly; do not use the warning for ordinary changes.

## Add Direct Code Links

Include direct links whenever a stable, relevant target exists. Prefer one high-value link per bullet and add more only when separate locations are essential to understanding the change.

- Link the smallest useful final line range containing the changed definition or behavior.
- Use `link` with its default `HEAD` revision for modified or added code.
- Use the merge-base revision for deleted code only when seeing the replaced behavior helps the reviewer.
- Prefer the final path after a rename.
- Omit a link when no stable code target exists. Never fabricate a GitHub URL or line number.

## Write the Description

Use this exact shape unless the user requests a repository-specific template:

```markdown
<A single high-level paragraph of no more than five sentences. Explain the problem and purpose, what changed at a conceptual level, why it mattered, and the resulting outcome.>

## Key changes

- <Linked change, what it replaced or how it worked before, and why the change fixes a problem or creates a meaningful gain. No more than three sentences.>
- :warning: <Surprising change and its consequence, using the same evidence requirements. No more than three sentences.>
```

Write the summary before the bullets, usually in two to five sentences. Make it understandable without reading commit messages or knowing the implementation details.

For each bullet:

- Explain what changed.
- Explain what it replaced or how the old behavior worked.
- Explain why it changed by naming the prior failure or limitation, or by stating the concrete gain.
- Keep it to three sentences or fewer.

Do not add a title, preamble, commit list, file inventory, routine test bullet, checklist, or generic conclusion unless requested. Avoid vague claims such as "improves robustness" when the exact failure prevented is known.

## Verify the Draft

Before returning it, confirm all of the following:

- The comparison range matches the intended PR base and `HEAD`.
- The summary is no more than five sentences and explains both purpose and importance.
- There are 10 or fewer bullets, each no more than three sentences.
- Every bullet states the change, prior state or replacement, and reason or gain.
- Routine test additions and mechanical noise are absent.
- Surprising choices carry `:warning:` and name their consequences.
- Every code link was generated by the helper and points to the correct repository, immutable SHA, path, and supporting line range.
- Every factual claim is supported by the committed branch or explicit thread context.
- The result is concise, specific, and ready to paste into a pull request.
