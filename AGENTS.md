# Project Instructions

- `PROTOCOL.md` is the authoritative definition of the Behave specification
  language. Make semantic protocol changes there first.
- `behave.py` implements the structural rules in `PROTOCOL.md`; keep the tool
  synchronized with the protocol.
- `README.md` explains and demonstrates the protocol. It may summarize
  `PROTOCOL.md`, but must link to it and must not contradict it.
- `CRITIQUE_PROMPT.md` defines the optional LLM critic's scope and output
  contract. Keep it synchronized with the critique response validator,
  `README.md`, and tests.
- The critic is diagnostic only. It may identify material evaluability
  problems, but must not recommend revisions or introduce governing intent.
- `example.md` must remain a current, valid example of `PROTOCOL.md`.
- Implement a unit test after every feature revision.
- After changing the protocol, tool, README, or example, run:

  ```sh
  python3 behave.py example.md
  python3 -m unittest
  ```

- After substantive changes, ask the user for permission, then commit and push.
