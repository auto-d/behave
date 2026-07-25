from __future__ import annotations

import argparse
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock
from urllib.error import URLError

import behave


ONE_REQUIREMENT = """# Contract

### R-FIRST

#### Intent

The system remains reviewable.

#### Behavior

- The system reports its state.
  - Evaluate: The state matches the documented values.
  - Evaluate: The explanation is consistent with the state.

- The system reports unavailable dependencies.
  - Evaluate: The response identifies each unavailable dependency.
"""

TWO_REQUIREMENTS = ONE_REQUIREMENT + """

### R-SECOND

#### Intent

The system remains understandable.

#### Behavior

- The system uses plain language.
  - Evaluate: A business user can understand the response.
"""


def no_findings(identifier: str) -> str:
    return (
        f"## {identifier}\n\n"
        "_No material evaluability issues identified._"
    )


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


class RawResponse(FakeResponse):
    def __init__(self, payload: bytes) -> None:
        self.payload = payload


class CritiqueValidationTests(unittest.TestCase):
    def test_targets_use_behavior_and_evaluation_document_order(self) -> None:
        requirement = behave.requirement_excerpts(
            Path("contract.md"),
            ONE_REQUIREMENT,
            "R-FIRST",
        )[0]

        self.assertEqual(
            {"B1", "B1.E1", "B1.E2", "B2", "B2.E1"},
            behave.critique_targets(requirement.markdown),
        )

    def test_accepts_no_findings_and_multiple_findings(self) -> None:
        targets = {"B1", "B1.E1", "B1.E2", "B2", "B2.E1"}
        findings = """## R-FIRST

### Finding 1: B1

**Problem:** The criteria leave part of the behavior unevaluated.

### Finding 2: B1.E1

**Problem:** Applicability is unclear enough to produce conflicting judgments.

### Finding 3: B1.E2

**Problem:** The necessary comparison lacks essential information.

### Finding 4: B2

**Problem:** The criteria conflict with the stated behavior.

### Finding 5: B2.E1

**Problem:** The criterion cannot distinguish satisfying evidence."""

        self.assertEqual(
            no_findings("R-FIRST"),
            behave.validate_critique_fragment(
                "R-FIRST",
                no_findings("R-FIRST") + "\n",
                targets,
            ),
        )
        self.assertEqual(
            findings,
            behave.validate_critique_fragment(
                "R-FIRST",
                findings,
                targets,
            ),
        )

    def test_rejects_nonconforming_fragments(self) -> None:
        valid_problem = (
            "**Problem:** The criterion cannot distinguish satisfying evidence."
        )
        cases = {
            "wrong requirement": (
                "## R-WRONG\n\n_No material evaluability issues identified._"
            ),
            "additional no-findings prose": (
                "## R-FIRST\n\n_No material evaluability issues identified._"
                "\n\nExtra."
            ),
            "invalid target": (
                "## R-FIRST\n\n### Finding 1: B9.E1\n\n"
                f"{valid_problem}"
            ),
            "skipped number": (
                "## R-FIRST\n\n### Finding 2: B1.E1\n\n"
                f"{valid_problem}"
            ),
            "missing problem": "## R-FIRST\n\n### Finding 1: B1.E1",
            "extra field": (
                "## R-FIRST\n\n### Finding 1: B1.E1\n\n"
                f"{valid_problem}\n\n**Revision:** Add a threshold."
            ),
            "overlong problem": (
                "## R-FIRST\n\n### Finding 1: B1.E1\n\n**Problem:** "
                + ("x" * 240)
                + "."
            ),
            "recommendation": (
                "## R-FIRST\n\n### Finding 1: B1.E1\n\n"
                "**Problem:** Add a criterion covering unavailable sources."
            ),
            "code fence": (
                "```md\n## R-FIRST\n\n"
                "_No material evaluability issues identified._\n```"
            ),
        }

        for name, fragment in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    behave.validate_critique_fragment(
                        "R-FIRST",
                        fragment,
                        {"B1", "B1.E1"},
                    )

    def test_problem_allows_target_references_and_multiple_periods(self) -> None:
        fragment = """## R-FIRST

### Finding 1: B1.E1

**Problem:** B1.E1 permits v2.1 evidence, e.g. partial traces, without establishing complete coverage."""

        self.assertEqual(
            fragment,
            behave.validate_critique_fragment(
                "R-FIRST",
                fragment,
                {"B1", "B1.E1"},
            ),
        )


