const state = {
  repo: new URLSearchParams(window.location.search).get("repo") || "",
  data: null,
  packetMode: "draft",
  lastPacket: null,
  selectedPacket: null,
};

const $ = (selector) => document.querySelector(selector);

function statusClass(value) {
  const lowered = String(value || "").toLowerCase();
  if (
    lowered.includes("ready") ||
    lowered.includes("wired") ||
    lowered.includes("pass") ||
    lowered.includes("recorded") ||
    lowered.includes("represented") ||
    lowered.includes("gated") ||
    lowered.includes("checked")
  ) {
    return "ready";
  }
  if (
    lowered.includes("planned") ||
    lowered.includes("module") ||
    lowered.includes("pending") ||
    lowered.includes("simulated") ||
    lowered.includes("skipped") ||
    lowered.includes("draft") ||
    lowered.includes("warn")
  ) {
    return "planned";
  }
  if (lowered.includes("block") || lowered.includes("missing")) return "missing";
  return "neutral";
}

function pill(text) {
  const span = document.createElement("span");
  span.className = `pill ${statusClass(text)}`;
  span.textContent = text;
  return span;
}

function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function renderAgents(data) {
  const select = $("#agent-select");
  const selected = select.value;
  const list = $("#agent-list");
  clear(select);
  clear(list);
  data.agents.forEach((agent) => {
    const option = document.createElement("option");
    option.value = agent.id;
    option.textContent = agent.name;
    select.appendChild(option);

    const row = document.createElement("article");
    row.className = "lane";
    const body = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = agent.name;
    const role = document.createElement("p");
    role.textContent = `${agent.role}: ${agent.notes}`;
    body.append(name, role);
    row.append(body, pill(agent.status));
    list.appendChild(row);
  });
  if (selected && [...select.options].some((option) => option.value === selected)) {
    select.value = selected;
  }
}

function renderLifecycle(data) {
  const list = $("#lifecycle");
  clear(list);
  data.lifecycle.forEach((item) => {
    const stage = document.createElement("div");
    stage.className = "stage";
    const title = document.createElement("strong");
    title.textContent = item.step;
    const owner = document.createElement("span");
    owner.textContent = item.owner;
    const stateText = document.createElement("p");
    stateText.textContent = item.state;
    stage.append(title, owner, stateText);
    list.appendChild(stage);
  });
}

function renderGates(data) {
  const list = $("#gate-list");
  clear(list);
  data.gates.forEach((gate) => {
    const row = document.createElement("article");
    row.className = "gate";
    const title = document.createElement("strong");
    title.textContent = gate.name;
    const purpose = document.createElement("p");
    purpose.textContent = `${gate.purpose} ${gate.integration ? `Module: ${gate.integration}.` : ""}`;
    row.append(title, purpose, pill(gate.status));
    list.appendChild(row);
  });
}

function renderIntegrations(data) {
  const list = $("#integration-list");
  clear(list);
  data.integrations.forEach((integration) => {
    const row = document.createElement("article");
    row.className = "integration";
    const body = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = integration.name;
    const detail = document.createElement("p");
    detail.textContent = integration.detail;
    body.append(title, detail);
    row.append(body, pill(integration.available ? "installed" : "missing"));
    list.appendChild(row);
  });
}

