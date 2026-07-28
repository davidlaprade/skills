# Code quality checks

Use this reference to decide what to measure and what deserves a finding.

## Size and control flow

Use these default thresholds unless the repository defines stricter ones:

| Check | Default trigger | Interpretation |
| --- | ---: | --- |
| File size | More than 1,000 code lines | Review for mixed responsibilities and poor navigation. |
| Class size | More than 500 code lines | Review whether state and behavior belong to separate concepts. |
| Function size | More than 300 code lines | Treat as severe. Also inspect shorter complex functions. |
| Control flow nesting | More than 2 levels | Review whether guard clauses or extraction would clarify the path. |
| Arguments | 10 or more | Exclude `self` and `cls`. Check whether a value object or narrower operation fits. |
| Cyclomatic complexity | More than 15 | Inspect independent paths and tests. Do not rank from the number alone. |
| Return statements | More than 6 | Review whether the function has several jobs or hard to follow exits. |

Count source lines from the first line through the last line of the file or
symbol. Also report code lines with blank lines and comments removed when the
language permits it. A threshold crossing is a review trigger. Explain the
actual problem before reporting it as a finding.

## Literals and configuration

Look for values whose meaning, ownership, or change policy is hidden:

* Domain limits, timeouts, retries, ports, status values, model names, paths,
  dates, identifiers, and protocol values embedded in logic.
* The same value repeated where the copies must stay equal.
* Environment specific data committed to application code.
* Large tables, prompts, schemas, or mappings mixed with behavior.
* Secrets or credentials. Rank these by their direct security risk.

Do not flag a literal merely because it is not a constant. Values such as zero,
one, an empty collection, a local error message, a dictionary key, or a clear
format string are often easier to understand in place. Confirm that naming or
centralizing the value would make a future change safer.

## Interfaces, types, and documentation

Check:

* Public functions and classes without useful documentation.
* Private functions without documentation when their contract is not clear
  from the name, types, and code.
* Function arguments without type annotations in typed application or library
  code.
* Missing return types where the result is not obvious.
* Ten or more arguments, long groups of related primitive values, boolean mode
  arguments, and arguments that are always passed together.
* Functions that both compute and perform input, output, network, process, or
  storage work.
* Interfaces that expose implementation details or require callers to repeat
  validation and ordering rules.

Do not demand docstrings that repeat a clear signature. Useful documentation
states behavior, units, side effects, errors, or constraints that the signature
cannot express.

## Complexity and structure

Inspect:

* High cyclomatic or cognitive complexity.
* Repeated branches and duplicated blocks.
* Dead, unreachable, or obsolete code.
* Circular imports and dependency cycles.
* Excessive imports, broad utility modules, and central modules that know about
  most of the system.
* Domain rules spread across unrelated layers.
* Hidden global state, mutable module state, and import time side effects.
* Boolean flags or mode strings that produce separate behaviors.
* Inconsistent levels of abstraction within one function.
* Temporal coupling where calls must occur in an undocumented order.
* Data classes with behavior elsewhere and service classes with unrelated jobs.

Use dependency graphs or duplicate detection tools when the repository already
has them. Otherwise confirm suspected problems by tracing imports and callers.

## Error handling and resource safety

Inspect:

* Bare `except` clauses and broad exception catches.
* Exceptions that are ignored, logged without action, or replaced without the
  original cause.
* Retry loops without clear limits or safe repeat behavior.
* Partial writes and multi step updates without cleanup or rollback.
* Files, processes, locks, sockets, and clients without reliable cleanup.
* Error return values that callers fail to check.
* Assertions used for runtime validation.
* Mutable default arguments.
* Mixed error styles that force callers to handle the same failure in several
  ways.

## Tests and coverage

Coverage claims require executed coverage data. Prefer branch coverage when
control flow is material. Report line and branch coverage separately.

Inspect:

* Source files and important branches with no executed coverage.
* Public behavior tested only through mocks.
* Tests with more setup and mock interaction than outcome checks.
* Assertions about calls instead of observable results when a result can be
  checked.
* Tests coupled to private methods or exact internal call order.
* Weak assertions such as only checking that a result is not `None`.
* Missing failure, boundary, concurrency, and cleanup tests.
* Flaky tests, arbitrary sleeps, dependence on wall clock time, and shared
  mutable state.
* Slow tests with no smaller focused layer.
* Large test files with repeated setup or unclear scenario names.
* Disabled tests and broad warning filters.

Mocks are appropriate at costly, unstable, or dangerous boundaries. A high mock
count is only a review candidate. Read the test and the production boundary
before calling it a finding.

## Tooling and dependency health

Check:

* Missing or bypassed lint, format, type, test, and coverage checks.
* Unexplained ignores such as `noqa`, type ignores, disabled rules, and warning
  filters.
* Generated files that are linted as source or source files excluded by broad
  patterns.
* Unused, duplicated, conflicting, or unbounded dependencies.
* Runtime dependencies used only by development tools.
* Committed build output and stale generated artifacts.

The absence of a tool is not automatically a finding. Show the defects or risk
that the missing check allows in this repository.

## Evidence and confidence

Use high confidence when the source or executed tool directly establishes the
claim. Use moderate confidence when the evidence is strong but depends on
runtime behavior or ownership information. Use low confidence only in a
separate review candidate section.

Do not inflate the report with repeated symptoms from one root cause. Group
closely related evidence and cite the best examples.
