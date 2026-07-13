# Contributing

Hamiltonian welcomes ideas, bug reports, safety findings, adapter proposals, and patches that fit its local-first, evidence-aware direction.

By submitting a pull request, patch, issue comment containing code, or other contribution, you agree that:

- you have the right to submit the contribution;
- your contribution is your own original work, or you clearly identify any third-party material and its license;
- your contribution is licensed to the project under the same public license as Hamiltonian;
- TWO HANDS NETWORK LTD may also use, modify, distribute, sublicense, and relicense your contribution as part of Hamiltonian, including under separate commercial licenses;
- your contribution is provided without warranty.

Do not submit secrets, API keys, private repository data, customer data, task packets, result receipts, evidence bundles, crash reports, or code copied from a source whose license is incompatible with Hamiltonian.

If you do not agree to these terms, open an issue describing the idea without including code.

## Pull Requests

- Keep changes bounded and explain the operator impact.
- Preserve local-only execution and explicit approval boundaries.
- Add focused regression tests for changed behavior.
- Run `python -m pytest -q`, Python compilation, relevant JavaScript syntax checks, and `git diff --check`.
- Do not weaken secret redaction, path containment, optional evidence, or no-remote-execution controls.
- Do not add automatic installs, credential handling, background services, telemetry, or public publishing behavior without explicit maintainers' approval.

Commercial-use questions belong in private correspondence, not pull requests. See [NOTICE.md](NOTICE.md).