class CritiqueRequestTests(unittest.TestCase):
    def test_instructions_include_prompt_and_verbatim_protocol(self) -> None:
        prompt = "Fixed prompt.\n"
        protocol = "# Protocol\n\nExact contents.\n"

        instructions = behave.critique_instructions(prompt, protocol)

        self.assertTrue(instructions.startswith(prompt))
        self.assertIn(
            f"<behave_protocol>\n{protocol}</behave_protocol>",
            instructions,
        )

    def test_request_uses_fixed_model_settings_and_one_requirement(self) -> None:
        requirement = behave.requirement_excerpts(
            Path("contract.md"),
            ONE_REQUIREMENT,
            "R-FIRST",
        )[0]
        response_payload = {
            "status": "completed",
            "usage": {
                "input_tokens": 4812,
                "output_tokens": 126,
                "total_tokens": 5962,
                "output_tokens_details": {"reasoning_tokens": 1024},
            },
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "## R-FIRST\n\n"},
                        {
                            "type": "output_text",
                            "text": (
                                "_No material evaluability issues identified._"
                            ),
                        },
                    ],
                }
            ],
        }

        with mock.patch(
            "behave.urlopen",
            return_value=FakeResponse(response_payload),
        ) as mocked_urlopen, mock.patch(
            "behave.time.monotonic",
            side_effect=[10.0, 30.3],
        ):
            result = behave.request_critique(
                "secret-key",
                "system instructions",
                requirement,
                "low",
                "gpt-5.6-terra",
            )

        request = mocked_urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        requirement_input = json.loads(payload["input"])

        self.assertEqual(no_findings("R-FIRST"), result.text)
        self.assertAlmostEqual(20.3, result.latency_seconds)
        self.assertEqual(4812, result.usage.input_tokens)
        self.assertEqual(1024, result.usage.reasoning_tokens)
        self.assertEqual(126, result.usage.output_tokens)
        self.assertEqual(5962, result.usage.total_tokens)
        self.assertEqual("gpt-5.6-terra", payload["model"])
        self.assertEqual({"effort": "low"}, payload["reasoning"])
        self.assertEqual({"verbosity": "low"}, payload["text"])
        self.assertFalse(payload["store"])
        self.assertEqual(8192, payload["max_output_tokens"])
        self.assertEqual("R-FIRST", requirement_input["requirement_id"])
        self.assertEqual(
            requirement.markdown,
            requirement_input["requirement_markdown"],
        )
        self.assertEqual(
            behave.CRITIQUE_TIMEOUT,
            mocked_urlopen.call_args.kwargs["timeout"],
        )

    def test_request_errors_do_not_expose_response_content(self) -> None:
        requirement = behave.requirement_excerpts(
            Path("contract.md"),
            ONE_REQUIREMENT,
            "R-FIRST",
        )[0]

        with mock.patch(
            "behave.urlopen",
            side_effect=URLError("offline"),
        ):
            with self.assertRaisesRegex(behave.CritiqueError, "offline"):
                behave.request_critique(
                    "secret-key",
                    "instructions",
                    requirement,
                )

    def test_request_rejects_incomplete_malformed_and_empty_responses(self) -> None:
        requirement = behave.requirement_excerpts(
            Path("contract.md"),
            ONE_REQUIREMENT,
            "R-FIRST",
        )[0]
        cases = {
            "incomplete": FakeResponse(
                {"status": "incomplete", "output": []}
            ),
            "refusal": FakeResponse(
                {
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {"type": "refusal", "refusal": "Unable."}
                            ],
                        }
                    ],
                }
            ),
            "malformed json": RawResponse(b"{not-json"),
        }

        for name, response in cases.items():
            with self.subTest(name=name), mock.patch(
                "behave.urlopen",
                return_value=response,
            ):
                with self.assertRaises(behave.CritiqueError):
                    behave.request_critique(
                        "secret-key",
                        "instructions",
                        requirement,
                    )

    def test_api_key_prefers_environment_then_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dotenv = Path(directory) / ".env"
            dotenv.write_text(
                "IGNORED=value\nOPENAI_API_KEY='file-key'\n",
                encoding="utf-8",
            )

            self.assertEqual(
                "environment-key",
                behave.load_openai_api_key(
                    {"OPENAI_API_KEY": "environment-key"},
                    dotenv,
                ),
            )
            self.assertEqual(
                "file-key",
                behave.load_openai_api_key({}, dotenv),
            )

    def test_usage_extraction_tolerates_missing_fields(self) -> None:
        self.assertEqual(
            behave.CritiqueUsage(),
            behave.critique_usage({"usage": {}}),
        )
        usage = behave.critique_usage(
            {
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 3,
                    "total_tokens": 13,
                    "reasoning_tokens": 2,
                }
            }
        )

        self.assertEqual(10, usage.input_tokens)
        self.assertEqual(2, usage.reasoning_tokens)
        self.assertEqual(3, usage.output_tokens)
        self.assertEqual(13, usage.total_tokens)

    def test_reasoning_effort_list_parses_and_rejects_invalid_values(self) -> None:
        self.assertEqual(
            ("low", "max"),
            behave.reasoning_effort_list("low, max"),
        )
        with self.assertRaisesRegex(argparse.ArgumentTypeError, "unknown effort"):
            behave.reasoning_effort_list("low,extra")

    def test_critique_model_list_parses_and_rejects_invalid_values(self) -> None:
        self.assertEqual(
            ("gpt-5.6-terra", "gpt-5.6-luna"),
            behave.critique_model_list("gpt-5.6-terra, gpt-5.6-luna"),
        )
        with self.assertRaisesRegex(argparse.ArgumentTypeError, "unknown model"):
            behave.critique_model_list("gpt-5.6-terra,gpt-4.1")

    def test_rubric_score_request_uses_fixed_contract(self) -> None:
        requirement = behave.requirement_excerpts(
            Path("contract.md"),
            ONE_REQUIREMENT,
            "R-FIRST",
        )[0]
        response_payload = {
            "status": "completed",
            "usage": {
                "input_tokens": 200,
                "output_tokens": 20,
                "total_tokens": 230,
                "output_tokens_details": {"reasoning_tokens": 10},
            },
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": (
                                "Score: 8.5\n"
                                "Note: Strong coverage with minor precision loss."
                            ),
                        }
                    ],
                }
            ],
        }

        with mock.patch(
            "behave.urlopen",
            return_value=FakeResponse(response_payload),
        ) as mocked_urlopen, mock.patch(
            "behave.time.monotonic",
            side_effect=[1.0, 3.5],
        ):
            score = behave.request_rubric_score(
                "secret-key",
                "rubric instructions",
                requirement,
                no_findings("R-FIRST"),
            )

        request = mocked_urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        score_input = json.loads(payload["input"])

        self.assertEqual(8.5, score.score)
        self.assertEqual(
            "Strong coverage with minor precision loss.",
            score.note,
        )
        self.assertAlmostEqual(2.5, score.latency_seconds)
        self.assertEqual(10, score.usage.reasoning_tokens)
        self.assertEqual("gpt-5.6-sol", payload["model"])
        self.assertEqual({"effort": "low"}, payload["reasoning"])
        self.assertEqual(512, payload["max_output_tokens"])
        self.assertEqual("R-FIRST", score_input["requirement_id"])
        self.assertEqual(
            requirement.markdown,
            score_input["requirement_markdown"],
        )
        self.assertEqual(no_findings("R-FIRST"), score_input["critique_markdown"])

    def test_rubric_score_rejects_malformed_response(self) -> None:
        requirement = behave.requirement_excerpts(
            Path("contract.md"),
            ONE_REQUIREMENT,
            "R-FIRST",
        )[0]

        with mock.patch(
            "behave.urlopen",
            return_value=FakeResponse(
                {
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": "Looks pretty good.",
                                }
                            ],
                        }
                    ],
                }
            ),
        ):
            with self.assertRaises(behave.CritiqueError):
                behave.request_rubric_score(
                    "secret-key",
                    "rubric instructions",
                    requirement,
                    no_findings("R-FIRST"),
                )


