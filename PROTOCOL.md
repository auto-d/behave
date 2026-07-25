# Behave Protocol

This document is the authoritative definition of the Behave specification
language. A Behave specification is repository-native Markdown that records
intended external behavior and the criteria by which that behavior can be
judged.

The protocol defines behavior, not implementation. It does not prescribe
architecture, algorithms, tools, programming languages, evidence-collection
mechanisms, or artifact formats.

## Document structure

A specification contains one or more requirements. Introductory prose and
headings may appear outside requirements, but level-three headings are reserved
for requirement declarations.

Each requirement begins with a unique, stable identifier:

```md
### R-UPPERCASE-ID
```

An identifier begins with `R-` and contains only uppercase ASCII letters,
digits, and hyphens. Its first character after `R-` is a letter or digit.

A requirement recognizes four level-four sections:

- `#### Intent`
- `#### Rationale`
- `#### References`
- `#### Behavior`

`Intent` and `Behavior` are required exactly once. `Rationale` and `References`
are optional and may occur at most once. No other level-four section is
permitted within a requirement, and requirement content must belong to a
recognized section. The protocol does not prescribe section order.

## Requirement sections

### Intent

`Intent` states the outcome the requirement exists to secure. It is
authoritative context for interpreting the requirement's behaviors and
evaluation criteria.

### Rationale

`Rationale` may explain why the requirement matters. It supports interpretation
without replacing or weakening the stated intent and behavior.

### References

`References` may identify documents or resources that supply necessary domain,
policy, compatibility, or dependency context. Referenced constraints remain
authoritative where the requirement makes them applicable.

References do not make a specification implementation-prescriptive merely
because they name a technology, contract, policy, or domain term.

### Behavior

`Behavior` contains one or more top-level list items. Each top-level item states
one coherent, externally observable obligation without prescribing how it is
implemented.

Every behavior has one or more immediate child list items beginning with
`Evaluate:`. Together, those Evaluate clauses form the collection of criteria
used to judge whether the behavior was satisfied.

For example:

```md
#### Behavior

- The system reports its state through one or more HTTP endpoints with explanatory text.

  - Evaluate: Each endpoint produces a documented HTTP status code.
  - Evaluate: Health explanations are plain English and consistent with the reported status codes.
```

## Evaluate clauses

An Evaluate clause is one criterion describing what must be true for its parent
behavior to count as satisfied. It provides a workable basis for judging
evidence; it does not prescribe how evidence is collected.

A criterion may require facts, comparisons, thresholds, coverage, observations,
or an observation period. Qualitative criteria are valid. A criterion need not
specify a deterministic test, telemetry source, evidence format, or evaluator
implementation.

An Evaluate clause has this form:

```md
- Evaluate: The response conforms to the published schema.
```

The statement may instead continue in an indented body. It must not be empty.
An Evaluate clause must be an immediate child of a behavior, not a deeper
descendant or a top-level behavior item.

Optional bracket annotations may appear between `Evaluate` and the colon:

```md
- Evaluate [evidence=workspace snapshot, response]: Each material factual claim is supported by the workspace state available when the response was produced.
```

Annotations are opaque, experimental, and non-normative. Tooling accepts their
contents without interpretation. A criterion must remain understandable without
its annotation.

## Evidence

Evidence is downstream of the specification. An implementation is responsible
for producing enough evidence to judge each applicable criterion, but the
protocol does not prescribe how that evidence is produced or packaged.

Evidence may be linked in its implementation-native form, including test
results, measurements, Markdown reports, screenshots, telemetry exports,
session captures, or API responses. A criterion may be supported by any number
of artifacts and by evidence gathered over whatever period its judgment
requires.

The absence of evidence does not demonstrate that a behavior was satisfied.

## Validation and conformance

Structural validation determines whether a Markdown document follows the
language rules in this protocol: requirement syntax and uniqueness, recognized
sections, behavior/evaluation nesting, and nonempty evaluation statements.
Reference availability may be checked separately.

Structural validity is not behavioral conformance. Validation does not execute
evaluations, inspect or interpret evidence, determine applicability, or decide
whether an implementation satisfies a behavior.

Behavioral conformance is judged by applying the requirement's Evaluate clauses
to the available evidence. The protocol defines the criteria; it does not
mandate a particular human, model, or deterministic arbiter.
