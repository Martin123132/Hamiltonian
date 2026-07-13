# Security Policy

Hamiltonian is a local-first public alpha for routing, supervising, and reviewing agent work. It stores task packets, local runner artifacts, goal handoffs, receipts, and optional evidence references in operator-selected local directories.

Hamiltonian applies bounded path checks and best-effort redaction for common credentials, private URLs, and local paths. These controls are safety layers, not a guarantee that arbitrary agent output is safe to publish.

## Supported Versions

Only the current `master` branch and latest release are supported during the public alpha.

## Reporting A Vulnerability

Do not open a public issue containing exploit details, credentials, private source code, task packets, receipts, evidence bundles, crash reports, or runner output.

Use GitHub private vulnerability reporting when it is available. If you already have a commercial or evaluation contact with TWO HANDS NETWORK LTD, use that private channel. Otherwise, open a minimal issue requesting a private security contact without technical details.

Include privately:

- the affected Hamiltonian version or commit;
- operating system and Python version;
- the adapter, packet stage, API route, or desktop workflow involved;
- whether private source, credentials, task text, runner output, evidence, or local paths were exposed;
- impact and reproduction notes.

## In Scope

- path traversal or repository-boundary escape;
- unintended local file disclosure through packets, exports, receipts, comparisons, goals, crash reports, or release artifacts;
- command execution without explicit operator action;
- gateway, delivery, SSH, Docker, telemetry, or other remote behavior contrary to a declared local-only boundary;
- evidence creation when evidence was not explicitly selected;
- secrets or private paths written to public-facing artifacts;
- release-manifest, checksum, receipt, or capability-boundary integrity failures.

## Operational Safety

- Treat `.hamiltonian/` as potentially sensitive and do not commit it.
- Review every exported handoff or receipt before sharing it.
- Keep model and CLI credentials outside Hamiltonian.
- Use only repositories and adapters you are authorized to access.
- Treat the Windows package as unsigned until its release manifest says otherwise.
- Rotate any credential that appears in an artifact or agent response.

Licensing and commercial-use disputes are outside the security-reporting process. See [NOTICE.md](NOTICE.md).
