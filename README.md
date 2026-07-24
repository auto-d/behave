# Behave

This project introduces Behave, a repository-native Markdown contract and companion tool that capture a system's intended external behavior and evaluation criteria.

Behave keeps governing intent available to humans, coding agents, implementations,and evaluators instead of allowing tests or conversation history to become lossy proxies for the original design.

> **Status:** Early draft. The structure is usable, but the protocol may evolve.

## Background

Coding agents have substantially reduced the cost of implementing a design, but they have not reduced the need to specify one. When intent is incomplete, an agent can produce many plausible implementations—including implementations that satisfy narrow tests while violating the system's broader purpose.

Traditional requirements often become progressively separated from implementation and evaluation:

requirements
→ derived requirements
→ implementation
→ tests
→ release

Over time, tests and implementation details may become operational proxies for the original design, while important intent remains distributed across conversations, source code, documentation, and issue history.

A Behave specification keeps that intent explicit and active throughout the system lifecycle. It serves as:
- the design contract between the operator and the implementation
- the governing behavioral reference for coding agents
- the basis for determining whether implementation is complete
- the anchor for implementation-appropriate evaluation 
- a traceable source of intent for downstream tests and evaluation results

The protocol describes behavior, not implementation. It defines what the system must do and how satisfaction will be determined without prescribing the architecture, algorithms, tools, or programming languages used to achieve it.

A conforming Behave specification remains readable as ordinary repository-native Markdown while providing enough structure for tooling to enumerate behaviors, verify that each has an evaluation path, and associate implementation and evaluation artifacts with the intent they are meant to satisfy.

## Quick start

Clone the repository and validate the included worked example:

```sh
python3 behave.py example.md
python3 -m unittest
```

To adopt the protocol, copy `behave.py` into your repository, create a
behavior specification, and run:

```sh
python3 behave.py path/to/behavior.md
```

The command-line tool uses only the Python standard library.

See [example.md](example.md) for a worked contract covering multiple
requirements, behaviors, and evaluation methods.

## A small, illustrative, and valid specification

```md
### R-EXAMPLE

#### Intent

The system exposes health and status.

#### Behavior

- The system reports its state through one or more HTTP endpoints with explanatory text.

  - Evaluate: Each endpoint produces a documented HTTP status code.
  - Evaluate: Health explanations are plain English and consistent with the reported status codes.
```

A requirement has a stable `R-UPPERCASE-ID` and four recognized sections:

- `#### Intent` — required exactly once.
- `#### Behavior` — required exactly once.
- `#### Rationale` — optional, at most once.
- `#### References` — optional, at most once.

The protocol constrains what the system must do and how satisfaction will be determined. It does not prescribe architecture, algorithms, tools, programming
languages, or internal reasoning.

## Behaviors

A behavior is one coherent, externally observable expectation. Behaviors describe what the system must do without prescribing its implementation.

The `Behavior` section expresses each behavior as a top-level bullet. Every behavior must have at least one immediate child `Evaluate:` bullet defining a criterion for judging whether the behavior is satisfied.

## Evaluations

An `Evaluate` clause says what must be true for its behavior to count as
satisfied. Together, the clauses beneath a behavior form its evaluation
checklist.

Each clause should make clear what the evidence needs to show. It may name
facts, comparisons, thresholds, coverage, or an observation period, but it
should not dictate how the implementation collects evidence or which artifact
format it uses.

Evidence may be supplied through tests, measurements, Markdown reports, screenshots, telemetry exports, session captures, API responses, or other implementation-appropriate artifacts.

Optional bracket annotations are opaque, experimental hints:

```md
- Evaluate: The response conforms to the published schema.
- Evaluate [evidence=workspace snapshot, response]: Each material factual claim is supported by the workspace state available when the response was produced.
- Evaluate [evidence=latency measurements]: p95 latency remains below 500 ms over a representative measurement period.
```

Annotations may help implementations discover likely evidence sources, but they are non-normative and may evolve. A criterion must remain understandable without them. The tool accepts annotation contents without interpreting or restricting them.

## Using `behave.py`

The examples below assume `behavior.md` contains the small `R-EXAMPLE`
specification shown above.

### Validate a specification

