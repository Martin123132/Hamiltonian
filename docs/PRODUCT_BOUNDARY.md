# Product Boundary

Hamiltonian should ship as its own package/repository.

## Why

AgentLedger already has a clean promise:

```text
Local-first black box recorder for AI coding agents.
```

Some users only want that. They do not want policy gates, memory systems, cost
governors, release checks, compression experiments, dashboards, or anything that
feels like another agent framework.

Hamiltonian has a different promise:

```text
Run any agent. Trust none. Keep evidence.
```

That includes evidence, but the product is broader: an agent cockpit/runtime
with memory, policy gates, budget posture, tool routing, verification, and
handoff state. It should not dilute AgentLedger's simple wedge.

The name points to Margaret Hamilton's flight software discipline and William
Rowan Hamilton's mathematics of state, motion, energy, and action.

## Relationship

AgentLedger is an optional integration.

Hamiltonian can call:

```powershell
agentledger run --repo . -- <command>
```

when a user selects the flight-recorder runner.

Hamiltonian may also read AgentLedger reports or point to AgentLedger
bundles. It should not require AgentLedger for the basic direct runner.

In the cockpit prototype, task packets are local first. The evidence gate writes
an AgentLedger placeholder only when the operator selects evidence. It does not
execute agents, transmit credentials, or publish data.

The RepoMori memory gate is the first adapter boundary. In this slice it writes
only sanitized local metadata: counts, extension mix, git availability, and
privacy flags. It does not read file contents, store private path names, call
remote services, or execute RepoMori.

Hermes Agent is the first callable non-Codex lane. Hamiltonian uses Hermes's
official scripted one-shot CLI with safe mode, checkpoints, a bounded turn
count, and an explicit operator launch. Hamiltonian does not install Hermes,
configure credentials, enable `--yolo`, start gateway or delivery services, or
enable remote terminal backends. Hermes safe mode is an application boundary,
not an OS sandbox, and model access still comes from the operator's existing
Hermes provider configuration.

## Product Contract

Hamiltonian owns the operator cockpit and runtime boundary above agents. Its
core job is to turn an operator's intent into a local task packet, assign that
packet to an adapter lane, run memory/safety/cost/evidence gates, and make the
state visible enough that the operator can decide what happens next.

The durable unit of work is the task packet, not the transcript. Packets should
capture:

- the operator task
- the selected lane or adapter
- the lane assignment and execution boundary
- gate decisions and fallback reasons
- the gate-run status and next operator action
- the execution boundary and approval requirement
- handoff state and next-step recommendation
- optional evidence references

Evidence can enrich a packet, but evidence is not the product boundary.

Packet detail views should render from the local task packet store. They should
not become arbitrary file browsers or expose private source content.

The packet index is a local manifest/cache for recent packet summaries. It is
not a remote telemetry feed and should be rebuilt from packet files if missing
or invalid.

CLI packet commands should create, read, repair, and write the same local packet
store as the cockpit, without adding remote execution, telemetry, or
publication behavior.

Packet advancement should preserve the packet id and packet directory, append a
local history event, rerun local gates for the target stage, and keep remote
execution off.

Packet exports are local handoff briefs. They should be sanitized, regenerated
inside the packet directory, and treated as operator notes rather than public
release material.

## Non-Goals

Hamiltonian should not become:

- a clone of AgentLedger or any other flight recorder
- a single-agent client for OpenClaw, Hermes, Codex, or one preferred runner
- a remote execution service
- a repo scraper that stores private source text by default
- a public telemetry collector
- a framework that requires every optional tool before it can start

If a feature mainly records what happened, it belongs behind the optional
evidence boundary. If a feature routes, gates, budgets, verifies, or hands off
agent work, it belongs in Hamiltonian.

## Adapter Contract

Every adapter lane should follow the same local-first contract:

1. Detect whether the tool is available.
2. Return a structured status when unavailable.
3. Use sanitized fallback data when useful.
4. Do not enable remote command execution; model-provider access may use the operator's existing agent configuration.
5. Avoid reading or storing private file contents unless a later mode asks for
   it clearly.
6. Keep credentials out of packets, logs, docs, screenshots, and demos.

RepoMori is the first memory adapter and Hermes is the first callable agent
adapter. The next adapters should prove the same boundary for command safety,
cost posture, compression, release gates, and additional agent lanes.

## Package Shape

Recommended package/repo:

```text
hamiltonian
```

Recommended CLI:

```powershell
hamiltonian cockpit --repo .
hamiltonian doctor --repo .
hamiltonian run --repo . -- <command>
hamiltonian run --repo . --runner agentledger -- <command>
hamiltonian packets --repo . create --task "Draft a local packet"
hamiltonian packets --repo . advance <packet-id> --stage gate
hamiltonian packets --repo . list
hamiltonian packets --repo . rebuild-index
```

Recommended first app surface:

```text
Local cockpit with agent lanes, runtime gates, lifecycle state, and tool mesh.
```

## First Integration Order

1. Local cockpit state API.
2. Agent lanes for Codex, local shell, OpenClaw dry-run adapter, and callable Hermes adapter.
3. RepoMori memory adapter boundary with sanitized fallback snapshot.
4. Jester pre-run command gate.
5. Tokometer usage snapshot.
6. TokenSquash compact-summary artifact.
7. Sentinel release-gate suite.
8. Optional AgentLedger runner and evidence packet.

## Guardrail

Do not make the standalone control plane depend on all optional tools at import
time. Every integration should degrade to a warning with a clear install path.

Do not reduce Hamiltonian to another flight recorder. The recorder is a module.
The durable wedge is operating control above any agent.
