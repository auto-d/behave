from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import behave


def specification(body: str) -> str:
    return f"""# Contract

Introductory prose is allowed.

### R-TEST

{body}
"""


def codes(text: str) -> list[str]:
    return [
        diagnostic.code
        for diagnostic in behave.validate_text(Path("contract.md"), text)
    ]


class StructureValidationTests(unittest.TestCase):
    def test_minimal_requirement_is_valid(self) -> None:
        text = specification(
            """#### Intent

Describe the intended outcome.

#### Behavior

- The system behaves observably.

  - Evaluate: Inspect the result."""
        )

        self.assertEqual([], codes(text))

    def test_optional_sections_are_valid(self) -> None:
        text = specification(
            """#### Intent

Describe the intended outcome.

#### Rationale

Explain why it matters.

#### References

- `behave.py`

#### Behavior

- The system behaves observably.

  - Evaluate: Verify the result."""
        )

        self.assertEqual([], codes(text))

    def test_intent_and_behavior_are_required(self) -> None:
        no_intent = specification(
            """#### Behavior

- It works.
  - Evaluate: Inspect."""
        )
        no_behavior = specification(
            """#### Intent

It should work."""
        )

        self.assertIn("R004", codes(no_intent))
        self.assertIn("R003", codes(no_behavior))

    def test_recognized_sections_cannot_repeat(self) -> None:
        text = specification(
            """#### Intent

First.

#### Intent

Second.

#### References

- `behave.py`

#### References

- `README.md`

#### Behavior

- It works.
  - Evaluate: Inspect."""
        )

        self.assertEqual(2, codes(text).count("S002"))

    def test_unknown_section_is_rejected_without_body_cascade(self) -> None:
        text = specification(
            """#### Intent

It should work.

#### Notes

This extension is not recognized.

#### Behavior

- It works.
  - Evaluate: Inspect."""
        )

        self.assertEqual(["S003"], codes(text))

    def test_requirement_prose_must_follow_a_section_heading(self) -> None:
        text = specification(
            """This prose is misplaced.

#### Intent

It should work.

#### Behavior

- It works.
  - Evaluate: Inspect."""
        )

        self.assertEqual(["P001"], codes(text))

    def test_wrong_heading_level_is_rejected(self) -> None:
        text = specification(
            """Intent

It should work.

#### Behavior

- It works.
  - Evaluate: Inspect."""
        )

        self.assertIn("S001", codes(text))
        self.assertIn("R004", codes(text))

    def test_level_three_headings_are_reserved_for_requirements(self) -> None:
        text = """### Not-A-Requirement

#### Intent

It should work.
"""

        self.assertIn("R001", codes(text))

    def test_requirement_identifiers_must_be_unique(self) -> None:
        requirement = """### R-SAME

#### Intent

It should work.

#### Behavior

- It works.
  - Evaluate: Inspect.
"""
        text = requirement + "\n" + requirement

        self.assertIn("R002", codes(text))


class BehaviorValidationTests(unittest.TestCase):
    def test_each_top_level_bullet_is_a_behavior(self) -> None:
        text = specification(
            """#### Intent

It should work.

#### Behavior

- First behavior.
  - Evaluate: Inspect.

- Second behavior.
  - Evaluate: Inspect."""
        )

        self.assertEqual([], codes(text))

    def test_top_level_evaluate_is_orphaned(self) -> None:
        text = specification(
            """#### Intent

It should work.

#### Behavior

- Evaluate: Inspect."""
        )

        self.assertIn("E001", codes(text))

    def test_evaluate_must_be_an_immediate_child(self) -> None:
        text = specification(
            """#### Intent

It should work.

#### Behavior

- A behavior.
  - Supporting detail.
    - Evaluate: Inspect."""
        )

        result = codes(text)
        self.assertIn("E001", result)
        self.assertIn("B003", result)

    def test_sibling_evaluations_share_the_behavior_parent(self) -> None:
        text = specification(
            """#### Intent

It should work.

#### Behavior

- A behavior.
  - Evaluate: Inspect once.
  - Evaluate: Inspect again."""
        )

        self.assertEqual([], codes(text))

    def test_empty_evaluation_is_rejected(self) -> None:
        text = specification(
            """#### Intent

It should work.

#### Behavior

- A behavior.
  - Evaluate [invented]:"""
        )

        self.assertEqual(["E002"], codes(text))

    def test_annotation_hints_are_accepted_without_interpretation(self) -> None:
        text = specification(
            """#### Intent

It should work.

#### Behavior

- The system grounds its conclusions.
  - Evaluate [evidence=calendar, tasks]: Each conclusion is supported by the available records."""
        )

        self.assertEqual([], codes(text))


class ReferenceValidationTests(unittest.TestCase):
    def test_references_stop_at_unknown_sections(self) -> None:
        text = specification(
            """#### Intent

It should work.

#### References

- `behave.py`

#### Notes

- `not-a-reference.md`

#### Behavior

- It works.
  - Evaluate: Inspect."""
        )

        self.assertEqual(
            ["behave.py"],
            [reference.target for reference in behave.local_references(text)],
        )

    def test_local_reference_existence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            existing = root / "existing.md"
            existing.touch()
            contract = root / "contract.md"
            text = specification(
                """#### Intent

It should work.

#### References

- `existing.md`
- `missing.md`

#### Behavior

- It works.
  - Evaluate: Inspect."""
            )

            diagnostics = behave.validate_local_references(contract, text)

        self.assertEqual(["REF002"], [item.code for item in diagnostics])
        self.assertIn("missing.md", diagnostics[0].message)