Run the default validation mode:

```sh
$ python3 behave.py behavior.md
Behavior specification valid: 1 file(s) checked.
```

Validation checks requirement IDs, required and duplicate sections, unknown
sections, stray requirement content, behavior/evaluation nesting, and nonempty
evaluation statements.

Use `--json` when another tool will consume the diagnostics:

```sh
$ python3 behave.py --json behavior.md
[]
```

An empty JSON array means no validation errors were found.

### Inspect requirements

List requirement IDs without reading the whole specification:

```sh
$ python3 behave.py --list-requirements behavior.md
R-EXAMPLE
```

Retrieve one requirement by its exact ID:

```sh
$ python3 behave.py --show-requirement R-EXAMPLE behavior.md
### R-EXAMPLE

#### Intent

The system exposes health and status.

#### Behavior

- The system reports its state through one or more HTTP endpoints with explanatory text.

  - Evaluate: Each endpoint produces a documented HTTP status code.
  - Evaluate: Health explanations are plain English and consistent with the reported status codes.
```

Queries require one specification file and preserve document order. Extraction
fails when the requirement is absent or duplicated. Add `--json` to either
query for structured output.

### Check references

Local and HTTP reference checks are opt-in:

```sh
$ python3 behave.py --check-references behavior.md
Behavior specification valid: 1 file(s) checked.
```

`--check-references` verifies local paths relative to the specification and
fetches HTTP(S) references. To check only HTTP(S) references, use
`--check-external-references`; add `--timeout 5` to set a five-second timeout
per request. External checks require network access.

### Generate a scoresheet

Generate a Markdown scoresheet from one valid specification:

```sh
$ python3 behave.py --scoresheet behavior.md > scoresheet.md
```

The generated file preserves the complete specification and adds an evidence
area beneath every criterion:

```md
  - Evaluate: Each endpoint produces a documented HTTP status code.
    - Evidence:
      - _No evidence linked yet._
```

Replace each placeholder with links to implementation-appropriate artifacts
such as test results, measurements, reports, screenshots, or session captures.
Scoresheets are deterministic and written to standard output. They do not
assign scores or statuses, interpret evidence, or prescribe artifact formats.

The tool does not execute evaluations, bind them to tests, inspect evidence,
interpret annotation hints, or determine whether an implementation actually
conforms.

## Maintenance

A specification that does not change with the user's intent becomes a precise description of the wrong system.

When an interaction introduces, refines, replaces, or contradicts intended behavior:

1. Amend the affected behaviors and evaluations.
2. Validate the specification.
3. Update the implementation and evaluator artifacts.
4. Run the applicable tests and evaluations.
5. Report unresolved manual checks, ambiguities, or failures.

Do not weaken or reinterpret an expectation merely to make an implementation conform. Material changes to intended behavior require explicit approval.

## Coding-agent directive

Repositories adopting the protocol can add the following to `AGENTS.md`, `CLAUDE.md`, or an equivalent instruction file:

```md
## Behavioral specification workflow

This project follows the Behave protocol:

    https://raw.githubusercontent.com/auto-d/behave/main/README.md

The reference command-line tool is available at:

    https://raw.githubusercontent.com/auto-d/behave/main/behave.py

This repository vendors that tool at:

    <path-to-behave>

The authoritative Behave behavioral specification for this project is:

    <path-to-project-specification>

Validate it with:

    python3 <path-to-behave> <path-to-project-specification>

List and inspect requirements with:

    python3 <path-to-behave> --list-requirements <path-to-project-specification>
    python3 <path-to-behave> --show-requirement R-ID <path-to-project-specification>

Treat the specification as the authoritative description of intended external behavior. When user intent introduces, changes, or contradicts behavior, update the specification before considering the related implementation complete.

Every behavior must declare at least one evaluation. After changing the specification, run the validator and resolve all conformance errors. Update the implementation and evaluators, then run the applicable checks.

Do not leave material intent only in conversation, code, tests, issues, or implementation notes. Do not weaken intended behavior to accommodate an existing implementation without explicit user or operator approval.
```

## Project status

This repository is an early protocol and reference tool. Contributions and examples are welcome. A public-use license has not yet been selected.
