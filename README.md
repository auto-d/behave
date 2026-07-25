# Behave

Behave is a repository-native Markdown contract and companion tool for
capturing a system's intended external behavior and the criteria used to judge
it.

It keeps governing intent available to humans, coding agents, implementations,
and evaluators instead of allowing tests or conversation history to become
lossy proxies for the original design.

> **Status:** Early draft. The structure is usable, but the protocol may evolve.

[PROTOCOL.md](PROTOCOL.md) is the authoritative definition of the specification
language. This README is the user guide.

## Why Behave

Coding agents have substantially reduced the cost of implementing a design, but
they have not reduced the need to specify one. When intent is incomplete, an
agent can produce many plausible implementations—including implementations
that satisfy narrow tests while violating the system's broader purpose.

Traditional requirements often become progressively separated from
implementation and evaluation:

requirements → derived requirements → implementation → tests → release

Over time, tests and implementation details can become proxies for the original
design, while important intent remains distributed across conversations, source
code, documentation, and issue history.

A Behave specification keeps that intent explicit and active. It is readable as
ordinary Markdown while giving tools enough structure to enumerate behaviors,
verify that each has an evaluation path, and associate evidence with the intent
it supports.

## Quick start

Clone the repository and validate the included worked example:

```sh
python3 behave.py example.md
python3 -m unittest
```

To adopt Behave, copy `PROTOCOL.md` and `behave.py` into your repository,
create a behavior specification, and run:

```sh
python3 behave.py path/to/behavior.md
```

The command-line tool uses only the Python standard library.

See [example.md](example.md) for a worked contract covering multiple
requirements, behaviors, and evaluation criteria.

The optional LLM critique mode also requires `CRITIQUE_PROMPT.md` beside
`behave.py`.

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

The protocol constrains what the system must do and how satisfaction will be
judged. It does not prescribe architecture, algorithms, tools, programming
languages, or internal reasoning. See [PROTOCOL.md](PROTOCOL.md) for the
complete language rules.

## Behaviors

A behavior is one coherent, externally observable expectation. Behaviors describe what the system must do without prescribing its implementation.

The `Behavior` section expresses each behavior as a top-level bullet. Every behavior must have at least one immediate child `Evaluate:` bullet defining a criterion for judging whether the behavior is satisfied.

## Evaluations

An `Evaluate` clause is one criterion saying what must be true for its behavior
to count as satisfied. Together, the clauses beneath a behavior form its
evaluation checklist.

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

Annotations may help implementations discover likely evidence sources, but
they are non-normative and may evolve. A criterion must remain understandable
without them. The tool accepts annotation contents without interpreting or
restricting them.

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

External references help keep your behavior specifications compact, but can introduce new sources of instability. Local and HTTP reference checks are supported but are opt-in:

```sh
$ python3 behave.py --check-references behavior.md
Behavior specification valid: 1 file(s) checked.
```

`--check-references` verifies local paths relative to the specification and
fetches HTTP(S) references. To check only HTTP(S) references, use
`--check-external-references`; add `--timeout 5` to set a five-second timeout
per request. External checks require network access.

### Generate a scoresheet

Divorcing the behavior specification from implementation allows the analysis of one or more implementations against the stated evaluation criteria. At present, the document that conveys an implementations conformance (or lack of) is the *scoresheet*. To generate a Markdown scoresheet from one valid specification:

```sh
$ python3 behave.py --scoresheet behavior.md > scoresheet.md
```

The generated file is a compact conformance submission table with one row per
evaluation criterion:

```md
| Requirement | Target | Criterion | Evidence hint | Conformance | Evidence | Notes |
|---|---|---|---|---|---|---|
| `R-EXAMPLE` | `B1.E1` | Each endpoint produces a documented HTTP status code. |  | TBD | TBD |  |
```

Fill each row with the implementation's conformance claim and links to
implementation-appropriate artifacts such as test results, measurements,
reports, screenshots, telemetry exports, session captures, or API responses.
For example, a completed row might look like:

```md
| `R-EXAMPLE` | `B1.E1` | Each endpoint produces a documented HTTP status code. |  | pass | [CI run 124](artifacts/ci-124.md) | Covers `/health` and `/ready`. |
```

Scoresheets are deterministic and written to standard output. They preserve
criterion text, opaque annotation contents as evidence hints, and stable
document-order targets such as `B1.E1`; they do not copy supplemental
specification prose, assign scores, inspect evidence, or prescribe artifact
formats.

The tool checks document structure. It does not execute evaluations, bind them
to tests, inspect evidence, interpret annotation hints, or determine whether an
implementation actually conforms.

### Critique evaluability

Behave will attempt to identify weaknesses in your specification's evaluation criteria, provided an API key. 

Request an advisory semantic critique of the Evaluate clauses in one valid
specification:

```sh
$ python3 behave.py --critique behavior.md > critique.md
```

The command uses `OPENAI_API_KEY` from the environment, falling back to
`./.env` in the directory where the command is run. The `.env` file should
contain:

```text
OPENAI_API_KEY=...
```

