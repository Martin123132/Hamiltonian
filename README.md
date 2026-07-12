# Hamiltonian

**Run any agent. Trust none. Keep evidence when it matters.**

Hamiltonian is a local-first operator cockpit for agent work. Describe the
result you want, run a bounded local check, hand the resulting goal to the
correct Codex project, and bring the completion receipt back for independent
review.

![Hamiltonian Mission Home](docs/images/mission-home-desktop.jpg)

The normal path stays deliberately simple:

1. Write the job in plain language.
2. Press **Run locally**.
3. Turn a useful result into a Maintenance or Expansion goal.
4. Let Hamiltonian detect the return receipt and review the completed work.

All application state stays in the selected repository or D-drive data
directory. The cockpit binds only to `127.0.0.1`, remote command execution is
off, and evidence remains optional unless the operator selects it.

## How It Works

### 1. Run a bounded local check

Hamiltonian saves a task packet, evaluates its local safety, memory, and cost
gates, then launches the selected local Codex lane only after the operator
presses **Run locally**.

![Completed Hamiltonian health check](docs/images/health-check-desktop.jpg)

### 2. Hand production work to the correct Codex project

**Get Codex goal** creates one bounded handoff with a workspace lock, baseline
commit, acceptance criteria, verification requirements, and a local return
receipt path.

| Goal | Use it for |
| --- | --- |
| **Maintenance** | Resolve confirmed findings and raise the current health result one defensible step. |
| **Expansion** | Add or extend one clearly bounded capability while preserving the current baseline. |

Hamiltonian copies the goal and can open the repository in Codex, but the user
still chooses the destination project task. It never injects work into another
task automatically.

### 3. Review the return receipt

When Codex writes `return.json`, Goal history notices it automatically and
shows **Review now**. Hamiltonian then runs a local, read-only check against the
saved baseline and acceptance criteria.

![Goal ready for review](docs/images/goal-ready-desktop.jpg)

### 4. Correct incomplete work without losing the thread

An incomplete review produces a focused corrective goal. Parent, lineage root,
correction number, receipt, review, and grade movement remain visible in one
history.

![Corrective goal lineage](docs/images/corrective-lineage-desktop.jpg)

## Desktop Experience

The native Windows shell opens on a workspace launcher, remembers recent local
repositories, and highlights goals that are ready for review. The same core
workflow adapts to a narrow mobile-sized viewport for remote desktop or compact
windows.

<table>
  <tr>
    <td width="66%"><img alt="Hamiltonian desktop workspace launcher" src="docs/images/desktop-launcher.jpg"></td>
    <td width="34%"><img alt="Hamiltonian compact Mission Home" src="docs/images/mission-home-mobile.jpg"></td>
  </tr>
</table>

## Version 0.4.1

- Mission Home `Auto / Codex / Hermes` worker selector with live local readiness.
- Task-aware Auto routing that chooses only callable Codex or Hermes adapters.
- Plain setup guidance when an adapter is unavailable, without installing tools or handling credentials.
- Lane-aware one-button progress, cancellation, failure, and result states on desktop and mobile.
- First callable non-Codex lane through the official Hermes Agent one-shot CLI.
- Hermes safe mode, checkpoints, bounded turns, explicit launch, timeout, cancellation, and local reports.
- Safe unavailable fallback when Hermes is not installed or its configured command cannot be probed.
- Lane-aware packet controls and a Windows Edge smoke journey covering Codex and Hermes.
- Read-only GitHub Actions checks on Python 3.10 and 3.13.
- Deterministic Windows browser-smoke verification with screenshot artifacts.
- Reproducible Windows portable ZIP, release manifest, and SHA-256 checksum.
- Tag packaging with release publication gated by an explicit manual boolean.
- Native Windows WebView2 desktop shell and D-drive-first storage.
- One-button local Codex workflow with cancellation and bounded runner state.
- Maintenance and Expansion goal handoffs.
- Automatic receipt discovery and local review recording.
- Corrective goals with parent and grade lineage.
- Goal status in Mission Home and the desktop launcher.
- Optional AgentLedger evidence boundary with no remote execution.

## Product Boundary

Hamiltonian is the orchestration and review layer. Its core unit is the task
packet: intent, selected lane, local gate results, execution state, handoff, and
optional evidence references.

AgentLedger remains a separate flight recorder for capturing what happened and
producing evidence bundles. Hamiltonian only represents AgentLedger when the
operator selects evidence or recorder mode.

Codex, OpenClaw, Hermes, and the local runner are adapter lanes. Route advice is
metadata, not execution authority. Prototype adapters stay local, degrade
safely when unavailable, and do not scrape private repositories or enable
remote commands.

