# Behavior Specification Protocol

## Purpose

A behavior specification is the authoritative description of a system’s intended external behavior.

LLM-powered coding agents have substantially reduced the cost and effort required to implement a design. At the same time, their willingness to improvise when intent is left unspecified—and the increasing distance between an engineer and the resulting implementation—make poorly articulated requirements more consequential.

Traditional software requirements mitigate this problem, but they commonly move through a largely linear lifecycle:

```text
requirements
→ derived requirements
→ implementation
→ unit and integration tests
→ system test plan
→ release
```

Although the original requirements may continue to inform development, tests often become a lossy operational proxy for the system’s governing intent. Important intent may remain distributed across design discussions, customer conversations, source code, test suites, and implementation-specific documentation. As the system evolves, the relationship between those artifacts and the original behavioral objective becomes increasingly indirect.

This problem is particularly acute when coding agents are responsible for implementation. A coding agent may produce many materially different but plausible solutions. Some may satisfy narrow tests while violating the broader purpose of the system. The governing behavioral intent must therefore remain directly available throughout implementation, evaluation, and maintenance.

A behavior specification is not merely prose intended to influence an engineer. It is a living, versioned behavioral contract that remains active throughout the system lifecycle. It serves as:

* the primary design contract between the operator and the implementation;
* the governing behavioral reference for coding agents;
* the basis for determining implementation completion;
* the anchor for deterministic, semantic, hybrid, and manual evaluation;
* a traceable source of intent for tests, scenarios, sessions, and evaluation results.

The protocol intentionally describes **behavior**, not implementation. It constrains what the system must do and how satisfaction of that behavior will be determined, without prescribing the architecture, algorithms, tools, or programming languages used to achieve it.

To support both human authorship and automated use, a conforming specification must be readable as ordinary repository-native Markdown while remaining structured enough for tooling to enumerate behavioral expectations, verify that each behavior has an evaluation path, and associate downstream implementation and evaluation artifacts with the intent they are intended to satisfy.

## Design Principles

A behavior specification shall be:

* repository-native;
* human-readable;
* LLM-readable;
* deterministically parseable;
* version controlled;
* implementation neutral;
* evaluation aware.

## Core Model

The protocol defines only two normative concepts.

### Behavior

A behavior is one coherent externally observable expectation.

Behaviors describe what the system must do.

They intentionally avoid prescribing implementation, architecture, algorithms, programming languages, or internal reasoning.

### Evaluation

Every behavior shall define one or more evaluations.

An evaluation describes one method by which satisfaction of the enclosing behavior may be determined.

Evaluations define the system's notion of completion and are often underpinned by evidence. 

Evidence may be produced by

* runtime telemetry
* session capture
* tool traces
* artifacts
* API responses
* external observation
* deterministic tests
* qualitative assessments

The specification doesn't require a formal evidence tag, but free-form definition of the evidence that unlocks objective evaluation is encouraged. 

#### Evaluation Hints (draft)

Our current thinking is that these can be adorned with hints on evaluation method, which include:

* deterministic;
* semantic;
* hybrid;
* manual;
* observational.

## Completion

A behavior without at least one declared evaluation is incomplete.

Such a behavior describes intent but provides no definition of done.

Repositories conforming to this protocol should reject behavioral specifications containing behaviors that cannot be evaluated. The included evaluation script attempts to enforce this on a provided behavior specification instance. 

## Specification Structure

Each requirement receives a stable identifier.

Within each requirement, field names are level-four Markdown headings. A field
heading may appear at most once in a requirement. The specification structure
is:

```text
### R-REQUIREMENT-NAME

#### Intent

#### Rationale

#### References

#### Behavior
    Evaluate
    Evaluate
    ...
```

So conforming requirement has a content hierarchy that looks roughly like this: 
```
R-REQUIREMENT-NAME
│ Intent
│    └── Intent text
│ Rationale
│    └── Rationale text
│ References
│   ├── Reference 1
│   └── Reference 2
├── Behavior 1
│   ├── Evaluate 1
│   ├── Evaluate 2
│   └── Evaluate 3
├── Behavior 2
│   ├── Evaluate 1
│   └── Evaluate 2
└── Behavior 3
    ├── Evaluate 1
    └── Evaluate 2
```