Critique mode sends the complete local `PROTOCOL.md` and one requirement at a
time to `gpt-5.6-sol` with `high` reasoning by default. It does not retrieve
the contents of documents named in `References`; the requirement and its
references remain authoritative as written.

To critique only one requirement while iterating, pass its exact identifier:

```sh
$ python3 behave.py --critique --critique-requirement R-EXAMPLE behavior.md
```

### Critic tuning
To compare latency, token cost, and diagnostic quality across reasoning levels, override the reasoning effort for a run:

```sh
$ python3 behave.py --critique --critique-requirement R-EXAMPLE --critique-reasoning-effort low behavior.md
```

The accepted effort names are `none`, `minimal`, `low`, `medium`, `high`, and
`xhigh`. Support is model-specific; unsupported values fail through the API
response.

To tune the reasoning effort for a specific requirement, run every supported
effort and score each returned critique with the built-in rubric:

```sh
$ python3 behave.py --critique-reasoning-eval R-EXAMPLE behavior.md
```

To limit cost during tuning, provide a comma-separated effort list:

```sh
$ python3 behave.py --critique-reasoning-eval R-EXAMPLE --critique-reasoning-efforts low,medium behavior.md
```

The output is a Markdown table:

| Effort | Findings | Critique latency | Critique reasoning tokens | Critique total tokens | Score | Score latency | Score total tokens | Note |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `low` | 4 | 7.1s | 366 | 2,843 | 8.0 | 6.4s | 2,410 | Finds the main material gaps with concise wording. |
| `medium` | 4 | 11.7s | 516 | 3,002 | 8.5 | 6.8s | 2,438 | Same coverage as low with slightly sharper precision. |

The table uses a ten-point rubric: material coverage is worth four points,
precision three, diagnostic usefulness two, and contract cleanliness one.
Scores are advisory and depend on the requirement's length, complexity, and
language density. The table reports critique cost separately from rubric-judge
cost so scoring overhead is visible. Each successful critique is scored in a
separate rubric call that sees only the requirement and that critique, not the
effort label, cost metadata, or other effort outputs.

A report with no findings looks like:

```md

# Behave evaluability critique

> Source specification: `behavior.md`
> Model: `gpt-5.6-sol`
> Reasoning effort: `high`
> Total latency: `20.3s`
> API calls: `1`
> Total tokens: input `4,812`, reasoning `1,024`, output `126`, total `5,962`

## R-EXAMPLE

_No material evaluability issues identified._

> API calls: `1`
> Latency: `20.3s`
> Tokens: input `4,812`, reasoning `1,024`, output `126`, total `5,962`
```

A material issue is tied to its behavior or Evaluate clause using document
order:

```md
## R-EXAMPLE

### Finding 1: B1.E2

**Problem:** The criterion cannot distinguish a satisfying explanation from one that conflicts with the reported status.
```

Findings are diagnostic only. The critic does not propose revisions,
replacement wording, thresholds, policies, or evidence-collection methods.
Findings are not intentionally capped; each requirement report should include
all material evaluability issues the model returns. “No material evaluability
issues identified” is advisory and is not a pass/fail declaration.

Each model response is checked against a strict Markdown template. If a request
fails or its response is malformed, the report contains an explicit
`Critique unavailable` section for that requirement, processing continues, and
the command exits nonzero. Invalid specifications or missing critique
configuration fail before a report is written.

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

This project follows the Behave protocol. Its authoritative language
definition is vendored at:

    <path-to-protocol>

The upstream protocol is available at:

    https://raw.githubusercontent.com/auto-d/behave/main/PROTOCOL.md

The reference command-line tool is vendored at:

    <path-to-behave>

The upstream tool is available at:

    https://raw.githubusercontent.com/auto-d/behave/main/behave.py

To use LLM critique, vendor the critic prompt beside the tool:

    <path-containing-behave>/CRITIQUE_PROMPT.md

The upstream critic prompt is available at:

    https://raw.githubusercontent.com/auto-d/behave/main/CRITIQUE_PROMPT.md

The authoritative Behave behavioral specification for this project is:

    <path-to-project-specification>

Validate it with:

    python3 <path-to-behave> <path-to-project-specification>

List and inspect requirements with:

    python3 <path-to-behave> --list-requirements <path-to-project-specification>
    python3 <path-to-behave> --show-requirement R-ID <path-to-project-specification>

Treat the specification as the authoritative description of intended external behavior. When user intent introduces, changes, or contradicts behavior, update the specification before considering the related implementation complete.

Every behavior must declare at least one evaluation. After changing the specification, run the validator and resolve all validation errors. Update the implementation and evaluators, then run the applicable checks.

Do not leave material intent only in conversation, code, tests, issues, or implementation notes. Do not weaken intended behavior to accommodate an existing implementation without explicit user or operator approval.

When updating the vendored Behave protocol or tool, keep them synchronized with
their upstream sources. Keep `CRITIQUE_PROMPT.md` synchronized when critique
mode is used. The protocol is authoritative when explanatory documentation and
the tool disagree.
```

## Project status

This repository is an early protocol and reference tool. Contributions and examples are welcome. A public-use license has not yet been selected.
