#!/usr/bin/env python3
"""Collect deterministic Git evidence and build verified GitHub permalinks."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import NoReturn
from urllib.parse import quote, urlparse


class EvidenceError(RuntimeError):
    """Report a user-correctable repository or argument problem."""


@dataclass(frozen=True)
class RepositoryState:
    root: Path
    branch: str | None
    head_sha: str
    remote_name: str | None
    remote_url: str | None
    github_url: str | None


@dataclass(frozen=True)
class Comparison:
    state: RepositoryState
    base_ref: str
    base_source: str
    base_sha: str
    merge_base_sha: str


@dataclass(frozen=True)
class Commit:
    sha: str
    subject: str
    body: str


@dataclass(frozen=True)
class ChangedFile:
    status: str
    path: str
    previous_path: str | None = None


def _run_git(
    *,
    repo: Path,
    args: Sequence[str],
    check: bool = True,
) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if check and completed.returncode != 0:
        stderr = completed.stderr.strip()
        detail = stderr or f"git exited with status {completed.returncode}"
        raise EvidenceError(f"git {' '.join(args)} failed: {detail}")
    return completed.stdout


def _try_git(*, root: Path, args: Sequence[str]) -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return None
    value = completed.stdout.strip()
    return value or None


def _repository_root(*, repo_arg: str) -> Path:
    candidate = Path(repo_arg).expanduser().resolve()
    output = _run_git(repo=candidate, args=("rev-parse", "--show-toplevel"))
    assert isinstance(output, str)
    return Path(output.strip()).resolve()


def _current_branch(*, root: Path) -> str | None:
    return _try_git(
        root=root, args=("symbolic-ref", "--quiet", "--short", "HEAD")
    )


def _select_remote(
    *,
    root: Path,
    branch: str | None,
    requested_remote: str | None,
) -> str | None:
    output = _run_git(repo=root, args=("remote",))
    assert isinstance(output, str)
    remotes = [line for line in output.splitlines() if line]

    if requested_remote is not None:
        if requested_remote not in remotes:
            raise EvidenceError(
                f"remote {requested_remote!r} does not exist; available remotes: "
                f"{', '.join(remotes) or '(none)'}"
            )
        return requested_remote

    if branch is not None:
        configured = _try_git(
            root=root,
            args=("config", "--get", f"branch.{branch}.remote"),
        )
        if configured in remotes:
            return configured

    if "origin" in remotes:
        return "origin"
    if len(remotes) == 1:
        return remotes[0]
    return None


def _github_url(*, remote_url: str | None) -> str | None:
    if remote_url is None:
        return None

    value = remote_url.strip()
    scp_match = re.fullmatch(
        r"(?:[^@]+@)?github\.com:(?P<path>[^?#]+)",
        value,
        flags=re.IGNORECASE,
    )
    if scp_match:
        repository_path = scp_match.group("path")
    else:
        parsed = urlparse(value)
        if (parsed.hostname or "").lower() != "github.com":
            return None
        repository_path = parsed.path.lstrip("/")

    if repository_path.endswith(".git"):
        repository_path = repository_path[:-4]
    parts = repository_path.strip("/").split("/")
    if len(parts) != 2 or not all(parts):
        return None

    owner, repository = (quote(part, safe="-._~") for part in parts)
    return f"https://github.com/{owner}/{repository}"


def _repository_state(
    *,
    repo_arg: str,
    requested_remote: str | None,
) -> RepositoryState:
    root = _repository_root(repo_arg=repo_arg)
    branch = _current_branch(root=root)
    head_sha = _resolve_revision(root=root, revision="HEAD")
    remote_name = _select_remote(
        root=root,
        branch=branch,
        requested_remote=requested_remote,
    )
    remote_url = (
        _try_git(root=root, args=("remote", "get-url", remote_name))
        if remote_name is not None
        else None
    )
    return RepositoryState(
        root=root,
        branch=branch,
        head_sha=head_sha,
        remote_name=remote_name,
        remote_url=remote_url,
        github_url=_github_url(remote_url=remote_url),
    )


def _resolve_revision(*, root: Path, revision: str) -> str:
    resolved = _try_git(
        root=root,
        args=("rev-parse", "--verify", f"{revision}^{{commit}}"),
    )
    if resolved is None:
        raise EvidenceError(f"{revision!r} is not a commit in {root}")
    return resolved


def _infer_base(
    *,
    state: RepositoryState,
    requested_base: str | None,
) -> tuple[str, str, str]:
    if requested_base is not None:
        return (
            requested_base,
            "explicit",
            _resolve_revision(root=state.root, revision=requested_base),
        )

    if state.branch is not None:
        configured_base = _try_git(
            root=state.root,
            args=("config", "--get", f"branch.{state.branch}.gh-merge-base"),
        )
        if configured_base is not None:
            configured_refs = [configured_base]
            if state.remote_name is not None and "/" not in configured_base:
                configured_refs.insert(
                    0, f"{state.remote_name}/{configured_base}"
                )
            for ref in configured_refs:
                sha = _try_git(
                    root=state.root,
                    args=("rev-parse", "--verify", f"{ref}^{{commit}}"),
                )
                if sha is not None:
                    return ref, "branch-gh-merge-base", sha

    if state.remote_name is not None:
        remote_head = _try_git(
            root=state.root,
            args=(
                "symbolic-ref",
                "--quiet",
                "--short",
                f"refs/remotes/{state.remote_name}/HEAD",
            ),
        )
        if remote_head is not None:
            return (
                remote_head,
                "remote-default",
                _resolve_revision(root=state.root, revision=remote_head),
            )

    fallback_refs: list[tuple[str, str]] = []
    if state.remote_name is not None:
        fallback_refs.extend([
            (f"{state.remote_name}/main", "remote-fallback"),
            (f"{state.remote_name}/master", "remote-fallback"),
        ])
    fallback_refs.extend([
        ("main", "local-fallback"),
        ("master", "local-fallback"),
    ])

    candidates: list[tuple[str, str, str]] = []
    seen_shas: set[str] = set()
    for ref, source in fallback_refs:
        sha = _try_git(
            root=state.root,
            args=("rev-parse", "--verify", f"{ref}^{{commit}}"),
        )
        if sha is not None and sha not in seen_shas:
            seen_shas.add(sha)
            candidates.append((ref, source, sha))

    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise EvidenceError(
            "could not infer a base branch from local refs; pass --base <ref>"
        )

    refs = ", ".join(ref for ref, _, _ in candidates)
    raise EvidenceError(
        f"base branch is ambiguous among {refs}; pass --base <ref>"
    )


def _comparison(
    *,
    repo_arg: str,
    requested_base: str | None,
    requested_remote: str | None,
) -> Comparison:
    state = _repository_state(
        repo_arg=repo_arg,
        requested_remote=requested_remote,
    )
    base_ref, base_source, base_sha = _infer_base(
        state=state,
        requested_base=requested_base,
    )
    merge_bases = _try_git(
        root=state.root,
        args=("merge-base", "--all", base_sha, state.head_sha),
    )
    if merge_bases is None:
        raise EvidenceError(f"{base_ref!r} and HEAD do not have a merge base")
    candidates = merge_bases.splitlines()
    if len(candidates) != 1:
        raise EvidenceError(
            f"{base_ref!r} and HEAD have multiple merge bases; pass a "
            "different --base or resolve the history before drafting"
        )
    return Comparison(
        state=state,
        base_ref=base_ref,
        base_source=base_source,
        base_sha=base_sha,
        merge_base_sha=candidates[0],
    )


def _commits(*, comparison: Comparison) -> list[Commit]:
    output = _run_git(
        repo=comparison.state.root,
        args=(
            "rev-list",
            "--reverse",
            "--topo-order",
            f"{comparison.base_sha}..{comparison.state.head_sha}",
        ),
    )
    assert isinstance(output, str)
    commits: list[Commit] = []
    for sha in output.splitlines():
        subject = _run_git(
            repo=comparison.state.root,
            args=("show", "-s", "--format=%s", sha),
        )
        body = _run_git(
            repo=comparison.state.root,
            args=("show", "-s", "--format=%b", sha),
        )
        assert isinstance(subject, str)
        assert isinstance(body, str)
        commits.append(
            Commit(
                sha=sha,
                subject=subject.rstrip("\n"),
                body=body.rstrip("\n"),
            )
        )
    return commits


def _changed_files(*, comparison: Comparison) -> list[ChangedFile]:
    output = _run_git(
        repo=comparison.state.root,
        args=(
            "diff",
            "--name-status",
            "-z",
            "--find-renames",
            comparison.merge_base_sha,
            comparison.state.head_sha,
        ),
    )
    assert isinstance(output, str)
    tokens = output.split("\0")
    if tokens and tokens[-1] == "":
        tokens.pop()

    changed: list[ChangedFile] = []
    index = 0
    while index < len(tokens):
        status = tokens[index]
        index += 1
        if not status:
            raise EvidenceError("git returned an empty file status")
        if status[0] in {"R", "C"}:
            if index + 1 >= len(tokens):
                raise EvidenceError(
                    "git returned a malformed rename or copy record"
                )
            previous_path = tokens[index]
            path = tokens[index + 1]
            index += 2
            changed.append(
                ChangedFile(
                    status=status,
                    path=path,
                    previous_path=previous_path,
                )
            )
        else:
            if index >= len(tokens):
                raise EvidenceError(
                    "git returned a malformed changed-file record"
                )
            path = tokens[index]
            index += 1
            changed.append(ChangedFile(status=status, path=path))
    return changed


def _inspect(*, args: argparse.Namespace) -> int:
    comparison = _comparison(
        repo_arg=args.repo,
        requested_base=args.base,
        requested_remote=args.remote,
    )
    diff_stat = _run_git(
        repo=comparison.state.root,
        args=(
            "diff",
            "--stat",
            "--find-renames",
            comparison.merge_base_sha,
            comparison.state.head_sha,
        ),
    )
    status = _run_git(
        repo=comparison.state.root,
        args=("status", "--short"),
    )
    assert isinstance(diff_stat, str)
    assert isinstance(status, str)

    payload = {
        "schema_version": 1,
        "repository_root": str(comparison.state.root),
        "branch": comparison.state.branch,
        "head_sha": comparison.state.head_sha,
        "remote": {
            "name": comparison.state.remote_name,
            "url": comparison.state.remote_url,
            "github_url": comparison.state.github_url,
        },
        "base_ref": comparison.base_ref,
        "base_source": comparison.base_source,
        "base_sha": comparison.base_sha,
        "merge_base_sha": comparison.merge_base_sha,
        "comparison_range": {
            "commits": f"{comparison.base_sha}..{comparison.state.head_sha}",
            "diff": f"{comparison.merge_base_sha}..{comparison.state.head_sha}",
        },
        "worktree": {
            "is_dirty": bool(status),
            "entries": status.splitlines(),
        },
        "commits": [
            asdict(commit) for commit in _commits(comparison=comparison)
        ],
        "changed_files": [
            asdict(changed_file)
            for changed_file in _changed_files(comparison=comparison)
        ],
        "diff_stat": diff_stat.rstrip("\n"),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def _normalize_path(*, raw_path: str) -> str:
    path = PurePosixPath(raw_path)
    if path.is_absolute():
        raise EvidenceError("--path must be repository-relative")
    if "\\" in raw_path or any(ord(character) < 32 for character in raw_path):
        raise EvidenceError("--path must be a canonical POSIX path")
    if not raw_path or any(part in {"", ".", ".."} for part in path.parts):
        raise EvidenceError(
            "--path must be a canonical repository-relative path"
        )
    normalized = path.as_posix()
    if normalized != raw_path:
        raise EvidenceError("--path must not contain redundant separators")
    return normalized


def _blob(
    *,
    root: Path,
    revision: str,
    path: str,
) -> tuple[str, bytes]:
    sha = _resolve_revision(root=root, revision=revision)
    tree_output = _run_git(
        repo=root,
        args=("ls-tree", "-z", sha, "--", f":(literal){path}"),
    )
    assert isinstance(tree_output, str)
    if not tree_output:
        raise EvidenceError(f"{path!r} does not exist at {sha}")
    tree_entry = tree_output.removesuffix("\0")
    metadata, _, returned_path = tree_entry.partition("\t")
    mode, object_type, object_sha = metadata.split()
    if returned_path != path:
        raise EvidenceError(f"git did not resolve {path!r} literally at {sha}")
    if object_type != "blob" or mode not in {"100644", "100755"}:
        raise EvidenceError(f"{path!r} is not a regular file at {sha}")

    result = subprocess.run(
        ["git", "-C", str(root), "cat-file", "blob", object_sha],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise EvidenceError(
            f"{path!r} does not exist at {sha}: {detail or 'git show failed'}"
        )
    if b"\0" in result.stdout:
        raise EvidenceError(f"{path!r} is binary at {sha}")
    return sha, result.stdout


def _validated_lines(
    *,
    content: bytes,
    start: int,
    end: int | None,
) -> tuple[list[str], int, int]:
    lines = content.decode("utf-8", errors="replace").splitlines()
    final_end = start if end is None else end
    if start < 1:
        raise EvidenceError("--start must be at least 1")
    if final_end < start:
        raise EvidenceError("--end must be greater than or equal to --start")
    if final_end > len(lines):
        raise EvidenceError(
            f"line range {start}-{final_end} exceeds file length {len(lines)}"
        )
    return lines, start, final_end


def _diff(*, args: argparse.Namespace) -> int:
    comparison = _comparison(
        repo_arg=args.repo,
        requested_base=args.base,
        requested_remote=args.remote,
    )
    git_args: list[str] = [
        "diff",
        "--find-renames",
        "--no-ext-diff",
        "--no-color",
        comparison.merge_base_sha,
        comparison.state.head_sha,
    ]
    if args.path is not None:
        path = _normalize_path(raw_path=args.path)
        git_args.extend(["--", f":(literal){path}"])
    output = _run_git(repo=comparison.state.root, args=git_args)
    assert isinstance(output, str)
    sys.stdout.write(output)
    return 0


def _show(*, args: argparse.Namespace) -> int:
    root = _repository_root(repo_arg=args.repo)
    path = _normalize_path(raw_path=args.path)
    _, content = _blob(root=root, revision=args.revision, path=path)
    lines, start, end = _validated_lines(
        content=content,
        start=args.start,
        end=args.end,
    )
    width = len(str(end))
    for number in range(start, end + 1):
        print(f"{number:>{width}}\t{lines[number - 1]}")
    return 0


def _markdown_label(*, label: str) -> str:
    return label.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def _link(*, args: argparse.Namespace) -> int:
    state = _repository_state(
        repo_arg=args.repo,
        requested_remote=args.remote,
    )
    if state.github_url is None:
        raise EvidenceError(
            "the selected remote is not an inferable github.com repository"
        )
    path = _normalize_path(raw_path=args.path)
    sha, content = _blob(root=state.root, revision=args.revision, path=path)
    _, start, end = _validated_lines(
        content=content,
        start=args.start,
        end=args.end,
    )
    encoded_path = quote(path, safe="/-._~")
    fragment = f"#L{start}" if start == end else f"#L{start}-L{end}"
    url = f"{state.github_url}/blob/{sha}/{encoded_path}{fragment}"
    label = _markdown_label(label=args.label or Path(path).name)
    markdown = f"[{label}]({url})"

    if args.json:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "markdown": markdown,
                    "url": url,
                    "label": args.label or Path(path).name,
                    "revision": sha,
                    "path": path,
                    "start": start,
                    "end": end,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print(markdown)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Collect deterministic evidence for a pull request description "
            "and generate verified GitHub links."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser(
        "inspect",
        help="emit branch, comparison, commit, file, and worktree evidence as JSON",
    )
    inspect_parser.add_argument("--repo", default=".")
    inspect_parser.add_argument("--base")
    inspect_parser.add_argument("--remote")
    inspect_parser.set_defaults(handler=_inspect)

    diff_parser = subparsers.add_parser(
        "diff",
        help="print the committed merge-base-to-HEAD diff",
    )
    diff_parser.add_argument("--repo", default=".")
    diff_parser.add_argument("--base")
    diff_parser.add_argument("--remote")
    diff_parser.add_argument("--path")
    diff_parser.set_defaults(handler=_diff)

    show_parser = subparsers.add_parser(
        "show",
        help="print a validated, numbered range from a file at a Git revision",
    )
    show_parser.add_argument("--repo", default=".")
    show_parser.add_argument("--path", required=True)
    show_parser.add_argument("--revision", default="HEAD")
    show_parser.add_argument("--start", type=int, default=1)
    show_parser.add_argument("--end", type=int)
    show_parser.set_defaults(handler=_show)

    link_parser = subparsers.add_parser(
        "link",
        help="generate a validated immutable GitHub Markdown link",
    )
    link_parser.add_argument("--repo", default=".")
    link_parser.add_argument("--remote")
    link_parser.add_argument("--path", required=True)
    link_parser.add_argument("--revision", default="HEAD")
    link_parser.add_argument("--start", type=int, required=True)
    link_parser.add_argument("--end", type=int)
    link_parser.add_argument("--label")
    link_parser.add_argument("--json", action="store_true")
    link_parser.set_defaults(handler=_link)
    return parser


def _fail(*, message: str) -> NoReturn:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(2)


def main() -> int:
    args = _parser().parse_args()
    try:
        return int(args.handler(args=args))
    except EvidenceError as error:
        _fail(message=str(error))


if __name__ == "__main__":
    raise SystemExit(main())