function renderRecentPackets(data) {
  const list = $("#packet-list");
  clear(list);
  if (!data.recent_packets || data.recent_packets.length === 0) {
    const empty = document.createElement("article");
    empty.className = "packet";
    const body = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = "No packets yet";
    const detail = document.createElement("p");
    detail.textContent = "Draft a packet to create the first local orchestration record.";
    body.append(title, detail);
    empty.append(body, pill("empty"));
    list.appendChild(empty);
    return;
  }
  data.recent_packets.forEach((packet) => {
    const lane = packet.lane || {
      name: packet.agent_name || "Unknown lane",
      status: "unknown",
      execution: "unknown",
      remote_execution: false,
    };
    const gateRun = packet.gate_run || {
      status: packet.status || "unknown",
      completed: 0,
      total: 0,
      blocked: 0,
      simulated: 0,
      next_action: "Review packet details.",
    };
    const executionBoundary = packet.execution_boundary || {
      status: "unknown",
      mode: "legacy",
      approval_required: true,
      local_execution: false,
      remote_execution: false,
      next_action: "Review packet details.",
    };
    const handoff = packet.handoff || {
      status: "unknown",
      mode: "legacy",
      ready: false,
      evidence_status: "unknown",
      includes_evidence: false,
      next_action: "Review packet details.",
    };
    const memoryStatus = packet.memory_status || "unknown";
    const memoryMode = packet.memory_mode || "unknown";
    const evidenceStatus = packet.evidence_status || "unknown";
    const row = document.createElement("article");
    row.className = "packet";
    const body = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = `${lane.name} -> ${packet.stage}`;
    const detail = document.createElement("p");
    detail.textContent = packet.task_excerpt;
    const meta = document.createElement("p");
    const remote = lane.remote_execution ? "remote" : "local-only";
    meta.textContent = `Lane: ${lane.status} (${lane.execution}, ${remote}). Gates: ${gateRun.completed}/${gateRun.total}, blocked ${gateRun.blocked}, simulated ${gateRun.simulated}.`;
    const execution = document.createElement("p");
    const localExec = executionBoundary.local_execution ? "local execution armed" : "local execution off";
    const remoteExec = executionBoundary.remote_execution ? "remote execution armed" : "remote execution off";
    execution.textContent = `Execute: ${executionBoundary.status} (${executionBoundary.mode}). ${localExec}; ${remoteExec}.`;
    const handoffLine = document.createElement("p");
    const handoffReady = handoff.ready ? "ready" : "not ready";
    handoffLine.textContent = `Handoff: ${handoff.status} (${handoff.mode}, ${handoffReady}). Evidence: ${handoff.evidence_status}.`;
    const proof = document.createElement("p");
    proof.textContent = `Memory: ${memoryStatus} (${memoryMode}). Evidence: ${evidenceStatus}. Packet: ${packet.packet_id}`;
    const next = document.createElement("p");
    next.className = "packet-next";
    next.textContent = handoff.next_action || executionBoundary.next_action || gateRun.next_action;
    body.append(title, detail, meta, execution, handoffLine, proof, next);
    const actions = document.createElement("div");
    actions.className = "packet-actions";
    const openButton = document.createElement("button");
    openButton.type = "button";
    openButton.className = "compact-button";
    openButton.textContent = "Open";
    openButton.title = "Open packet detail";
    openButton.addEventListener("click", () => {
      loadPacketDetail(packet.packet_id).catch((error) => {
        $("#packet-detail-status").textContent = error.message;
      });
    });
    actions.append(pill(gateRun.status || packet.status), openButton);
    row.append(body, actions);
    list.appendChild(row);
  });
}

function detailRow(label, value) {
  const row = document.createElement("div");
  row.className = "detail-row";
  const key = document.createElement("strong");
  key.textContent = label;
  const val = document.createElement("span");
  val.textContent = value ?? "unknown";
  row.append(key, val);
  return row;
}