The name nods to Margaret Hamilton's correctness-under-pressure flight software
and William Rowan Hamilton's language of state, trajectories, and action.

## Quick Start

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
D:\Codex\Builds\Hamiltonian\Hamiltonian-windows-x64-0.4.1.zip
D:\Codex\Builds\Hamiltonian\Hamiltonian-windows-x64-0.4.1.release.json
D:\Codex\Builds\Hamiltonian\Hamiltonian-windows-x64-0.4.1.sha256
```

The shortcut opens the workspace launcher and points its application data at
`D:\Codex\Data\Hamiltonian`. The build manifest and checksum provide the
versioned verification boundary needed for a future manual updater. No remote
update check or background update service is enabled.

Every pull request now runs the complete test matrix, the real Edge browser
journey, and a Windows desktop package build. Tag pushes build reviewable
workflow artifacts but do not publish them. The separate **Package Release**
workflow only attaches the unsigned ZIP to a private GitHub release when it is
started manually with `publish` explicitly enabled.

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
4. Hamiltonian detects the receipt automatically and shows **Review now** in
   Goal history. The review runs locally against the saved baseline and
   acceptance criteria.
5. A complete review closes the goal. An incomplete review offers **Create
   corrective goal**, preserving the parent goal and grade lineage.

Goal packages remain local under:

```text
.hamiltonian/goals/<goal-id>/
  goal.md
  goal.json
  source-report.md
  return.json
  review-report.md
  review.json
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
      state.json
      events.jsonl
      runner-output.log
      last-message.txt
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

Mission Home exposes `Auto`, `Codex`, and `Hermes` before the run starts. Auto
uses task-aware route advice but selects only a callable adapter. Each lane
shows `Ready` or `Unavailable` in words, and unavailable lanes explain what the
operator must configure outside Hamiltonian. Choosing a worker never installs
software, edits credentials, or starts a process; execution still requires the
main Run action.

The Hermes lane can launch the official scripted one-shot boundary only after
the same explicit operator action. Hamiltonian invokes `hermes` with safe mode,
tool source, a 24-turn cap, checkpoints, and `-z`, then supervises the process
from the selected Git workspace. It does not use `--yolo`, start a gateway or
delivery service, or enable SSH, Docker, or another remote command backend.
Hermes safe mode and checkpoints are application controls, not an OS sandbox.
Hermes may still use the model provider already configured by the operator.
[Hermes CLI reference](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/reference/cli-commands.md)

If Codex or Hermes is not callable, its plan remains visible but launch stays
disabled with the probe failure shown in the cockpit. OpenClaw and the direct
local lane still stop at the dry-run adapter contract. Runner-plan artifacts
contain a task digest and workspace name, not task text or the workspace path.
Blocked packets do not write a runner artifact.
Handoff-stage packets add a compact operator brief with lane, route, gate,
approval, and evidence state in one place.

Packets can also advance in place. Advancement preserves the packet id and
packet directory, reruns the local gates for the target stage, updates the
packet index, and appends a local history event without executing agents.

The packet stages are:

- `draft`: save the operator task and selected agent lane.
- `gate`: check memory through the RepoMori adapter boundary, then run local intent and cost gates.
- `execute`: prepare an explicit approval boundary and, for a ready Codex or Hermes lane, optionally launch one bounded local CLI run.
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

No remote command executor is used in this slice. Codex and Hermes launches are
locally supervised CLI processes; model access remains the responsibility of
the operator's existing CLI configuration. Missing Hermes, RepoMori, Jester,
Tokometer, and AgentLedger integrations degrade to explicit local fallback
states.

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
verifies unavailable guidance, Auto/Codex/Hermes selection, optional recorder
evidence, and a Hermes one-shot packet through Mission Home in a real local
Edge session. The smoke journey supplies deterministic local fakes for
the Codex and Hermes commands, so it uses no model credits or credentials. QA
packets are removed after the run. The
sanitized Mission Home, completed check, goal review, corrective lineage,
launcher, and mobile captures are written under
`D:\Codex\Temp\Hamiltonian` by default.

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
- Hermes Agent: optional local one-shot agent lane using existing provider configuration.

Missing tools are reported as warnings, not failures. That lets the wrapper work
today while the full product stack is assembled.

## Market Wedge

OpenClaw and Hermes fight over being the agent. Hamiltonian owns the layer above
the agent:

```text
Run any agent. Trust none. Keep evidence.
```

The cockpit keeps OpenClaw behind a dry-run adapter and makes Hermes its first
callable non-Codex lane. The market is not
"which agent is coolest"; the market is who operators trust to route, gate,
verify, and prove agent work across all of them.
