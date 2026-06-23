# Hamiltonian

Flight software for agentic systems.

Hamiltonian is the operator layer above AI agents. It gives the user a local
cockpit for assigning work, choosing an agent lane, checking memory/policy/cost
gates, and attaching evidence only when a run needs it.

The name points in two directions:

- Margaret Hamilton: flight software, Apollo, correctness under pressure.
- William Rowan Hamilton: state, motion, trajectories, energy, and action.

That is the product: agent actions with state, cost, risk, memory, and proof.
AgentLedger is one instrument in that cockpit, not the cockpit itself.

## Product Boundary

Hamiltonian is separate from AgentLedger.

AgentLedger remains the clean flight recorder: capture what happened, keep
evidence, produce bundles. Hamiltonian is the policy/orchestration layer for
users who want more on top: gates, budget posture, repo memory, compression
evidence, and release checks.

Hamiltonian can call AgentLedger when the user wants flight-recorder evidence,
but it does not require AgentLedger as the product home.

Hamiltonian's core unit is the task packet: task intent, selected lane, local
gate results, handoff state, and optional evidence references. If a feature
mainly records a run, it belongs behind the AgentLedger evidence boundary. If it
routes, gates, budgets, verifies, or hands off work across agents, it belongs in
Hamiltonian.

Hamiltonian is not a remote execution service and not a repo scraper. Prototype
adapters stay local, degrade safely when missing, and write sanitized metadata
unless a later operator mode explicitly asks for more.

## Run

```powershell
python -m pip install -e .
hamiltonian cockpit --repo .
python .\scripts\run-cockpit.py --repo .
hamiltonian doctor --repo .
hamiltonian run --repo . -- python -c "print('hello Hamiltonian')"
hamiltonian run --repo . --runner agentledger -- python -m pytest
```

The cockpit starts a local web app at:

```text
http://127.0.0.1:8765
```

## Task Packets

The cockpit now persists local task packets under:

```text
.hamiltonian/tasks/<packet-id>/
  task-packet.json
  task-packet.md
  evidence/
    agentledger-placeholder.json
```

Each packet includes an explicit lane assignment and gate-run summary. The lane
records which adapter was selected and confirms that remote execution stayed off
in the prototype. The gate run records counts, blocked gates, simulated gates,
and the next operator action. Execute-stage packets also include an execution
boundary that can be awaiting approval or blocked while keeping local and remote
execution off. Handoff-stage packets add a compact operator brief with lane,
gate, approval, and evidence state in one place.

The packet stages are:

- `draft`: save the operator task and selected agent lane.
- `gate`: check memory through the RepoMori adapter boundary, then run local intent and cost gates.
- `execute`: prepare a dry-run/manual approval boundary without running an agent or command.
- `handoff`: prepare a local operator handoff brief without running an agent or command.
- `record`: run the same gates and attach a local AgentLedger evidence placeholder.

The cockpit exposes recent packet summaries through `/api/packets` and full
packet detail through `/api/packets/<packet-id>`. Detail reads stay inside the
repo-local task packet store.

Packet detail can export a sanitized handoff markdown file to:

```text
.hamiltonian/tasks/<packet-id>/handoff-export.md
```

The export omits repo paths, packet storage paths, artifact paths, file
contents, credentials, and remote URLs.

No remote agent execution happens in this prototype slice. Missing RepoMori,
Jester, Tokometer, and AgentLedger integrations degrade to explicit local
fallback gate results.

The RepoMori adapter is privacy-preserving in this slice: it writes sanitized
metadata only, with no file contents, private path names, credentials, URLs, or
remote calls. If RepoMori is installed, Hamiltonian marks the adapter boundary as
ready but still does not execute the external tool yet.

The lower-level `run` command still writes:

```text
.hamiltonian/runs/<timestamp>/
  hamiltonian-report.md
  hamiltonian-report.json
  manifest.json
  artifacts/
    command.stdout.txt
    command.stderr.txt
    git-status-before.txt
    git-status-after.txt
    git-diff-after.patch
```

## Optional Integrations

The prototype detects these tools if already installed:

- AgentLedger: evidence bundles for agent work sessions.
- RepoMori: compact repo memory.
- Memento Mori Jester: plan, command, diff, and final-answer safety checks.
- Tokometer: local Codex token burn posture.
- TokenSquash: measurable prompt/reply compression.
- Sentinel Manifold: release-gate / behavior-regression proof layer.

Missing tools are reported as warnings, not failures. That lets the wrapper work
today while the full product stack is assembled.

## Market Wedge

OpenClaw and Hermes fight over being the agent. Hamiltonian owns the layer above
the agent:

```text
Run any agent. Trust none. Keep evidence.
```

The first cockpit treats OpenClaw and Hermes as adapter lanes. The market is not
"which agent is coolest"; the market is who operators trust to route, gate,
verify, and prove agent work across all of them.