class CritiqueReportTests(unittest.TestCase):
    def test_report_calls_once_per_requirement_in_document_order(self) -> None:
        identifiers: list[str] = []

        def respond(
            api_key: str,
            instructions: str,
            requirement: behave.RequirementExcerpt,
            reasoning_effort: str = behave.CRITIQUE_REASONING_EFFORT,
            model: str = behave.CRITIQUE_MODEL,
            timeout: float = behave.CRITIQUE_TIMEOUT,
        ) -> behave.CritiqueResult:
            identifiers.append(requirement.identifier)
            return behave.CritiqueResult(
                no_findings(requirement.identifier),
                1.25,
                behave.CritiqueUsage(10, 2, 3, 15),
            )

        with mock.patch("behave.request_critique", side_effect=respond):
            report, failures = behave.generate_critique_report(
                Path("contract.md"),
                TWO_REQUIREMENTS,
                "prompt\n",
                "protocol\n",
                "secret-key",
                reasoning_effort="medium",
            )

        self.assertEqual(["R-FIRST", "R-SECOND"], identifiers)
        self.assertEqual([], failures)
        self.assertLess(report.index("## R-FIRST"), report.index("## R-SECOND"))
        self.assertIn("> Model: `gpt-5.6-sol`", report)
        self.assertIn("> Reasoning effort: `medium`", report)
        self.assertIn("> Total latency: `2.5s`", report)
        self.assertIn("> API calls: `2`", report)
        self.assertIn(
            "> Total tokens: input `20`, reasoning `4`, output `6`, total `30`",
            report,
        )
        self.assertEqual(2, report.count("> Latency: `1.2s`"))
        self.assertEqual(
            2,
            report.count(
                "> Tokens: input `10`, reasoning `2`, output `3`, total `15`"
            ),
        )

    def test_report_can_target_one_requirement(self) -> None:
        identifiers: list[str] = []

        def respond(
            api_key: str,
            instructions: str,
            requirement: behave.RequirementExcerpt,
            reasoning_effort: str = behave.CRITIQUE_REASONING_EFFORT,
            model: str = behave.CRITIQUE_MODEL,
            timeout: float = behave.CRITIQUE_TIMEOUT,
        ) -> behave.CritiqueResult:
            identifiers.append(requirement.identifier)
            return behave.CritiqueResult(
                no_findings(requirement.identifier),
                3.0,
                behave.CritiqueUsage(20, None, 4, 24),
            )

        with mock.patch("behave.request_critique", side_effect=respond):
            report, failures = behave.generate_critique_report(
                Path("contract.md"),
                TWO_REQUIREMENTS,
                "prompt\n",
                "protocol\n",
                "secret-key",
                "R-SECOND",
            )

        self.assertEqual(["R-SECOND"], identifiers)
        self.assertEqual([], failures)
        self.assertNotIn("## R-FIRST", report)
        self.assertIn("## R-SECOND", report)
        self.assertIn("> Total latency: `3.0s`", report)
        self.assertIn("> API calls: `1`", report)
        self.assertIn(
            "> Tokens: input `20`, reasoning `unknown`, output `4`, total `24`",
            report,
        )

    def test_report_continues_after_request_and_template_failures(self) -> None:
        with mock.patch(
            "behave.request_critique",
            side_effect=[
                behave.CritiqueError("offline"),
                behave.CritiqueResult(
                    "## R-SECOND\n\nExtra prose.",
                    4.0,
                    behave.CritiqueUsage(30, 5, 6, 41),
                ),
            ],
        ):
            report, failures = behave.generate_critique_report(
                Path("contract.md"),
                TWO_REQUIREMENTS,
                "prompt\n",
                "protocol\n",
                "secret-key",
            )

        self.assertEqual(2, len(failures))
        self.assertIn(behave.UNUSABLE_RESPONSE_TEXT, report)
        self.assertIn(behave.MALFORMED_RESPONSE_TEXT, report)
        self.assertNotIn("offline", report)
        self.assertNotIn("Extra prose.", report)
        self.assertIn("> Total latency: `4.0s`", report)
        self.assertIn("> API calls: `1`", report)
        self.assertIn(
            "> Total tokens: input `30`, reasoning `5`, output `6`, total `41`",
            report,
        )
        self.assertIn("> Latency: `4.0s`", report)
        self.assertIn(
            "> Tokens: input `30`, reasoning `5`, output `6`, total `41`",
            report,
        )

    def test_reasoning_evaluation_table_scores_each_effort(self) -> None:
        critique_calls: list[str] = []
        score_calls: list[str] = []
        progress_events: list[str] = []

        def critique(
            api_key: str,
            instructions: str,
            requirement: behave.RequirementExcerpt,
            reasoning_effort: str = behave.CRITIQUE_REASONING_EFFORT,
            model: str = behave.CRITIQUE_MODEL,
            timeout: float = behave.CRITIQUE_TIMEOUT,
        ) -> behave.CritiqueResult:
            critique_calls.append(f"{model}/{reasoning_effort}")
            if model == "gpt-5.6-sol" and reasoning_effort == "none":
                raise behave.CritiqueError("unsupported effort")
            return behave.CritiqueResult(
                no_findings(requirement.identifier),
                2.0,
                behave.CritiqueUsage(100, 10, 5, 115),
            )

        def score(
            api_key: str,
            instructions: str,
            requirement: behave.RequirementExcerpt,
            critique_fragment: str,
            model: str = behave.RUBRIC_MODEL,
            timeout: float = behave.CRITIQUE_TIMEOUT,
        ) -> behave.RubricScore:
            score_calls.append(f"{model}/{requirement.identifier}")
            return behave.RubricScore(
                8.5,
                "Good coverage | concise.",
                1.0,
                behave.CritiqueUsage(50, 5, 3, 58),
            )

        with mock.patch(
            "behave.request_critique",
            side_effect=critique,
        ), mock.patch(
            "behave.request_rubric_score",
            side_effect=score,
        ):
            table, failures = behave.generate_reasoning_evaluation_table(
                Path("contract.md"),
                ONE_REQUIREMENT,
                "prompt\n",
                "protocol\n",
                "secret-key",
                "R-FIRST",
                ("none", "low"),
                ("gpt-5.6-sol", "gpt-5.6-luna"),
                progress=progress_events.append,
            )

        self.assertEqual(
            [
                "gpt-5.6-sol/none",
                "gpt-5.6-sol/low",
                "gpt-5.6-luna/none",
                "gpt-5.6-luna/low",
            ],
            critique_calls,
        )
        self.assertEqual(
            [
                "gpt-5.6-sol/R-FIRST",
                "gpt-5.6-sol/R-FIRST",
                "gpt-5.6-sol/R-FIRST",
            ],
            score_calls,
        )
        self.assertEqual(
            [
                "gpt-5.6-sol/none: critique unavailable: unsupported effort"
            ],
            failures,
        )
        self.assertIn(
            "| `gpt-5.6-sol` | `none` | 0 | n/a | unknown | unknown | 0.0 | n/a | unknown |",
            table,
        )
        self.assertIn(
            "| `gpt-5.6-sol` | `low` | 0 | 2.0s | 10 | 115 | 8.5 | 1.0s | 58 |",
            table,
        )
        self.assertIn("> Critique models: `gpt-5.6-sol, gpt-5.6-luna`", table)
        self.assertIn("Good coverage \\| concise.", table)
        self.assertEqual(
            "Critique eval: R-FIRST across 2 model(s) x 2 effort(s) = 4 run(s)",
            progress_events[0],
        )
        self.assertIn(
            "Critique eval 1/4: gpt-5.6-sol / none: requesting critique...",
            progress_events,
        )
        self.assertIn(
            "Critique eval 1/4: gpt-5.6-sol / none: failed: unsupported effort",
            progress_events,
        )
        self.assertIn(
            "Critique eval 2/4: gpt-5.6-sol / low: scoring critique...",
            progress_events,
        )
        self.assertTrue(
            any(
                event.startswith(
                    "Critique eval 2/4: gpt-5.6-sol / low: complete in "
                )
                and "score 8.5, tokens critique 115 + score 58" in event
                for event in progress_events
            )
        )
        self.assertTrue(
            progress_events[-1].startswith(
                "Critique eval complete: 3/4 succeeded in "
            )
        )

    def test_cli_emits_reasoning_evaluation_table(self) -> None:
        table = "# Behave critique reasoning evaluation\n"
        with tempfile.TemporaryDirectory() as directory:
            contract = Path(directory) / "contract.md"
            contract.write_text(ONE_REQUIREMENT, encoding="utf-8")
            output = io.StringIO()
            error = io.StringIO()

            with mock.patch(
                "behave.load_openai_api_key",
                return_value="secret-key",
            ), mock.patch(
                "behave.generate_reasoning_evaluation_table",
                return_value=(table, []),
            ) as mocked_table, redirect_stdout(output), redirect_stderr(error):
                status = behave.main(
                    [
                        "--critique-reasoning-eval",
                        "R-FIRST",
                        "--critique-reasoning-efforts",
                        "low,medium",
                        "--critique-models",
                        "gpt-5.6-terra,gpt-5.6-luna",
                        str(contract),
                    ]
                )

        self.assertEqual(0, status)
        self.assertEqual(table, output.getvalue())
        self.assertEqual("", error.getvalue())
        self.assertEqual("R-FIRST", mocked_table.call_args.args[5])
        self.assertEqual(("low", "medium"), mocked_table.call_args.args[6])
        self.assertEqual(
            ("gpt-5.6-terra", "gpt-5.6-luna"),
            mocked_table.call_args.args[7],
        )

    def test_cli_writes_reasoning_evaluation_progress_to_stderr(self) -> None:
        table = "# Behave critique reasoning evaluation\n"

        def generate(
            *args: object,
            progress: object = None,
        ) -> tuple[str, list[str]]:
            assert callable(progress)
            progress("Critique eval 1/1: gpt-5.6-luna / low: requesting critique...")
            return table, []

        with tempfile.TemporaryDirectory() as directory:
            contract = Path(directory) / "contract.md"
            contract.write_text(ONE_REQUIREMENT, encoding="utf-8")
            output = io.StringIO()
            error = io.StringIO()

            with mock.patch(
                "behave.load_openai_api_key",
                return_value="secret-key",
            ), mock.patch(
                "behave.generate_reasoning_evaluation_table",
                side_effect=generate,
            ), redirect_stdout(output), redirect_stderr(error):
                status = behave.main(
                    [
                        "--critique-reasoning-eval",
                        "R-FIRST",
                        "--critique-reasoning-efforts",
                        "low",
                        "--critique-models",
                        "gpt-5.6-luna",
                        str(contract),
                    ]
                )

        self.assertEqual(0, status)
        self.assertEqual(table, output.getvalue())
        self.assertIn(
            "Critique eval 1/1: gpt-5.6-luna / low: requesting critique...",
            error.getvalue(),
        )

    def test_cli_quiet_suppresses_reasoning_evaluation_progress(self) -> None:
        table = "# Behave critique reasoning evaluation\n"
        progress_values: list[object] = []

        def generate(
            *args: object,
            progress: object = None,
        ) -> tuple[str, list[str]]:
            progress_values.append(progress)
            return table, []

        with tempfile.TemporaryDirectory() as directory:
            contract = Path(directory) / "contract.md"
            contract.write_text(ONE_REQUIREMENT, encoding="utf-8")
            output = io.StringIO()
            error = io.StringIO()

            with mock.patch(
                "behave.load_openai_api_key",
                return_value="secret-key",
            ), mock.patch(
                "behave.generate_reasoning_evaluation_table",
                side_effect=generate,
            ), redirect_stdout(output), redirect_stderr(error):
                status = behave.main(
                    [
                        "--quiet",
                        "--critique-reasoning-eval",
                        "R-FIRST",
                        "--critique-reasoning-efforts",
                        "low",
                        "--critique-models",
                        "gpt-5.6-luna",
                        str(contract),
                    ]
                )

        self.assertEqual(0, status)
        self.assertEqual(table, output.getvalue())
        self.assertEqual("", error.getvalue())
        self.assertEqual([None], progress_values)

    def test_cli_rejects_missing_reasoning_evaluation_requirement_before_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            contract = Path(directory) / "contract.md"
            contract.write_text(ONE_REQUIREMENT, encoding="utf-8")
            output = io.StringIO()
            error = io.StringIO()

            with mock.patch(
                "behave.load_openai_api_key"
            ) as mocked_key, redirect_stdout(output), redirect_stderr(error):
                status = behave.main(
                    [
                        "--critique-reasoning-eval",
                        "R-MISSING",
                        str(contract),
                    ]
                )

        self.assertEqual(1, status)
        self.assertEqual("", output.getvalue())
        self.assertIn("R-MISSING", error.getvalue())
        mocked_key.assert_not_called()

    def test_cli_rejects_invalid_spec_before_resolving_credentials(self) -> None:
        invalid = """### R-INVALID

#### Intent

Missing behavior.
"""
        with tempfile.TemporaryDirectory() as directory:
            contract = Path(directory) / "invalid.md"
            contract.write_text(invalid, encoding="utf-8")
            output = io.StringIO()
            error = io.StringIO()

            with mock.patch(
                "behave.load_openai_api_key"
            ) as mocked_key, redirect_stdout(output), redirect_stderr(error):
                status = behave.main(["--critique", str(contract)])

        self.assertEqual(1, status)
        self.assertEqual("", output.getvalue())
        self.assertIn("R003", error.getvalue())
        mocked_key.assert_not_called()

    def test_cli_requires_credentials_without_starting_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            contract = Path(directory) / "contract.md"
            contract.write_text(ONE_REQUIREMENT, encoding="utf-8")
            output = io.StringIO()
            error = io.StringIO()

            with mock.patch(
                "behave.load_openai_api_key",
                return_value=None,
            ), redirect_stdout(output), redirect_stderr(error):
                status = behave.main(["--critique", str(contract)])

        self.assertEqual(1, status)
        self.assertEqual("", output.getvalue())
        self.assertIn("OPENAI_API_KEY", error.getvalue())

    def test_cli_requires_prompt_configuration_before_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            contract = Path(directory) / "contract.md"
            contract.write_text(ONE_REQUIREMENT, encoding="utf-8")
            missing_prompt = Path(directory) / "missing-prompt.md"
            output = io.StringIO()
            error = io.StringIO()

            with mock.patch(
                "behave.CRITIQUE_PROMPT_PATH",
                missing_prompt,
            ), mock.patch(
                "behave.load_openai_api_key"
            ) as mocked_key, redirect_stdout(output), redirect_stderr(error):
                status = behave.main(["--critique", str(contract)])

        self.assertEqual(1, status)
        self.assertEqual("", output.getvalue())
        self.assertIn("Critique configuration unavailable", error.getvalue())
        mocked_key.assert_not_called()

    def test_cli_emits_complete_report_and_returns_zero(self) -> None:
        complete_report = "# Behave evaluability critique\n\n## R-FIRST\n"
        with tempfile.TemporaryDirectory() as directory:
            contract = Path(directory) / "contract.md"
            contract.write_text(ONE_REQUIREMENT, encoding="utf-8")
            output = io.StringIO()
            error = io.StringIO()

            with mock.patch(
                "behave.load_openai_api_key",
                return_value="secret-key",
            ), mock.patch(
                "behave.generate_critique_report",
                return_value=(complete_report, []),
            ), redirect_stdout(output), redirect_stderr(error):
                status = behave.main(["--critique", str(contract)])

        self.assertEqual(0, status)
        self.assertEqual(complete_report, output.getvalue())
        self.assertEqual("", error.getvalue())

    def test_cli_passes_target_requirement_to_report_generator(self) -> None:
        complete_report = "# Behave evaluability critique\n\n## R-SECOND\n"
        with tempfile.TemporaryDirectory() as directory:
            contract = Path(directory) / "contract.md"
            contract.write_text(TWO_REQUIREMENTS, encoding="utf-8")
            output = io.StringIO()

            with mock.patch(
                "behave.load_openai_api_key",
                return_value="secret-key",
            ), mock.patch(
                "behave.generate_critique_report",
                return_value=(complete_report, []),
            ) as mocked_report, redirect_stdout(output):
                status = behave.main(
                    [
                        "--critique",
                        "--critique-requirement",
                        "R-SECOND",
                        "--critique-reasoning-effort",
                        "low",
                        "--critique-model",
                        "gpt-5.6-terra",
                        str(contract),
                    ]
                )

        self.assertEqual(0, status)
        self.assertEqual(complete_report, output.getvalue())
        self.assertEqual("R-SECOND", mocked_report.call_args.args[5])
        self.assertEqual("low", mocked_report.call_args.args[6])
        self.assertEqual("gpt-5.6-terra", mocked_report.call_args.args[7])

    def test_cli_rejects_missing_target_requirement_before_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            contract = Path(directory) / "contract.md"
            contract.write_text(ONE_REQUIREMENT, encoding="utf-8")
            output = io.StringIO()
            error = io.StringIO()

            with mock.patch(
                "behave.load_openai_api_key"
            ) as mocked_key, redirect_stdout(output), redirect_stderr(error):
                status = behave.main(
                    [
                        "--critique",
                        "--critique-requirement",
                        "R-MISSING",
                        str(contract),
                    ]
                )

        self.assertEqual(1, status)
        self.assertEqual("", output.getvalue())
        self.assertIn("R-MISSING", error.getvalue())
        mocked_key.assert_not_called()

    def test_cli_emits_partial_report_and_returns_nonzero(self) -> None:
        partial_report = "# Behave evaluability critique\n\n## R-FIRST\n"
        with tempfile.TemporaryDirectory() as directory:
            contract = Path(directory) / "contract.md"
            contract.write_text(ONE_REQUIREMENT, encoding="utf-8")
            output = io.StringIO()
            error = io.StringIO()

            with mock.patch(
                "behave.load_openai_api_key",
                return_value="secret-key",
            ), mock.patch(
                "behave.generate_critique_report",
                return_value=(partial_report, ["R-FIRST: unavailable"]),
            ), redirect_stdout(output), redirect_stderr(error):
                status = behave.main(["--critique", str(contract)])

        self.assertEqual(1, status)
        self.assertEqual(partial_report, output.getvalue())
        self.assertIn("R-FIRST: unavailable", error.getvalue())
        self.assertNotIn("secret-key", error.getvalue())

    def test_cli_rejects_incompatible_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            contract = Path(directory) / "contract.md"
            contract.write_text(ONE_REQUIREMENT, encoding="utf-8")
            argument_sets = [
                ["--critique", str(contract), str(contract)],
                ["--critique", directory],
                ["--critique", "--json", str(contract)],
                ["--critique", "--check-references", str(contract)],
                [
                    "--critique",
                    "--check-external-references",
                    str(contract),
                ],
                ["--critique", "--scoresheet", str(contract)],
                ["--critique-requirement", "R-FIRST", str(contract)],
                [
                    "--critique",
                    "--critique-requirement",
                    "not-valid",
                    str(contract),
                ],
                [
                    "--critique-reasoning-effort",
                    "low",
                    str(contract),
                ],
                [
                    "--critique",
                    "--critique-reasoning-efforts",
                    "low,medium",
                    str(contract),
                ],
                [
                    "--critique",
                    "--critique-models",
                    "gpt-5.6-terra",
                    str(contract),
                ],
                ["--critique", "--quiet", str(contract)],
                [
                    "--critique-reasoning-efforts",
                    "low,medium",
                    str(contract),
                ],
                [
                    "--critique-model",
                    "gpt-5.6-terra",
                    str(contract),
                ],
                [
                    "--critique-models",
                    "gpt-5.6-terra",
                    str(contract),
                ],
                ["--quiet", str(contract)],
            ]

            for arguments in argument_sets:
                with self.subTest(arguments=arguments):
                    with redirect_stderr(io.StringIO()):
                        with self.assertRaises(SystemExit) as raised:
                            behave.main(arguments)
                    self.assertEqual(2, raised.exception.code)


if __name__ == "__main__":
    unittest.main()
