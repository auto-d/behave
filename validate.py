#!/usr/bin/env python3
"""
Validate a Markdown behavior specification.

Current protocol rules enforced:

1. The document contains at least one requirement heading:
       ### R-STABLE-IDENTIFIER
2. Requirement identifiers are unique.
3. Each requirement contains exactly one `#### Intent` and `#### Behavior`.
4. Optional `#### Rationale` and `#### References` sections occur at most once.
5. Unknown level-four requirement sections are rejected.
6. Content inside a requirement belongs to a recognized section.
7. A `#### Behavior` section contains at least one behavior bullet.
8. Every behavior bullet contains at least one immediate child `Evaluate` clause.
9. Every `Evaluate` clause contains a non-empty evaluation statement.
10. When an assessment type is supplied, it is recognized.
11. Optionally, targets in `References` sections are fetchable or exist locally.

This intentionally does not validate evaluator bindings, tests, scenarios,
evidence schemas, rubrics, or implementation conformance.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


REQUIREMENT_RE = re.compile(r"^###\s+(R-[A-Z0-9][A-Z0-9-]*)\s*$")
LEVEL_THREE_RE = re.compile(r"^###(?:\s+.*)?$")
SECTION_RE = re.compile(r"^####\s+(Intent|Rationale|References|Behavior)\s*$")
LEVEL_FOUR_RE = re.compile(r"^####(?:\s+(?P<name>.*\S))?\s*$")
SECTION_KEYWORD_RE = re.compile(
    r"^(?:#{1,6}\s+)?(Intent|Rationale|References|Behavior)\s*:?\s*$"
)
LIST_ITEM_RE = re.compile(
    r"^(?P<indent>[ \t]*)[-+*]\s+(?P<text>.*\S|\s*)$"
)
EVALUATE_RE = re.compile(
    r"^Evaluate"
    r"(?:\s*\[(?P<annotations>[^\]]*)\])?"
    r"\s*:\s*(?P<body>.*)$",
    re.IGNORECASE,
)
EXTERNAL_REFERENCE_RE = re.compile(r"""https?://[^\s<>()\[\]`"']+""")
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]*\]\((?P<target>[^)]+)\)")
BACKTICK_REFERENCE_RE = re.compile(r"`(?P<target>[^`]+)`")

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


@dataclass(frozen=True)
class ListContext:
    indent: int
    kind: str
    line: int


@dataclass
class Requirement:
    identifier: str
    line: int
    has_behavior_section: bool = False
    behaviors: int = 0
    sections: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class ExternalReference:
    line: int
    url: str


@dataclass(frozen=True)
class LocalReference:
    line: int
    target: str


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

        if REQUIREMENT_RE.match(raw) or SECTION_RE.match(raw):
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
    current_section: str | None = None
    current_behavior: Behavior | None = None
    behavior_indent: int | None = None
    list_context: list[ListContext] = []

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
        nonlocal current_requirement, current_section, behavior_indent
        close_behavior()
        if current_requirement is not None:
            if "Intent" not in current_requirement.sections:
                diagnostics.append(
                    Diagnostic(
                        str(path),
                        current_requirement.line,
                        "R004",
                        f"{current_requirement.identifier} has no Intent section",
                    )
                )
            if "Behavior" not in current_requirement.sections:
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
        current_section = None
        behavior_indent = None
        list_context.clear()

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
            current_section = None
            continue

        # Level-three headings are reserved for requirements.
        if LEVEL_THREE_RE.match(raw):
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

        section_match = SECTION_RE.match(raw)
        if section_match:
            label = section_match.group(1)
            if current_requirement is not None:
                first_line = current_requirement.sections.get(label)
                if first_line is not None:
                    diagnostics.append(
                        Diagnostic(
                            str(path),
                            line_number,
                            "S002",
                            f"duplicate `{label}` section; first declared on "
                            f"line {first_line}",
                        )
                    )
                else:
                    current_requirement.sections[label] = line_number

            current_section = label if current_requirement is not None else None
            if label == "Behavior":
                close_behavior()
                behavior_indent = None
                list_context.clear()
                if current_requirement is not None:
                    current_requirement.has_behavior_section = True
            else:
                close_behavior()
                behavior_indent = None
                list_context.clear()
            continue

        malformed_section = SECTION_KEYWORD_RE.match(stripped)
        if malformed_section and current_requirement is not None:
            diagnostics.append(
                Diagnostic(
                    str(path),
                    line_number,
                    "S001",
                    f"requirement section `{malformed_section.group(1)}` must use "
                    f"a level-four heading",
                )
            )
            close_behavior()
            current_section = "__invalid__"
            behavior_indent = None
            list_context.clear()
            continue

        level_four = LEVEL_FOUR_RE.match(raw)
        if level_four and current_requirement is not None:
            name = level_four.group("name") or ""
            diagnostics.append(
                Diagnostic(
                    str(path),
                    line_number,
                    "S003",
                    f"unknown requirement section `{name}`",
                )
            )
            close_behavior()
            current_section = "__unknown__"
            behavior_indent = None
            list_context.clear()
            continue

        if current_requirement is not None and current_section is None:
            if stripped:
                diagnostics.append(
                    Diagnostic(
                        str(path),
                        line_number,
                        "P001",
                        "content inside a requirement must belong to a recognized section",
                    )
                )
            continue

        if current_section != "Behavior" or current_requirement is None:
            continue

        item = LIST_ITEM_RE.match(raw)
        if not item:
            continue

        indent = indentation_width(item.group("indent"))
        item_text = item.group("text").strip()
        evaluate_match = EVALUATE_RE.match(item_text)

        # The first list item establishes the behavior-list indentation.
        if behavior_indent is None:
            behavior_indent = indent

        if behavior_indent is not None and indent == behavior_indent:
            close_behavior()
            list_context.clear()

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
            list_context.append(
                ListContext(indent, "behavior", line_number)
            )
            continue

        while list_context and list_context[-1].indent >= indent:
            list_context.pop()
        parent = list_context[-1] if list_context else None

        if evaluate_match:
            if (
                current_behavior is None
                or parent is None
                or parent.kind != "behavior"
                or parent.line != current_behavior.line
            ):
                diagnostics.append(
                    Diagnostic(
                        str(path),
                        line_number,
                        "E001",
                        "Evaluate clause must be an immediate child of a behavior",
                    )
                )
                list_context.append(
                    ListContext(indent, "evaluate", line_number)
                )
                continue

            current_behavior.evaluations += 1
            list_context.append(
                ListContext(indent, "evaluate", line_number)
            )

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
        else:
            list_context.append(ListContext(indent, "other", line_number))

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


