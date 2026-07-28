# Default code quality report

Use this structure for every audit unless the user asks for another format.

## 1. Executive summary

State:

* The number of major verified findings by priority.
* The number of measured concerns from the requested checks.
* Whether tests, lint, type checks, line coverage, and branch coverage ran.
* The most important limit on the audit.

Keep this section short. Do not use it instead of the detailed sections.

## 2. Major findings

Include verified findings that have a concrete maintenance, test, correctness,
or operational effect. Order them by priority and then confidence.

Use these fields for each finding:

```text
[P1] Short finding title
Location: path/to/file.py:123
Confidence: high
Category: error handling
Evidence: Exact source fact, measurement, or executed reproduction.
Impact: Concrete effect on changes, testing, correctness, or operation.
Recommendation: Smallest sound direction for fixing it.
Related requested checks: deep nesting, 10 or more arguments
```

Do not create a separate major finding for a metric when the metric is only a
symptom of a finding already reported.

## 3. Requested checks

Create one subsection for each requested check in the required order. Never
omit a subsection.

Start each subsection with these fields:

```text
Status: findings | measured concerns | none found | unknown
Count: number or unknown
Method: tool, command, source review, or coverage artifact used
```

For each item, provide:

```text
Location: path/to/file.py:123
Symbol: qualified name, when applicable
Measurement: exact size, depth, argument count, or coverage value
Details: what the code does and why the result deserves attention
Recommendation: concrete next step
Related major finding: title, or none
```

Apply these rules:

* List every file, class, and function above its size threshold.
* List every function with 10 or more arguments.
* For deep nesting, list the measured depth and describe the nested path.
* For hard coded data, name the value or data block and explain why it should
  have another owner. Do not dump unverified literal candidates.
* For documentation and typing, give the total and a complete count by file.
  Describe the most important individual gaps.
* For coverage, give line and branch coverage separately. List untested files
  and important branches only when the evidence proves they were not executed.
* For mock heavy tests, explain whether each test asserts observable behavior
  or only mock interactions.

## 4. Other findings

Report verified findings from the broader checklist that are not already in the
major findings section. Group closely related examples.

## 5. Measurement gaps and review candidates

List anything that could not be established. State the missing evidence. Keep
low confidence tool output here.

## 6. Scope and commands

State:

* Directories and file types reviewed.
* Generated, vendored, fixture, migration, or example code excluded.
* Commands run and whether each passed.
* Existing working tree changes that were preserved.

## 7. Checks with no material issue

List important checks that completed and found no concern. Do not use this
section for checks marked unknown.
