from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import validate


def specification(body: str) -> str:
    return f"""# Contract

Introductory prose is allowed.

### R-TEST

{body}
"""


def codes(text: str) -> list[str]:
    return [
        diagnostic.code
        for diagnostic in validate.validate_text(Path("contract.md"), text)
    ]


class StructureValidationTests(unittest.TestCase):
    def test_minimal_requirement_is_valid(self) -> None:
        text = specification(
            """#### Intent

Describe the intended outcome.

#### Behavior

- The system behaves observably.

  - Evaluate [manual]: Inspect the result."""
        )

        self.assertEqual([], codes(text))

    def test_optional_sections_are_valid(self) -> None:
        text = specification(
            """#### Intent

Describe the intended outcome.

#### Rationale

Explain why it matters.

#### References

- `validate.py`

#### Behavior

- The system behaves observably.

  - Evaluate [deterministic]: Verify the result."""
        )

        self.assertEqual([], codes(text))

    def test_intent_and_behavior_are_required(self) -> None:
        no_intent = specification(
            """#### Behavior

- It works.
  - Evaluate [manual]: Inspect."""
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

- `validate.py`

#### References

- `README.md`

#### Behavior

- It works.
  - Evaluate [manual]: Inspect."""
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
  - Evaluate [manual]: Inspect."""
        )

        self.assertEqual(["S003"], codes(text))

    def test_requirement_prose_must_follow_a_section_heading(self) -> None:
        text = specification(
            """This prose is misplaced.

#### Intent

It should work.

#### Behavior

- It works.
  - Evaluate [manual]: Inspect."""
        )

        self.assertEqual(["P001"], codes(text))

    def test_wrong_heading_level_is_rejected(self) -> None:
        text = specification(
            """Intent

It should work.

#### Behavior

- It works.
  - Evaluate [manual]: Inspect."""
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
  - Evaluate [manual]: Inspect.
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
  - Evaluate [manual]: Inspect.

- Second behavior.
  - Evaluate [manual]: Inspect."""
        )

        self.assertEqual([], codes(text))

    def test_top_level_evaluate_is_orphaned(self) -> None:
        text = specification(
            """#### Intent

It should work.

#### Behavior

- Evaluate [manual]: Inspect."""
        )

        self.assertIn("E001", codes(text))

    def test_evaluate_must_be_an_immediate_child(self) -> None:
        text = specification(
            """#### Intent

It should work.

#### Behavior

- A behavior.
  - Supporting detail.
    - Evaluate [manual]: Inspect."""
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
  - Evaluate [manual]: Inspect once.
  - Evaluate [semantic]: Inspect again."""
        )

        self.assertEqual([], codes(text))

    def test_empty_evaluation_and_unknown_type_are_rejected(self) -> None:
        text = specification(
            """#### Intent

It should work.

#### Behavior

- A behavior.
  - Evaluate [invented]:"""
        )

        result = codes(text)
        self.assertIn("E002", result)
        self.assertIn("E003", result)


class ReferenceValidationTests(unittest.TestCase):
    def test_references_stop_at_unknown_sections(self) -> None:
        text = specification(
            """#### Intent

It should work.

#### References

- `validate.py`

#### Notes

- `not-a-reference.md`

#### Behavior

- It works.
  - Evaluate [manual]: Inspect."""
        )

        self.assertEqual(
            ["validate.py"],
            [reference.target for reference in validate.local_references(text)],
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
  - Evaluate [manual]: Inspect."""
            )

            diagnostics = validate.validate_local_references(contract, text)

        self.assertEqual(["REF002"], [item.code for item in diagnostics])
        self.assertIn("missing.md", diagnostics[0].message)


if __name__ == "__main__":
    unittest.main()
