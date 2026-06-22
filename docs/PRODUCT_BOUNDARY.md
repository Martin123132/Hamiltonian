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
```

Recommended first app surface:

```text
Local cockpit with agent lanes, runtime gates, lifecycle state, and tool mesh.
```

## First Integration Order

1. Local cockpit state API.
2. Agent lanes for Codex, local shell, OpenClaw adapter, Hermes adapter.
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
