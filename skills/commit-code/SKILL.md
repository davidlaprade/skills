---
name: commit-code
description: Commit code changes in the user's preferred style. Use when asked to commit changes, write or revise commit messages, organize staged or unstaged work into commits, split changes into modular commits, or decide what supporting context belongs in a commit body.
---

# Commit Code

## Overview

Create clear, modular Git commits that are easy to understand and easy to
revert. Keep commit messages concise, imperative, and useful in history.

## Commit Message

- Write the subject line in 80 characters or less.
- Use imperative mood: `Add`, `Fix`, `Update`, `Remove`, `Refactor`, and so on.
- Make the subject understandable from `git log` alone. Name the concrete
  change, and include the reason only when it fits cleanly.
- Avoid vague subjects such as `Update files`, `Fix stuff`, `Changes`, or `WIP`.
- Put extra details below the fold, after a blank line, only when they justify
  the change and would otherwise be hard to find.
- Use the body for details such as exact error messages, unusual constraints,
  documentation consulted, migration notes, or URLs that informed the work.
- Do not add a body that merely repeats the subject.

## Commit Scope

- Prefer modular commits centered on one reversible decision.
- Use this heuristic: if undoing one part of a proposed commit would not imply
  undoing the rest, split the work into separate commits.
- Avoid putting an entire feature in one commit. Commit coherent building
  blocks instead, such as schema changes, core behavior, UI wiring, and docs.
- Include tests with the code they exercise in the same commit, because those
  changes should usually be reverted together.
- Keep purely mechanical formatting, generated files, dependency updates, and
  unrelated cleanup separate when they are not tightly coupled to the behavior
  change.
- Preserve unrelated user changes. Do not include them just because they are
  present in the working tree.

## Workflow

- Inspect the working tree before committing.
- Group changes by behavior, intent, and revert boundary, not by file type alone.
- Stage only the files or hunks for the next coherent commit.
- Review the staged diff before writing the commit message.
- Write the subject from the staged diff, not from memory.
- Add a commit body only when the supporting context is genuinely useful.
- Repeat until the requested work is committed or only unrelated changes remain.

## Examples

Good subject lines:

- `Fix retry handling for expired API tokens`
- `Add keyword filters to trial matching evals`
- `Split patient note parsing from prompt assembly`

Good body content when needed:

```text
Fix retry handling for expired API tokens

The failure surfaced as:

  401 invalid_token after token refresh

The provider docs say refresh responses can rotate both access and refresh
tokens: https://example.com/docs/token-refresh
```

Bad subject lines:

- `Update stuff`
- `Make changes`
- `WIP`
- `Fix`