function renderPacketDetail(packet) {
  const title = $("#packet-detail-title");
  const status = $("#packet-detail-status");
  const detail = $("#packet-detail");
  const exportButton = $("#packet-export-button");
  clear(detail);

  if (!packet) {
    title.textContent = "No packet selected";
    status.textContent = "Waiting";
    exportButton.disabled = true;
    const empty = document.createElement("p");
    empty.className = "muted-line";
    empty.textContent = "No packet selected.";
    detail.appendChild(empty);
    return;
  }

  const lane = packet.lane || {};
  const gateRun = packet.gate_run || {};
  const executionBoundary = packet.execution_boundary || {};
  const handoff = packet.handoff || {};
  const handoffExport = packet.exports?.handoff_markdown || null;
  const gates = packet.gates || [];
  const evidenceGate = gates.find((gate) => gate.id === "evidence") || {};

  title.textContent = packet.packet_id || "Packet detail";
  status.textContent = packet.status || "unknown";
  exportButton.disabled = false;

  const summary = document.createElement("div");
  summary.className = "detail-grid";
  summary.append(
    detailRow("Stage", packet.stage),
    detailRow("Agent", packet.agent_name),
    detailRow("Lane", `${lane.status || "unknown"} / ${lane.execution || "unknown"}`),
    detailRow("Gate run", `${gateRun.status || "unknown"} (${gateRun.completed || 0}/${gateRun.total || 0})`),
    detailRow("Execution", `${executionBoundary.status || "unknown"} / ${executionBoundary.mode || "unknown"}`),
    detailRow("Handoff", `${handoff.status || "unknown"} / ${handoff.ready ? "ready" : "not ready"}`),
    detailRow("Evidence", evidenceGate.status || "unknown"),
    detailRow("Export", handoffExport ? `${handoffExport.filename} / sanitized` : "none"),
    detailRow("Remote execution", String(Boolean(executionBoundary.remote_execution || lane.remote_execution)))
  );

  const task = document.createElement("section");
  task.className = "detail-block";
  const taskTitle = document.createElement("strong");
  taskTitle.textContent = "Task";
  const taskBody = document.createElement("p");
  taskBody.textContent = packet.task || "";
  task.append(taskTitle, taskBody);

  const next = document.createElement("section");
  next.className = "detail-block";
  const nextTitle = document.createElement("strong");
  nextTitle.textContent = "Next";
  const nextBody = document.createElement("p");
  nextBody.textContent = handoff.next_action || executionBoundary.next_action || gateRun.next_action || "";
  next.append(nextTitle, nextBody);

  const gateList = document.createElement("div");
  gateList.className = "detail-gates";
  gates.forEach((gate) => {
    const gateItem = document.createElement("article");
    gateItem.className = "detail-gate";
    const gateTitle = document.createElement("strong");
    gateTitle.textContent = gate.name;
    const gateSummary = document.createElement("p");
    gateSummary.textContent = `${gate.status} (${gate.mode}). ${gate.summary}`;
    gateItem.append(gateTitle, gateSummary, pill(gate.status));
    gateList.appendChild(gateItem);
  });

  detail.append(summary, task, next, gateList);
}

function renderNextActions(data) {
  const list = $("#next-actions");
  clear(list);
  data.next_actions.forEach((action) => {
    const item = document.createElement("li");
    const text = document.createElement("span");
    text.textContent = action;
    item.appendChild(text);
    list.appendChild(item);
  });
}

function renderHeader(data) {
  $("#repo-input").value = data.repo;
  $("#repo-name").textContent = data.repo_name;
  $("#git-state").textContent = data.git_available ? "available" : "not a git repo";
  $("#agent-count").textContent = `${data.agents.length} lanes`;
  $("#gate-count").textContent = `${data.gates.length} gates`;
  $("#generated-at").textContent = new Date(data.generated_at).toLocaleString();
}

function renderPacket() {
  const preview = $("#packet-preview");
  const task = $("#task-input").value.trim() || "No task written.";
  const agent = $("#agent-select").selectedOptions[0]?.textContent || "No agent";
  const modeCopy = {
    draft: "Draft only.",
    gate: "Gates will run.",
    execute: "Execution boundary will be prepared without running.",
    handoff: "Operator handoff will be prepared without running.",
    record: "Evidence packet requested.",
  };
  const detail = modeCopy[state.packetMode] || "Evidence optional.";
  preview.innerHTML = "";
  const strong = document.createElement("strong");
  strong.textContent = `${state.packetMode.toUpperCase()} packet`;
  const body = document.createElement("span");
  if (state.lastPacket) {
    body.textContent = ` ${agent}: ${state.lastPacket.status}. ${detail} Saved as ${state.lastPacket.packet_id}.`;
  } else {
    body.textContent = ` ${agent}: ${task} ${detail}`;
  }
  preview.append(strong, body);
}

