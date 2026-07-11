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

Hamiltonian now keeps local lane contracts and route recommendations. The
operator can still select Codex, OpenClaw, Hermes, or the local runner, but the
packet records what Hamiltonian recommended, why, and whether the selected lane
is an override. Route advice is metadata only; it does not authorize remote
execution.

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
hamiltonian packets --repo . create --task "Draft a local packet" --agent codex
hamiltonian packets --repo . advance <packet-id> --stage gate
hamiltonian packets --repo . list
hamiltonian packets --repo . rebuild-index
hamiltonian packets --repo . detail <packet-id>
hamiltonian packets --repo . export <packet-id>
```

The cockpit starts a local web app at:

```text
http://127.0.0.1:8765
```

### Windows Desktop

Install the optional desktop shell and open Hamiltonian in its own native
WebView2 window:

```powershell
python -m pip install -e ".[desktop]"
hamiltonian desktop --repo D:\Codex\Projects\YourProject --data-dir D:\Codex\Data\Hamiltonian
```

Omit `--repo` to start on the desktop workspace launcher. It lists up to eight
recent local repositories and provides a native folder picker. Recent paths are
stored only in the selected desktop data directory; missing folders are removed
from the list automatically.

Desktop mode allows one Hamiltonian instance at a time, binds an ephemeral port
on `127.0.0.1`, locks every API request to the repository chosen for that
window, keeps WebView storage in the selected data directory, and stops the
local server when the window closes. Remote execution remains off.

Build a portable Windows application entirely under `D:` with:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build-windows-app.ps1
```

The default executable is written to:

```text
D:\Codex\Builds\Hamiltonian\dist\Hamiltonian\Hamiltonian.exe
```

The build also writes:

```text
D:\Codex\Builds\Hamiltonian\Hamiltonian.lnk
D:\Codex\Builds\Hamiltonian\dist\Hamiltonian\build-info.json
D:\Codex\Builds\Hamiltonian\dist\Hamiltonian\SHA256SUMS.txt
```

The shortcut opens the workspace launcher and points its application data at
`D:\Codex\Data\Hamiltonian`. The build manifest and checksum provide the
versioned verification boundary needed for a future manual updater. No remote
update check or background update service is enabled.

The packaged app uses a `data` directory beside the executable unless
`HAMILTONIAN_HOME` or `--data-dir` is supplied. It does not use `%APPDATA%` for
its WebView profile. The build also generates and embeds the Hamiltonian app
icon without writing packaging caches to `C:`.

Desktop runtime failures write sanitized local reports under
`<data-dir>\crashes\`. Reports omit absolute paths, secret-like values, file
contents, environment variables, and remote URLs. They are never uploaded.

The normal cockpit flow is deliberately short:

1. Write the result you want in the large task field on Home.
2. Press **Run locally**.
3. Read the result under **Check**, **Run**, and **Done**.

Hamiltonian chooses the Codex lane, creates the execute packet, runs the local
gates, and launches the bounded runner through that single action. Press the
same button while a job is running to stop it. Evidence, timeout, and the older
manual cockpit are available under **Options**; they are not required for the
normal path. When the Codex CLI cannot be called, Home says so directly and
keeps the checked packet available through **Open details**.

## Codex Goal Handoff

After Hamiltonian completes a check, **Get Codex goal** turns the result into a
bounded production handoff:

1. Choose **Maintenance** to raise the current result one defensible grade step,
   or **Expansion** and state the capability that should become possible.
2. Review, copy, or save the generated goal. **Open in Codex** copies it and
   opens the repository in the Codex desktop app; choose the existing project
   task and paste the goal there.
3. Codex performs the work and writes the requested local completion receipt.
4. Return to Hamiltonian and press **Review completed goal** for a read-only
   check against the saved baseline and acceptance criteria.

Goal packages remain local under:

```text
.hamiltonian/goals/<goal-id>/
  goal.md
  goal.json
  source-report.md
  return.json
