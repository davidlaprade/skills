#!/usr/bin/env python3
"""Collect Python code quality metrics and review candidates."""

from __future__ import annotations

import argparse
import ast
import io
import json
import tokenize
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

IGNORED_DIRS = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "site-packages",
    "vendor",
}


@dataclass(frozen=True)
class Finding:
    check: str
    severity: str
    confidence: str
    path: str
    line: int
    end_line: int
    symbol: str
    message: str
    evidence: dict[str, Any]


def code_line_numbers(source: str) -> set[int]:
    lines: set[int] = set()
    ignored = {
        tokenize.ENCODING,
        tokenize.ENDMARKER,
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.NEWLINE,
        tokenize.NL,
        tokenize.COMMENT,
    }
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for token in tokens:
            if token.type not in ignored:
                lines.update(range(token.start[0], token.end[0] + 1))
    except (IndentationError, tokenize.TokenError):
        return {
            number
            for number, line in enumerate(source.splitlines(), start=1)
            if line.strip() and not line.lstrip().startswith("#")
        }
    return lines


def count_span(code_lines: set[int], node: ast.AST) -> int:
    start = getattr(node, "lineno", 1)
    end = getattr(node, "end_lineno", start)
    return sum(start <= line <= end for line in code_lines)


def source_span(node: ast.AST) -> int:
    start = getattr(node, "lineno", 1)
    end = getattr(node, "end_lineno", start)
    return end - start + 1


def public_name(name: str) -> bool:
    return not name.startswith("_")


def is_test_path(path: Path) -> bool:
    return "tests" in path.parts or path.name.startswith("test_")


def iter_scope_nodes(root: ast.AST) -> Iterable[ast.AST]:
    """Yield nodes in one function scope, excluding nested definitions."""
    stack = list(ast.iter_child_nodes(root))
    while stack:
        node = stack.pop()
        if isinstance(
            node,
            (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda),
        ):
            continue
        yield node
        stack.extend(ast.iter_child_nodes(node))


def qualified_name(parents: list[str], name: str) -> str:
    return ".".join([*parents, name])


def decorator_name(node: ast.expr) -> str | None:
    """Return the final name component for a decorator expression."""
    if isinstance(node, ast.Call):
        return decorator_name(node.func)
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def is_protocol_class(node: ast.ClassDef) -> bool:
    """Return whether a class directly declares the Protocol contract."""
    return any(
        (isinstance(base, ast.Name) and base.id == "Protocol")
        or (isinstance(base, ast.Attribute) and base.attr == "Protocol")
        for base in node.bases
    )


class NestingVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.depth = 0
        self.maximum = 0

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return

    def _visit_control(self, node: ast.AST) -> None:
        self.depth += 1
        self.maximum = max(self.maximum, self.depth)
        self.generic_visit(node)
        self.depth -= 1

    def visit_If(self, node: ast.If) -> None:
        self.depth += 1
        self.maximum = max(self.maximum, self.depth)
        self.visit(node.test)
        for statement in node.body:
            self.visit(statement)
        self.depth -= 1
        if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
            self.visit(node.orelse[0])
        else:
            self.depth += 1
            for statement in node.orelse:
                self.visit(statement)
            self.depth -= 1

    visit_For = _visit_control
    visit_AsyncFor = _visit_control
    visit_While = _visit_control
    visit_With = _visit_control
    visit_AsyncWith = _visit_control
    visit_Try = _visit_control
    visit_TryStar = _visit_control
    visit_Match = _visit_control