Example:

```md
### R-RUNTIME-CONFORMANCE

#### Intent

The agent shall conform to the runtime contract.

#### Behavior

- The agent exposes runtime health.

  - Evaluate [deterministic]:
    Verify the runtime health endpoint reports the current lifecycle state.

- The agent accepts runtime configuration.

  - Evaluate [deterministic]:
    Verify valid configuration updates are applied.

  - Evaluate [deterministic]:
    Verify invalid configuration updates are rejected.
```

Nested evaluations provide confidence that the enclosing behavior has been satisfied.

The protocol intentionally permits multiple evaluations per behavior and multiple implementations of a single evaluation.

## Evaluation Hints

Evaluations may declare optional annotations describing the intended assessment.

Example:

```text
Evaluate [semantic, judge=llm]

Evaluate [deterministic, runner=pytest]

Evaluate [manual]

Evaluate [hybrid]
```

These annotations constrain evaluator design but do not prescribe implementation.

## Maintenance

Behavior specifications are living documents.

**A specification that does not change with the user’s intent becomes a precise description of the wrong system.**

Design intent commonly emerges through conversation rather than arriving as a complete upfront document. New features, clarified expectations, rejected approaches, and revised priorities may all materially change the behavior the system is expected to exhibit. Those changes must not remain confined to conversation history, implementation notes, source code, or tests.

When an interaction introduces, refines, replaces, or contradicts intended behavior, the behavioral specification must be amended before the related implementation is considered complete. The implementation and its evaluations are then brought into conformance with the revised specification.

The design conversation may therefore serve as an authoring process for the specification:

```text
user intent
→ specification refinement
→ specification validation
→ implementation
→ evaluation
→ further refinement
```

The behavioral specification is the durable output of that conversation. It preserves current intent after the conversational context has disappeared and provides the stable contract against which implementation work can continue.

### Coding-agent directives

The protocol defines the maintenance obligation, but it does not by itself cause a coding agent to follow the required workflow. Repositories adopting the protocol should include project-specific directives in `AGENTS.md`, `CLAUDE.md`, or the equivalent instruction file used by their coding tools.

Those directives should identify:

* the location of the behavioral specification;
* the command used to validate it;
* when the specification must be amended;
* who may approve material changes to intended behavior;
* the validation and evaluation work required before completion may be claimed.

A reusable starting point follows:

```md
## Behavioral specification workflow

This project uses the Behavior Specification Protocol to preserve user intent
and define how implementation completion is determined.

The authoritative behavioral specification is located at:

    <PATH-TO-BEHAVIOR-SPECIFICATION>

Validate it with:

    ~<BEHAVIOR-SPECIFICATION-VALIDATION-COMMAND~>

Treat the behavioral specification as the authoritative description of the
system's currently intended external behavior.

During every user interaction, determine whether the user has introduced,
refined, replaced, or contradicted an intended behavior. When they have, update
the behavioral specification before treating the related implementation work
as complete.

Do not leave material behavioral intent only in conversation history, source
code, tests, issues, or implementation notes.

Every behavioral expectation must contain at least one declared evaluation.
After modifying the specification, run the behavior specification validator and
resolve all reported conformance errors.

When intended behavior changes:

1. Amend the affected behavioral expectations and evaluations.
2. Run the specification validator.
3. Update the implementation and evaluator artifacts.
4. Execute the applicable tests and evaluations.
5. Report unresolved manual evaluations, ambiguities, or failures as an
   explicit completion punch list.

Implementations that introduce material behavior not represented in the
specification are incomplete.

Specifications that declare behavior without an evaluation path are incomplete.

Do not weaken, remove, or reinterpret a behavioral expectation merely to make
an existing implementation conform. Material changes to user intent require
explicit user or operator approval.
```

Repositories may extend these directives with delegation requirements, review procedures, evaluator-binding conventions, and project-specific approval rules. Those additions operationalize the protocol but do not alter its central maintenance requirement: **the specification must remain synchronized with the user’s current intent.**
