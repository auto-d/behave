#!/usr/bin/env python3
"""
Validate a Markdown behavior specification.

Current protocol rules enforced:

1. The document contains at least one requirement heading:
       ### R-STABLE-IDENTIFIER
2. Requirement identifiers are unique.
3. Each requirement contains a `Behavior` section.
4. A `Behavior` section contains at least one behavior bullet.
5. Every behavior bullet contains at least one nested `Evaluate` clause.
6. Every `Evaluate` clause contains a non-empty evaluation statement.
7. When an assessment type is supplied, it is recognized.

This intentionally does not validate evaluator bindings, tests, scenarios,
evidence schemas, rubrics, or implementation conformance.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence


REQUIREMENT_RE = re.compile(r"^###\s+(R-[A-Z0-9][A-Z0-9-]*)\s*$")
LABEL_RE = re.compile(r"^(Intent|Rationale|References|Behavior)\s*:?\s*$")
LIST_ITEM_RE = re.compile(r"^(?P<indent>[ \t]*)-\s+(?P<text>.*\S|\s*)$")
EVALUATE_RE = re.compile(
    r"^Evaluate"
    r"(?:\s*\[(?P<annotations>[^\]]*)\])?"
    r"\s*:\s*(?P<body>.*)$",
    re.IGNORECASE,
)

ALLOWED_ASSESSMENT_TYPES = {
    "deterministic",
    "semantic",
    "hybrid",
    "manual",
    "observational",
}


@dataclass(frozen=True)
class Diagnostic:
    path: str
    line: int
    code: str
    message: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.code}: {self.message}"


@dataclass
class Behavior:
    line: int
    indent: int
    text: str
    evaluations: int = 0


@dataclass
class Requirement:
    identifier: str
    line: int
    has_behavior_section: bool = False
    behaviors: int = 0


def indentation_width(value: str) -> int:
    """Treat a tab as four spaces for structural comparison."""
    return sum(4 if char == "\t" else 1 for char in value)


def first_annotation_token(raw: str) -> str | None:
    if not raw.strip():
        return None
    first = raw.split(",", 1)[0].strip()
    return first if "=" not in first else None


def has_indented_body(
    lines: Sequence[str],
    start_index: int,
    evaluate_indent: int,
) -> bool:
    """
    Return True when a following indented, non-empty line belongs to an
    Evaluate clause before the next peer-or-parent list item or section.
    """
    for raw in lines[start_index + 1 :]:
        stripped = raw.strip()

        if not stripped:
            continue

        if REQUIREMENT_RE.match(raw) or LABEL_RE.match(stripped):
            return False

        item = LIST_ITEM_RE.match(raw)
        if item:
            indent = indentation_width(item.group("indent"))
            if indent <= evaluate_indent:
                return False
            return bool(item.group("text").strip())

        leading = raw[: len(raw) - len(raw.lstrip(" \t"))]
        indent = indentation_width(leading)
        if indent > evaluate_indent:
            return True

        return False

    return False


def validate_text(path: Path, text: str) -> list[Diagnostic]:
    lines = text.splitlines()
    diagnostics: list[Diagnostic] = []

    requirements: list[Requirement] = []
    requirement_ids: dict[str, int] = {}

    current_requirement: Requirement | None = None
    in_behavior_section = False
    current_behavior: Behavior | None = None
    behavior_indent: int | None = None

    def close_behavior() -> None:
        nonlocal current_behavior
        if current_behavior is None:
            return
        if current_behavior.evaluations == 0:
            diagnostics.append(
                Diagnostic(
                    str(path),
                    current_behavior.line,
                    "B003",
                    "behavior has no nested Evaluate clause",
                )
            )
        current_behavior = None

    def close_requirement() -> None:
        nonlocal current_requirement, in_behavior_section, behavior_indent
        close_behavior()
        if current_requirement is not None:
            if not current_requirement.has_behavior_section:
                diagnostics.append(
                    Diagnostic(
                        str(path),
                        current_requirement.line,
                        "R003",
                        f"{current_requirement.identifier} has no Behavior section",
                    )
                )
            elif current_requirement.behaviors == 0:
                diagnostics.append(
                    Diagnostic(
                        str(path),
                        current_requirement.line,
                        "B001",
                        f"{current_requirement.identifier} has an empty Behavior section",
                    )
                )
        current_requirement = None
        in_behavior_section = False
        behavior_indent = None

    for index, raw in enumerate(lines):
        line_number = index + 1
        stripped = raw.strip()

        requirement_match = REQUIREMENT_RE.match(raw)
        if requirement_match:
            close_requirement()

            identifier = requirement_match.group(1)
            if identifier in requirement_ids:
                diagnostics.append(
                    Diagnostic(
                        str(path),
                        line_number,
                        "R002",
                        f"duplicate requirement identifier {identifier}; "
                        f"first declared on line {requirement_ids[identifier]}",
                    )
                )
            else:
                requirement_ids[identifier] = line_number

            current_requirement = Requirement(identifier, line_number)
            requirements.append(current_requirement)
            continue

        # Catch malformed requirement-like headings explicitly.
        if raw.startswith("### ") and stripped.startswith("### R-"):
            diagnostics.append(
                Diagnostic(
                    str(path),
                    line_number,
                    "R001",
                    "malformed requirement heading; expected `### R-UPPERCASE-ID`",
                )
            )
            close_requirement()
            continue

        label_match = LABEL_RE.match(stripped)
        if label_match:
            label = label_match.group(1)
            if label == "Behavior":
                close_behavior()
                in_behavior_section = current_requirement is not None
                behavior_indent = None
                if current_requirement is not None:
                    current_requirement.has_behavior_section = True
            elif in_behavior_section:
                close_behavior()
                in_behavior_section = False
                behavior_indent = None
            continue

        if not in_behavior_section or current_requirement is None:
            continue

        item = LIST_ITEM_RE.match(raw)
        if not item:
            continue

        indent = indentation_width(item.group("indent"))
        item_text = item.group("text").strip()
        evaluate_match = EVALUATE_RE.match(item_text)

        # The first ordinary bullet establishes the behavior-list indentation.
        if behavior_indent is None and not evaluate_match:
            behavior_indent = indent

        if behavior_indent is not None and indent == behavior_indent:
            close_behavior()

            if evaluate_match:
                diagnostics.append(
                    Diagnostic(
                        str(path),
                        line_number,
                        "E001",
                        "Evaluate clause is not nested beneath a behavior",
                    )
                )
                continue

            if not item_text:
                diagnostics.append(
                    Diagnostic(
                        str(path),
                        line_number,
                        "B002",
                        "behavior bullet is empty",
                    )
                )

            current_behavior = Behavior(line_number, indent, item_text)
            current_requirement.behaviors += 1
            continue

        if evaluate_match:
            if current_behavior is None:
                diagnostics.append(
                    Diagnostic(
                        str(path),
                        line_number,
                        "E001",
                        "Evaluate clause is not nested beneath a behavior",
                    )
                )
                continue

            if indent <= current_behavior.indent:
                diagnostics.append(
                    Diagnostic(
                        str(path),
                        line_number,
                        "E001",
                        "Evaluate clause must be indented beneath its behavior",
                    )
                )
                continue

            current_behavior.evaluations += 1

            annotations = evaluate_match.group("annotations") or ""
            assessment_type = first_annotation_token(annotations)
            if assessment_type and assessment_type.lower() not in ALLOWED_ASSESSMENT_TYPES:
                allowed = ", ".join(sorted(ALLOWED_ASSESSMENT_TYPES))
                diagnostics.append(
                    Diagnostic(
                        str(path),
                        line_number,
                        "E003",
                        f"unknown assessment type `{assessment_type}`; expected one of: {allowed}",
                    )
                )

            inline_body = evaluate_match.group("body").strip()
            if not inline_body and not has_indented_body(lines, index, indent):
                diagnostics.append(
                    Diagnostic(
                        str(path),
                        line_number,
                        "E002",
                        "Evaluate clause has no evaluation statement",
                    )
                )

    close_requirement()

    if not requirements:
        diagnostics.append(
            Diagnostic(
                str(path),
                1,
                "R000",
                "document contains no valid requirement headings",
            )
        )

    return diagnostics


def validate_file(path: Path) -> list[Diagnostic]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [
            Diagnostic(
                str(path),
                1,
                "IO001",
                f"could not read file: {exc}",
            )
        ]
    return validate_text(path, text)


def iter_markdown_files(inputs: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    for path in inputs:
        if path.is_dir():
            files.extend(sorted(path.rglob("*.md")))
        else:
            files.append(path)
    return files


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate behavior specification Markdown files."
    )
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="Markdown files or directories to validate",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit diagnostics as JSON",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    files = iter_markdown_files(args.paths)

    if not files:
        print("No Markdown files found.", file=sys.stderr)
        return 2

    diagnostics: list[Diagnostic] = []
    for path in files:
        diagnostics.extend(validate_file(path))

    if args.json:
        print(json.dumps([asdict(item) for item in diagnostics], indent=2))
    elif diagnostics:
        for item in diagnostics:
            print(item.render(), file=sys.stderr)
        print(
            f"\nValidation failed: {len(diagnostics)} issue(s) "
            f"across {len(files)} file(s).",
            file=sys.stderr,
        )
    else:
        print(f"Behavior specification valid: {len(files)} file(s) checked.")

    return 1 if diagnostics else 0


if __name__ == "__main__":
    raise SystemExit(main())