def maximum_nesting(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    visitor = NestingVisitor()
    for statement in node.body:
        visitor.visit(statement)
    return visitor.maximum


def function_complexity(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    complexity = 1
    for child in iter_scope_nodes(node):
        if isinstance(child, (ast.If, ast.For, ast.AsyncFor, ast.While)):
            complexity += 1
        elif isinstance(child, ast.BoolOp):
            complexity += max(1, len(child.values) - 1)
        elif isinstance(child, ast.Try):
            complexity += len(child.handlers) + bool(child.orelse)
        elif isinstance(child, ast.Match):
            complexity += len(child.cases)
        elif isinstance(child, ast.comprehension):
            complexity += len(child.ifs)
    return complexity


def function_arguments(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[ast.arg]:
    positional = [*node.args.posonlyargs, *node.args.args]
    if positional and positional[0].arg in {"self", "cls"}:
        positional = positional[1:]
    result = [*positional, *node.args.kwonlyargs]
    if node.args.vararg:
        result.append(node.args.vararg)
    if node.args.kwarg:
        result.append(node.args.kwarg)
    return result


def mutable_default_count(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> int:
    defaults = [*node.args.defaults, *node.args.kw_defaults]
    mutable_calls = {"dict", "list", "set"}
    count = 0
    for default in defaults:
        if default is None:
            continue
        if isinstance(default, (ast.Dict, ast.List, ast.Set)) or (
            isinstance(default, ast.Call)
            and isinstance(default.func, ast.Name)
            and default.func.id in mutable_calls
        ):
            count += 1
    return count


def literal_candidates(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    parents: dict[ast.AST, ast.AST],
) -> list[object]:
    values: list[object] = []
    docstring_node = (
        node.body[0].value
        if node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        else None
    )
    for child in iter_scope_nodes(node):
        if not isinstance(child, ast.Constant) or child is docstring_node:
            continue
        value = child.value
        if value is None or isinstance(value, (bool, bytes)):
            continue
        if isinstance(value, (int, float, complex)) and value in {0, 1}:
            continue
        if isinstance(value, str) and not value:
            continue
        parent = parents.get(child)
        if isinstance(parent, (ast.JoinedStr, ast.FormattedValue)):
            continue
        values.append(value)
    return values


class PythonAuditor(ast.NodeVisitor):
    def __init__(
        self,
        path: Path,
        relative_path: str,
        code_lines: set[int],
        thresholds: argparse.Namespace,
        include_literals: bool,
        tree: ast.AST,
    ) -> None:
        self.path = path
        self.relative_path = relative_path
        self.code_lines = code_lines
        self.thresholds = thresholds
        self.include_literals = include_literals
        self.findings: list[Finding] = []
        self.parents: list[str] = []
        self.class_contexts: list[tuple[str, bool]] = []
        self.parent_map = {
            child: parent
            for parent in ast.walk(tree)
            for child in ast.iter_child_nodes(parent)
        }

    def add(
        self,
        check: str,
        severity: str,
        confidence: str,
        node: ast.AST,
        symbol: str,
        message: str,
        **evidence: Any,
    ) -> None:
        line = getattr(node, "lineno", 1)
        end_line = getattr(node, "end_lineno", line)
        self.findings.append(
            Finding(
                check=check,
                severity=severity,
                confidence=confidence,
                path=self.relative_path,
                line=line,
                end_line=end_line,
                symbol=symbol,
                message=message,
                evidence=evidence,
            )
        )

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        symbol = qualified_name(self.parents, node.name)
        source_lines = source_span(node)
        code_lines = count_span(self.code_lines, node)
        if source_lines > self.thresholds.class_lines:
            self.add(
                "large-class",
                "review",
                "high",
                node,
                symbol,
                f"Class spans {source_lines} source lines.",
                source_lines=source_lines,
                code_lines=code_lines,
                threshold=self.thresholds.class_lines,
            )
        if (
            not is_test_path(self.path)
            and public_name(node.name)
            and ast.get_docstring(node, clean=False) is None
        ):
            self.add(
                "missing-docstring",
                "review",
                "high",
                node,
                symbol,
                "Public class has no docstring.",
            )
        self.parents.append(node.name)
        self.class_contexts.append((node.name, is_protocol_class(node)))
        self.generic_visit(node)
        self.class_contexts.pop()
        self.parents.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        symbol = qualified_name(self.parents, node.name)
        source_lines = source_span(node)
        code_lines = count_span(self.code_lines, node)
        arguments = function_arguments(node)
        untyped = [
            argument.arg
            for argument in arguments
            if argument.annotation is None
        ]
        nesting = maximum_nesting(node)
        complexity = function_complexity(node)
        returns = sum(
            isinstance(child, ast.Return) for child in iter_scope_nodes(node)
        )
        broad_handlers = [
            child
            for child in iter_scope_nodes(node)
            if isinstance(child, ast.ExceptHandler)
            and (
                child.type is None
                or (
                    isinstance(child.type, ast.Name)
                    and child.type.id in {"BaseException", "Exception"}
                )
            )
        ]
        decorator_names = {
            name
            for decorator in node.decorator_list
            if (name := decorator_name(decorator)) is not None
        }
        containing_class = (
            self.class_contexts[-1] if self.class_contexts else None
        )
        is_pydantic_validator = bool(
            decorator_names
            & {
                "field_validator",
                "model_validator",
                "root_validator",
                "validator",
            }
        )
        is_protocol_property = bool(
            containing_class
            and containing_class[1]
            and decorator_names
            & {"property", "cached_property", "setter", "deleter"}
        )
        is_private_prepared_method = bool(
            containing_class and containing_class[0].startswith("_Prepared")
        )

        if source_lines > self.thresholds.function_lines:
            self.add(
                "large-function",
                "review",
                "high",
                node,
                symbol,
                f"Function spans {source_lines} source lines.",
                source_lines=source_lines,
                code_lines=code_lines,
                threshold=self.thresholds.function_lines,
            )
        if nesting > self.thresholds.nesting:
            self.add(
                "deep-nesting",
                "review",
                "high",
                node,
                symbol,
                f"Function reaches {nesting} control flow levels.",
                nesting=nesting,
                threshold=self.thresholds.nesting,
            )
        if len(arguments) >= self.thresholds.arguments:
            self.add(
                "many-arguments",
                "review",
                "high",
                node,
                symbol,
                f"Function has {len(arguments)} arguments.",
                arguments=len(arguments),
                threshold=self.thresholds.arguments,
            )
        if complexity > self.thresholds.complexity:
            self.add(
                "high-complexity",
                "review",
                "moderate",
                node,
                symbol,
                f"Estimated cyclomatic complexity is {complexity}.",
                complexity=complexity,
                threshold=self.thresholds.complexity,
            )
        if returns > self.thresholds.returns:
            self.add(
                "many-returns",
                "review",
                "high",
                node,
                symbol,
                f"Function has {returns} return statements.",
                returns=returns,
                threshold=self.thresholds.returns,
            )

        if not is_test_path(self.path):
            if (
                public_name(node.name)
                and ast.get_docstring(node, clean=False) is None
                and not is_pydantic_validator
                and not is_protocol_property
                and not is_private_prepared_method
            ):
                self.add(
                    "missing-docstring",
                    "review",
                    "high",
                    node,
                    symbol,
                    "Public function has no docstring.",
                )
            if untyped:
                self.add(
                    "untyped-arguments",
                    "review",
                    "high",
                    node,
                    symbol,
                    f"Function has {len(untyped)} untyped arguments.",
                    arguments=untyped,
                )
            if node.returns is None:
                self.add(
                    "missing-return-type",
                    "review",
                    "high",
                    node,
                    symbol,
                    "Function has no return type annotation.",
                )

        mutable_defaults = mutable_default_count(node)
        if mutable_defaults:
            self.add(
                "mutable-default",
                "likely-defect",
                "high",
                node,
                symbol,
                "Function has a mutable default argument.",
                mutable_defaults=mutable_defaults,
            )
        if broad_handlers:
            self.add(
                "broad-exception",
                "review",
                "high",
                broad_handlers[0],
                symbol,
                f"Function has {len(broad_handlers)} broad exception handlers.",
                handlers=len(broad_handlers),
            )

        if self.include_literals:
            values = literal_candidates(node, self.parent_map)
            if values:
                examples = [repr(value)[:100] for value in values[:8]]
                self.add(
                    "hard-coded-literals",
                    "candidate",
                    "low",
                    node,
                    symbol,
                    f"Function contains {len(values)} literal candidates.",
                    count=len(values),
                    examples=examples,
                )

        self.parents.append(node.name)
        self.generic_visit(node)
        self.parents.pop()


def mock_heavy_candidate(
    tree: ast.AST,
    relative_path: str,
) -> Finding | None:
    mock_names = {"AsyncMock", "MagicMock", "Mock", "monkeypatch", "patch"}
    mocks = 0
    assertions = 0
    first_line = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            assertions += 1
        elif isinstance(node, ast.Call):
            name = ""
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            if name in mock_names or name.startswith("assert_"):
                if name.startswith("assert_"):
                    assertions += 1
                else:
                    mocks += 1
                    first_line = min(first_line or node.lineno, node.lineno)
            if name in {"raises", "warns"}:
                assertions += 1
        elif isinstance(node, ast.Name) and node.id == "monkeypatch":
            mocks += 1
            first_line = min(first_line or node.lineno, node.lineno)
    if mocks >= 5 and mocks > assertions:
        return Finding(
            check="mock-heavy-test",
            severity="candidate",
            confidence="low",
            path=relative_path,
            line=first_line,
            end_line=first_line,
            symbol="",
            message=(
                f"Test file has {mocks} mock references and "
                f"{assertions} observed assertions."
            ),
            evidence={"mock_references": mocks, "assertions": assertions},
        )
    return None


def python_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root] if root.suffix == ".py" else []
    return sorted(
        path
        for path in root.rglob("*.py")
        if not any(part in IGNORED_DIRS for part in path.parts)
    )


def audit_file(
    path: Path,
    root: Path,
    args: argparse.Namespace,
) -> tuple[dict[str, Any], list[Finding]]:
    relative_path = path.name if root.is_file() else str(path.relative_to(root))
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        finding = Finding(
            "unreadable-file",
            "error",
            "high",
            relative_path,
            1,
            1,
            "",
            f"Could not read file: {error}",
            {},
        )
        return {"path": relative_path, "error": str(error)}, [finding]

    code_lines = code_line_numbers(source)
    metrics = {
        "path": relative_path,
        "physical_lines": len(source.splitlines()),
        "code_lines": len(code_lines),
    }
    findings: list[Finding] = []
    physical_lines = len(source.splitlines())
    if physical_lines > args.file_lines:
        findings.append(
            Finding(
                "large-file",
                "review",
                "high",
                relative_path,
                1,
                max(1, len(source.splitlines())),
                "",
                f"File has {physical_lines} source lines.",
                {
                    "source_lines": physical_lines,
                    "code_lines": len(code_lines),
                    "threshold": args.file_lines,
                },
            )
        )

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as error:
        line = error.lineno or 1
        findings.append(
            Finding(
                "syntax-error",
                "error",
                "high",
                relative_path,
                line,
                line,
                "",
                error.msg,
                {},
            )
        )
        return metrics, findings

    auditor = PythonAuditor(
        path,
        relative_path,
        code_lines,
        args,
        args.include_literals,
        tree,
    )
    auditor.visit(tree)
    findings.extend(auditor.findings)
    if is_test_path(path):
        candidate = mock_heavy_candidate(tree, relative_path)
        if candidate:
            findings.append(candidate)
    return metrics, findings


def render_text(report: dict[str, Any]) -> str:
    lines = [
        f"Python files: {report['summary']['files']}",
        f"Code lines: {report['summary']['code_lines']}",
        f"Review items: {report['summary']['findings']}",
        "",
    ]
    for finding in report["findings"]:
        location = f"{finding['path']}:{finding['line']}"
        symbol = f" ({finding['symbol']})" if finding["symbol"] else ""
        lines.append(
            f"[{finding['severity']}] {finding['check']} "
            f"at {location}{symbol}: {finding['message']}"
        )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect Python code quality metrics and review candidates."
    )
    parser.add_argument("root", type=Path)
    parser.add_argument("--format", choices=("json", "text"), default="text")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--include-literals", action="store_true")
    parser.add_argument("--file-lines", type=int, default=1000)
    parser.add_argument("--class-lines", type=int, default=500)
    parser.add_argument("--function-lines", type=int, default=300)
    parser.add_argument("--nesting", type=int, default=2)
    parser.add_argument("--arguments", type=int, default=10)
    parser.add_argument("--complexity", type=int, default=15)
    parser.add_argument("--returns", type=int, default=6)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    if not root.exists():
        raise SystemExit(f"Path does not exist: {root}")

    metrics: list[dict[str, Any]] = []
    findings: list[Finding] = []
    for path in python_files(root):
        file_metrics, file_findings = audit_file(path, root, args)
        metrics.append(file_metrics)
        findings.extend(file_findings)

    findings.sort(key=lambda item: (item.path, item.line, item.check))
    report = {
        "root": str(root),
        "thresholds": {
            "file_lines": args.file_lines,
            "class_lines": args.class_lines,
            "function_lines": args.function_lines,
            "nesting": args.nesting,
            "arguments": args.arguments,
            "complexity": args.complexity,
            "returns": args.returns,
        },
        "summary": {
            "files": len(metrics),
            "code_lines": sum(item.get("code_lines", 0) for item in metrics),
            "findings": len(findings),
        },
        "files": metrics,
        "findings": [asdict(finding) for finding in findings],
    }
    output = (
        json.dumps(report, indent=2, sort_keys=True)
        if args.format == "json"
        else render_text(report)
    )
    if args.output:
        args.output.write_text(f"{output}\n", encoding="utf-8")
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