class RequirementExtractionTests(unittest.TestCase):
    document = """# Contract

### R-FIRST

#### Intent

First intent.

#### Behavior

- First behavior.
  - Evaluate: Inspect.

### R-SECOND

#### Intent

Second intent.

#### Behavior

- Second behavior.
  - Evaluate: Inspect.
"""

    def test_extracts_exact_requirement_boundaries(self) -> None:
        excerpts = behave.requirement_excerpts(
            Path("contract.md"),
            self.document,
            "R-FIRST",
        )

        self.assertEqual(1, len(excerpts))
        self.assertEqual(3, excerpts[0].line)
        self.assertTrue(excerpts[0].markdown.startswith("### R-FIRST\n"))
        self.assertNotIn("R-SECOND", excerpts[0].markdown)

    def test_extracts_last_requirement_through_end_of_file(self) -> None:
        excerpt = behave.requirement_excerpts(
            Path("contract.md"),
            self.document,
            "R-SECOND",
        )[0]

        self.assertIn("Second behavior.", excerpt.markdown)
        self.assertTrue(excerpt.markdown.endswith("\n"))

    def test_missing_requirement_returns_no_excerpt(self) -> None:
        self.assertEqual(
            [],
            behave.requirement_excerpts(
                Path("contract.md"),
                self.document,
                "R-MISSING",
            ),
        )

    def test_duplicate_requirement_is_ambiguous(self) -> None:
        duplicate = self.document + "\n" + self.document

        self.assertEqual(
            2,
            len(
                behave.requirement_excerpts(
                    Path("contract.md"),
                    duplicate,
                    "R-FIRST",
                )
            ),
        )

    def test_lists_requirements_in_document_order(self) -> None:
        summaries = behave.requirement_summaries(
            Path("contract.md"),
            self.document,
        )

        self.assertEqual(
            ["R-FIRST", "R-SECOND"],
            [summary.identifier for summary in summaries],
        )
        self.assertEqual([3, 14], [summary.line for summary in summaries])

    def test_list_cli_prints_ids_and_json_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            contract = Path(directory) / "contract.md"
            contract.write_text(self.document, encoding="utf-8")

            plain_output = io.StringIO()
            with redirect_stdout(plain_output):
                plain_status = behave.main(
                    ["--list-requirements", str(contract)]
                )

            json_output = io.StringIO()
            with redirect_stdout(json_output):
                json_status = behave.main(
                    ["--json", "--list-requirements", str(contract)]
                )

        self.assertEqual(0, plain_status)
        self.assertEqual(
            ["R-FIRST", "R-SECOND"],
            plain_output.getvalue().splitlines(),
        )
        self.assertEqual(0, json_status)
        payload = json.loads(json_output.getvalue())
        self.assertEqual(
            ["R-FIRST", "R-SECOND"],
            [item["identifier"] for item in payload],
        )
        self.assertEqual([3, 14], [item["line"] for item in payload])
        self.assertTrue(all(item["path"] == str(contract) for item in payload))

    def test_list_cli_preserves_duplicate_ids(self) -> None:
        duplicate = self.document + "\n" + self.document
        with tempfile.TemporaryDirectory() as directory:
            contract = Path(directory) / "contract.md"
            contract.write_text(duplicate, encoding="utf-8")

            output = io.StringIO()
            with redirect_stdout(output):
                status = behave.main(
                    ["--list-requirements", str(contract)]
                )

        self.assertEqual(0, status)
        self.assertEqual(2, output.getvalue().splitlines().count("R-FIRST"))

    def test_cli_prints_markdown_and_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            contract = Path(directory) / "contract.md"
            contract.write_text(self.document, encoding="utf-8")

            plain_output = io.StringIO()
            with redirect_stdout(plain_output):
                plain_status = behave.main(
                    ["--show-requirement", "R-FIRST", str(contract)]
                )

            json_output = io.StringIO()
            with redirect_stdout(json_output):
                json_status = behave.main(
                    [
                        "--json",
                        "--show-requirement",
                        "R-SECOND",
                        str(contract),
                    ]
                )

        self.assertEqual(0, plain_status)
        self.assertTrue(plain_output.getvalue().startswith("### R-FIRST\n"))
        self.assertEqual(0, json_status)
        payload = json.loads(json_output.getvalue())
        self.assertEqual("R-SECOND", payload["identifier"])
        self.assertEqual(14, payload["line"])
        self.assertIn("Second behavior.", payload["markdown"])

    def test_cli_reports_missing_and_duplicate_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            contract = Path(directory) / "contract.md"
            contract.write_text(self.document, encoding="utf-8")

            missing_error = io.StringIO()
            with redirect_stderr(missing_error):
                missing_status = behave.main(
                    ["--show-requirement", "R-MISSING", str(contract)]
                )

            contract.write_text(
                self.document + "\n" + self.document,
                encoding="utf-8",
            )
            duplicate_error = io.StringIO()
            with redirect_stderr(duplicate_error):
                duplicate_status = behave.main(
                    ["--show-requirement", "R-FIRST", str(contract)]
                )

        self.assertEqual(1, missing_status)
        self.assertIn("R005", missing_error.getvalue())
        self.assertEqual(1, duplicate_status)
        self.assertIn("R002", duplicate_error.getvalue())


if __name__ == "__main__":
    unittest.main()