def reference_lines(text: str) -> list[tuple[int, str]]:
    """Return list-item contents declared in References sections."""
    lines: list[tuple[int, str]] = []
    in_references = False

    for index, raw in enumerate(text.splitlines()):
        stripped = raw.strip()

        if REQUIREMENT_RE.match(raw):
            in_references = False
            continue

        level_four = LEVEL_FOUR_RE.match(raw)
        if level_four:
            section_match = SECTION_RE.match(raw)
            in_references = bool(
                section_match and section_match.group(1) == "References"
            )
            continue

        if in_references:
            item = LIST_ITEM_RE.match(raw)
            if item:
                lines.append((index + 1, item.group("text").strip()))

    return lines


def external_references(text: str) -> list[ExternalReference]:
    """Return HTTP(S) URLs declared in References sections."""
    references: list[ExternalReference] = []
    for line, item_text in reference_lines(text):
        references.extend(
            ExternalReference(line, match.group(0))
            for match in EXTERNAL_REFERENCE_RE.finditer(item_text)
        )

    return references


def local_references(text: str) -> list[LocalReference]:
    """Return filesystem targets declared in References sections."""
    references: list[LocalReference] = []

    for line, item_text in reference_lines(text):
        markdown_link = MARKDOWN_LINK_RE.fullmatch(item_text)
        backtick = BACKTICK_REFERENCE_RE.fullmatch(item_text)

        if markdown_link:
            target = markdown_link.group("target").strip()
        elif backtick:
            target = backtick.group("target").strip()
        elif not any(char.isspace() for char in item_text):
            target = item_text
        else:
            continue

        if target and not target.lower().startswith(("http://", "https://")):
            references.append(LocalReference(line, target))

    return references


def validate_local_references(path: Path, text: str) -> list[Diagnostic]:
    """Verify that local References targets exist on the filesystem."""
    diagnostics: list[Diagnostic] = []

    for reference in local_references(text):
        target_without_fragment = reference.target.split("#", 1)[0]
        target = Path(target_without_fragment)
        resolved = (
            target
            if target.is_absolute()
            else path.parent.resolve() / target
        )

        if not resolved.exists():
            diagnostics.append(
                Diagnostic(
                    str(path),
                    reference.line,
                    "REF002",
                    f"local reference does not exist: {reference.target} "
                    f"(resolved to {resolved})",
                )
            )

    return diagnostics


def validate_external_references(
    path: Path,
    text: str,
    timeout: float,
) -> list[Diagnostic]:
    """Verify that external References URLs can be retrieved."""
    diagnostics: list[Diagnostic] = []
    results: dict[str, str | None] = {}

    for reference in external_references(text):
        if reference.url not in results:
            request = Request(
                reference.url,
                headers={
                    "User-Agent": "behavior-specification-validator/1",
                    "Range": "bytes=0-0",
                },
            )
            try:
                with urlopen(request, timeout=timeout):
                    results[reference.url] = None
            except (HTTPError, URLError, TimeoutError, OSError) as exc:
                results[reference.url] = str(exc)

        error = results[reference.url]
        if error is not None:
            diagnostics.append(
                Diagnostic(
                    str(path),
                    reference.line,
                    "REF001",
                    f"external reference is not fetchable: {reference.url} ({error})",
                )
            )

    return diagnostics


def positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


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
    parser.add_argument(
        "--check-external-references",
        action="store_true",
        help="fetch HTTP(S) URLs in References sections and report failures",
    )
    parser.add_argument(
        "--check-references",
        action="store_true",
        help="check both filesystem and HTTP(S) targets in References sections",
    )
    parser.add_argument(
        "--timeout",
        type=positive_float,
        default=10.0,
        help="network timeout in seconds for each external reference (default: 10)",
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
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            diagnostics.append(
                Diagnostic(
                    str(path),
                    1,
                    "IO001",
                    f"could not read file: {exc}",
                )
            )
            continue

        diagnostics.extend(validate_text(path, text))
        if args.check_references:
            diagnostics.extend(validate_local_references(path, text))
        if args.check_external_references or args.check_references:
            diagnostics.extend(
                validate_external_references(path, text, args.timeout)
            )

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