function render(data) {
  state.data = data;
  renderHeader(data);
  renderAgents(data);
  renderLifecycle(data);
  renderGates(data);
  renderIntegrations(data);
  renderRecentPackets(data);
  renderPacketDetail(state.selectedPacket);
  renderNextActions(data);
  renderPacket();
}

async function load(repo) {
  const params = new URLSearchParams();
  if (repo) params.set("repo", repo);
  const response = await fetch(`/api/state?${params.toString()}`);
  const data = await response.json();
  if (!response.ok || data.error) throw new Error(data.error || "State request failed");
  state.repo = data.repo;
  render(data);
}

async function loadPacketDetail(packetId) {
  if (!packetId) return;
  const params = new URLSearchParams();
  const repo = $("#repo-input").value || state.repo;
  if (repo) params.set("repo", repo);
  $("#packet-detail-status").textContent = "Loading";
  const response = await fetch(`/api/packets/${encodeURIComponent(packetId)}?${params.toString()}`);
  const data = await response.json();
  if (!response.ok || data.error) throw new Error(data.error || "Packet detail request failed");
  state.selectedPacket = data.packet;
  renderPacketDetail(data.packet);
}

async function exportSelectedPacket() {
  const packetId = state.selectedPacket?.packet_id;
  if (!packetId) {
    $("#packet-detail-status").textContent = "Select a packet first";
    return;
  }
  const params = new URLSearchParams();
  const repo = $("#repo-input").value || state.repo;
  if (repo) params.set("repo", repo);
  $("#packet-detail-status").textContent = "Exporting";
  const response = await fetch(`/api/packets/${encodeURIComponent(packetId)}/export?${params.toString()}`, {
    method: "POST",
  });
  const data = await response.json();
  if (!response.ok || data.error) throw new Error(data.error || "Packet export failed");
  state.selectedPacket = data.packet;
  renderPacketDetail(data.packet);
  $("#packet-detail-status").textContent = `Exported ${data.export.filename}`;
}

async function submitPacket(stageName) {
  const task = $("#task-input").value.trim();
  if (!task) {
    $("#packet-preview").textContent = "Write a task before creating a packet.";
    return;
  }
  state.packetMode = stageName;
  state.lastPacket = null;
  $("#packet-preview").textContent = "Saving packet...";
  const repo = $("#repo-input").value || state.repo;
  const response = await fetch("/api/packets", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      repo,
      task,
      agent_id: $("#agent-select").value || "codex",
      stage: stageName,
      attach_evidence: stageName === "record",
    }),
  });
  const data = await response.json();
  if (!response.ok || data.error) throw new Error(data.error || "Packet request failed");
  state.lastPacket = data.packet;
  state.selectedPacket = data.packet;
  await load(repo);
}

$("#repo-form").addEventListener("submit", (event) => {
  event.preventDefault();
  load($("#repo-input").value).catch((error) => {
    $("#packet-preview").textContent = error.message;
  });
});

$("#draft-button").addEventListener("click", () => {
  submitPacket("draft").catch((error) => {
    $("#packet-preview").textContent = error.message;
  });
});

$("#gate-button").addEventListener("click", () => {
  submitPacket("gate").catch((error) => {
    $("#packet-preview").textContent = error.message;
  });
});

$("#execute-button").addEventListener("click", () => {
  submitPacket("execute").catch((error) => {
    $("#packet-preview").textContent = error.message;
  });
});

$("#handoff-button").addEventListener("click", () => {
  submitPacket("handoff").catch((error) => {
    $("#packet-preview").textContent = error.message;
  });
});

$("#record-button").addEventListener("click", () => {
  submitPacket("record").catch((error) => {
    $("#packet-preview").textContent = error.message;
  });
});

$("#packet-export-button").addEventListener("click", () => {
  exportSelectedPacket().catch((error) => {
    $("#packet-detail-status").textContent = error.message;
  });
});

$("#task-input").addEventListener("input", () => {
  state.lastPacket = null;
  renderPacket();
});
$("#agent-select").addEventListener("change", renderPacket);

load(state.repo).catch((error) => {
  $("#packet-preview").textContent = error.message;
});
