from __future__ import annotations

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
            "two sentences": (
                "## R-FIRST\n\n### Finding 1: B1.E1\n\n"
                "**Problem:** One issue exists. Another issue exists."
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
        ) as mocked_urlopen:
            output = behave.request_critique(
                "secret-key",
                "system instructions",
                requirement,
            )

        request = mocked_urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        requirement_input = json.loads(payload["input"])

        self.assertEqual(no_findings("R-FIRST"), output)
        self.assertEqual("gpt-5.6-sol", payload["model"])
        self.assertEqual({"effort": "high"}, payload["reasoning"])
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


class CritiqueReportTests(unittest.TestCase):
    def test_report_calls_once_per_requirement_in_document_order(self) -> None:
        identifiers: list[str] = []

        def respond(
            api_key: str,
            instructions: str,
            requirement: behave.RequirementExcerpt,
            timeout: float = behave.CRITIQUE_TIMEOUT,
        ) -> str:
            identifiers.append(requirement.identifier)
            return no_findings(requirement.identifier)

        with mock.patch("behave.request_critique", side_effect=respond):
            report, failures = behave.generate_critique_report(
                Path("contract.md"),
                TWO_REQUIREMENTS,
                "prompt\n",
                "protocol\n",
                "secret-key",
            )

        self.assertEqual(["R-FIRST", "R-SECOND"], identifiers)
        self.assertEqual([], failures)
        self.assertLess(report.index("## R-FIRST"), report.index("## R-SECOND"))
        self.assertIn("> Model: `gpt-5.6-sol`", report)
        self.assertIn("> Reasoning effort: `high`", report)

    def test_report_continues_after_request_and_template_failures(self) -> None:
        with mock.patch(
            "behave.request_critique",
            side_effect=[
                behave.CritiqueError("offline"),
                "## R-SECOND\n\nExtra prose.",
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
            ]

            for arguments in argument_sets:
                with self.subTest(arguments=arguments):
                    with redirect_stderr(io.StringIO()):
                        with self.assertRaises(SystemExit) as raised:
                            behave.main(arguments)
                    self.assertEqual(2, raised.exception.code)


if __name__ == "__main__":
    unittest.main()
