from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Sequence
from pathlib import Path
from typing import cast

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "pr_evidence.py"


class PrEvidenceCliTest(unittest.TestCase):
    repository: Path
    base_sha: str

    def setUp(self) -> None:
        temporary_directory = tempfile.TemporaryDirectory(
            prefix="pr-evidence-test-"
        )
        self.addCleanup(temporary_directory.cleanup)
        self.repository = Path(temporary_directory.name) / "repository"
        self.repository.mkdir()

        self._command(args=("git", "init", "-b", "main", str(self.repository)))
        self._git(args=("config", "user.name", "PR Evidence Test"))
        self._git(args=("config", "user.email", "pr-evidence-test@example.com"))
        self._write(
            path="src/module.py",
            content="def value():\n    return 'base'\n",
        )
        self._commit(subject="Create base")
        self.base_sha = self._git(args=("rev-parse", "HEAD"))

        self._git(
            args=(
                "remote",
                "add",
                "origin",
                "git@github.com:Example-Org/demo-repo.git",
            )
        )
        self._git(
            args=("update-ref", "refs/remotes/origin/main", self.base_sha)
        )
        self._git(
            args=(
                "symbolic-ref",
                "refs/remotes/origin/HEAD",
                "refs/remotes/origin/main",
            )
        )
        self._git(args=("switch", "-c", "feature"))

    def _command(
        self,
        *,
        args: Sequence[str],
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            list(args),
            check=False,
            capture_output=True,
            text=True,
        )
        if check and result.returncode != 0:
            self.fail(
                f"command failed with exit code {result.returncode}: {args}\n"
                f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )
        return result

    def _git(self, *, args: Sequence[str]) -> str:
        result = self._command(args=("git", "-C", str(self.repository), *args))
        return result.stdout.rstrip("\n")

    def _cli(
        self,
        *,
        args: Sequence[str],
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return self._command(
            args=(
                sys.executable,
                "-B",
                str(SCRIPT),
                *args,
                "--repo",
                str(self.repository),
            ),
            check=check,
        )

    def _write(self, *, path: str, content: str | bytes) -> None:
        destination = self.repository / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            destination.write_bytes(content)
        else:
            destination.write_text(content, encoding="utf-8")

    def _commit(self, *, subject: str, body: str | None = None) -> str:
        self._git(args=("add", "--all"))
        commit_args = ["commit", "-m", subject]
        if body is not None:
            commit_args.extend(["-m", body])
        self._git(args=commit_args)
        return self._git(args=("rev-parse", "HEAD"))

    def _payload(
        self, *, result: subprocess.CompletedProcess[str]
    ) -> dict[str, object]:
        value: object = json.loads(result.stdout)
        self.assertIsInstance(value, dict)
        return cast(dict[str, object], value)

    def test_inspect_reports_commits_and_excludes_uncommitted_changes(
        self,
    ) -> None:
        self._write(
            path="src/module.py",
            content="def value():\n    return 'feature'\n",
        )
        head_sha = self._commit(
            subject="Change behavior",
            body="Fix stale values.",
        )
        self._write(path="uncommitted.txt", content="not part of the PR\n")

        payload = self._payload(result=self._cli(args=("inspect",)))

        self.assertEqual(payload["base_ref"], "origin/main")
        self.assertEqual(payload["base_source"], "remote-default")
        self.assertEqual(payload["head_sha"], head_sha)
        self.assertEqual(payload["merge_base_sha"], self.base_sha)

        commits = cast(list[dict[str, object]], payload["commits"])
        self.assertEqual(
            commits,
            [
                {
                    "sha": head_sha,
                    "subject": "Change behavior",
                    "body": "Fix stale values.",
                }
            ],
        )

        changed_files = cast(list[dict[str, object]], payload["changed_files"])
        self.assertEqual(
            changed_files,
            [
                {
                    "status": "M",
                    "path": "src/module.py",
                    "previous_path": None,
                }
            ],
        )

        worktree = cast(dict[str, object], payload["worktree"])
        self.assertIs(worktree["is_dirty"], True)
        entries = cast(list[str], worktree["entries"])
        self.assertIn("?? uncommitted.txt", entries)

    def test_explicit_base_overrides_configured_pr_base(self) -> None:
        self._git(args=("config", "branch.feature.gh-merge-base", "main"))

        configured = self._payload(result=self._cli(args=("inspect",)))
        self.assertEqual(configured["base_ref"], "origin/main")
        self.assertEqual(configured["base_source"], "branch-gh-merge-base")

        explicit = self._payload(
            result=self._cli(args=("inspect", "--base", self.base_sha))
        )
        self.assertEqual(explicit["base_ref"], self.base_sha)
        self.assertEqual(explicit["base_source"], "explicit")

    def test_missing_remote_head_falls_back_to_origin_main(self) -> None:
        self._git(args=("symbolic-ref", "--delete", "refs/remotes/origin/HEAD"))

        payload = self._payload(result=self._cli(args=("inspect",)))

        self.assertEqual(payload["base_ref"], "origin/main")
        self.assertEqual(payload["base_source"], "remote-fallback")

    def test_ambiguous_fallback_bases_require_an_explicit_base(self) -> None:
        self._git(args=("symbolic-ref", "--delete", "refs/remotes/origin/HEAD"))
        tree_sha = self._git(args=("rev-parse", f"{self.base_sha}^{{tree}}"))
        other_base = self._git(
            args=(
                "commit-tree",
                tree_sha,
                "-p",
                self.base_sha,
                "-m",
                "Create other base",
            )
        )
        self._git(args=("update-ref", "refs/remotes/origin/master", other_base))

        result = self._cli(args=("inspect",), check=False)

        self.assertEqual(result.returncode, 2)
        self.assertIn("base branch is ambiguous", result.stderr)
        self.assertIn("origin/main", result.stderr)
        self.assertIn("origin/master", result.stderr)

    def test_detached_head_is_reported_without_losing_evidence(self) -> None:
        self._write(path="src/new.py", content="VALUE = 1\n")
        head_sha = self._commit(subject="Add detached change")
        self._git(args=("checkout", "--detach", head_sha))

        payload = self._payload(
            result=self._cli(args=("inspect", "--base", "origin/main"))
        )

        self.assertIsNone(payload["branch"])
        self.assertEqual(payload["head_sha"], head_sha)
        commits = cast(list[dict[str, object]], payload["commits"])
        self.assertEqual([commit["sha"] for commit in commits], [head_sha])

    def test_github_remote_forms_produce_the_same_web_url(self) -> None:
        remote_urls = (
            "git@github.com:Example-Org/demo-repo.git",
            "https://github.com/Example-Org/demo-repo.git",
            "ssh://git@github.com/Example-Org/demo-repo.git",
        )

        for remote_url in remote_urls:
            with self.subTest(remote_url=remote_url):
                self._git(args=("remote", "set-url", "origin", remote_url))
                payload = self._payload(
                    result=self._cli(
                        args=(
                            "link",
                            "--path",
                            "src/module.py",
                            "--start",
                            "1",
                            "--json",
                        )
                    )
                )
                self.assertEqual(
                    payload["url"],
                    (
                        "https://github.com/Example-Org/demo-repo/blob/"
                        f"{self.base_sha}/src/module.py#L1"
                    ),
                )

    def test_link_uses_full_sha_and_encodes_special_path_characters(
        self,
    ) -> None:
        path = "src/a # ü.py"
        self._write(
            path=path,
            content="def replacement():\n    return 'new'\n",
        )
        head_sha = self._commit(subject="Add special path")

        payload = self._payload(
            result=self._cli(
                args=(
                    "link",
                    "--path",
                    path,
                    "--start",
                    "1",
                    "--end",
                    "2",
                    "--json",
                )
            )
        )

        self.assertEqual(payload["revision"], head_sha)
        self.assertEqual(payload["start"], 1)
        self.assertEqual(payload["end"], 2)
        url = cast(str, payload["url"])
        self.assertIn(f"/blob/{head_sha}/", url)
        self.assertIn("a%20%23%20%C3%BC.py", url)
        self.assertTrue(url.endswith("#L1-L2"))

    def test_rename_metadata_and_path_limited_diff(self) -> None:
        new_path = "src/renamed # module.py"
        self._git(args=("mv", "src/module.py", new_path))
        self._commit(subject="Rename module")

        payload = self._payload(result=self._cli(args=("inspect",)))
        changed_files = cast(list[dict[str, object]], payload["changed_files"])

        self.assertEqual(len(changed_files), 1)
        self.assertEqual(changed_files[0]["status"], "R100")
        self.assertEqual(changed_files[0]["previous_path"], "src/module.py")
        self.assertEqual(changed_files[0]["path"], new_path)

        diff = self._cli(args=("diff", "--path", new_path))
        self.assertIn(f"diff --git a/{new_path} b/{new_path}", diff.stdout)
        self.assertIn("+def value():", diff.stdout)

    def test_deleted_file_can_only_link_to_the_base_revision(self) -> None:
        self._git(args=("rm", "src/module.py"))
        self._commit(subject="Delete module")

        missing = self._cli(
            args=(
                "link",
                "--path",
                "src/module.py",
                "--start",
                "1",
            ),
            check=False,
        )
        self.assertEqual(missing.returncode, 2)
        self.assertIn("does not exist", missing.stderr)

        old_link = self._cli(
            args=(
                "link",
                "--path",
                "src/module.py",
                "--revision",
                self.base_sha,
                "--start",
                "1",
            )
        )
        self.assertIn(
            f"/blob/{self.base_sha}/src/module.py#L1",
            old_link.stdout,
        )

    def test_line_links_reject_binary_symlink_and_invalid_ranges(
        self,
    ) -> None:
        self._write(path="binary.bin", content=b"text\0binary")
        os.symlink("src/module.py", self.repository / "linked.py")
        self._commit(subject="Add unsupported files")

        unsupported = (
            ("binary.bin", "binary"),
            ("linked.py", "not a regular file"),
        )
        for path, message in unsupported:
            with self.subTest(path=path):
                result = self._cli(
                    args=(
                        "link",
                        "--path",
                        path,
                        "--start",
                        "1",
                    ),
                    check=False,
                )
                self.assertEqual(result.returncode, 2)
                self.assertIn(message, result.stderr)

        invalid_ranges = (
            (("0",), "--start must be at least 1"),
            (
                ("2", "--end", "1"),
                "--end must be greater than or equal to --start",
            ),
            (("99",), "exceeds file length"),
        )
        for range_args, message in invalid_ranges:
            with self.subTest(range_args=range_args):
                result = self._cli(
                    args=(
                        "link",
                        "--path",
                        "src/module.py",
                        "--start",
                        *range_args,
                    ),
                    check=False,
                )
                self.assertEqual(result.returncode, 2)
                self.assertIn(message, result.stderr)

    def test_show_counts_an_unterminated_final_line(self) -> None:
        self._write(path="src/module.py", content="first\nsecond")
        self._commit(subject="Use unterminated final line")

        result = self._cli(
            args=(
                "show",
                "--path",
                "src/module.py",
                "--start",
                "2",
                "--end",
                "2",
            )
        )

        self.assertEqual(result.stdout, "2\tsecond\n")

    def test_non_github_remote_and_noncanonical_paths_fail(self) -> None:
        self._git(
            args=(
                "remote",
                "set-url",
                "origin",
                "https://gitlab.com/Example-Org/demo-repo.git",
            )
        )
        non_github = self._cli(
            args=(
                "link",
                "--path",
                "src/module.py",
                "--start",
                "1",
            ),
            check=False,
        )
        self.assertEqual(non_github.returncode, 2)
        self.assertIn("not an inferable github.com", non_github.stderr)

        self._git(
            args=(
                "remote",
                "set-url",
                "origin",
                "git@github.com:Example-Org/demo-repo.git",
            )
        )
        invalid_paths = ("../module.py", "./src/module.py", "src//module.py")
        for path in invalid_paths:
            with self.subTest(path=path):
                result = self._cli(
                    args=(
                        "link",
                        "--path",
                        path,
                        "--start",
                        "1",
                    ),
                    check=False,
                )
                self.assertEqual(result.returncode, 2)
                self.assertIn("--path must", result.stderr)


if __name__ == "__main__":
    unittest.main()
