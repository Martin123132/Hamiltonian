const state = {
  repo: new URLSearchParams(window.location.search).get("repo") || "",
  data: null,
  packetMode: "draft",
  lastPacket: null,
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
    const memoryStatus = packet.memory_status || "unknown";
    const memoryMode = packet.memory_mode || "unknown";
    const evidenceStatus = packet.evidence_status || "unknown";
    const row = document.createElement("article");
    row.className = "packet";
    const body = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = `${packet.agent_name} -> ${packet.stage}`;
    const detail = document.createElement("p");
    detail.textContent = packet.task_excerpt;
    const meta = document.createElement("p");
    meta.textContent = `Memory: ${memoryStatus} (${memoryMode}). Evidence: ${evidenceStatus}. Packet: ${packet.packet_id}`;
    body.append(title, detail, meta);
    row.append(body, pill(packet.status));
    list.appendChild(row);
  });
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
  const evidence = state.packetMode === "record" ? "Evidence packet requested." : "Evidence optional.";
  preview.innerHTML = "";
  const strong = document.createElement("strong");
  strong.textContent = `${state.packetMode.toUpperCase()} packet`;
  const body = document.createElement("span");
  if (state.lastPacket) {
    body.textContent = ` ${agent}: ${state.lastPacket.status}. ${evidence} Saved as ${state.lastPacket.packet_id}.`;
  } else {
    body.textContent = ` ${agent}: ${task} ${evidence}`;
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

$("#record-button").addEventListener("click", () => {
  submitPacket("record").catch((error) => {
    $("#packet-preview").textContent = error.message;
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
