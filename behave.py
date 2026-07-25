#!/usr/bin/env python3
"""
Work with Behave Markdown specifications.

PROTOCOL.md is the authoritative definition of the Behave specification
language. This tool implements its structural validation rules and optional
reference checks; it does not determine behavioral conformance.

The tool can also derive a Markdown scoresheet that preserves a specification
and adds an evidence-links area beneath each evaluation criterion, or request
an advisory LLM critique of criteria evaluability.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


REQUIREMENT_RE = re.compile(r"^###\s+(R-[A-Z0-9][A-Z0-9-]*)\s*$")
REQUIREMENT_ID_RE = re.compile(r"^R-[A-Z0-9][A-Z0-9-]*$")
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
CRITIQUE_FINDING_RE = re.compile(
    r"^### Finding (?P<number>[1-9][0-9]*): "
    r"(?P<target>B[1-9][0-9]*(?:\.E[1-9][0-9]*)?)$"
)
CRITIQUE_PROBLEM_RE = re.compile(
    r"^\*\*Problem:\*\* (?P<problem>\S(?:.*\S)?)$"
)
RECOMMENDATION_RE = re.compile(
    r"^(?:add|revise|rewrite|clarify|change|replace|remove|define|specify|"
    r"include|require)\b|\b(?:should|ought to|needs to|recommend(?:s|ed)?)\b",
    re.IGNORECASE,
)
RUBRIC_SCORE_RE = re.compile(
    r"^Score: (?P<score>(?:10(?:\.0)?|[0-9](?:\.[0-9])?))\n"
    r"Note: (?P<note>\S(?:.*\S)?)$"
)

TOOL_DIRECTORY = Path(__file__).resolve().parent
PROTOCOL_PATH = TOOL_DIRECTORY / "PROTOCOL.md"
CRITIQUE_PROMPT_PATH = TOOL_DIRECTORY / "CRITIQUE_PROMPT.md"
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
CRITIQUE_MODEL = "gpt-5.6-sol"
CRITIQUE_REASONING_EFFORT = "high"
CRITIQUE_REASONING_EFFORTS = (
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
)
CRITIQUE_TIMEOUT = 120.0
CRITIQUE_MAX_OUTPUT_TOKENS = 8192
RUBRIC_MODEL = CRITIQUE_MODEL
RUBRIC_REASONING_EFFORT = "low"
RUBRIC_MAX_OUTPUT_TOKENS = 512
NO_FINDINGS_TEXT = "_No material evaluability issues identified._"
UNUSABLE_RESPONSE_TEXT = (
    "_Critique unavailable because the model did not return a usable response._"
)
MALFORMED_RESPONSE_TEXT = (
    "_Critique unavailable because the model response did not conform to the "
    "required Markdown template._"
)

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


@dataclass(frozen=True)
class RequirementExcerpt:
    identifier: str
    path: str
    line: int
    markdown: str


@dataclass(frozen=True)
class RequirementSummary:
    identifier: str
    path: str
    line: int


@dataclass(frozen=True)
class ScoresheetCriterion:
    requirement_id: str
    target: str
    line: int
    statement: str
    annotations: str | None = None


@dataclass(frozen=True)
class CritiqueUsage:
    input_tokens: int | None = None
    reasoning_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True)
class CritiqueResult:
    text: str
    latency_seconds: float
    usage: CritiqueUsage


@dataclass(frozen=True)
class RubricScore:
    score: float
    note: str
    latency_seconds: float
    usage: CritiqueUsage


@dataclass(frozen=True)
class ReasoningEvaluation:
    effort: str
    findings: int
    critique_latency_seconds: float | None
    critique_usage: CritiqueUsage
    score: float
    note: str
    score_latency_seconds: float | None
    score_usage: CritiqueUsage
    error: str | None = None


class CritiqueError(Exception):
    """Raised when a critique request cannot produce usable model text."""


def indentation_width(value: str) -> int:
    """Treat a tab as four spaces for structural comparison."""
    return sum(4 if char == "\t" else 1 for char in value)


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


def requirement_excerpts(
    path: Path,
    text: str,
    identifier: str,
) -> list[RequirementExcerpt]:
    """Return exact requirement blocks matching an identifier."""
    lines = text.splitlines()
    matches: list[RequirementExcerpt] = []

    for index, raw in enumerate(lines):
        match = REQUIREMENT_RE.match(raw)
        if not match or match.group(1) != identifier:
            continue

        end_index = len(lines)
        for candidate in range(index + 1, len(lines)):
            if LEVEL_THREE_RE.match(lines[candidate]):
                end_index = candidate
                break

        markdown = "\n".join(lines[index:end_index]).rstrip() + "\n"
        matches.append(
            RequirementExcerpt(
                identifier=identifier,
                path=str(path),
                line=index + 1,
                markdown=markdown,
            )
        )

    return matches


def requirement_summaries(
    path: Path,
    text: str,
) -> list[RequirementSummary]:
    """Return valid requirement headings in document order."""
    summaries: list[RequirementSummary] = []
    for index, raw in enumerate(text.splitlines()):
        match = REQUIREMENT_RE.match(raw)
        if match:
            summaries.append(
                RequirementSummary(
                    identifier=match.group(1),
                    path=str(path),
                    line=index + 1,
                )
            )
    return summaries


def critique_targets(requirement_markdown: str) -> set[str]:
    """Return behavior and Evaluate document-order targets for a requirement."""
    targets: set[str] = set()
    current_section: str | None = None
    behavior_indent: int | None = None
    behavior_number = 0
    evaluation_number = 0

    for raw in requirement_markdown.splitlines():
        section_match = SECTION_RE.match(raw)
        if section_match:
            current_section = section_match.group(1)
            behavior_indent = None
            continue

        if current_section != "Behavior":
            continue

        item = LIST_ITEM_RE.match(raw)
        if not item:
            continue

        indent = indentation_width(item.group("indent"))
        item_text = item.group("text").strip()

        if behavior_indent is None:
            behavior_indent = indent

        if indent == behavior_indent:
            behavior_number += 1
            evaluation_number = 0
            targets.add(f"B{behavior_number}")
        elif EVALUATE_RE.match(item_text):
            evaluation_number += 1
            targets.add(f"B{behavior_number}.E{evaluation_number}")

    return targets


def validate_critique_fragment(
    identifier: str,
    fragment: str,
    targets: set[str],
) -> str:
    """
    Return normalized model Markdown or raise ValueError when it does not match
    the critique output contract.
    """
    normalized = fragment.replace("\r\n", "\n").replace("\r", "\n").strip()
    lines = normalized.split("\n")
    expected_heading = f"## {identifier}"

    if len(lines) < 3 or lines[0] != expected_heading or lines[1] != "":
        raise ValueError("response must begin with the exact requirement heading")

    if lines[2] == NO_FINDINGS_TEXT:
        if len(lines) != 3:
            raise ValueError("no-findings response contains additional content")
        return normalized

    finding_number = 1
    index = 2

    while index < len(lines):
        heading_match = CRITIQUE_FINDING_RE.fullmatch(lines[index])
        if not heading_match:
            raise ValueError("finding heading is malformed")

        actual_number = int(heading_match.group("number"))
        if actual_number != finding_number:
            raise ValueError("finding numbers must be sequential")

        target = heading_match.group("target")
        if target not in targets:
            raise ValueError(f"finding target does not exist: {target}")

        if index + 2 >= len(lines) or lines[index + 1] != "":
            raise ValueError("finding must contain one Problem field")

        problem_match = CRITIQUE_PROBLEM_RE.fullmatch(lines[index + 2])
        if not problem_match:
            raise ValueError("Problem field is malformed")

        problem = problem_match.group("problem")
        if len(problem) > 240:
            raise ValueError("Problem field exceeds 240 characters")
        if RECOMMENDATION_RE.search(problem):
            raise ValueError("Problem field contains recommendation language")

        index += 3
        finding_number += 1
        if index < len(lines):
            if lines[index] != "":
                raise ValueError("findings must be separated by one blank line")
            index += 1

    return normalized


def load_openai_api_key(
    environment: dict[str, str] | None = None,
    dotenv_path: Path | None = None,
) -> str | None:
    """Resolve OPENAI_API_KEY from the environment, then a local .env file."""
    values = os.environ if environment is None else environment
    environment_value = values.get("OPENAI_API_KEY", "").strip()
    if environment_value:
        return environment_value

    path = Path(".env") if dotenv_path is None else dotenv_path
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return None

    for raw in lines:
        line = raw.strip()
        if line.startswith("export "):
            line = line[7:].lstrip()
        if not line.startswith("OPENAI_API_KEY="):
            continue

        value = line.split("=", 1)[1].strip()
        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in {'"', "'"}
        ):
            value = value[1:-1]
        return value or None

    return None


def critique_instructions(prompt: str, protocol: str) -> str:
    """Combine the fixed critic prompt with the verbatim Behave protocol."""
    return (
        f"{prompt}\n"
        "<behave_protocol>\n"
        f"{protocol}"
        "</behave_protocol>"
    )


def rubric_instructions(protocol: str) -> str:
    return (
        "Score one Behave evaluability critique for diagnostic value.\n\n"
        "The Behave protocol, requirement, and critique are authoritative "
        "inputs for scoring. The critique is diagnostic only; do not propose "
        "revisions or replacement wording.\n\n"
        "Rubric, 10 points total:\n"
        "- Material coverage, 4 points: important evaluability gaps are found.\n"
        "- Precision, 3 points: findings are tied to real behavior/evaluate "
        "mismatches without weak false positives.\n"
        "- Diagnostic usefulness, 2 points: findings identify the kind of gap "
        "a maintainer must consider without prescribing fixes.\n"
        "- Contract cleanliness, 1 point: the critique follows the output "
        "contract and avoids extra prose or recommendation language.\n\n"
        "Return exactly two lines:\n"
        "Score: N.N\n"
        "Note: One concise sentence explaining the score.\n\n"
        "<behave_protocol>\n"
        f"{protocol}"
        "</behave_protocol>"
    )


def integer_value(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def critique_usage(response_payload: dict[str, object]) -> CritiqueUsage:
    """Extract token usage from a Responses API payload when available."""
    usage = response_payload.get("usage")
    if not isinstance(usage, dict):
        return CritiqueUsage()

    input_tokens = integer_value(usage.get("input_tokens"))
    output_tokens = integer_value(usage.get("output_tokens"))
    total_tokens = integer_value(usage.get("total_tokens"))
    reasoning_tokens = integer_value(usage.get("reasoning_tokens"))

    output_details = usage.get("output_tokens_details")
    if reasoning_tokens is None and isinstance(output_details, dict):
        reasoning_tokens = integer_value(output_details.get("reasoning_tokens"))

    return CritiqueUsage(
        input_tokens=input_tokens,
        reasoning_tokens=reasoning_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )


def format_seconds(value: float) -> str:
    return f"{value:.1f}s"


def format_count(value: int | None) -> str:
    return f"{value:,}" if value is not None else "unknown"


def markdown_table_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def usage_summary(usage: CritiqueUsage) -> str:
    return (
        f"input `{format_count(usage.input_tokens)}`, "
        f"reasoning `{format_count(usage.reasoning_tokens)}`, "
        f"output `{format_count(usage.output_tokens)}`, "
        f"total `{format_count(usage.total_tokens)}`"
    )


def add_usage(left: CritiqueUsage, right: CritiqueUsage) -> CritiqueUsage:
    def combine(first: int | None, second: int | None) -> int | None:
        if first is None and second is None:
            return None
        return (first or 0) + (second or 0)

    return CritiqueUsage(
        input_tokens=combine(left.input_tokens, right.input_tokens),
        reasoning_tokens=combine(left.reasoning_tokens, right.reasoning_tokens),
        output_tokens=combine(left.output_tokens, right.output_tokens),
        total_tokens=combine(left.total_tokens, right.total_tokens),
    )


def request_critique(
    api_key: str,
    instructions: str,
    requirement: RequirementExcerpt,
    reasoning_effort: str = CRITIQUE_REASONING_EFFORT,
    timeout: float = CRITIQUE_TIMEOUT,
) -> CritiqueResult:
    """Request one requirement critique through the OpenAI Responses API."""
    input_payload = json.dumps(
        {
            "requirement_id": requirement.identifier,
            "requirement_markdown": requirement.markdown,
        },
        ensure_ascii=False,
    )
    request_payload = {
        "model": CRITIQUE_MODEL,
        "instructions": instructions,
        "input": input_payload,
        "reasoning": {"effort": reasoning_effort},
        "text": {"verbosity": "low"},
        "store": False,
        "max_output_tokens": CRITIQUE_MAX_OUTPUT_TOKENS,
    }
    request = Request(
        OPENAI_RESPONSES_URL,
        data=json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "behave-critique/1",
        },
        method="POST",
    )

    try:
        started = time.monotonic()
        with urlopen(request, timeout=timeout) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
        latency_seconds = time.monotonic() - started
    except HTTPError as exc:
        raise CritiqueError(f"OpenAI API returned HTTP {exc.code}") from exc
    except URLError as exc:
        raise CritiqueError(f"OpenAI API request failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise CritiqueError("OpenAI API request timed out") from exc
    except OSError as exc:
        raise CritiqueError(f"OpenAI API request failed: {exc}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CritiqueError("OpenAI API returned malformed JSON") from exc

    if not isinstance(response_payload, dict):
        raise CritiqueError("OpenAI API returned an unexpected response")
    if response_payload.get("status") != "completed":
        raise CritiqueError("OpenAI API response was not completed")

    output_text: list[str] = []
    output = response_payload.get("output")
    if not isinstance(output, list):
        raise CritiqueError("OpenAI API response contained no output")

    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if (
                isinstance(part, dict)
                and part.get("type") == "output_text"
                and isinstance(part.get("text"), str)
            ):
                output_text.append(part["text"])

    combined = "".join(output_text)
    if not combined.strip():
        raise CritiqueError("OpenAI API response contained no output text")
    return CritiqueResult(
        text=combined,
        latency_seconds=latency_seconds,
        usage=critique_usage(response_payload),
    )


def response_output_text(response_payload: dict[str, object]) -> str:
    output_text: list[str] = []
    output = response_payload.get("output")
    if not isinstance(output, list):
        raise CritiqueError("OpenAI API response contained no output")

    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if (
                isinstance(part, dict)
                and part.get("type") == "output_text"
                and isinstance(part.get("text"), str)
            ):
                output_text.append(part["text"])

    combined = "".join(output_text)
    if not combined.strip():
        raise CritiqueError("OpenAI API response contained no output text")
    return combined


def request_rubric_score(
    api_key: str,
    instructions: str,
    requirement: RequirementExcerpt,
    critique_fragment: str,
    timeout: float = CRITIQUE_TIMEOUT,
) -> RubricScore:
    """Score one accepted critique fragment using the rubric."""
    input_payload = json.dumps(
        {
            "requirement_id": requirement.identifier,
            "requirement_markdown": requirement.markdown,
            "critique_markdown": critique_fragment,
        },
        ensure_ascii=False,
    )
    request_payload = {
        "model": RUBRIC_MODEL,
        "instructions": instructions,
        "input": input_payload,
        "reasoning": {"effort": RUBRIC_REASONING_EFFORT},
        "text": {"verbosity": "low"},
        "store": False,
        "max_output_tokens": RUBRIC_MAX_OUTPUT_TOKENS,
    }
    request = Request(
        OPENAI_RESPONSES_URL,
        data=json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "behave-rubric/1",
        },
        method="POST",
    )

    try:
        started = time.monotonic()
        with urlopen(request, timeout=timeout) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
        latency_seconds = time.monotonic() - started
    except HTTPError as exc:
        raise CritiqueError(f"OpenAI API returned HTTP {exc.code}") from exc
    except URLError as exc:
        raise CritiqueError(f"OpenAI API request failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise CritiqueError("OpenAI API request timed out") from exc
    except OSError as exc:
        raise CritiqueError(f"OpenAI API request failed: {exc}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CritiqueError("OpenAI API returned malformed JSON") from exc

    if not isinstance(response_payload, dict):
        raise CritiqueError("OpenAI API returned an unexpected response")
    if response_payload.get("status") != "completed":
        raise CritiqueError("OpenAI API response was not completed")

    score_text = response_output_text(response_payload).strip()
    match = RUBRIC_SCORE_RE.fullmatch(score_text)
    if not match:
        raise CritiqueError("rubric score response was malformed")

    return RubricScore(
        score=float(match.group("score")),
        note=match.group("note"),
        latency_seconds=latency_seconds,
        usage=critique_usage(response_payload),
    )


def unavailable_critique_fragment(identifier: str, message: str) -> str:
    return f"## {identifier}\n\n{message}"


def generate_critique_report(
    path: Path,
    text: str,
    prompt: str,
    protocol: str,
    api_key: str,
    requirement_id: str | None = None,
    reasoning_effort: str = CRITIQUE_REASONING_EFFORT,
) -> tuple[str, list[str]]:
    """Generate a report and return any per-requirement failure diagnostics."""
    instructions = critique_instructions(prompt, protocol)
    summaries = requirement_summaries(path, text)
    if requirement_id is not None:
        summaries = [
            summary
            for summary in summaries
            if summary.identifier == requirement_id
        ]
    fragments: list[str] = []
    failures: list[str] = []
    api_calls = 0
    total_latency = 0.0
    total_usage = CritiqueUsage()

    for summary in summaries:
        requirement = requirement_excerpts(
            path,
            text,
            summary.identifier,
        )[0]
        try:
            result = request_critique(
                api_key,
                instructions,
                requirement,
                reasoning_effort,
            )
        except CritiqueError as exc:
            failures.append(f"{summary.identifier}: {exc}")
            fragments.append(
                unavailable_critique_fragment(
                    summary.identifier,
                    UNUSABLE_RESPONSE_TEXT,
                )
            )
            continue

        api_calls += 1
        total_latency += result.latency_seconds
        total_usage = add_usage(total_usage, result.usage)

        try:
            accepted_fragment = validate_critique_fragment(
                summary.identifier,
                result.text,
                critique_targets(requirement.markdown),
            )
        except ValueError as exc:
            failures.append(
                f"{summary.identifier}: model response was malformed: {exc}"
            )
            fragment_metadata = (
                f"> API calls: `1`\n"
                f"> Latency: `{format_seconds(result.latency_seconds)}`\n"
                f"> Tokens: {usage_summary(result.usage)}"
            )
            fragments.append(
                unavailable_critique_fragment(
                    summary.identifier,
                    MALFORMED_RESPONSE_TEXT,
                )
                + "\n\n"
                + fragment_metadata
            )
            continue

        fragment_metadata = (
            f"> API calls: `1`\n"
            f"> Latency: `{format_seconds(result.latency_seconds)}`\n"
            f"> Tokens: {usage_summary(result.usage)}"
        )
        fragments.append(accepted_fragment + "\n\n" + fragment_metadata)

    escaped_path = str(path).replace("`", "\\`")
    header = "\n".join(
        [
            "# Behave evaluability critique",
            "",
            f"> Source specification: `{escaped_path}`",
            f"> Model: `{CRITIQUE_MODEL}`",
            f"> Reasoning effort: `{reasoning_effort}`",
            f"> Total latency: `{format_seconds(total_latency)}`",
            f"> API calls: `{api_calls}`",
            f"> Total tokens: {usage_summary(total_usage)}",
        ]
    )
    report = header + "\n\n" + "\n\n".join(fragments) + "\n"
    return report, failures


def count_findings(fragment: str) -> int:
    return sum(
        1
        for line in fragment.splitlines()
        if CRITIQUE_FINDING_RE.fullmatch(line)
    )


def generate_reasoning_evaluation_table(
    path: Path,
    text: str,
    prompt: str,
    protocol: str,
    api_key: str,
    requirement_id: str,
    efforts: Sequence[str] = CRITIQUE_REASONING_EFFORTS,
) -> tuple[str, list[str]]:
    """Run one requirement at several reasoning efforts and score each result."""
    requirement = requirement_excerpts(path, text, requirement_id)[0]
    critique_prompt = critique_instructions(prompt, protocol)
    score_prompt = rubric_instructions(protocol)
    targets = critique_targets(requirement.markdown)
    evaluations: list[ReasoningEvaluation] = []
    failures: list[str] = []

    for effort in efforts:
        try:
            result = request_critique(
                api_key,
                critique_prompt,
                requirement,
                effort,
            )
        except CritiqueError as exc:
            message = str(exc)
            failures.append(f"{effort}: critique unavailable: {message}")
            evaluations.append(
                ReasoningEvaluation(
                    effort=effort,
                    findings=0,
                    critique_latency_seconds=None,
                    critique_usage=CritiqueUsage(),
                    score=0.0,
                    note=f"Critique unavailable: {message}",
                    score_latency_seconds=None,
                    score_usage=CritiqueUsage(),
                    error=message,
                )
            )
            continue

        try:
            accepted_fragment = validate_critique_fragment(
                requirement_id,
                result.text,
                targets,
            )
        except ValueError as exc:
            message = f"model response was malformed: {exc}"
            failures.append(f"{effort}: {message}")
            evaluations.append(
                ReasoningEvaluation(
                    effort=effort,
                    findings=0,
                    critique_latency_seconds=result.latency_seconds,
                    critique_usage=result.usage,
                    score=0.0,
                    note=message,
                    score_latency_seconds=None,
                    score_usage=CritiqueUsage(),
                    error=message,
                )
            )
            continue

        try:
            score = request_rubric_score(
                api_key,
                score_prompt,
                requirement,
                accepted_fragment,
            )
        except CritiqueError as exc:
            message = f"rubric score unavailable: {exc}"
            failures.append(f"{effort}: {message}")
            evaluations.append(
                ReasoningEvaluation(
                    effort=effort,
                    findings=count_findings(accepted_fragment),
                    critique_latency_seconds=result.latency_seconds,
                    critique_usage=result.usage,
                    score=0.0,
                    note=message,
                    score_latency_seconds=None,
                    score_usage=CritiqueUsage(),
                    error=message,
                )
            )
            continue

        evaluations.append(
            ReasoningEvaluation(
                effort=effort,
                findings=count_findings(accepted_fragment),
                critique_latency_seconds=result.latency_seconds,
                critique_usage=result.usage,
                score=score.score,
                note=score.note,
                score_latency_seconds=score.latency_seconds,
                score_usage=score.usage,
            )
        )

    escaped_path = str(path).replace("`", "\\`")
    lines = [
        "# Behave critique reasoning evaluation",
        "",
        f"> Source specification: `{escaped_path}`",
        f"> Requirement: `{requirement_id}`",
        f"> Critique model: `{CRITIQUE_MODEL}`",
        f"> Rubric model: `{RUBRIC_MODEL}`",
        f"> Rubric reasoning effort: `{RUBRIC_REASONING_EFFORT}`",
        "",
        (
            "Rubric: material coverage 4, precision 3, diagnostic usefulness "
            "2, contract cleanliness 1."
        ),
        "",
        (
            "| Effort | Findings | Critique latency | Critique reasoning tokens | "
            "Critique total tokens | Score | Score latency | Score total tokens | Note |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for evaluation in evaluations:
        critique_latency = (
            "n/a"
            if evaluation.critique_latency_seconds is None
            else format_seconds(evaluation.critique_latency_seconds)
        )
        score_latency = (
            "n/a"
            if evaluation.score_latency_seconds is None
            else format_seconds(evaluation.score_latency_seconds)
        )
        lines.append(
            "| "
            f"`{evaluation.effort}` | "
            f"{evaluation.findings} | "
            f"{critique_latency} | "
            f"{format_count(evaluation.critique_usage.reasoning_tokens)} | "
            f"{format_count(evaluation.critique_usage.total_tokens)} | "
            f"{evaluation.score:.1f} | "
            f"{score_latency} | "
            f"{format_count(evaluation.score_usage.total_tokens)} | "
            f"{markdown_table_cell(evaluation.note)} |"
        )

    lines.append("")
    return "\n".join(lines), failures


def evaluation_locations(
    text: str,
) -> list[tuple[int, int, str, str]]:
    """
    Return evaluation locations as line indexes, indentation widths, raw
    indentation, and list markers.

    Callers should validate the specification before using these locations.
    """
    locations: list[tuple[int, int, str, str]] = []
    current_section: str | None = None

    for index, raw in enumerate(text.splitlines()):
        if REQUIREMENT_RE.match(raw):
            current_section = None
            continue

        section_match = SECTION_RE.match(raw)
        if section_match:
            current_section = section_match.group(1)
            continue

        if LEVEL_FOUR_RE.match(raw):
            current_section = None
            continue

        if current_section != "Behavior":
            continue

        item = LIST_ITEM_RE.match(raw)
        if not item or not EVALUATE_RE.match(item.group("text").strip()):
            continue

        raw_indent = item.group("indent")
        marker = raw[len(raw_indent)]
        locations.append(
            (
                index,
                indentation_width(raw_indent),
                raw_indent,
                marker,
            )
        )

    return locations


def evaluation_body_end(
    lines: Sequence[str],
    start_index: int,
    evaluate_indent: int,
) -> int:
    """Return the final non-blank line belonging to an evaluation criterion."""
    end_index = start_index

    for index in range(start_index + 1, len(lines)):
        raw = lines[index]
        if not raw.strip():
            continue

        if REQUIREMENT_RE.match(raw) or LEVEL_FOUR_RE.match(raw):
            break

        item = LIST_ITEM_RE.match(raw)
        if item:
            indent = indentation_width(item.group("indent"))
            if indent <= evaluate_indent:
                break
            end_index = index
            continue

        leading = raw[: len(raw) - len(raw.lstrip(" \t"))]
        if indentation_width(leading) <= evaluate_indent:
            break

        end_index = index

    return end_index


def normalize_criterion_statement(
    lines: Sequence[str],
    start_index: int,
    end_index: int,
    inline_body: str,
) -> str:
    parts: list[str] = []
    if inline_body.strip():
        parts.append(inline_body.strip())

    for raw in lines[start_index + 1 : end_index + 1]:
        stripped = raw.strip()
        if stripped:
            parts.append(stripped)

    return " ".join(parts)


def scoresheet_criteria(text: str) -> list[ScoresheetCriterion]:
    """
    Return criteria in document order with stable behavior/evaluation targets.

    Callers should validate the specification before using these locations.
    """
    lines = text.splitlines()
    criteria: list[ScoresheetCriterion] = []
    current_requirement: str | None = None
    current_section: str | None = None
    behavior_indent: int | None = None
    behavior_number = 0
    evaluation_number = 0

    for index, raw in enumerate(lines):
        requirement_match = REQUIREMENT_RE.match(raw)
        if requirement_match:
            current_requirement = requirement_match.group(1)
            current_section = None
            behavior_indent = None
            behavior_number = 0
            evaluation_number = 0
            continue

        section_match = SECTION_RE.match(raw)
        if section_match:
            current_section = section_match.group(1)
            behavior_indent = None
            continue

        if LEVEL_FOUR_RE.match(raw):
            current_section = None
            continue

        if current_requirement is None or current_section != "Behavior":
            continue

        item = LIST_ITEM_RE.match(raw)
        if not item:
            continue

        indent = indentation_width(item.group("indent"))
        item_text = item.group("text").strip()
        evaluate_match = EVALUATE_RE.match(item_text)

        if behavior_indent is None:
            behavior_indent = indent

        if indent == behavior_indent:
            behavior_number += 1
            evaluation_number = 0
            continue

        if not evaluate_match:
            continue

        evaluation_number += 1
        end_index = evaluation_body_end(lines, index, indent)
        statement = normalize_criterion_statement(
            lines,
            index,
            end_index,
            evaluate_match.group("body"),
        )
        criteria.append(
            ScoresheetCriterion(
                requirement_id=current_requirement,
                target=f"B{behavior_number}.E{evaluation_number}",
                line=index + 1,
                statement=statement,
                annotations=evaluate_match.group("annotations"),
            )
        )

    return criteria


def markdown_cell(value: str | None) -> str:
    if not value:
        return ""
    return value.replace("|", "\\|").replace("\n", " ")


def render_scoresheet(path: Path, text: str) -> str:
    """Return a Markdown scoresheet for a validated specification."""
    escaped_path = str(path).replace("`", "\\`")
    output = [
        "# Behave conformance scoresheet",
        "",
        f"> Source specification: `{escaped_path}`",
        "> Fill one row per evaluation criterion with implementation evidence.",
        "",
        (
            "| Requirement | Target | Criterion | Evidence hint | "
            "Conformance | Evidence | Notes |"
        ),
        "|---|---|---|---|---|---|---|",
    ]

    for criterion in scoresheet_criteria(text):
        output.append(
            "| "
            f"`{criterion.requirement_id}` | "
            f"`{criterion.target}` | "
            f"{markdown_cell(criterion.statement)} | "
            f"{markdown_cell(criterion.annotations)} | "
            "TBD | TBD |  |"
        )

    output.extend(
        [
            "",
            (
                "Conformance values are implementation-supplied, for example "
                "`pass`, `fail`, `partial`, `n/a`, or `unknown`."
            ),
            (
                "Evidence should link to native artifacts such as test results, "
                "measurements, reports, screenshots, telemetry, session captures, "
                "or API responses."
            ),
        ]
    )

    return "\n".join(output).rstrip() + "\n"


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
                    "User-Agent": "behavior-specification-tool/1",
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


def reasoning_effort_list(value: str) -> tuple[str, ...]:
    efforts = tuple(item.strip() for item in value.split(",") if item.strip())
    if not efforts:
        raise argparse.ArgumentTypeError("must include at least one effort")

    invalid = [
        effort
        for effort in efforts
        if effort not in CRITIQUE_REASONING_EFFORTS
    ]
    if invalid:
        allowed = ", ".join(CRITIQUE_REASONING_EFFORTS)
        raise argparse.ArgumentTypeError(
            f"unknown effort {invalid[0]!r}; expected one of: {allowed}"
        )

    return efforts


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
        description="Validate Behave specifications and derive related artifacts."
    )
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="Markdown specifications, or directories when validating",
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
    query_group = parser.add_mutually_exclusive_group()
    query_group.add_argument(
        "--show-requirement",
        metavar="R-ID",
        help="print one requirement block from exactly one specification file",
    )
    query_group.add_argument(
        "--list-requirements",
        action="store_true",
        help="list requirement identifiers from exactly one specification file",
    )
    query_group.add_argument(
        "--scoresheet",
        action="store_true",
        help="print a conformance scoresheet for one valid specification",
    )
    query_group.add_argument(
        "--critique",
        action="store_true",
        help="critique Evaluate clauses for one valid specification",
    )
    query_group.add_argument(
        "--critique-reasoning-eval",
        metavar="R-ID",
        help="compare critique value across reasoning efforts for one requirement",
    )
    parser.add_argument(
        "--critique-requirement",
        metavar="R-ID",
        help="with --critique, critique only one requirement by exact ID",
    )
    parser.add_argument(
        "--critique-reasoning-effort",
        choices=CRITIQUE_REASONING_EFFORTS,
        metavar="EFFORT",
        help=(
            "with --critique, set Responses API reasoning effort "
            f"(default: {CRITIQUE_REASONING_EFFORT})"
        ),
    )
    parser.add_argument(
        "--critique-reasoning-efforts",
        type=reasoning_effort_list,
        metavar="EFFORTS",
        help=(
            "with --critique-reasoning-eval, comma-separated reasoning "
            "efforts to compare"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.critique:
        if len(args.paths) != 1 or args.paths[0].is_dir():
            parser.error(
                "critique generation requires exactly one Markdown file"
            )
        if args.json:
            parser.error("--critique cannot be combined with --json")
        if args.check_references or args.check_external_references:
            parser.error("--critique cannot be combined with reference checks")
        if args.critique_reasoning_efforts is not None:
            parser.error("--critique-reasoning-efforts requires --critique-reasoning-eval")
        if (
            args.critique_requirement
            and not REQUIREMENT_ID_RE.fullmatch(args.critique_requirement)
        ):
            parser.error(
                "--critique-requirement expects an identifier such as R-EXAMPLE"
            )
    elif args.critique_requirement:
        parser.error("--critique-requirement requires --critique")
    elif args.critique_reasoning_effort is not None:
        parser.error("--critique-reasoning-effort requires --critique")
    elif (
        args.critique_reasoning_efforts is not None
        and not args.critique_reasoning_eval
    ):
        parser.error("--critique-reasoning-efforts requires --critique-reasoning-eval")

    if args.critique_reasoning_eval:
        if len(args.paths) != 1 or args.paths[0].is_dir():
            parser.error(
                "critique reasoning evaluation requires exactly one Markdown file"
            )
        if args.json:
            parser.error("--critique-reasoning-eval cannot be combined with --json")
        if args.check_references or args.check_external_references:
            parser.error(
                "--critique-reasoning-eval cannot be combined with reference checks"
            )
        if not REQUIREMENT_ID_RE.fullmatch(args.critique_reasoning_eval):
            parser.error(
                "--critique-reasoning-eval expects an identifier such as R-EXAMPLE"
            )

        path = args.paths[0]
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            print(
                f"{path}:1: IO001: could not read file: {exc}",
                file=sys.stderr,
            )
            return 1

        diagnostics = validate_text(path, text)
        if diagnostics:
            for item in diagnostics:
                print(item.render(), file=sys.stderr)
            print(
                f"\nValidation failed: {len(diagnostics)} issue(s) "
                "across 1 file(s).",
                file=sys.stderr,
            )
            return 1

        matches = requirement_excerpts(
            path,
            text,
            args.critique_reasoning_eval,
        )
        if len(matches) > 1:
            print(
                f"{path}:{matches[1].line}: R002: duplicate requirement "
                f"identifier {args.critique_reasoning_eval}; critique target "
                "is ambiguous",
                file=sys.stderr,
            )
            return 1
        if not matches:
            print(
                f"{path}:1: R005: requirement "
                f"{args.critique_reasoning_eval} was not found",
                file=sys.stderr,
            )
            return 1

        try:
            prompt = CRITIQUE_PROMPT_PATH.read_text(encoding="utf-8")
            protocol = PROTOCOL_PATH.read_text(encoding="utf-8")
        except OSError as exc:
            print(
                f"Critique configuration unavailable: {exc}",
                file=sys.stderr,
            )
            return 1

        if not prompt.strip() or not protocol.strip():
            print(
                "Critique configuration unavailable: prompt and protocol "
                "must not be empty.",
                file=sys.stderr,
            )
            return 1

        try:
            api_key = load_openai_api_key()
        except OSError as exc:
            print(f"Could not read .env: {exc}", file=sys.stderr)
            return 1

        if api_key is None:
            print(
                "OPENAI_API_KEY is required in the environment or ./.env.",
                file=sys.stderr,
            )
            return 1

        table, failures = generate_reasoning_evaluation_table(
            path,
            text,
            prompt,
            protocol,
            api_key,
            args.critique_reasoning_eval,
            args.critique_reasoning_efforts or CRITIQUE_REASONING_EFFORTS,
        )
        sys.stdout.write(table)
        for failure in failures:
            print(f"Critique reasoning evaluation issue: {failure}", file=sys.stderr)
        return 1 if failures else 0

    if args.critique:
        path = args.paths[0]
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            print(
                f"{path}:1: IO001: could not read file: {exc}",
                file=sys.stderr,
            )
            return 1

        diagnostics = validate_text(path, text)
        if diagnostics:
            for item in diagnostics:
                print(item.render(), file=sys.stderr)
            print(
                f"\nValidation failed: {len(diagnostics)} issue(s) "
                "across 1 file(s).",
                file=sys.stderr,
            )
            return 1

        if args.critique_requirement:
            matches = requirement_excerpts(
                path,
                text,
                args.critique_requirement,
            )
            if len(matches) > 1:
                print(
                    f"{path}:{matches[1].line}: R002: "
                    f"duplicate requirement identifier "
                    f"{args.critique_requirement}; critique target is "
                    "ambiguous",
                    file=sys.stderr,
                )
                return 1
            if not matches:
                print(
                    f"{path}:1: R005: requirement "
                    f"{args.critique_requirement} was not found",
                    file=sys.stderr,
                )
                return 1

        try:
            prompt = CRITIQUE_PROMPT_PATH.read_text(encoding="utf-8")
            protocol = PROTOCOL_PATH.read_text(encoding="utf-8")
        except OSError as exc:
            print(
                f"Critique configuration unavailable: {exc}",
                file=sys.stderr,
            )
            return 1

        if not prompt.strip() or not protocol.strip():
            print(
                "Critique configuration unavailable: prompt and protocol "
                "must not be empty.",
                file=sys.stderr,
            )
            return 1

        try:
            api_key = load_openai_api_key()
        except OSError as exc:
            print(f"Could not read .env: {exc}", file=sys.stderr)
            return 1

        if api_key is None:
            print(
                "OPENAI_API_KEY is required in the environment or ./.env.",
                file=sys.stderr,
            )
            return 1

        report, failures = generate_critique_report(
            path,
            text,
            prompt,
            protocol,
            api_key,
            args.critique_requirement,
            args.critique_reasoning_effort or CRITIQUE_REASONING_EFFORT,
        )
        sys.stdout.write(report)
        for failure in failures:
            print(f"Critique unavailable: {failure}", file=sys.stderr)
        return 1 if failures else 0

    if args.scoresheet:
        if len(args.paths) != 1 or args.paths[0].is_dir():
            parser.error(
                "scoresheet generation requires exactly one Markdown file"
            )
        if args.json:
            parser.error("--scoresheet cannot be combined with --json")
        if args.check_references or args.check_external_references:
            parser.error(
                "--scoresheet cannot be combined with reference checks"
            )

        path = args.paths[0]
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            diagnostic = Diagnostic(
                str(path),
                1,
                "IO001",
                f"could not read file: {exc}",
            )
            print(diagnostic.render(), file=sys.stderr)
            return 1

        diagnostics = validate_text(path, text)
        if diagnostics:
            for item in diagnostics:
                print(item.render(), file=sys.stderr)
            print(
                f"\nValidation failed: {len(diagnostics)} issue(s) "
                "across 1 file(s).",
                file=sys.stderr,
            )
            return 1

        sys.stdout.write(render_scoresheet(path, text))
        return 0

    if args.show_requirement or args.list_requirements:
        if args.show_requirement and not REQUIREMENT_ID_RE.fullmatch(
            args.show_requirement
        ):
            parser.error(
                "--show-requirement expects an identifier such as R-EXAMPLE"
            )
        if len(args.paths) != 1 or args.paths[0].is_dir():
            parser.error(
                "requirement queries require exactly one Markdown file"
            )
        if args.check_references or args.check_external_references:
            parser.error(
                "requirement queries cannot be combined with reference checks"
            )

        path = args.paths[0]
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            diagnostic = Diagnostic(
                str(path),
                1,
                "IO001",
                f"could not read file: {exc}",
            )
            if args.json:
                print(json.dumps([asdict(diagnostic)], indent=2))
            else:
                print(diagnostic.render(), file=sys.stderr)
            return 1

        if args.list_requirements:
            summaries = requirement_summaries(path, text)
            if args.json:
                print(
                    json.dumps(
                        [asdict(summary) for summary in summaries],
                        indent=2,
                    )
                )
            else:
                for summary in summaries:
                    print(summary.identifier)
            return 0

        matches = requirement_excerpts(path, text, args.show_requirement)
        if len(matches) != 1:
            if matches:
                line = matches[1].line
                code = "R002"
                message = (
                    f"duplicate requirement identifier {args.show_requirement}; "
                    f"first declared on line {matches[0].line}"
                )
            else:
                line = 1
                code = "R005"
                message = f"requirement {args.show_requirement} was not found"

            diagnostic = Diagnostic(str(path), line, code, message)
            if args.json:
                print(json.dumps([asdict(diagnostic)], indent=2))
            else:
                print(diagnostic.render(), file=sys.stderr)
            return 1

        excerpt = matches[0]
        if args.json:
            print(json.dumps(asdict(excerpt), indent=2))
        else:
            sys.stdout.write(excerpt.markdown)
        return 0

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
