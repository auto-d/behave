# Behavior Specification Protocol

A behavior specification is a repository-native Markdown contract describing a system's intended external behavior and how completion will be evaluated.

It keeps governing intent available to humans, coding agents, implementations,and evaluators instead of allowing tests or conversation history to become lossy proxies for the original design.

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

A behavior specification keeps that intent explicit and active throughout the system lifecycle. It serves as:
the design contract between the operator and the implementation;
the governing behavioral reference for coding agents;
the basis for determining whether implementation is complete;
the anchor for deterministic, semantic, hybrid, and manual evaluation; and
a traceable source of intent for downstream tests and evaluation results.

The protocol describes behavior, not implementation. It defines what the system must do and how satisfaction will be determined without prescribing the architecture, algorithms, tools, or programming languages used to achieve it.

A conforming specification remains readable as ordinary repository-native Markdown while providing enough structure for tooling to enumerate behaviors, verify that each has an evaluation path, and associate implementation and evaluation artifacts with the intent they are meant to satisfy.

## Quick start

Clone the repository and validate the included worked example:

```sh
python3 validate.py example.md
python3 -m unittest
```

To adopt the protocol, copy `validate.py` into your repository, create a
behavior specification, and run:

```sh
python3 validate.py path/to/behavior.md
```

The validator uses only the Python standard library.

See [example.md](example.md) for a worked contract covering multiple
requirements, behaviors, and evaluation methods.

## A small, illustrative, and valid specification

```md
### R-EXAMPLE

#### Intent

The system exposes health and status.

#### Behavior

- The system reports its state through one or more HTTP endpoints with explanatory text.

  - Evaluate [deterministic]: Verify that endpoint(s) produce common HTTP status codes.
  - Evaluate [semantic, judge:llm]: Health explanations must be plain English and consistent with reported status codes. 
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

The `Behavior` section expresses each behavior as a top-level bullet. Every behavior must have at least one immediate child `Evaluate:` bullet defining how
its satisfaction can be assessed.

## Evaluations

An evaluation defines one way to determine whether its parent behavior is satisfied. Evidence may come from tests, telemetry, session captures, tool
traces, artifacts, API responses, external observation, or human assessment.

The first annotation identifies the assessment type:

- `deterministic`
- `semantic`
- `hybrid`
- `manual`
- `observational`

Additional annotations are free-form evaluator bindings:

```md
- Evaluate [deterministic, runner=pytest]: Verify the response schema.
- Evaluate [semantic, judge=llm, source=session]: Assess source grounding.
- Evaluate [manual, judge=human]: Review the operational usefulness.
```

Bindings such as `runner`, `judge`, and `source` describe downstream evaluator design. The validator recognizes them as annotations but does not execute or verify the referenced evaluator.

## What the validator checks

Ordinary validation is deterministic and offline:

```sh
python3 validate.py behavior.md
python3 validate.py --json behavior.md
```

It checks requirement IDs, required and duplicate sections, unknown sections, stray requirement content, behavior/evaluation nesting, nonempty evaluation statements, and recognized assessment types.

Retrieve one requirement without reading the full specification:

```sh
python3 validate.py --show-requirement R-RUNTIME-CONFORMANCE behavior.md
python3 validate.py --json --show-requirement R-RUNTIME-CONFORMANCE behavior.md
```

Extraction matches the ID exactly, requires one specification file, and fails
when the requirement is absent or duplicated.

Reference checks are opt-in:

```sh
python3 validate.py --check-references behavior.md
python3 validate.py --check-external-references --timeout 5 behavior.md
```

`--check-references` verifies local paths relative to the specification and fetches HTTP(S) references. `--check-external-references` checks only HTTP(S) references and may require network access.

The validator does not execute evaluations, bind them to tests, inspect evidence, or determine whether an implementation actually conforms.

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

This project follows the Behavior Specification Protocol:

    https://raw.githubusercontent.com/auto-d/behave/main/README.md

The reference validator is available at:

    https://raw.githubusercontent.com/auto-d/behave/main/validate.py

This repository vendors that validator at:

    <path-to-validator>

The authoritative behavioral specification for this project is:

    <path-to-project-specification>

Validate it with:

    python3 <path-to-validator> <path-to-project-specification>

Inspect one requirement at a time with:

    python3 <path-to-validator> --show-requirement R-ID <path-to-project-specification>

Treat the specification as the authoritative description of intended external behavior. When user intent introduces, changes, or contradicts behavior, update the specification before considering the related implementation complete.

Every behavior must declare at least one evaluation. After changing the specification, run the validator and resolve all conformance errors. Update the implementation and evaluators, then run the applicable checks.

Do not leave material intent only in conversation, code, tests, issues, or implementation notes. Do not weaken intended behavior to accommodate an existing implementation without explicit user or operator approval.
```

## Project status

This repository is an early protocol and reference validator. Contributions and examples are welcome. A public-use license has not yet been selected.