```

Hamiltonian adds `.hamiltonian/` to the repository's local Git exclude file;
it does not modify tracked ignore rules. The handoff never pushes, publishes,
injects work into an existing Codex task, or enables remote execution. The user
chooses the destination project task explicitly.

Every generated goal contains a workspace lock. Codex must resolve its current
workspace and stop without changing files when it does not exactly match the
absolute path recorded by Hamiltonian.

## Task Packets

The cockpit now persists local task packets under:

```text
.hamiltonian/tasks/<packet-id>/
  task-packet.json
  task-packet.md
  runner/
    runner-plan.json
    latest-run.json
    runs/<run-id>/
      run-state.json
      events.jsonl
      final-message.txt
      runner-report.json
  evidence/
    agentledger-placeholder.json
  history.json
.hamiltonian/tasks/index.json
```

Each packet includes an explicit lane assignment and gate-run summary. The lane
records which adapter was selected and confirms that remote execution stayed off
in the prototype. The route decision records the recommended lane, the selected
lane, confidence, reasons, warnings, and the local-only routing policy. The gate
run records counts, blocked gates, simulated gates, and the next operator
action. Execute-stage packets also include an execution boundary that can be
awaiting approval or blocked while keeping local and remote execution off.
Clear execute packets now persist a sanitized runner plan behind a shared
`prepare`, `launch`, `stream`, `cancel`, `finish`, and `report` adapter contract.
The Codex lane can launch `codex exec` only after an explicit operator action,
inside the selected Git workspace, with `workspace-write`, approvals disabled
for the child process, an operator-selected timeout, and remote command
execution off. Hamiltonian supervises the local process, supports cancellation,
and stores capped, sanitized lifecycle events plus the final response. It never
uses the Codex danger-full-access or sandbox-bypass flags.

If the Codex CLI is not callable, the plan remains visible but launch stays
disabled with the probe failure shown in the cockpit. Other lanes still stop at
the adapter contract. Runner-plan artifacts contain a task digest and workspace
name, not task text or the workspace path. Blocked packets do not write a runner
artifact.
Handoff-stage packets add a compact operator brief with lane, route, gate,
approval, and evidence state in one place.

Packets can also advance in place. Advancement preserves the packet id and
packet directory, reruns the local gates for the target stage, updates the
packet index, and appends a local history event without executing agents.

The packet stages are:

- `draft`: save the operator task and selected agent lane.
- `gate`: check memory through the RepoMori adapter boundary, then run local intent and cost gates.
- `execute`: prepare an explicit approval boundary and, for a ready Codex lane, optionally launch one bounded local CLI run.
- `handoff`: prepare a local operator handoff brief after gates and any launched run are complete.
- `record`: run the same gates and attach a local AgentLedger evidence placeholder.

The cockpit exposes recent packet summaries through `/api/packets`, full packet
detail through `/api/packets/<packet-id>`, and local runner lifecycle controls
through `/api/packets/<packet-id>/run` and
`/api/packets/<packet-id>/run/cancel`. Reads and writes stay inside the
repo-local task packet store.

Recent packet listings use `.hamiltonian/tasks/index.json` first and rebuild it
from packet files when the index is missing or invalid.

The same packet create, advance, list, index rebuild, detail, and sanitized
export surfaces are available from the CLI through `hamiltonian packets`.

Packet detail can export a sanitized handoff markdown file to:

```text
.hamiltonian/tasks/<packet-id>/handoff-export.md
```

The export omits repo paths, packet storage paths, artifact paths, file
contents, credentials, and remote URLs.

No remote command executor is used in this prototype slice. A Codex launch is a
local, supervised CLI process; model access remains the responsibility of the
operator's existing Codex CLI session. Missing RepoMori, Jester, Tokometer, and
AgentLedger integrations degrade to explicit local fallback gate results.

The RepoMori adapter is privacy-preserving in this slice: it writes sanitized
metadata only, with no file contents, private path names, credentials, URLs, or
remote calls. If RepoMori is installed, Hamiltonian marks the adapter boundary as
ready but still does not execute the external tool yet.

The rendered cockpit journey can be replayed in a clean temporary D-drive
workspace with the dependency-free browser smoke check:

```powershell
node scripts\cockpit_browser_smoke.mjs
```

It drives the one-button Home flow through successful completion and
cancellation, checks that only four primary navigation choices are visible, and
verifies optional recorder evidence in a real local Edge session. The smoke
journey supplies a deterministic local fake for the Codex command, so it uses no
model credits or credentials. QA packets are removed after the run; desktop and
mobile screenshots are written under `D:\Codex\Temp\Hamiltonian` by default.

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
