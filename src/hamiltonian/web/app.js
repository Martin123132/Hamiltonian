const state = {
  repo: new URLSearchParams(window.location.search).get("repo") || "",
  data: null,
  packetMode: "draft",
  cockpitMode: "orchestrate",
  activePage: "start",
  lastPacket: null,
  selectedPacket: null,
  lastExport: null,
  routeTimer: null,
  routeRequestSeq: 0,
  pendingRouteLaneId: null,
  guideOpen: false,
  guideStage: null,
  mapCursorIndex: null,
  mapCursorStage: null,
  readinessFocus: null,
  packetDetailTab: "overview",
  runnerPollTimer: null,
  runnerPollSeq: 0,
  simplePollTimer: null,
  simplePollSeq: 0,
  goalPreviewTimer: null,
  goalHistoryTimer: null,
  goalDraft: null,
  goals: [],
  activeReviewGoalId: null,
  appInfo: null,
  simpleRun: {
    status: "idle",
    title: "Ready",
    body: "",
    packetId: null,
    result: "",
  },
};
const ACTIVE_RUN_STATES = new Set(["starting", "running", "cancelling"]);
const STAGE_RANK = {
  draft: 0,
  gate: 1,
  execute: 2,
  handoff: 3,
  record: 4,
};
const STAGE_LABELS = {
  draft: { title: "Draft", goal: "Capture intent and lane choice." },
  gate: { title: "Gate", goal: "Run memory and safety checks." },
  execute: { title: "Execute", goal: "Prepare approval boundary." },
  handoff: { title: "Handoff", goal: "Publish operator brief." },
  record: { title: "Record", goal: "Attach a local evidence placeholder." },
};
const STAGE_ORDER = ["draft", "gate", "execute", "handoff", "record"];
const PACKET_ACTIONS = [
  { stage: "gate", selector: "#packet-gate-button", label: "Run gates" },
  { stage: "execute", selector: "#packet-execute-button", label: "Prepare execute" },
  { stage: "handoff", selector: "#packet-handoff-button", label: "Prepare handoff" },
  { stage: "record", selector: "#packet-record-button", label: "Attach evidence" },
];
const MAP_STEPS = [
  {
    id: "draft",
    title: "Write the job",
    anchor: "cockpit",
    summary: "Start by writing the work as a bounded packet.",
  },
  {
    id: "route",
    title: "Pick the lane",
    anchor: "routes",
    summary: "Use the live route advice or override it deliberately.",
  },
  {
    id: "gate",
    title: "Clear gates",
    anchor: "gates",
    summary: "Check memory, intent, and cost before anything runs.",
  },
  {
    id: "execute",
    title: "Prepare work",
    anchor: "packet-detail-panel",
    summary: "Create the manual approval boundary without execution.",
  },
  {
    id: "handoff",
    title: "Handoff",
    anchor: "handoff-panel",
    summary: "Turn the packet into an operator-ready brief.",
  },
  {
    id: "record",
    title: "Attach proof",
    anchor: "recorder-panel",
    summary: "Add evidence only when this run needs a recorder packet.",
  },
];
const TUTORIAL_STEPS = {
  draft: {
    title: "Tell it the job",
    body: "Write one bounded job. Hamiltonian turns it into a packet the rest of the cockpit can guide.",
    anchor: "cockpit",
  },
  route: {
    title: "Choose the worker",
    body: "Use the recommended lane or override it deliberately. The route is advice; the gates still decide.",
    anchor: "routes",
  },
  gate: {
    title: "Check before moving",
    body: "Run the local memory, intent, and cost checks before any execution boundary exists.",
    anchor: "gates",
  },
  execute: {
    title: "Prepare the work",
    body: "Create the manual execution boundary. Nothing runs here; it only prepares the approval step.",
    anchor: "packet-detail-panel",
  },
  handoff: {
    title: "Prepare the handoff",
    body: "Turn the packet into an operator-ready note another person can inspect.",
    anchor: "handoff-panel",
  },
  record: {
    title: "Add proof when needed",
    body: "Attach evidence only when this run needs a recorder packet.",
    anchor: "recorder-panel",
  },
};
const TUTORIAL_ORDER = ["draft", "route", "gate", "execute", "handoff", "record"];
const PAGE_ORDER = ["start", "create", "map", "learn", "routes", "gates", "recorder", "handoff", "packets", "advanced"];
const PAGE_ALIASES = {
  cockpit: "create",
  "mission-map": "map",
  tutorial: "learn",
  gates: "gates",
  "recorder-panel": "recorder",
  "handoff-panel": "handoff",
  runs: "packets",
  mission: "map",
  "packet-detail-panel": "packets",
  "next-build": "advanced",
};

const $ = (selector) => document.querySelector(selector);

function statusTone(value) {
  const lowered = String(value || "").toLowerCase();
  if (lowered === "done" || lowered === "complete") {
    return {
      className: "chip-confirmed",
      meaning: "Completed in this path",
    };
  }
  if (lowered === "current") {
    return {
      className: "chip-ready",
      meaning: "Current step",
    };
  }
  if (lowered === "next") {
    return {
      className: "chip-advisory",
      meaning: "Suggested next move",
    };
  }
  if (lowered === "locked") {
    return {
      className: "chip-optional",
      meaning: "Not available yet",
    };
  }
  if (
    lowered.includes("block") ||
    lowered.includes("missing") ||
    lowered.includes("failed") ||
    lowered.includes("error") ||
    lowered.includes("timed-out") ||
    lowered.includes("refuse")
  ) {
    return {
      className: "chip-blocked",
      meaning: "Needs operator attention",
    };
  }
  if (
    lowered.includes("skipped") ||
    lowered.includes("optional") ||
    lowered.includes("not requested") ||
    lowered.includes("not-prepared") ||
    lowered.includes("not ready") ||
    lowered.includes("off")
  ) {
    return {
      className: "chip-optional",
      meaning: "Not part of the active path",
    };
  }
  if (
    lowered.includes("pending") ||
    lowered.includes("planned") ||
    lowered.includes("running") ||
    lowered.includes("starting") ||
    lowered.includes("cancelling") ||
    lowered.includes("choose") ||
    lowered.includes("draft") ||
    lowered.includes("loading") ||
    lowered.includes("saving") ||
    lowered.includes("empty")
  ) {
    return {
      className: "chip-pending",
      meaning: "Waiting for the next step",
    };
  }
  if (
    lowered.includes("simulated") ||
    lowered.includes("warn") ||
    lowered.includes("review") ||
    lowered.includes("override") ||
    lowered.includes("external")
  ) {
    return {
      className: "chip-advisory",
      meaning: "Review before treating as final",
    };
  }
  if (
    lowered.includes("pass") ||
    lowered.includes("checked") ||
    lowered.includes("succeed") ||
    lowered.includes("recorded") ||
    lowered.includes("represented")
  ) {
    return {
      className: "chip-confirmed",
      meaning: "Verified by this local run",
    };
  }
  if (
    lowered.includes("ready") ||
    lowered.includes("wired") ||
    lowered.includes("gated") ||
    lowered.includes("recommended") ||
    lowered.includes("selected") ||
    lowered.includes("installed") ||
    lowered.includes("available")
  ) {
    return {
      className: "chip-ready",
      meaning: "Ready or available",
    };
  }
  return {
    className: "chip-neutral",
    meaning: "Reference state",
  };
}

function statusClass(value) {
  return statusTone(value).className;
}

function pill(text) {
  const span = document.createElement("span");
  const tone = statusTone(text);
  span.className = `pill ${tone.className}`;
  span.title = tone.meaning;
  span.setAttribute("aria-label", `${text}: ${tone.meaning}`);
  span.textContent = text;
  return span;
}

function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function splitPages(value) {
  return String(value || "")
    .split(/\s+/)
    .filter(Boolean);
}

function normalizePage(page) {
  return PAGE_ORDER.includes(page) ? page : "start";
}

function pageForAnchor(anchor) {
  if (PAGE_ORDER.includes(anchor)) return anchor;
  return PAGE_ALIASES[anchor] || "start";
}

function currentHashId() {
  return decodeURIComponent(window.location.hash.replace(/^#/, ""));
}

function setActivePage(page, options = {}) {
  const activePage = normalizePage(page);
  state.activePage = activePage;
  document.body.dataset.activePage = activePage;

  document.querySelectorAll("[data-pages]").forEach((section) => {
    const visible = splitPages(section.dataset.pages).includes(activePage);
    section.classList.toggle("is-page-hidden", !visible);
    section.setAttribute("aria-hidden", visible ? "false" : "true");
  });

  document.querySelectorAll("[data-page-target]").forEach((link) => {
    const active = link.dataset.pageTarget === activePage;
    link.classList.toggle("active", active);
    link.setAttribute("aria-selected", String(active));
    if (active) {
      link.setAttribute("aria-current", "page");
    } else {
      link.removeAttribute("aria-current");
    }
  });

  if (options.updateHash) {
    const hash = options.hash || `#${activePage}`;
    if (window.location.hash !== hash) {
      const method = options.replace ? "replaceState" : "pushState";
      window.history[method](null, "", hash);
    }
  }

  if (activePage === "handoff" && state.data) {
    renderHandoffExport(state.data);
  }
}

function revealSection(anchor, options = {}) {
  const target = document.getElementById(anchor);
  setActivePage(pageForAnchor(anchor), {
    updateHash: options.updateHash !== false,
    hash: `#${anchor}`,
  });
  if (target && options.scroll !== false) {
    target.scrollIntoView({ behavior: options.instant ? "auto" : "smooth", block: "start" });
  }
  return target;
}

function syncPageToHash() {
  const hashId = currentHashId();
  const page = pageForAnchor(hashId);
  setActivePage(page, { updateHash: false });
  if (hashId && !PAGE_ORDER.includes(hashId)) {
    window.requestAnimationFrame(() => {
      const target = document.getElementById(hashId);
      if (target && !target.classList.contains("is-page-hidden")) {
        target.scrollIntoView({ behavior: "auto", block: "start" });
      }
    });
  }
}

function initPageNavigation() {
  document.querySelectorAll("[data-page-target]").forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      const page = normalizePage(link.dataset.pageTarget);
      setActivePage(page, { updateHash: true, hash: `#${page}` });
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  });
  window.addEventListener("hashchange", syncPageToHash);
  window.addEventListener("popstate", syncPageToHash);
  syncPageToHash();
}

function activeCockpitMode() {
  const selected = document.querySelector('input[name="cockpit-mode"]:checked');
  return selected && selected.value === "recorder" ? "recorder" : "orchestrate";
}

function normalizeStage(stage) {
  return String(stage || "draft").toLowerCase();
}

function buildAdvancePlan(packet) {
  if (!packet) {
    return {
      stage: "draft",
      stageRank: STAGE_RANK.draft,
      blocked: false,
      blockedMessage: "",
      allowed: new Set(["draft"]),
      nextStages: [],
      nextRecommended: null,
    };
  }

  const normalizedStage = normalizeStage(packet.stage);
  const stage = STAGE_LABELS[normalizedStage] ? normalizedStage : "draft";
  const gateRun = packet.gate_run || {};
  const blocked = Number(gateRun.blocked || 0) > 0;
  const blockedMessage =
    blocked && gateRun.blocked_gate_ids?.length
      ? `Blocked by ${gateRun.blocked_gate_ids.join(", ")}. Resolve those gates first.`
      : blocked
        ? "Packet is blocked by policy gates."
        : "";

  const nextActions = {
    draft: ["gate"],
    gate: ["execute", "record"],
    execute: ["handoff", "record"],
    handoff: ["record"],
    record: [],
  };
  const allowed = blocked ? new Set() : new Set(nextActions[stage] || []);

  const nextRecommended = allowed.size > 0 ? [...allowed].sort((a, b) => STAGE_RANK[a] - STAGE_RANK[b])[0] : null;

  return {
    stage,
    stageRank: STAGE_RANK[stage] ?? STAGE_RANK.draft,
    blocked,
    blockedMessage,
    allowed,
    nextStages: nextActions[stage] || [],
    nextRecommended,
  };
}

function renderMissionPath(packet) {
  const path = $("#mission-path");
  const missionNext = $("#mission-next");
  clear(path);
  clear(missionNext);

  if (!packet) {
    missionNext.textContent =
      "Choose a lane, write a task, and create a draft packet to start a new guided workflow.";
    const intro = document.createElement("p");
    intro.className = "mission-empty";
    intro.textContent = "No active packet. Create one in task control, then follow the guidance steps below.";
    path.appendChild(intro);
    return;
  }

  const lane = packet.lane || { name: packet.agent_name || "Unknown lane" };
  const plan = buildAdvancePlan(packet);
  const heading = document.createElement("p");
  heading.className = "mission-title";
  heading.textContent = `${lane.name} packet: ${STAGE_LABELS[plan.stage].title} -> mission ${packet.stage}.`;
  path.appendChild(heading);

  STAGE_ORDER.forEach((step) => {
    const stage = STAGE_LABELS[step];
    const row = document.createElement("div");
    const status = document.createElement("span");
    const title = document.createElement("strong");
    const goal = document.createElement("p");

    if (STAGE_RANK[step] < plan.stageRank) {
      row.className = "mission-step mission-step-done";
      status.textContent = "done";
      title.textContent = `${stage.title} complete`;
    } else if (step === plan.stage) {
      row.className = "mission-step mission-step-current";
      status.textContent = "current";
      title.textContent = `${stage.title} active`;
    } else {
      row.className = `mission-step ${
        plan.blocked || plan.stageRank > STAGE_RANK[step] ? "mission-step-locked" : plan.allowed.has(step) ? "mission-step-ready" : "mission-step-locked"
      }`;
      status.textContent = plan.allowed.has(step) ? "next" : "locked";
      title.textContent = stage.title;
    }

    goal.textContent = stage.goal;
    status.className = "pill";
    const tone = statusTone(status.textContent);
    status.classList.add(tone.className);
    status.title = tone.meaning;
    status.setAttribute("aria-label", `${status.textContent}: ${tone.meaning}`);
    row.append(title, status, goal);

    if (!plan.blocked && plan.allowed.has(step)) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "compact-button mission-step-button";
      button.textContent = `Advance to ${stage.title}`;
      button.addEventListener("click", () => {
        advanceSelectedPacket(step).catch((error) => {
          $("#packet-detail-status").textContent = error.message;
        });
      });
      row.appendChild(button);
    }
    path.appendChild(row);
  });

  const blockedText = plan.blocked ? plan.blockedMessage : "All gates are clear for this packet.";
  missionNext.append(
    plan.blocked ? blockedText : `Next suggested move: ${plan.nextRecommended ? STAGE_LABELS[plan.nextRecommended].title : "Review"}`
  );
}

function mapStage(packet) {
  if (!packet) return "draft";
  const plan = buildAdvancePlan(packet);
  if (plan.blocked) return "gate";
  const stage = normalizeStage(packet.stage);
  if (stage === "draft" && packetHasLaneDecision(packet)) return "gate";
  if (stage === "draft") return "route";
  if (stage === "gate") return "execute";
  if (stage === "execute") return "handoff";
  if (stage === "handoff") return "record";
  if (stage === "record") return "record";
  return "draft";
}

function packetHasLaneDecision(packet) {
  return Boolean(
    packet &&
      Array.isArray(packet.history) &&
      packet.history.some((event) => event && event.event === "lane-selected"),
  );
}

function packetRequiresLaneDecision(packet) {
  return Boolean(packet && normalizeStage(packet.stage) === "draft" && !packetHasLaneDecision(packet));
}

function mapStatusFor(stepIndex, currentIndex, packet) {
  if (packet && normalizeStage(packet.stage) === "record" && stepIndex === currentIndex) return "complete";
  if (stepIndex < currentIndex) return "complete";
  if (stepIndex === currentIndex) return "current";
  return "future";
}

function jumpToMapStep(step) {
  revealSection(step.anchor);
  if (step.id === "draft") {
    const taskInput = $("#task-input");
    if (taskInput) taskInput.focus();
  }
}

async function focusFirstRouteAction() {
  setActivePage("routes", { updateHash: true, hash: "#routes" });
  window.scrollTo({ top: 0, behavior: "smooth" });
  await refreshLiveRoutes().catch((error) => console.warn(error));
  const button = document.querySelector("#route-confirm-button") || document.querySelector("#route-list .route-select-button");
  if (button) {
    button.focus({ preventScroll: true });
    return;
  }
}

function mapActionFor(current, packet) {
  if (!packet) {
    return {
      label: "Focus task",
      run: () => jumpToMapStep(MAP_STEPS.find((step) => step.id === "draft")),
    };
  }
  const plan = buildAdvancePlan(packet);
  if (plan.blocked) {
    return {
      label: "Review gates",
      run: () => jumpToMapStep(MAP_STEPS.find((step) => step.id === "gate")),
    };
  }
  if (current === "route") {
    return {
      label: "Choose lane",
      run: focusFirstRouteAction,
    };
  }
  if (current === "gate" && plan.allowed.has("gate")) {
    return {
      label: "Run gates",
      run: () => {
        revealSection("packet-detail-panel");
        return advanceSelectedPacket("gate");
      },
    };
  }
  if (current === "execute" && plan.allowed.has("execute")) {
    return {
      label: "Prepare execute",
      run: () => {
        revealSection("packet-detail-panel");
        return advanceSelectedPacket("execute");
      },
    };
  }
  if (current === "handoff" && plan.allowed.has("handoff")) {
    return {
      label: "Prepare handoff",
      run: () => {
        revealSection("packet-detail-panel");
        return advanceSelectedPacket("handoff");
      },
    };
  }
  if (current === "record" && plan.allowed.has("record")) {
    return {
      label: "Attach evidence",
      run: () => {
        revealSection("packet-detail-panel");
        return advanceSelectedPacket("record");
      },
    };
  }
  return {
    label: "Review packet",
    run: () => jumpToMapStep(MAP_STEPS.find((step) => step.id === current)),
  };
}

function runMapAction(current, packet) {
  const action = mapActionFor(current, packet);
  Promise.resolve(action.run()).catch((error) => {
    const status = $("#packet-detail-status");
    if (status) status.textContent = error.message;
  });
}

function missionHudBody(step, packet) {
  if (!packet) {
    return "Start with a bounded packet. The cockpit will keep the next action visible while you roam.";
  }
  const laneName = packet.lane?.name || packet.agent_name || "Selected lane";
  return `${step.summary} ${laneName} is the active lane; packet state stays local until the operator chooses the next boundary.`;
}

function missionHudStepLabel(step) {
  const labels = {
    draft: "Write",
    route: "Lane",
    gate: "Gates",
    execute: "Prep",
    handoff: "Brief",
    record: "Proof",
  };
  return labels[step.id] || step.title;
}

function renderMissionHud(packet) {
  const hud = $("#mission-hud");
  const title = $("#mission-hud-title");
  const body = $("#mission-hud-body");
  const count = $("#mission-hud-count");
  const steps = $("#mission-hud-steps");
  const actionButton = $("#mission-hud-action");
  const mapButton = $("#mission-hud-map");
  const guideButton = $("#mission-hud-guide");
  if (!hud || !title || !body || !count || !steps || !actionButton || !mapButton || !guideButton) return;

  const current = mapStage(packet);
  const currentIndex = Math.max(0, MAP_STEPS.findIndex((step) => step.id === current));
  const currentStep = MAP_STEPS[currentIndex] || MAP_STEPS[0];
  const action = mapActionFor(current, packet);
  hud.dataset.currentStage = current;
  hud.style.setProperty("--hud-progress", `${((currentIndex + 1) / MAP_STEPS.length) * 100}%`);

  count.textContent = `Step ${currentIndex + 1} of ${MAP_STEPS.length}`;
  title.textContent = currentStep.title;
  body.textContent = missionHudBody(currentStep, packet);
  actionButton.textContent = action.label;
  actionButton.onclick = () => runMapAction(current, packet);
  mapButton.onclick = () => revealSection("mission-map");
  guideButton.onclick = () => openGuide(tutorialStage(packet));
  guideButton.textContent = state.guideOpen ? "Guide open" : "Guide";

  clear(steps);
  MAP_STEPS.forEach((step, index) => {
    const status = mapStatusFor(index, currentIndex, packet);
    const marker = document.createElement("button");
    marker.type = "button";
    marker.className = `mission-hud-step mission-hud-step-${status}`;
    marker.dataset.stage = step.id;
    marker.title = `${step.title}: ${status}`;
    marker.setAttribute("aria-label", `${step.title}: ${status}`);
    if (status === "current") marker.setAttribute("aria-current", "step");
    marker.addEventListener("click", () => {
      if (status === "current") {
        runMapAction(current, packet);
        return;
      }
      jumpToMapStep(step);
    });

    const dot = document.createElement("span");
    dot.textContent = String(index + 1);
    const text = document.createElement("strong");
    text.textContent = missionHudStepLabel(step);
    marker.append(dot, text);
    steps.appendChild(marker);
  });
}

function mapCurrentIndex(packet) {
  const current = mapStage(packet);
  return Math.max(0, MAP_STEPS.findIndex((step) => step.id === current));
}

function syncMapCursor(current, currentIndex) {
  if (state.mapCursorIndex === null || state.mapCursorStage !== current) {
    state.mapCursorIndex = currentIndex;
    state.mapCursorStage = current;
  }
  state.mapCursorIndex = Math.max(0, Math.min(MAP_STEPS.length - 1, state.mapCursorIndex));
}

function applyMapCursor() {
  document.querySelectorAll("#map-path .map-node").forEach((node, index) => {
    const selected = index === state.mapCursorIndex;
    node.classList.toggle("map-node-cursor", selected);
    node.tabIndex = selected ? 0 : -1;
    if (selected) {
      node.setAttribute("aria-selected", "true");
    } else {
      node.removeAttribute("aria-selected");
    }
  });
}

function focusMapCursor(options = {}) {
  const node = document.querySelector(`#map-path .map-node[data-map-index="${state.mapCursorIndex}"]`);
  if (!node) return;
  node.focus({ preventScroll: true });
  if (options.scroll !== false) {
    node.scrollIntoView({ behavior: options.instant ? "auto" : "smooth", block: "nearest", inline: "nearest" });
  }
}

function setMapCursor(index, options = {}) {
  state.mapCursorIndex = Math.max(0, Math.min(MAP_STEPS.length - 1, index));
  applyMapCursor();
  if (options.focus !== false) focusMapCursor(options);
}

function moveMapCursor(delta) {
  if (!PAGE_ORDER.includes(state.activePage)) return false;
  const nextIndex = (state.mapCursorIndex ?? mapCurrentIndex(state.selectedPacket)) + delta;
  setMapCursor(nextIndex);
  return true;
}

function activateMapCursor() {
  const step = MAP_STEPS[state.mapCursorIndex ?? mapCurrentIndex(state.selectedPacket)];
  if (!step) return false;
  const current = mapStage(state.selectedPacket);
  if (step.id === current) {
    runMapAction(current, state.selectedPacket);
  } else {
    jumpToMapStep(step);
  }
  return true;
}

function renderMissionMap(packet) {
  renderMissionHud(packet);
  const mapPath = $("#map-path");
  const mapTitle = $("#map-title");
  const mapCurrent = $("#map-current");
  const mapAction = $("#map-action");
  if (!mapPath) return;
  clear(mapPath);
  const current = mapStage(packet);
  const currentIndex = Math.max(0, MAP_STEPS.findIndex((step) => step.id === current));
  syncMapCursor(current, currentIndex);
  const currentStep = MAP_STEPS[currentIndex];
  const progress = (currentIndex / Math.max(1, MAP_STEPS.length - 1)) * 100;
  mapPath.style.setProperty("--map-progress", `${progress}%`);
  mapPath.dataset.currentStage = current;
  if (mapTitle) {
    mapTitle.textContent = packet ? `${packet.agent_name || "Packet"} mission` : "Start with a packet";
  }
  if (mapCurrent) {
    mapCurrent.textContent = currentStep.title;
  }
  if (mapAction) {
    const action = mapActionFor(current, packet);
    mapAction.textContent = action.label;
    mapAction.onclick = () => runMapAction(current, packet);
  }

  MAP_STEPS.forEach((step, index) => {
    const status = mapStatusFor(index, currentIndex, packet);
    const node = document.createElement("button");
    node.type = "button";
    node.className = `map-node map-node-${status}`;
    node.dataset.mapIndex = String(index);
    node.dataset.mapStatus = status;
    node.tabIndex = index === state.mapCursorIndex ? 0 : -1;
    node.style.setProperty("--step-index", String(index + 1));
    node.setAttribute("aria-label", `${step.title}: ${status}`);
    node.setAttribute("aria-selected", index === state.mapCursorIndex ? "true" : "false");
    if (status === "current") node.setAttribute("aria-current", "step");
    node.title = status === "current" ? "Run the current mission action" : `Open ${step.title}`;
    const orbit = document.createElement("span");
    orbit.className = "map-node-orbit";
    const number = document.createElement("span");
    number.className = "map-node-index";
    number.textContent = String(index + 1);
    orbit.appendChild(number);
    const body = document.createElement("span");
    body.className = "map-node-body";
    const title = document.createElement("strong");
    title.textContent = step.title;
    const summary = document.createElement("span");
    summary.textContent = step.summary;
    body.append(title, summary);
    const marker = document.createElement("span");
    marker.className = "map-node-status";
    marker.textContent = status === "future" ? "open" : status;
    const hint = document.createElement("span");
    hint.className = "map-node-hint";
    hint.textContent = status === "current" ? "Act here" : status === "complete" ? "Review" : "Scout";
    node.append(orbit, body, marker, hint);
    node.addEventListener("click", () => {
      setMapCursor(index, { focus: false });
      if (status === "current") {
        runMapAction(current, packet);
        return;
      }
      jumpToMapStep(step);
    });
    mapPath.appendChild(node);
  });
  applyMapCursor();
}

function tutorialStage(packet) {
  if (!packet) return "draft";
  const stage = normalizeStage(packet.stage);
  if (stage === "draft" && packetHasLaneDecision(packet)) return "gate";
  if (stage === "draft") return "route";
  if (stage === "gate") return "execute";
  if (stage === "execute") return "handoff";
  if (stage === "handoff") return "record";
  if (stage === "record") return "record";
  return "draft";
}

function tutorialStepStatus(stage, current, currentIndex) {
  const index = TUTORIAL_ORDER.indexOf(stage);
  if (stage === current) return "current";
  if (index >= 0 && index < currentIndex) return "done";
  return "preview";
}

function runTutorialStep(stage, packet, isCurrent) {
  if (isCurrent) {
    runMapAction(mapStage(packet), packet);
    return;
  }
  const step = TUTORIAL_STEPS[stage] || TUTORIAL_STEPS.draft;
  jumpToMapStep({ id: stage, anchor: step.anchor });
}

function tutorialButtonLabel(stage, packet, isCurrent) {
  if (isCurrent) return mapActionFor(mapStage(packet), packet).label;
  const index = TUTORIAL_ORDER.indexOf(stage);
  const currentIndex = TUTORIAL_ORDER.indexOf(tutorialStage(packet));
  return index >= 0 && index < currentIndex ? "Review" : "Preview";
}

function normalizeTutorialStage(stage) {
  return TUTORIAL_ORDER.includes(stage) ? stage : "draft";
}

function guideAnchorForStage(stage, packet) {
  const normalized = normalizeTutorialStage(stage);
  if (packet?.packet_id && normalized === "gate") {
    return "gates";
  }
  if (packet?.packet_id && normalized === "record") {
    return "recorder-panel";
  }
  if (packet?.packet_id && ["execute", "handoff"].includes(normalized)) {
    return "packet-detail-panel";
  }
  return (TUTORIAL_STEPS[normalized] || TUTORIAL_STEPS.draft).anchor;
}

function elementIsVisible(element) {
  return Boolean(element && !element.closest(".is-page-hidden") && element.getClientRects().length);
}

function guideTargetForStage(stage, packet) {
  const normalized = normalizeTutorialStage(stage);
  const selectors = {
    draft: ["#task-input", "#cockpit"],
    route: ["#route-confirm-button", "#route-list .lane-option-selected", "#route-list .route-select-button", "#routes"],
    gate: ["#gate-list .gate-check-row", "#gate-primary-action", "#gates"],
    execute: ["#packet-command", "#packet-execute-button", "#packet-detail-panel"],
    handoff: ["#packet-command", "#packet-handoff-button", "#packet-detail-panel"],
    record: ["#recorder-create-button", "#recorder-panel", "#packet-record-button"],
  };
  for (const selector of selectors[normalized] || []) {
    const target = document.querySelector(selector);
    if (elementIsVisible(target)) return target;
  }
  const fallback = document.getElementById(guideAnchorForStage(normalized, packet));
  return elementIsVisible(fallback) ? fallback : null;
}

function clearGuideFocus() {
  document.querySelectorAll(".guide-focus").forEach((target) => {
    target.classList.remove("guide-focus");
  });
}

function updateGuideFocus(stage, packet) {
  clearGuideFocus();
  if (!state.guideOpen) return;
  window.requestAnimationFrame(() => {
    const target = guideTargetForStage(stage, packet);
    if (target) target.classList.add("guide-focus");
  });
}

function revealGuideStage(stage, packet, options = {}) {
  const normalized = normalizeTutorialStage(stage);
  const anchor = guideAnchorForStage(normalized, packet);
  revealSection(anchor, { instant: options.instant, updateHash: options.updateHash });
  updateGuideFocus(normalized, packet);
}

function setGuideStage(stage, options = {}) {
  const normalized = normalizeTutorialStage(stage);
  state.guideStage = normalized;
  if (options.reveal !== false) {
    revealGuideStage(normalized, state.selectedPacket, { instant: options.instant });
  }
  renderGuide(state.selectedPacket);
}

function openGuide(stage = tutorialStage(state.selectedPacket)) {
  state.guideOpen = true;
  setGuideStage(stage, { instant: true });
}

function closeGuide() {
  state.guideOpen = false;
  clearGuideFocus();
  renderGuide(state.selectedPacket);
}

function moveGuideStep(delta) {
  const current = normalizeTutorialStage(state.guideStage || tutorialStage(state.selectedPacket));
  const currentIndex = TUTORIAL_ORDER.indexOf(current);
  const nextIndex = Math.max(0, Math.min(TUTORIAL_ORDER.length - 1, currentIndex + delta));
  setGuideStage(TUTORIAL_ORDER[nextIndex]);
}

function activateGuideAction() {
  const action = $("#guide-action");
  if (action && !action.disabled) action.click();
}

function syncGuideStage(packet) {
  const liveStage = tutorialStage(packet);
  if (!state.guideStage) {
    state.guideStage = liveStage;
    return false;
  }
  const liveIndex = TUTORIAL_ORDER.indexOf(liveStage);
  const guideIndex = TUTORIAL_ORDER.indexOf(state.guideStage);
  if (liveIndex > guideIndex) {
    state.guideStage = liveStage;
    return true;
  }
  return false;
}

function renderGuide(packet) {
  const layer = $("#guide-layer");
  const toggle = $("#guide-toggle");
  if (toggle) toggle.textContent = state.guideOpen ? "Hide guide" : "Guide me";
  const hudGuide = $("#mission-hud-guide");
  if (hudGuide) hudGuide.textContent = state.guideOpen ? "Guide open" : "Guide";
  if (!layer) return;
  layer.hidden = !state.guideOpen;
  if (!state.guideOpen) {
    clearGuideFocus();
    return;
  }

  const progressed = syncGuideStage(packet);
  const stage = normalizeTutorialStage(state.guideStage || tutorialStage(packet));
  const step = TUTORIAL_STEPS[stage] || TUTORIAL_STEPS.draft;
  const index = TUTORIAL_ORDER.indexOf(stage);
  const liveStage = tutorialStage(packet);
  const isCurrent = stage === liveStage;
  const progress = ((index + 1) / TUTORIAL_ORDER.length) * 100;
  const actionLabel = tutorialButtonLabel(stage, packet, isCurrent);

  $("#guide-step-count").textContent = `Step ${index + 1} of ${TUTORIAL_ORDER.length}`;
  $("#guide-title").textContent = step.title;
  $("#guide-body").textContent = step.body;
  $("#guide-progress-fill").style.width = `${progress}%`;

  const back = $("#guide-back");
  const next = $("#guide-next");
  const action = $("#guide-action");
  back.disabled = index <= 0;
  next.disabled = index >= TUTORIAL_ORDER.length - 1;
  back.onclick = () => setGuideStage(TUTORIAL_ORDER[Math.max(0, index - 1)]);
  next.onclick = () => setGuideStage(TUTORIAL_ORDER[Math.min(TUTORIAL_ORDER.length - 1, index + 1)]);
  action.textContent = actionLabel;
  action.onclick = () => {
    runTutorialStep(stage, packet, isCurrent);
    window.requestAnimationFrame(() => renderGuide(state.selectedPacket));
  };

  if (progressed) {
    window.requestAnimationFrame(() => revealGuideStage(stage, packet, { instant: true }));
  } else {
    updateGuideFocus(stage, packet);
  }
}

function isEditableKeyTarget(target) {
  return Boolean(
    target &&
      (target.closest?.("input") ||
        target.closest?.("textarea") ||
        target.closest?.("select") ||
        target.closest?.("[contenteditable='true']"))
  );
}

function mapKeyboardIsActive(target) {
  return Boolean(
    target?.closest?.("#mission-map") ||
      ["start", "map", "learn"].includes(state.activePage) ||
      document.activeElement?.closest?.("#mission-map")
  );
}

function handleGlobalKeydown(event) {
  if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return;
  if (isEditableKeyTarget(event.target)) return;

  if (event.key === "Escape" && state.guideOpen) {
    event.preventDefault();
    closeGuide();
    return;
  }

  if (event.key.toLowerCase() === "g") {
    event.preventDefault();
    if (state.guideOpen) {
      closeGuide();
    } else {
      openGuide();
    }
    return;
  }

  if (state.guideOpen && (event.key === "ArrowLeft" || event.key === "ArrowRight")) {
    event.preventDefault();
    moveGuideStep(event.key === "ArrowRight" ? 1 : -1);
    return;
  }

  if (state.guideOpen && event.key === "Enter" && !event.target.closest?.("button, a")) {
    event.preventDefault();
    activateGuideAction();
    return;
  }

  if (!mapKeyboardIsActive(event.target)) return;

  if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
    event.preventDefault();
    moveMapCursor(event.key === "ArrowRight" ? 1 : -1);
    return;
  }

  if (event.key === "Home" || event.key === "End") {
    event.preventDefault();
    setMapCursor(event.key === "Home" ? 0 : MAP_STEPS.length - 1);
    return;
  }

  if (event.key === "Enter" && event.target.closest?.(".map-node")) {
    event.preventDefault();
    activateMapCursor();
  }
}

function renderTutorial(packet) {
  const current = tutorialStage(packet);
  const currentIndex = TUTORIAL_ORDER.indexOf(current);
  document.querySelectorAll(".tutorial-step").forEach((step) => {
    const stage = step.dataset.stage || "draft";
    const status = tutorialStepStatus(stage, current, currentIndex);
    const isCurrent = status === "current";
    step.classList.toggle("tutorial-step-active", isCurrent);
    step.classList.toggle("tutorial-step-done", status === "done");
    step.classList.toggle("tutorial-step-preview", status === "preview");
    step.setAttribute("data-status", status);
    let action = step.querySelector(".tutorial-step-action");
    if (!action) {
      action = document.createElement("button");
      action.type = "button";
      action.className = "compact-button tutorial-step-action";
      step.appendChild(action);
    }
    action.textContent = tutorialButtonLabel(stage, packet, isCurrent);
    action.onclick = () => runTutorialStep(stage, packet, isCurrent);
  });
  const chip = $("#tutorial-current");
  if (chip) {
    const active = document.querySelector(`.tutorial-step[data-stage="${current}"] strong`);
    chip.textContent = active ? active.textContent : "Start here";
  }
  const coachTitle = $("#tutorial-coach-title");
  const coachBody = $("#tutorial-coach-body");
  const coachButton = $("#tutorial-action");
  const currentStep = TUTORIAL_STEPS[current] || TUTORIAL_STEPS.draft;
  if (coachTitle) coachTitle.textContent = currentStep.title;
  if (coachBody) coachBody.textContent = currentStep.body;
  if (coachButton) {
    coachButton.textContent = mapActionFor(mapStage(packet), packet).label;
    coachButton.onclick = () => runMapAction(mapStage(packet), packet);
  }
  renderGuide(packet);
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

function gateToneName(value) {
  const lowered = String(value || "").toLowerCase();
  if (
    lowered.includes("block") ||
    lowered.includes("fail") ||
    lowered.includes("refuse") ||
    lowered.includes("risk") ||
    lowered.includes("error")
  ) {
    return "blocked";
  }
  if (
    lowered.includes("warn") ||
    lowered.includes("degraded") ||
    lowered.includes("partial") ||
    lowered.includes("pending") ||
    lowered.includes("waiting") ||
    lowered.includes("choose") ||
    lowered.includes("missing") ||
    lowered.includes("external") ||
    lowered.includes("not ready")
  ) {
    return "warn";
  }
  if (
    lowered.includes("pass") ||
    lowered.includes("checked") ||
    lowered.includes("clear") ||
    lowered.includes("ready") ||
    lowered.includes("selected") ||
    lowered.includes("recommended") ||
    lowered.includes("represented") ||
    lowered.includes("within")
  ) {
    return "safe";
  }
  return "optional";
}

function gateToneLabel(tone) {
  return {
    safe: "Clear",
    warn: "Action",
    blocked: "Blocked",
    optional: "Neutral",
  }[tone] || "Neutral";
}

function gateDisplayPacket(data) {
  if (state.selectedPacket?.packet_id) return state.selectedPacket;
  if (state.lastPacket?.packet_id) return state.lastPacket;
  return homePacketForDisplay(data);
}

function renderGateMetrics(items) {
  const metrics = $("#gate-summary-metrics");
  if (!metrics) return;
  clear(metrics);
  const counts = { safe: 0, warn: 0, blocked: 0, optional: 0 };
  items.forEach((item) => {
    counts[gateToneName(item.status)] += 1;
  });
  [
    ["safe", "Clear"],
    ["warn", "Needs action"],
    ["blocked", "Blocked"],
    ["optional", "Optional"],
  ].forEach(([tone, label]) => {
    const card = document.createElement("article");
    card.className = `gate-metric-card gate-tone-${tone}`;
    const value = document.createElement("strong");
    value.textContent = String(counts[tone]);
    const name = document.createElement("span");
    name.textContent = label;
    card.append(value, name);
    metrics.appendChild(card);
  });
}

function renderGateSelectedDetail(item) {
  const detail = $("#gate-selected-detail");
  if (!detail) return;
  clear(detail);
  if (!item) {
    const empty = document.createElement("p");
    empty.className = "muted-line";
    empty.textContent = "Select a readiness check to inspect it.";
    detail.appendChild(empty);
    return;
  }
  const tone = gateToneName(item.status);
  detail.dataset.tone = tone;

  const head = document.createElement("div");
  head.className = "gate-selected-head";
  const label = document.createElement("span");
  label.textContent = `${item.label} check`;
  const title = document.createElement("strong");
  title.textContent = item.explainerTitle || item.label;
  head.append(label, title);

  const body = document.createElement("p");
  body.textContent = item.explainer || item.detail;

  const next = document.createElement("p");
  next.className = "gate-next";
  const nextLabel = document.createElement("strong");
  nextLabel.textContent = "Next: ";
  const nextText = document.createElement("span");
  nextText.textContent = item.next || "Review the packet state.";
  next.append(nextLabel, nextText);

  detail.append(head, pill(gateToneLabel(tone)), body, next);
}

function gateIssueItems(items) {
  const blocking = items.filter((item) => ["blocked", "warn"].includes(gateToneName(item.status)));
  if (blocking.length > 0) return blocking;
  return items.filter((item) => item.id === "gates" || item.id === "execution").slice(0, 2);
}

function renderGateRequiredActions(packet, items) {
  const target = $("#gate-required-actions");
  if (!target) return;
  clear(target);
  const list = document.createElement("ol");
  list.className = "gate-action-list";
  const actions = packet ? gateIssueItems(items) : items.slice(0, 2);
  actions.forEach((item) => {
    const row = document.createElement("li");
    const title = document.createElement("strong");
    title.textContent = item.label;
    const body = document.createElement("span");
    body.textContent = item.next || item.detail;
    row.className = `gate-action-${gateToneName(item.status)}`;
    row.append(title, body);
    list.appendChild(row);
  });
  if (!list.children.length) {
    const row = document.createElement("li");
    row.className = "gate-action-safe";
    const title = document.createElement("strong");
    title.textContent = "No blocking actions";
    const body = document.createElement("span");
    body.textContent = "Continue to the next packet step when ready.";
    row.append(title, body);
    list.appendChild(row);
  }
  target.appendChild(list);
}

function renderGates(data) {
  const list = $("#gate-list");
  if (!list) return;
  clear(list);
  const packet = gateDisplayPacket(data);
  const items = readinessItemsForPacket(packet);
  const selected = readinessSelectedItem(items);
  const tones = items.map((item) => gateToneName(item.status));
  const blocked = tones.filter((tone) => tone === "blocked").length;
  const warnings = tones.filter((tone) => tone === "warn").length;
  const clearCount = tones.filter((tone) => tone === "safe").length;
  const summaryState = blocked > 0 ? "Blocked" : warnings > 0 ? "Action needed" : packet ? "Ready" : "Waiting";
  const summaryTitle = !packet
    ? "Open or create a packet"
    : blocked > 0
      ? "Packet is blocked by readiness gates"
      : warnings > 0
        ? "Packet needs operator attention"
        : "Packet gates are clear enough to continue";
  const summaryBody = !packet
    ? "Hamiltonian needs a packet before route, memory, safety, execution, or evidence checks can move."
    : blocked > 0
      ? "Resolve the blocked check before preparing execution, handoff, or evidence."
      : warnings > 0
        ? "Review the highlighted checks and complete the next safe action before launch."
        : `${clearCount}/${items.length} readiness checks are clear or locally represented. Remote execution remains off.`;

  setText("#gate-view-title", packet ? homeTaskTitle(packet) : "No packet selected");
  setText("#gate-summary-state", summaryState);
  setText("#gate-summary-title", summaryTitle);
  setText("#gate-summary-body", summaryBody);
  renderGateMetrics(items);

  items.forEach((item) => {
    const tone = gateToneName(item.status);
    const row = document.createElement("button");
    row.type = "button";
    row.className = `gate-check-row gate-tone-${tone}`;
    row.classList.toggle("gate-check-row-selected", item.id === selected?.id);
    row.dataset.gateId = item.id;
    row.dataset.testid = "gate-row";
    row.setAttribute("aria-pressed", String(item.id === selected?.id));
    row.setAttribute("aria-controls", "gate-selected-detail");

    const marker = document.createElement("span");
    marker.className = "gate-check-marker";
    marker.textContent = gateToneLabel(tone);
    const body = document.createElement("span");
    body.className = "gate-check-body";
    const title = document.createElement("strong");
    title.textContent = item.label;
    const detail = document.createElement("span");
    detail.textContent = item.detail;
    body.append(title, detail);
    row.append(marker, body, pill(item.status));
    row.addEventListener("click", () => {
      state.readinessFocus = item.id;
      renderGates(state.data || data);
    });
    list.appendChild(row);
  });

  renderGateSelectedDetail(selected);
  renderGateRequiredActions(packet, items);

  const primary = $("#gate-primary-action");
  if (!primary) return;
  if (!packet) {
    primary.disabled = false;
    primary.textContent = "Create packet";
    primary.onclick = () => revealSection("cockpit");
    return;
  }
  if (!state.selectedPacket?.packet_id || state.selectedPacket.packet_id !== packet.packet_id) {
    primary.disabled = false;
    primary.textContent = "Open packet";
    primary.onclick = () => loadPacketDetail(packet.packet_id).catch((error) => {
      const status = $("#packet-detail-status");
      if (status) status.textContent = error.message;
    });
    return;
  }
  const current = mapStage(packet);
  const action = mapActionFor(current, packet);
  primary.disabled = false;
  primary.textContent = action.label;
  primary.onclick = () => runMapAction(current, packet);
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

function advancedStatusRow(label, status, detail) {
  const row = document.createElement("article");
  row.className = `advanced-status-row gate-tone-${gateToneName(status)}`;
  const body = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = label;
  const copy = document.createElement("p");
  copy.textContent = detail;
  body.append(title, copy);
  row.append(body, pill(status));
  return row;
}

function integrationByName(data, name) {
  const needle = String(name || "").toLowerCase();
  return (data?.integrations || []).find((integration) => String(integration.name || "").toLowerCase().includes(needle));
}

function renderAdvancedDataSources(data) {
  const list = $("#advanced-data-sources");
  if (!list) return;
  clear(list);
  const repoMori = integrationByName(data, "RepoMori");
  const tokenSquash = integrationByName(data, "TokenSquash");
  const rows = [
    ["Local filesystem", "connected", `Workspace: ${data.repo_name || data.repo || "local repo"}`],
    [data.git_available ? "Git repository" : "Git repository", data.git_available ? "connected" : "missing", data.git_available ? "Git metadata available locally." : "This workspace is not reporting git metadata."],
    ["Knowledge base", repoMori?.available ? "connected" : "degraded", repoMori?.detail || "RepoMori is unavailable; Hamiltonian uses sanitized local fallback data."],
    ["Context compaction", tokenSquash?.available ? "connected" : "degraded", tokenSquash?.detail || "TokenSquash unavailable; context estimates stay synthetic."],
  ];
  rows.forEach(([label, status, detail]) => list.appendChild(advancedStatusRow(label, status, detail)));
  setText("#advanced-source-count", `${rows.length} sources`);
}

function renderAdvancedRouteScoring(data) {
  const routeState = $("#advanced-route-state");
  const summary = $("#advanced-route-recommendation");
  const bars = $("#advanced-route-bars");
  if (!summary || !bars) return;
  const routes = data?.route_recommendations || [];
  const topRoute = routes[0] || null;
  if (routeState) routeState.textContent = topRoute ? "Ready" : "Waiting";
  clear(summary);
  clear(bars);

  if (!topRoute) {
    summary.appendChild(
      advancedStatusRow(
        "No route signal",
        "waiting",
        "Write a task or refresh cockpit state to generate local route recommendations.",
      ),
    );
    return;
  }

  const top = document.createElement("article");
  top.className = "advanced-route-top";
  const orbit = document.createElement("span");
  orbit.className = "lane-orbit";
  orbit.setAttribute("aria-hidden", "true");
  const body = document.createElement("div");
  const label = document.createElement("span");
  label.textContent = "Top recommendation";
  const title = document.createElement("strong");
  title.textContent = topRoute.lane_name;
  const detail = document.createElement("p");
  detail.textContent = `${topRoute.summary} Remote execution remains off.`;
  body.append(label, title, detail);
  top.append(orbit, body, pill(topRoute.status || "recommended"));
  summary.appendChild(top);

  routes.slice(0, 5).forEach((route) => {
    const score = Math.max(0, Math.min(100, Number(route.score || 0)));
    const row = document.createElement("article");
    row.className = "advanced-route-bar";
    row.style.setProperty("--advanced-route-score", `${score}%`);
    const head = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = route.lane_name;
    const value = document.createElement("span");
    value.textContent = `${score}`;
    head.append(name, value);
    const track = document.createElement("i");
    track.setAttribute("aria-hidden", "true");
    const reason = document.createElement("p");
    reason.textContent = (route.reasons || []).slice(0, 2).join("; ") || "Local route signal.";
    row.append(head, track, reason);
    bars.appendChild(row);
  });
}

function advancedSettingRow(label, value, detail, status = "ready") {
  const row = document.createElement("article");
  row.className = `advanced-setting-row gate-tone-${gateToneName(status)}`;
  const body = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = label;
  const copy = document.createElement("p");
  copy.textContent = detail;
  body.append(title, copy);
  const badge = document.createElement("span");
  badge.className = "advanced-setting-value";
  badge.textContent = value;
  row.append(body, badge);
  return row;
}

function renderAdvancedStaticSettings(data) {
  const packet = homePacketForDisplay(data);
  const evidenceList = $("#advanced-evidence-settings");
  if (evidenceList) {
    clear(evidenceList);
    evidenceList.append(
      advancedSettingRow(
        "Default evidence posture",
        packet?.attach_evidence ? "Recorder" : "Recommended",
        packet?.attach_evidence
          ? "Current packet has AgentLedger represented locally."
          : "Evidence is suggested for most work but not mandatory.",
        packet?.attach_evidence ? "represented" : "recommended",
      ),
      advancedSettingRow("Default trace level", "Standard", "Captures packet history, gates, routes, and local adapter state.", "ready"),
      advancedSettingRow("Auto-bundle on completion", "Off", "Handoff export remains an explicit operator action.", "off"),
    );
  }

  const privacyList = $("#advanced-privacy-settings");
  if (privacyList) {
    clear(privacyList);
    privacyList.append(
      advancedSettingRow("Data handling", "Local-only", "Mission data, packets, and evidence stay on this machine.", "ready"),
      advancedSettingRow("Remote execution", "Off", "Adapters may be represented, but no remote agent runner is launched.", "off"),
      advancedSettingRow("Sanitized export", "Enabled", "Handoff exports avoid local filesystem paths and private workspace details.", "ready"),
    );
  }

  const debugList = $("#advanced-debug-settings");
  if (debugList) {
    clear(debugList);
    debugList.append(
      advancedSettingRow("Debug mode", "Off", "No verbose runtime tracing is enabled from the cockpit.", "off"),
      advancedSettingRow("Verbose logging", "Off", "The prototype keeps diagnostics minimal unless explicitly exported.", "off"),
      advancedSettingRow("Export diagnostics", "Manual", "Generate sanitized diagnostics only from an operator action.", "optional"),
    );
  }

  const aboutList = $("#advanced-about-settings");
  if (aboutList) {
    clear(aboutList);
    const appInfo = state.appInfo || {};
    aboutList.append(
      advancedSettingRow("Hamiltonian", `v${appInfo.version || "unknown"}`, "Local agent operations cockpit.", "ready"),
      advancedSettingRow("Application surface", appInfo.surface === "desktop" ? "Desktop" : "Browser", "The same local cockpit runs inside the selected application surface.", "ready"),
      advancedSettingRow("Workspace lock", appInfo.workspace_locked ? "Enforced" : "Session", appInfo.workspace_locked ? "This desktop window is locked to its selected repository." : "The browser cockpit uses its current repository session.", appInfo.workspace_locked ? "ready" : "optional"),
      advancedSettingRow("Updates", "Manual", "Updates use a verified local build package; no remote updater runs in the background.", "optional"),
      advancedSettingRow("Crash diagnostics", "Local only", "Sanitized desktop crash reports stay in the selected application data directory.", "ready"),
    );
  }
}

function renderAdvancedSettings(data) {
  if (!$("#advanced")) return;
  const installed = (data.integrations || []).filter((integration) => integration.available).length;
  const totalIntegrations = (data.integrations || []).length;
  setText("#advanced-integration-count", `${installed}/${totalIntegrations} ok`);
  setText("#advanced-agent-count", `${(data.agents || []).length} lanes`);
  setText("#advanced-debug-state", "Off");
  renderAdvancedDataSources(data);
  renderAdvancedRouteScoring(data);
  renderAdvancedStaticSettings(data);
}

function advancedTabTarget(tabName) {
  return {
    integrations: ".advanced-integrations-card",
    workspace: ".advanced-data-card",
    privacy: ".advanced-privacy-card",
    adapters: ".advanced-adapter-card",
    "route-scoring": ".advanced-route-card",
    export: "#next-build",
    debug: ".advanced-debug-card",
    about: ".advanced-about-card",
  }[tabName] || ".advanced-data-card";
}

function initAdvancedSettingsControls() {
  const tabs = document.querySelectorAll("#advanced-tabs button");
  tabs.forEach((tab) => {
    tab.setAttribute("aria-pressed", String(tab.classList.contains("advanced-tab-active")));
    tab.addEventListener("click", () => {
      tabs.forEach((button) => {
        const active = button === tab;
        button.classList.toggle("advanced-tab-active", active);
        button.setAttribute("aria-pressed", String(active));
      });
      const target = document.querySelector(advancedTabTarget(tab.dataset.advancedTab));
      if (target) {
        target.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }
    });
  });
}

function routeBackTarget() {
  return state.selectedPacket?.packet_id ? "packet-detail-panel" : "cockpit";
}

function routeSelectionLaneId(routes, activePacket) {
  const currentLaneId = activePacket?.agent_id || $("#agent-select")?.value || "";
  const pendingIsValid = routes.some((route) => route.lane_id === state.pendingRouteLaneId);
  if (pendingIsValid) return state.pendingRouteLaneId;
  if (routes.some((route) => route.lane_id === currentLaneId)) return currentLaneId;
  return routes[0]?.lane_id || null;
}

function routeImpactMetric(label, value, tone = "optional") {
  const card = document.createElement("article");
  card.className = `route-impact-metric gate-tone-${tone}`;
  const strong = document.createElement("strong");
  strong.textContent = value;
  const span = document.createElement("span");
  span.textContent = label;
  card.append(strong, span);
  return card;
}

function renderRouteCompass(routes, selectedRoute, activePacket) {
  const compass = $("#route-compass");
  const impact = $("#route-impact");
  if (compass) clear(compass);
  if (impact) clear(impact);
  if (!compass || routes.length === 0) return;

  const recommended = routes[0];
  const selected = selectedRoute || recommended;
  const isRecommended = selected?.lane_id === recommended?.lane_id;
  const target = activePacket?.packet_id ? "this packet" : "new packets";

  const orbit = document.createElement("div");
  orbit.className = "lane-orbit";
  orbit.setAttribute("aria-hidden", "true");
  const body = document.createElement("div");
  body.className = "route-compass-body";
  const label = document.createElement("span");
  label.textContent = isRecommended ? "Recommended lane" : "Operator override";
  const title = document.createElement("strong");
  title.textContent = selected?.lane_name || "No lane selected";
  const detail = document.createElement("p");
  detail.textContent = selected
    ? `${selected.summary} This selection will apply to ${target}.`
    : "Choose a lane before continuing.";
  body.append(label, title, detail);
  compass.append(orbit, body, pill(isRecommended ? "best fit" : "override"));

  if (impact && selected) {
    const boundary = selected.remote_execution ? "represented" : "local-only";
    impact.append(
      routeImpactMetric("fit", String(selected.score || 0), isRecommended ? "safe" : "warn"),
      routeImpactMetric("rank", `#${selected.rank || "-"}`, "optional"),
      routeImpactMetric("boundary", boundary, selected.remote_execution ? "warn" : "safe"),
    );
  }
}

function renderRoutes(data) {
  const list = $("#route-list");
  const confirm = $("#route-confirm-button");
  clear(list);
  const routes = data.route_recommendations || [];
  const activePacket = state.selectedPacket;
  const selectedLaneId = routeSelectionLaneId(routes, activePacket);
  const selectedRoute = routes.find((route) => route.lane_id === selectedLaneId) || null;
  const recommendedRoute = routes[0] || null;
  state.pendingRouteLaneId = selectedLaneId;

  setText("#route-screen-title", activePacket?.packet_id ? "Select lane for packet" : "Select agent lane");
  setText("#route-selection-count", `${routes.length} lane${routes.length === 1 ? "" : "s"}`);
  setText("#route-recommended-badge", recommendedRoute?.status || "Waiting");

  if (routes.length === 0) {
    const empty = document.createElement("article");
    empty.className = "route lane-option-card lane-option-empty";
    const title = document.createElement("strong");
    title.textContent = "No route recommendations";
    const detail = document.createElement("p");
    detail.textContent = "Refresh cockpit state to build local lane recommendations.";
    empty.append(title, detail, pill("empty"));
    list.appendChild(empty);
    renderRouteCompass(routes, null, activePacket);
    setText("#route-selection-summary", "No lane signal yet. Write a task or refresh cockpit state.");
    setText("#route-override-title", "No lane available yet");
    setText("#route-override-body", "Hamiltonian needs a task before it can score local lane recommendations.");
    if (confirm) {
      confirm.disabled = true;
      confirm.textContent = "Confirm lane";
      confirm.onclick = null;
    }
    return;
  }

  renderRouteCompass(routes, selectedRoute, activePacket);

  const isOverride = selectedRoute && recommendedRoute && selectedRoute.lane_id !== recommendedRoute.lane_id;
  setText("#route-override-title", isOverride ? "Override selected" : "Recommended lane selected");
  setText(
    "#route-override-body",
    isOverride
      ? `${selectedRoute.lane_name} is not the top recommendation. The packet will record this as an operator lane override.`
      : "Hamiltonian recommends this lane from local task metadata. Gates still decide before execution.",
  );
  setText(
    "#route-selection-summary",
    selectedRoute
      ? `${selectedRoute.lane_name} is selected. Remote execution remains off.`
      : "Choose a lane to continue.",
  );

  routes.forEach((route) => {
    const isActivePacketLane = Boolean(activePacket?.packet_id && activePacket.agent_id === route.lane_id);
    const isSelected = route.lane_id === selectedLaneId;
    const isRecommended = recommendedRoute?.lane_id === route.lane_id;
    const activeLaneReviewed = isActivePacketLane && packetHasLaneDecision(activePacket);
    const scoreValue = Math.max(0, Math.min(100, Number(route.score || 0)));
    const row = document.createElement("article");
    row.className = "route lane-option-card";
    row.classList.toggle("route-current", isActivePacketLane);
    row.classList.toggle("lane-option-selected", isSelected);
    row.classList.toggle("lane-option-recommended", isRecommended);
    row.dataset.routeLaneId = route.lane_id;
    row.dataset.testid = "route-lane";
    row.style.setProperty("--route-strength", `${scoreValue}%`);
    row.setAttribute("role", "radio");
    row.setAttribute("aria-checked", String(isSelected));
    row.tabIndex = 0;
    row.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      state.pendingRouteLaneId = route.lane_id;
      renderRoutes(state.data || data);
    });

    const body = document.createElement("div");
    body.className = "route-body";
    const kicker = document.createElement("span");
    kicker.className = "route-kicker";
    kicker.textContent = isRecommended ? "Recommended lane" : `Lane ${route.rank}`;
    const title = document.createElement("strong");
    title.textContent = route.lane_name;
    const summary = document.createElement("p");
    summary.textContent = route.summary;
    const reasons = document.createElement("p");
    reasons.textContent = `Why: ${(route.reasons || []).join("; ")}`;
    const boundary = document.createElement("p");
    boundary.className = "route-boundary";
    boundary.textContent = route.remote_execution
      ? "Boundary: remote execution represented only."
      : "Boundary: local-only lane; execution requires a separate operator action.";
    body.append(kicker, title, summary, reasons, boundary);

    if (route.warnings && route.warnings.length) {
      const warnings = document.createElement("p");
      warnings.className = "route-warning";
      warnings.textContent = `Check: ${route.warnings.join("; ")}`;
      body.appendChild(warnings);
    }

    const actions = document.createElement("div");
    actions.className = "route-actions";
    const score = document.createElement("span");
    score.className = "route-score";
    score.textContent = route.score;
    score.title = "Route match score";
    const strength = document.createElement("div");
    strength.className = "route-strength";
    const strengthFill = document.createElement("span");
    const strengthLabel = document.createElement("small");
    strengthLabel.textContent = "match";
    strength.append(strengthFill, strengthLabel);
    const useButton = document.createElement("button");
    useButton.type = "button";
    useButton.className = "compact-button";
    useButton.classList.add("route-select-button");
    useButton.textContent = isSelected ? "Selected" : isActivePacketLane ? "Current" : "Select";
    useButton.title = `Stage ${route.lane_name} as the lane selection`;
    useButton.dataset.testid = "select-route-lane";
    useButton.dataset.laneId = route.lane_id;
    useButton.addEventListener("click", () => {
      state.pendingRouteLaneId = route.lane_id;
      renderRoutes(state.data || data);
    });
    actions.append(score, strength, pill(route.status), useButton);
    row.append(body, actions);
    row.addEventListener("click", (event) => {
      if (event.target.closest("button")) return;
      state.pendingRouteLaneId = route.lane_id;
      renderRoutes(state.data || data);
    });
    list.appendChild(row);
  });

  if (confirm) {
    const selectedIsReviewedCurrent = Boolean(
      activePacket?.packet_id && activePacket.agent_id === selectedRoute?.lane_id && packetHasLaneDecision(activePacket),
    );
    confirm.disabled = !selectedRoute || selectedIsReviewedCurrent;
    confirm.textContent = selectedIsReviewedCurrent
      ? "Current lane"
      : activePacket?.packet_id
        ? "Confirm lane"
        : "Use lane for packet";
    confirm.onclick = selectedRoute
      ? () => {
          useRouteLane(selectedRoute, confirm).catch((error) => {
            const status = $("#packet-detail-status");
            if (status) status.textContent = error.message;
            setText("#route-selection-summary", error.message);
          });
        }
      : null;
  }
}

async function useRouteLane(route, button) {
  const select = $("#agent-select");
  if ([...select.options].some((option) => option.value === route.lane_id)) {
    select.value = route.lane_id;
  }
  state.pendingRouteLaneId = route.lane_id;

  if (!state.selectedPacket?.packet_id || state.cockpitMode === "recorder") {
    state.lastPacket = null;
    renderPacket();
    scheduleLiveRouteUpdate(0);
    revealSection("cockpit");
    return;
  }

  if (button) {
    button.disabled = true;
    button.textContent = "Confirming...";
  }
  const packet = await selectPacketLane(route.lane_id);
  state.selectedPacket = packet;
  state.lastPacket = packet;
  state.pendingRouteLaneId = packet.agent_id;
  await load(state.repo);
  await refreshLiveRoutes().catch((error) => console.warn(error));
  revealSection("gates");
}

function routeRequestPayload() {
  const recorderMode = state.cockpitMode === "recorder";
  const useActivePacket = Boolean(state.lastPacket?.packet_id && state.selectedPacket?.packet_id);
  return {
    repo: $("#repo-input").value || state.repo,
    task: useActivePacket ? state.selectedPacket.task || "" : $("#task-input").value.trim(),
    agent_id: recorderMode
      ? "codex"
      : useActivePacket
        ? state.selectedPacket.agent_id || "codex"
        : $("#agent-select").value || "codex",
  };
}

function scheduleLiveRouteUpdate(delay = 250) {
  if (!state.data) return;
  window.clearTimeout(state.routeTimer);
  state.routeTimer = window.setTimeout(() => {
    refreshLiveRoutes().catch((error) => {
      const list = $("#route-list");
      if (list && list.firstChild) {
        list.firstChild.appendChild(pill("route refresh failed"));
      }
      console.warn(error);
    });
  }, delay);
}

async function refreshLiveRoutes() {
  const seq = state.routeRequestSeq + 1;
  state.routeRequestSeq = seq;
  const response = await fetch("/api/routes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(routeRequestPayload()),
  });
  const data = await response.json();
  if (!response.ok || data.error) throw new Error(data.error || "Route request failed");
  if (seq !== state.routeRequestSeq || !state.data) return;
  state.data.route_recommendations = data.route_recommendations || [];
  renderRoutes(state.data);
  renderMissionHome(state.data);
  renderCreatePacketScreen(state.data);
  renderAdvancedSettings(state.data);
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
    const route = packet.route || {};
    const runnerPlan = packet.runner_plan || {
      status: "unknown",
      mode: "legacy",
      launch_supported: false,
      remote_execution: false,
    };
    const row = document.createElement("article");
    row.className = "packet";
    row.dataset.packetId = packet.packet_id;
    row.dataset.testid = "packet-row";
    const body = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = `${lane.name} -> ${packet.stage}`;
    const detail = document.createElement("p");
    detail.textContent = packet.task_excerpt;
    const meta = document.createElement("p");
    const remote = lane.remote_execution ? "remote" : "local-only";
    meta.textContent = `Lane: ${lane.status} (${lane.execution}, ${remote}). Gates: ${gateRun.completed}/${gateRun.total}, blocked ${gateRun.blocked}, simulated ${gateRun.simulated}.`;
    const routeLine = document.createElement("p");
    routeLine.textContent = `Route: ${route.status || "unknown"}; recommended ${route.recommended_lane_name || lane.name}.`;
    const execution = document.createElement("p");
    const localExec = executionBoundary.local_execution ? "local execution armed" : "local execution off";
    const remoteExec = executionBoundary.remote_execution ? "remote execution armed" : "remote execution off";
    execution.textContent = `Execute: ${executionBoundary.status} (${executionBoundary.mode}). ${localExec}; ${remoteExec}.`;
    const runner = document.createElement("p");
    runner.textContent = `Runner: ${runnerPlan.status} (${runnerPlan.mode}). Launch ${runnerPlan.launch_supported ? "available" : "disabled"}; remote execution ${runnerPlan.remote_execution ? "on" : "off"}.`;
    const handoffLine = document.createElement("p");
    const handoffReady = handoff.ready ? "ready" : "not ready";
    handoffLine.textContent = `Handoff: ${handoff.status} (${handoff.mode}, ${handoffReady}). Evidence: ${handoff.evidence_status}.`;
    const proof = document.createElement("p");
    proof.textContent = `Memory: ${memoryStatus} (${memoryMode}). Evidence: ${evidenceStatus}. Packet: ${packet.packet_id}`;
    const next = document.createElement("p");
    next.className = "packet-next";
    next.textContent = handoff.next_action || executionBoundary.next_action || gateRun.next_action;
    body.append(title, detail, meta, routeLine, execution, runner, handoffLine, proof, next);
    const actions = document.createElement("div");
    actions.className = "packet-actions";
    const openButton = document.createElement("button");
    openButton.type = "button";
    openButton.className = "compact-button";
    openButton.textContent = "Open";
    openButton.title = "Open packet detail";
    openButton.dataset.testid = "open-packet";
    openButton.dataset.packetId = packet.packet_id;
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

function setText(selector, value) {
  const node = $(selector);
  if (node) node.textContent = value ?? "";
}

function formatHomeTime(value) {
  if (!value) return "Waiting";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function homePacketForDisplay(data) {
  if (state.selectedPacket?.packet_id) return state.selectedPacket;
  if (state.lastPacket?.packet_id) return state.lastPacket;
  return (data?.recent_packets || [])[0] || null;
}

function homeTaskTitle(packet) {
  if (!packet) return "No mission packet yet";
  const task = packet.task || packet.task_excerpt || "Untitled packet";
  const firstLine = String(task).split(/\r?\n/).find(Boolean) || "Untitled packet";
  return firstLine.length > 54 ? `${firstLine.slice(0, 51)}...` : firstLine;
}

function homePacketCode(packet) {
  if (!packet?.packet_id) return "M-00";
  const compact = String(packet.packet_id).replace(/[^a-z0-9]/gi, "");
  return `M-${compact.slice(-4).toUpperCase() || "00"}`;
}

function homeObjective(packet) {
  if (!packet) {
    return "Define the mission, choose a lane, and add evidence when it matters.";
  }
  const task = packet.task || packet.task_excerpt || "Review packet details and choose the next safe action.";
  return task.length > 130 ? `${task.slice(0, 127)}...` : task;
}

function homeEvidenceOptions(packet) {
  const evidenceGate = packetGate(packet, "evidence");
  const evidenceStatus = evidenceGate.status || packet?.evidence_status || "skipped";
  const attached = Boolean(packet?.attach_evidence) || ["represented", "simulated"].includes(evidenceStatus);
  const options = [
    {
      id: "optional",
      title: "Optional",
      body: "Faster outputs, lighter traces.",
      status: "optional",
      selected: !packet,
    },
    {
      id: "recommended",
      title: "Recommended",
      body: "Balanced evidence for most work. Evidence is not always required.",
      status: "recommended",
      selected: Boolean(packet && !attached),
    },
    {
      id: "required",
      title: "Required",
      body: "Maximum traceability. All claims must be supported.",
      status: "required",
      selected: false,
    },
  ];
  if (attached) {
    options.push({
      id: "recorder",
      title: "Recorder-attached",
      body: "AgentLedger evidence is represented locally only.",
      status: evidenceStatus,
      selected: true,
    });
  }
  return options;
}

function homeReadinessRows(packet) {
  if (!packet) {
    return [
      { label: "Safety / Intent", status: "pending", detail: "Create a packet first." },
      { label: "Memory Check", status: "waiting", detail: "RepoMori boundary has not run." },
      { label: "Cost / Context", status: "waiting", detail: "Local estimate waits for a task." },
      { label: "Execution Readiness", status: "off", detail: "Remote execution remains off." },
      { label: "Handoff Readiness", status: "not ready", detail: "No packet to hand off yet." },
    ];
  }

  const gates = Object.fromEntries((packet.gates || []).map((gate) => [gate.id, gate]));
  const gateRun = packet.gate_run || {};
  const executionBoundary = packet.execution_boundary || {};
  const handoff = packet.handoff || {};
  const memory = gates.memory || {};
  const intent = gates.intent || {};
  const cost = gates.cost || {};
  return [
    {
      label: "Safety / Intent",
      status: intent.status || gateRun.status || packet.status || "pending",
      detail: intent.summary || gateRun.next_action || "Safety gate waits for the packet.",
    },
    {
      label: "Memory Check",
      status: memory.status || packet.memory_status || "pending",
      detail: memory.mode ? `RepoMori boundary: ${memory.mode}.` : "RepoMori boundary has not checked yet.",
    },
    {
      label: "Cost / Context",
      status: cost.status || "pending",
      detail: cost.summary || "Local cost and context check is synthetic until wired.",
    },
    {
      label: "Execution Readiness",
      status: executionBoundary.status || "not-prepared",
      detail: executionBoundary.remote_execution
        ? "External execution is represented only."
        : "Remote execution off; manual boundary only.",
    },
    {
      label: "Handoff Readiness",
      status: handoff.status || "not-prepared",
      detail: handoff.ready ? "Packet is ready for operator handoff." : handoff.next_action || "Prepare handoff after gates.",
    },
  ];
}

function renderHomeReadiness(packet) {
  const list = $("#home-readiness-list");
  if (!list) return;
  clear(list);
  homeReadinessRows(packet).forEach((item) => {
    const row = document.createElement("article");
    row.className = "home-readiness-row";
    row.dataset.statusTone = statusClass(item.status);
    const body = document.createElement("div");
    const label = document.createElement("strong");
    label.textContent = item.label;
    const detail = document.createElement("p");
    detail.textContent = item.detail;
    body.append(label, detail);
    row.append(body, pill(item.status));
    list.appendChild(row);
  });
}

function renderHomeEvidence(packet) {
  const list = $("#home-evidence-options");
  if (!list) return;
  clear(list);
  homeEvidenceOptions(packet).forEach((option) => {
    const card = document.createElement("button");
    card.type = "button";
    card.className = `home-evidence-option ${option.selected ? "home-evidence-selected" : ""}`;
    card.setAttribute("aria-pressed", String(option.selected));
    card.addEventListener("click", () => {
      if (option.id === "recorder") {
        revealSection("packet-detail-panel");
        return;
      }
      if (option.id === "recommended" || option.id === "required") {
        revealSection(packet?.packet_id ? "packet-detail-panel" : "cockpit");
      }
    });
    const title = document.createElement("strong");
    title.textContent = option.title;
    const body = document.createElement("span");
    body.textContent = option.body;
    card.append(pill(option.status), title, body);
    list.appendChild(card);
  });
}

function renderHomeLane(data, packet) {
  const route = (data.route_recommendations || [])[0] || packet?.route || null;
  const lane = packet?.lane || {};
  const title = route?.lane_name || route?.recommended_lane_name || lane.name || packet?.agent_name || "No lane selected";
  const fit = route?.status || (packet ? lane.status || "selected" : "Waiting");
  const summary =
    route?.summary ||
    (packet
      ? `${title} owns the packet through a local adapter boundary.`
      : "Write a task to generate a local route recommendation.");
  setText("#home-lane-title", title);
  setText("#home-lane-fit", fit);
  setText("#home-lane-body", summary);
}

function renderHomeRecentPackets(data) {
  const list = $("#home-recent-packets");
  if (!list) return;
  clear(list);
  const packets = (data.recent_packets || []).slice(0, 5);
  if (packets.length === 0) {
    const empty = document.createElement("article");
    empty.className = "recent-packet-card recent-packet-empty";
    const title = document.createElement("strong");
    title.textContent = "No packets yet";
    const detail = document.createElement("span");
    detail.textContent = "Your first mission will appear here.";
    empty.append(title, detail);
    list.appendChild(empty);
    return;
  }

  packets.forEach((packet) => {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "recent-packet-card";
    card.dataset.packetId = packet.packet_id;
    card.dataset.testid = "home-recent-packet";
    card.addEventListener("click", () => {
      loadPacketDetail(packet.packet_id).catch((error) => {
        const status = $("#packet-detail-status");
        if (status) status.textContent = error.message;
      });
    });
    const code = document.createElement("span");
    code.textContent = homePacketCode(packet);
    const title = document.createElement("strong");
    title.textContent = homeTaskTitle(packet);
    const meta = document.createElement("small");
    meta.textContent = `Updated ${formatHomeTime(packet.updated_at || packet.created_at)}`;
    const trace = document.createElement("i");
    trace.setAttribute("aria-hidden", "true");
    card.append(code, title, meta, trace);
    list.appendChild(card);
  });
}

function goalStatusLabel(status) {
  return {
    "awaiting-codex": "Waiting for Codex",
    "ready-for-review": "Ready for review",
    complete: "Complete",
    corrected: "Corrected by follow-up",
    "needs-correction": "Needs correction",
    "correction-in-progress": "Correction in progress",
    "receipt-invalid": "Receipt needs attention",
  }[status] || String(status || "Unknown").replaceAll("-", " ");
}

function renderGoalHistory() {
  const list = $("#goal-history-list");
  if (!list) return;
  clear(list);
  const goals = state.goals || [];
  const ready = goals.filter((goal) => goal.lifecycle_status === "ready-for-review").length;
  const correction = goals.filter((goal) => goal.lifecycle_status === "needs-correction").length;
  setText(
    "#goal-history-summary",
    ready ? `${ready} ready for review` : correction ? `${correction} need correction` : goals.length ? `${goals.length} local goals` : "No goals yet",
  );
  if (!goals.length) {
    const empty = document.createElement("p");
    empty.className = "goal-history-empty";
    empty.textContent = "Completed Codex handoffs will appear here automatically.";
    list.appendChild(empty);
    return;
  }

  goals.forEach((goal) => {
    const row = document.createElement("article");
    row.className = "goal-history-row";
    row.dataset.goalId = goal.goal_id;
    row.dataset.testid = "goal-history-row";

    const identity = document.createElement("div");
    identity.className = "goal-history-identity";
    const type = document.createElement("span");
    type.textContent = goal.goal_type === "corrective" ? `Corrective goal ${goal.correction_index}` : `${goal.goal_type} goal`;
    const objective = document.createElement("strong");
    objective.textContent = goal.objective || goal.goal_id;
    const id = document.createElement("small");
    id.textContent = goal.goal_id;
    identity.append(type, objective, id);

    const detail = document.createElement("div");
    detail.className = "goal-history-detail";
    const stage = document.createElement("span");
    const receiptReady = Boolean(goal.receipt?.valid);
    const reviewReady = Boolean(goal.review?.valid);
    stage.textContent = `Diagnosis saved / Goal saved / Receipt ${receiptReady ? "received" : "waiting"} / Review ${reviewReady ? "recorded" : "waiting"}`;
    const summary = document.createElement("p");
    summary.textContent = reviewReady
      ? goal.review.summary || "Review recorded locally."
      : receiptReady
        ? goal.receipt.summary || "Codex reports the goal is ready for review."
        : goal.receipt?.status === "invalid"
          ? goal.receipt.error || "The return receipt could not be validated."
          : "Waiting for Codex to write the local return receipt.";
    const lineage = document.createElement("small");
    const grade = goal.grade_movement ? `Grade: ${goal.grade_movement}. ` : "";
    const parent = goal.parent_goal_id ? `Follows ${goal.parent_goal_id}. ` : "";
    const children = goal.child_goal_ids?.length ? `${goal.child_goal_ids.length} corrective follow-up${goal.child_goal_ids.length === 1 ? "" : "s"}.` : "";
    lineage.textContent = `${grade}${parent}${children}`.trim() || "Original goal.";
    detail.append(stage, summary, lineage);

    const status = document.createElement("div");
    status.className = "goal-history-status";
    const badge = document.createElement("span");
    badge.className = "goal-history-badge";
    badge.dataset.status = goal.lifecycle_status;
    badge.textContent = goalStatusLabel(goal.lifecycle_status);
    const actions = document.createElement("div");
    actions.className = "goal-history-actions";

    const copy = document.createElement("button");
    copy.type = "button";
    copy.className = "compact-button";
    copy.textContent = "Copy goal";
    copy.addEventListener("click", () => {
      copyText(goal.goal_markdown)
        .then(() => setText("#goal-history-summary", `Copied ${goal.goal_id}.`))
        .catch((error) => setText("#goal-history-summary", error.message));
    });
    actions.appendChild(copy);

    if (goal.lifecycle_status === "ready-for-review") {
      const review = document.createElement("button");
      review.type = "button";
      review.className = "compact-button primary-action";
      review.textContent = "Review now";
      review.addEventListener("click", () => {
        reviewGoalById(goal.goal_id).catch((error) => setText("#goal-history-summary", error.message));
      });
      actions.appendChild(review);
    }
    if (goal.lifecycle_status === "needs-correction") {
      const corrective = document.createElement("button");
      corrective.type = "button";
      corrective.className = "compact-button primary-action";
      corrective.textContent = "Create corrective goal";
      corrective.addEventListener("click", () => {
        createCorrectiveGoal(goal.goal_id).catch((error) => setText("#goal-history-summary", error.message));
      });
      actions.appendChild(corrective);
    }
    status.append(badge, actions);
    row.append(identity, detail, status);
    list.appendChild(row);
  });
}

async function refreshGoalHistory() {
  window.clearTimeout(state.goalHistoryTimer);
  try {
    const params = _queryRepoParams();
    const response = await fetch(`/api/goals?${params.toString()}`);
    const payload = await response.json();
    if (!response.ok || payload.error) throw new Error(payload.error || "Could not refresh goal history.");
    state.goals = payload.goals || [];
    renderGoalHistory();
  } finally {
    state.goalHistoryTimer = window.setTimeout(() => {
      refreshGoalHistory().catch((error) => setText("#goal-history-summary", error.message));
    }, 10000);
  }
}

async function createCorrectiveGoal(goalId) {
  const response = await fetch(`/api/goals/${encodeURIComponent(goalId)}/corrective`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ repo: $("#repo-input").value || state.repo }),
  });
  const payload = await response.json();
  if (!response.ok || payload.error) throw new Error(payload.error || "Could not create the corrective goal.");
  state.goalDraft = { goalType: "corrective", preview: payload.goal, saved: payload.goal };
  renderGoalBuilder();
  $("#goal-dialog")?.showModal();
  await refreshGoalHistory();
}

function setSimpleRunState(status, title, body, options = {}) {
  state.simpleRun = {
    ...state.simpleRun,
    ...options,
    status,
    title,
    body,
  };
  renderSimpleRunExperience();
}

function simpleRunIsActive() {
  return ["starting", "running", "cancelling"].includes(state.simpleRun.status);
}

function setSimpleStep(selector, stepState) {
  const node = $(selector);
  if (!node) return;
  node.dataset.state = stepState;
  node.setAttribute("aria-label", `${node.textContent.trim()}: ${stepState}`);
}

function renderSimpleRunExperience() {
  const run = state.simpleRun;
  const home = $("#mission-home");
  const statusPanel = $("#simple-run-status");
  const runButton = $("#simple-run-button");
  const taskInput = $("#simple-task-input");
  const openButton = $("#simple-open-packet");
  const goalButton = $("#simple-goal-button");
  const result = $("#simple-run-result");
  const active = simpleRunIsActive();
  const busyBeforeLaunch = ["saving", "checking"].includes(run.status);

  if (home) home.dataset.packetId = run.packetId || "";

  if (statusPanel) {
    statusPanel.hidden = run.status === "idle";
    statusPanel.dataset.status = run.status;
  }
  setText("#simple-status-badge", run.status.replaceAll("-", " "));
  setText("#simple-status-title", run.title);
  setText("#simple-status-body", run.body);

  if (runButton) {
    runButton.textContent = active ? (run.status === "cancelling" ? "Stopping..." : "Stop") : "Run locally";
    runButton.disabled = busyBeforeLaunch || run.status === "cancelling";
  }
  if (taskInput) taskInput.disabled = active || busyBeforeLaunch;
  if (openButton) openButton.disabled = !run.packetId;
  if (goalButton) goalButton.hidden = !(run.status === "succeeded" && Boolean(run.result));

  const checkState = ["idle", "saving"].includes(run.status)
    ? run.status === "saving" ? "current" : "waiting"
    : ["blocked", "error"].includes(run.status) ? "issue" : "done";
  const runState = ["starting", "running", "cancelling"].includes(run.status)
    ? "current"
    : run.status === "succeeded" ? "done"
      : ["unavailable", "blocked", "failed", "timed-out", "cancelled", "error"].includes(run.status) ? "issue" : "waiting";
  const doneState = run.status === "succeeded" ? "done" : ["failed", "timed-out", "cancelled", "error"].includes(run.status) ? "issue" : "waiting";
  setSimpleStep("#simple-step-check", checkState);
  setSimpleStep("#simple-step-run", runState);
  setSimpleStep("#simple-step-done", doneState);

  if (result) {
    result.hidden = !run.result;
    result.textContent = run.result || "";
  }
}

function goalPayload() {
  return {
    repo: $("#repo-input").value || state.repo,
    goal_type: state.goalDraft?.goalType || "maintenance",
    source_report: state.simpleRun.result || "",
    source_packet_id: state.simpleRun.packetId || null,
    expansion_request: $("#goal-expansion-input")?.value.trim() || null,
    goal_id: state.goalDraft?.preview?.goal_id || state.goalDraft?.saved?.goal_id || null,
    parent_goal_id: state.goalDraft?.preview?.parent_goal_id || state.goalDraft?.saved?.parent_goal_id || null,
  };
}

function renderGoalBuilder() {
  const draft = state.goalDraft || { goalType: "maintenance", preview: null, saved: null };
  const corrective = draft.goalType === "corrective";
  const maintenance = draft.goalType === "maintenance";
  const maintenanceButton = $("#goal-type-maintenance");
  const expansionButton = $("#goal-type-expansion");
  const typeControl = $("#goal-type-control");
  const expansionField = $("#goal-expansion-field");
  const saveButton = $("#goal-save-button");
  const preview = draft.saved || draft.preview;
  if (typeControl) typeControl.hidden = corrective;
  if (saveButton) saveButton.hidden = corrective;
  setText("#goal-dialog-title", corrective ? "Corrective Codex goal" : "Create Codex goal");
  if (maintenanceButton) {
    maintenanceButton.classList.toggle("goal-type-selected", maintenance);
    maintenanceButton.setAttribute("aria-checked", String(maintenance));
  }
  if (expansionButton) {
    expansionButton.classList.toggle("goal-type-selected", !maintenance);
    expansionButton.setAttribute("aria-checked", String(!maintenance));
  }
  if (expansionField) expansionField.hidden = draft.goalType !== "expansion";
  setText("#goal-target-label", corrective ? "Corrective goal" : maintenance ? "Maintenance goal" : "Expansion goal");
  setText(
    "#goal-objective",
    preview?.objective || (maintenance ? "Generating maintenance goal..." : "Describe the capability to generate the goal."),
  );
  const grade = maintenance && preview?.source_grade && preview?.target_grade
    ? `${preview.source_grade} to ${preview.target_grade}`
    : corrective ? `Correction ${preview?.correction_index || 1}` : maintenance ? "Next step" : "New capability";
  setText("#goal-grade-change", grade);
  setText(
    "#goal-preview",
    preview?.goal_markdown || (maintenance ? "Generating goal..." : "Describe what should become possible."),
  );
  const ready = Boolean(preview?.goal_markdown);
  ["#goal-copy-button", "#goal-save-button", "#goal-open-codex-button"].forEach((selector) => {
    const button = $(selector);
    if (button) button.disabled = !ready;
  });
  const reviewButton = $("#goal-review-button");
  if (reviewButton) reviewButton.hidden = true;
  if (draft.saved) {
    setText("#goal-dialog-status", `Saved locally as ${draft.saved.goal_id}.`);
  }
}

async function refreshGoalPreview() {
  const payload = goalPayload();
  if (!payload.source_report) throw new Error("Run a Hamiltonian check before creating a Codex goal.");
  if (payload.goal_type === "expansion" && !payload.expansion_request) {
    if (state.goalDraft) {
      state.goalDraft.preview = null;
      state.goalDraft.saved = null;
    }
    renderGoalBuilder();
    return;
  }
  setText("#goal-dialog-status", "Generating local goal preview...");
  const response = await fetch("/api/goals/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok || data.error) throw new Error(data.error || "Could not generate the Codex goal.");
  state.goalDraft = {
    goalType: payload.goal_type,
    preview: data.goal,
    saved: null,
  };
  setText("#goal-dialog-status", "Goal preview stays local until you save or open it.");
  renderGoalBuilder();
}

function scheduleGoalPreview(delay = 350) {
  window.clearTimeout(state.goalPreviewTimer);
  state.goalPreviewTimer = window.setTimeout(() => {
    refreshGoalPreview().catch((error) => setText("#goal-dialog-status", error.message));
  }, delay);
}

async function ensureGoalSaved() {
  if (state.goalDraft?.saved) return state.goalDraft.saved;
  const payload = goalPayload();
  if (!state.goalDraft?.preview) await refreshGoalPreview();
  payload.goal_id = state.goalDraft?.preview?.goal_id || payload.goal_id;
  setText("#goal-dialog-status", "Saving goal locally...");
  const response = await fetch("/api/goals", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok || data.error) throw new Error(data.error || "Could not save the Codex goal.");
  state.goalDraft.saved = data.goal;
  state.goalDraft.preview = data.goal;
  renderGoalBuilder();
  return data.goal;
}

async function copyText(value) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
    return;
  }
  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand("copy");
  textarea.remove();
}

async function copyCodexGoal() {
  const goal = await ensureGoalSaved();
  await copyText(goal.goal_markdown);
  setText("#goal-dialog-status", `Copied ${goal.goal_id}. Set it as the goal in the Codex project chat.`);
}

async function openGoalInCodex() {
  const goal = await ensureGoalSaved();
  await copyText(goal.goal_markdown);
  setText("#goal-dialog-status", "Opening the repository in Codex...");
  const response = await fetch("/api/codex/open", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ repo: goal.repo }),
  });
  const data = await response.json();
  if (!response.ok || data.error) throw new Error(data.error || "Could not open the Codex workspace.");
  setText("#goal-dialog-status", "Repository opened in Codex and the goal is copied. Choose the project chat and paste it.");
}

async function reviewCompletedGoal() {
  const goal = await ensureGoalSaved();
  await reviewGoalById(goal.goal_id);
}

async function reviewGoalById(goalId) {
  const goal = state.goals.find((item) => item.goal_id === goalId);
  if (!goal || goal.lifecycle_status !== "ready-for-review") {
    throw new Error("This goal does not have a valid Codex receipt ready for review.");
  }
  const taskInput = $("#simple-task-input");
  if (taskInput) {
    taskInput.value = goal.review_prompt;
    taskInput.dispatchEvent(new Event("input", { bubbles: true }));
  }
  state.activeReviewGoalId = goal.goal_id;
  $("#goal-dialog")?.close();
  revealSection("mission-home", { instant: true });
  try {
    await runSimpleMission();
  } catch (error) {
    state.activeReviewGoalId = null;
    throw error;
  }
}

function selectGoalType(goalType) {
  state.goalDraft = {
    goalType: goalType === "expansion" ? "expansion" : "maintenance",
    preview: null,
    saved: null,
  };
  renderGoalBuilder();
  scheduleGoalPreview(0);
}

function openGoalBuilder() {
  if (!(state.simpleRun.status === "succeeded" && state.simpleRun.result)) return;
  state.goalDraft = { goalType: "maintenance", preview: null, saved: null };
  const expansionInput = $("#goal-expansion-input");
  if (expansionInput) expansionInput.value = "";
  renderGoalBuilder();
  $("#goal-dialog")?.showModal();
  scheduleGoalPreview(0);
}

function clearSimplePoll() {
  window.clearTimeout(state.simplePollTimer);
  state.simplePollTimer = null;
}

async function recordGoalReview(goalId, packetId, report) {
  const response = await fetch(`/api/goals/${encodeURIComponent(goalId)}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      repo: $("#repo-input").value || state.repo,
      report,
      source_packet_id: packetId,
    }),
  });
  const payload = await response.json();
  if (!response.ok || payload.error) throw new Error(payload.error || "Could not record the goal review.");
  state.goals = payload.goals || state.goals;
  renderGoalHistory();
  return payload.review;
}

async function applySimpleRunnerState(packetId, run) {
  const status = String(run?.status || "failed");
  if (["starting", "running", "cancelling"].includes(status)) {
    const title = status === "cancelling" ? "Stopping the job" : "Working on it";
    setSimpleRunState(status, title, run.summary || "Codex is working inside the local workspace.", {
      packetId,
      result: "",
    });
    return true;
  }

  const messages = {
    succeeded: ["Done", run.summary || "The local job completed."],
    failed: ["The job failed", run.summary || "Codex stopped with an error."],
    "timed-out": ["The job took too long", run.summary || "Hamiltonian stopped it at the selected time limit."],
    cancelled: ["Job stopped", run.summary || "The local job was stopped."],
    interrupted: ["Job interrupted", run.summary || "The local process ended unexpectedly."],
  };
  let [title, body] = messages[status] || ["The job stopped", run?.summary || "No final runner state was returned."];
  if (state.activeReviewGoalId) {
    const goalId = state.activeReviewGoalId;
    state.activeReviewGoalId = null;
    if (status === "succeeded" && run?.last_message) {
      try {
        const review = await recordGoalReview(goalId, packetId, run.last_message);
        title = review.verdict === "complete" ? "Goal review complete" : "Goal needs a corrective pass";
        body = review.summary || "The review was recorded in local goal history.";
      } catch (error) {
        title = "Review finished, but was not recorded";
        body = error.message;
      }
    }
  }
  setSimpleRunState(status, title, body, {
    packetId,
    result: run?.last_message || "",
  });
  await load(state.repo);
  return false;
}

async function pollSimpleRunner(packetId, immediate = false) {
  clearSimplePoll();
  const sequence = state.simplePollSeq + 1;
  state.simplePollSeq = sequence;
  if (!immediate) await new Promise((resolve) => window.setTimeout(resolve, 650));
  const params = _queryRepoParams();
  const response = await fetch(`/api/packets/${encodeURIComponent(packetId)}/run?${params.toString()}`);
  const payload = await response.json();
  if (!response.ok || payload.error) throw new Error(payload.error || "Could not read the local job status.");
  if (sequence !== state.simplePollSeq || state.simpleRun.packetId !== packetId) return;
  state.selectedPacket = payload.packet || state.selectedPacket;
  const keepPolling = await applySimpleRunnerState(packetId, payload.run);
  if (keepPolling) {
    state.simplePollTimer = window.setTimeout(() => {
      pollSimpleRunner(packetId, true).catch((error) => {
        setSimpleRunState("error", "Could not read job status", error.message, { packetId });
      });
    }, 700);
  }
}

async function cancelSimpleMission() {
  const packetId = state.simpleRun.packetId;
  if (!packetId) return;
  setSimpleRunState("cancelling", "Stopping the job", "Stopping the local process...", { packetId });
  const params = _queryRepoParams();
  const response = await fetch(`/api/packets/${encodeURIComponent(packetId)}/run/cancel?${params.toString()}`, {
    method: "POST",
  });
  const payload = await response.json();
  if (!response.ok || payload.error) throw new Error(payload.error || "Could not stop the local job.");
  await applySimpleRunnerState(packetId, payload.run);
  if (["starting", "running", "cancelling"].includes(payload.run?.status)) {
    pollSimpleRunner(packetId).catch((error) => {
      setSimpleRunState("error", "Could not read job status", error.message, { packetId });
    });
  }
}

async function runSimpleMission() {
  if (simpleRunIsActive()) {
    await cancelSimpleMission();
    return;
  }

  const taskInput = $("#simple-task-input");
  const task = taskInput?.value.trim() || "";
  if (!task) {
    setSimpleRunState("error", "Write the job first", "Describe the result you want, then press Run locally.", {
      packetId: null,
      result: "",
    });
    taskInput?.focus();
    return;
  }

  clearSimplePoll();
  state.simplePollSeq += 1;
  state.goalDraft = null;
  setHomeCockpitMode("orchestrate");
  const repo = $("#repo-input").value || state.repo;
  const attachEvidence = Boolean($("#simple-evidence-toggle")?.checked);
  const timeoutSeconds = Number.parseInt($("#simple-timeout-input")?.value || "900", 10);
  setSimpleRunState("saving", "Checking the job", "Saving it locally and running the safety checks...", {
    packetId: null,
    result: "",
  });

  const response = await fetch("/api/packets", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      repo,
      task,
      agent_id: "codex",
      stage: "execute",
      attach_evidence: attachEvidence,
      mode: "orchestrate",
    }),
  });
  const payload = await response.json();
  if (!response.ok || payload.error) throw new Error(payload.error || "Could not save the local job.");
  const packet = payload.packet;
  state.lastPacket = packet;
  state.selectedPacket = packet;
  setSimpleRunState("checking", "Checks complete", packet.gate_run?.next_action || "The job passed its local checks.", {
    packetId: packet.packet_id,
  });

  if (packet.gate_run?.blocked || packet.status === "blocked") {
    state.activeReviewGoalId = null;
    setSimpleRunState("blocked", "Hamiltonian stopped this job", packet.gate_run?.next_action || "A safety check blocked it.", {
      packetId: packet.packet_id,
    });
    await load(repo);
    return;
  }

  if (!packet.runner_plan?.launch_supported) {
    state.activeReviewGoalId = null;
    setSimpleRunState(
      "unavailable",
      "Job saved, but Codex could not start",
      packet.runner_plan?.adapter_detail || "The Codex command is not available on this computer.",
      { packetId: packet.packet_id },
    );
    await load(repo);
    return;
  }

  setSimpleRunState("starting", "Starting the job", "Opening Codex inside the local workspace...", {
    packetId: packet.packet_id,
  });
  const params = _queryRepoParams();
  const launchResponse = await fetch(`/api/packets/${encodeURIComponent(packet.packet_id)}/run?${params.toString()}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ timeout_seconds: timeoutSeconds }),
  });
  const launchPayload = await launchResponse.json();
  if (!launchResponse.ok || launchPayload.error) throw new Error(launchPayload.error || "Codex could not start the local job.");
  const keepPolling = await applySimpleRunnerState(packet.packet_id, launchPayload.run);
  if (keepPolling) await pollSimpleRunner(packet.packet_id);
}

function renderMissionHome(data) {
  if (!data) return;
  const home = $("#mission-home");
  if (!home) return;
  home.dataset.packetId = state.simpleRun.packetId || "";
  setText("#simple-task-count", `${$("#simple-task-input")?.value.length || 0}/600`);
  renderSimpleRunExperience();
  renderHomeRecentPackets(data);
  renderGoalHistory();
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

function packetGate(packet, gateId) {
  return (packet?.gates || []).find((gate) => gate && gate.id === gateId) || {};
}

function readinessItemsForPacket(packet) {
  if (!packet) {
    return [
      {
        id: "packet",
        label: "Packet",
        status: "empty",
        detail: "Create or open a task packet.",
        explainerTitle: "No active packet",
        explainer:
          "Hamiltonian needs a packet before it can route work, run gates, or prepare any operator handoff.",
        next: "Write one bounded task or open a recent packet.",
      },
      {
        id: "route",
        label: "Route",
        status: "pending",
        detail: "Choose the lane after the packet exists.",
        explainerTitle: "Lane choice waits for the packet",
        explainer:
          "Routing is local advice. It decides which adapter lane should own the packet, not whether anything runs.",
        next: "Create the packet, then review the recommended lane.",
      },
      {
        id: "evidence",
        label: "Evidence",
        status: "optional",
        detail: "Recorder evidence stays off until selected.",
        explainerTitle: "Evidence remains separate",
        explainer:
          "AgentLedger evidence is not represented until the operator asks for a recorder packet or attaches evidence.",
        next: "Leave this optional unless the run needs proof.",
      },
    ];
  }

  const lane = packet.lane || {};
  const route = packet.route || {};
  const gateRun = packet.gate_run || {};
  const memoryGate = packetGate(packet, "memory");
  const evidenceGate = packetGate(packet, "evidence");
  const executionBoundary = packet.execution_boundary || {};
  const runnerPlan = packet.runner_plan || {};
  const runnerRun = runnerRunState(packet);
  const gateTotal = Number(gateRun.total || packet.gates?.length || 0);
  const gateCompleted = Number(gateRun.completed || 0);
  const gateBlocked = Number(gateRun.blocked || 0) > 0;
  const needsLane = packetRequiresLaneDecision(packet);

  const gateStatus = gateBlocked
    ? "blocked"
    : gateCompleted > 0 && gateTotal > 0
      ? `${gateCompleted}/${gateTotal} checked`
      : gateRun.status || "pending";
  const gateDetail = gateBlocked
    ? `Blocked by ${(gateRun.blocked_gate_ids || ["policy gate"]).join(", ")}.`
    : gateCompleted > 0
      ? "Local checks have written their packet state."
      : "Memory, safety, and cost checks are waiting.";
  const evidenceStatus = packet.attach_evidence ? evidenceGate.status || "requested" : "optional";
  const evidenceDetail = packet.attach_evidence
    ? "AgentLedger is represented as a local placeholder."
    : "AgentLedger stays out unless evidence is selected.";
  const laneName = lane.name || packet.agent_name || "Lane";

  return [
    {
      id: "route",
      label: "Route",
      status: needsLane ? "choose lane" : route.status || lane.status || "selected",
      detail: needsLane
        ? "Pick or keep a lane before gates."
        : `${laneName} is the selected adapter lane.`,
      explainerTitle: needsLane ? "Choose the adapter lane" : `${laneName} owns this packet`,
      explainer: needsLane
        ? "The packet is drafted, but Hamiltonian still wants an explicit lane choice before gates run."
        : "The route is advice recorded in the packet. The selected lane is bounded by local adapter rules and remote execution remains off.",
      next: needsLane ? "Choose or keep a lane, then run gates." : "Run the local gates against this lane.",
    },
    {
      id: "gates",
      label: "Gates",
      status: gateStatus,
      detail: gateDetail,
      explainerTitle: gateBlocked ? "A gate is blocking the packet" : "Gates decide whether the packet can move",
      explainer: gateBlocked
        ? "Hamiltonian found a policy problem and will not prepare execution or handoff until it is resolved."
        : "Memory, intent, cost, and optional evidence checks write packet state locally before any execution boundary exists.",
      next: gateBlocked
        ? "Rewrite the task or inspect the blocked gate."
        : gateCompleted > 0
          ? "Prepare execution or attach evidence if this packet needs proof."
          : "Run gates before preparing execution.",
    },
    {
      id: "memory",
      label: "Memory",
      status: memoryGate.status || packet.memory_status || "pending",
      detail: memoryGate.mode ? `RepoMori boundary: ${memoryGate.mode}.` : "RepoMori boundary has not checked yet.",
      explainerTitle: "Repo memory stays inside the adapter boundary",
      explainer: memoryGate.mode
        ? "Hamiltonian checked memory through the RepoMori boundary or a sanitized fallback. It records metadata, not private repo contents."
        : "The memory gate has not run for this packet yet, so no RepoMori boundary result exists.",
      next: memoryGate.status === "checked" ? "Keep moving through the packet gates." : "Run gates to check memory.",
    },
    {
      id: "execution",
      label: "Execution",
      status: executionBoundary.remote_execution ? "external" : runnerPlan.status || "manual only",
      detail: ACTIVE_RUN_STATES.has(runnerRun.status)
        ? runnerRun.summary
        : runnerRun.status === "succeeded"
          ? `The bounded local ${packetRunnerLabel(packet)} run completed successfully.`
          : runnerPlan.status === "prepared"
            ? `${runnerPlan.adapter_id || "Local runner"} prepared; launch ${runnerPlan.launch_supported ? "available" : "disabled"}.`
            : executionBoundary.status || "No local or remote execution has been prepared.",
      explainerTitle: "Execution is a manual approval boundary",
      explainer: executionBoundary.remote_execution
        ? "This packet is warning that an external execution path is present, so it needs operator review."
        : "Hamiltonian launches only after an explicit operator action, supervises the local process, and keeps remote command execution off.",
      next:
        runnerRun.status === "succeeded"
          ? "Review the result, then prepare handoff."
          : executionBoundary.status === "awaiting-approval"
            ? "Review the timeout and explicitly launch when ready."
          : "Prepare execution after gates are clear.",
    },
    {
      id: "evidence",
      label: "Evidence",
      status: evidenceStatus,
      detail: evidenceDetail,
      explainerTitle: packet.attach_evidence ? "Evidence is represented locally" : "Evidence is optional by design",
      explainer: packet.attach_evidence
        ? "AgentLedger is represented as a local placeholder for this packet, without executing a recorder or sending data away."
        : "Hamiltonian keeps AgentLedger out of the packet unless the operator selects evidence or recorder mode.",
      next: packet.attach_evidence ? "Use the represented proof in the handoff." : "Attach evidence only when proof matters.",
    },
  ];
}

function readinessSelectedItem(items) {
  if (!items.length) return null;
  const selected = items.find((item) => item.id === state.readinessFocus);
  if (selected) return selected;
  const preferred = items.find((item) => item.id === "gates") || items[0];
  state.readinessFocus = preferred.id;
  return preferred;
}

function renderReadinessDetail(item) {
  const detail = $("#readiness-detail");
  if (!detail) return;
  clear(detail);
  if (!item) {
    detail.hidden = true;
    return;
  }
  detail.hidden = false;
  detail.dataset.readiness = item.id;

  const heading = document.createElement("div");
  heading.className = "readiness-detail-heading";
  const eyebrow = document.createElement("span");
  eyebrow.textContent = `${item.label} check`;
  const title = document.createElement("strong");
  title.textContent = item.explainerTitle || item.label;
  heading.append(eyebrow, title);

  const body = document.createElement("p");
  body.textContent = item.explainer || item.detail;

  const next = document.createElement("p");
  next.className = "readiness-next";
  const nextLabel = document.createElement("strong");
  nextLabel.textContent = "Next: ";
  const nextText = document.createElement("span");
  nextText.textContent = item.next || "Review the packet state.";
  next.append(nextLabel, nextText);

  detail.append(heading, body, next);
}

function renderReadinessStrip(packet) {
  const strip = $("#readiness-strip");
  if (!strip) return;
  clear(strip);
  const items = readinessItemsForPacket(packet);
  const selected = readinessSelectedItem(items);
  items.forEach((item) => {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "readiness-item";
    card.dataset.readiness = item.id;
    card.setAttribute("aria-controls", "readiness-detail");
    card.setAttribute("aria-pressed", String(item.id === selected?.id));
    card.classList.toggle("readiness-item-selected", item.id === selected?.id);
    card.addEventListener("click", () => {
      state.readinessFocus = item.id;
      renderReadinessStrip(packet);
    });

    const label = document.createElement("span");
    label.className = "readiness-label";
    label.textContent = item.label;

    const detail = document.createElement("span");
    detail.className = "readiness-copy";
    detail.textContent = item.detail;

    card.append(label, pill(item.status), detail);
    strip.appendChild(card);
  });
  renderReadinessDetail(selected);
}

function packetDetailCode(packet) {
  if (!packet?.packet_id) return "M-00";
  const match = String(packet.packet_id).match(/([a-f0-9]{4,8})$/i);
  return match ? `M-${match[1].slice(0, 4).toUpperCase()}` : homePacketCode(packet);
}

function packetStatusRows(packet) {
  if (!packet) {
    return [
      { label: "Packet", status: "empty", detail: "Open or create a mission packet." },
      { label: "Route", status: "pending", detail: "Lane advice appears after the packet exists." },
      { label: "Evidence", status: "optional", detail: "AgentLedger stays out until selected." },
    ];
  }

  const lane = packet.lane || {};
  const route = packet.route || {};
  const gateRun = packet.gate_run || {};
  const executionBoundary = packet.execution_boundary || {};
  const runnerPlan = packet.runner_plan || {};
  const runnerRun = runnerRunState(packet);
  const handoff = packet.handoff || {};
  const memoryGate = packetGate(packet, "memory");
  const evidenceGate = packetGate(packet, "evidence");
  const gateStatus =
    Number(gateRun.blocked || 0) > 0
      ? "blocked"
      : gateRun.completed && gateRun.total
        ? `${gateRun.completed}/${gateRun.total} checked`
        : gateRun.status || "pending";

  return [
    {
      label: "Stage",
      status: packet.stage || "draft",
      detail: packet.status || "Packet state is local.",
    },
    {
      label: "Route",
      status: packetRequiresLaneDecision(packet) ? "choose lane" : route.status || lane.status || "selected",
      detail: route.recommended_lane_name || lane.name || packet.agent_name || "No lane selected.",
    },
    {
      label: "Memory",
      status: memoryGate.status || packet.memory_status || "pending",
      detail: memoryGate.mode || packet.memory_mode || "RepoMori boundary waiting.",
    },
    {
      label: "Gates",
      status: gateStatus,
      detail: gateRun.next_action || "Run local readiness gates before execution.",
    },
    {
      label: "Execution",
      status: executionBoundary.remote_execution ? "external" : executionBoundary.status || "manual only",
      detail: executionBoundary.mode || "No remote agent execution.",
    },
    {
      label: "Runner plan",
      status: runnerPlan.status || "unknown",
      detail: runnerPlan.status === "prepared"
        ? `${runnerPlan.adapter_id || "Local adapter"}; launch ${runnerPlan.launch_supported ? "available" : "disabled"}.`
        : runnerPlan.next_action || "Prepare execution after gates are clear.",
    },
    {
      label: "Runner run",
      status: runnerRun.status || "not-started",
      detail: runnerRun.summary || "No bounded local run recorded.",
    },
    {
      label: "Evidence",
      status: packet.attach_evidence ? evidenceGate.status || "represented" : "optional",
      detail: packet.attach_evidence
        ? "AgentLedger placeholder represented locally."
        : "AgentLedger stays out unless selected.",
    },
    {
      label: "Handoff",
      status: handoff.ready ? "ready" : handoff.status || "not ready",
      detail: handoff.next_action || "Prepare handoff after execution boundary.",
    },
  ];
}

function renderPacketMissionControl(packet) {
  const statusList = $("#packet-status-list");
  if (statusList) {
    clear(statusList);
    packetStatusRows(packet).forEach((item) => {
      const row = document.createElement("article");
      row.className = "packet-status-row";
      row.dataset.testid = `packet-status-${String(item.label || "status").toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
      const body = document.createElement("div");
      const label = document.createElement("span");
      label.textContent = item.label;
      const detail = document.createElement("p");
      detail.textContent = item.detail;
      body.append(label, detail);
      row.append(body, pill(item.status));
      statusList.appendChild(row);
    });
  }

  setText("#detail-packet-title", homeTaskTitle(packet));
  setText("#detail-packet-stage", packet ? STAGE_LABELS[normalizeStage(packet.stage)]?.title || packet.stage : "Waiting");
  setText("#detail-packet-objective", packet?.task || "Open a packet to inspect mission state.");
  setText("#detail-packet-lane", packet?.lane?.name || packet?.agent_name || "No lane selected");
  setText("#detail-packet-updated", formatHomeTime(packet?.updated_at || packet?.created_at));
  setText("#detail-packet-code", packetDetailCode(packet));
  setText("#detail-packet-id", packet?.packet_id ? `Packet ID ${packet.packet_id}` : "Packet ID not selected");
  setText("#detail-evidence-stamp", packet?.attach_evidence ? "Evidence attached" : "Evidence optional");
}

function detailPanel(id, title) {
  const section = document.createElement("section");
  section.className = `detail-panel-section detail-panel-${id}`;
  section.dataset.packetPanel = id;
  section.setAttribute("role", "tabpanel");
  const heading = document.createElement("div");
  heading.className = "detail-panel-heading";
  const eyebrow = document.createElement("span");
  eyebrow.textContent = "Packet tab";
  const strong = document.createElement("strong");
  strong.textContent = title;
  heading.append(eyebrow, strong);
  section.appendChild(heading);
  return section;
}

function applyPacketDetailTab() {
  const activeTab = state.packetDetailTab || "overview";
  document.querySelectorAll("[data-packet-tab]").forEach((button) => {
    const active = button.dataset.packetTab === activeTab;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  document.querySelectorAll("[data-packet-panel]").forEach((panel) => {
    panel.hidden = panel.dataset.packetPanel !== activeTab;
  });
}

function initPacketDetailControls() {
  const backButton = $("#packet-control-back");
  if (backButton) {
    backButton.addEventListener("click", () => revealSection("runs"));
  }

  document.querySelectorAll("[data-packet-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      state.packetDetailTab = button.dataset.packetTab || "overview";
      applyPacketDetailTab();
    });
  });
}

function initGateViewControls() {
  const backButton = $("#gate-back-packet");
  if (backButton) {
    backButton.addEventListener("click", () => {
      revealSection(state.selectedPacket?.packet_id ? "packet-detail-panel" : "runs");
    });
  }
}

function renderPacketDetail(packet) {
  const title = $("#packet-detail-title");
  const status = $("#packet-detail-status");
  const detail = $("#packet-detail");
  const exportButton = $("#packet-export-button");
  const packetGateButton = $("#packet-gate-button");
  const packetExecuteButton = $("#packet-execute-button");
  const packetHandoffButton = $("#packet-handoff-button");
  const packetRecordButton = $("#packet-record-button");
  const panel = $("#packet-detail-panel");
  if (panel) panel.dataset.packetId = packet?.packet_id || "";
  clear(detail);
  renderReadinessStrip(packet);
  renderPacketMissionControl(packet);
  renderRunnerControl(packet);

  if (!packet) {
    title.textContent = "No packet selected";
    status.textContent = "Waiting";
    exportButton.disabled = true;
    if (packetGateButton) packetGateButton.disabled = true;
    if (packetExecuteButton) packetExecuteButton.disabled = true;
    if (packetHandoffButton) packetHandoffButton.disabled = true;
    if (packetRecordButton) packetRecordButton.disabled = true;
    updatePacketAdvanceButtons(null);
    state.packetDetailTab = "overview";
    const empty = detailPanel("overview", "No packet selected");
    const emptyLine = document.createElement("p");
    emptyLine.className = "muted-line";
    emptyLine.textContent = "Open a recent packet or create a new one to inspect mission control.";
    empty.appendChild(emptyLine);
    ["context", "gates", "evidence", "handoff"].forEach((tab) => {
      const panel = detailPanel(tab, "Waiting for packet");
      const line = document.createElement("p");
      line.className = "muted-line";
      line.textContent = "This section becomes available after a packet is selected.";
      panel.appendChild(line);
      detail.appendChild(panel);
    });
    detail.prepend(empty);
    applyPacketDetailTab();
    renderMissionMap(null);
    renderTutorial(null);
    renderMissionHome(state.data);
    if (state.data) renderGates(state.data);
    return;
  }

  const lane = packet.lane || {};
  const executionBoundary = packet.execution_boundary || {};
  const handoff = packet.handoff || {};
  const handoffExport = packet.exports?.handoff_markdown || null;
  const gates = packet.gates || [];
  const gateRun = packet.gate_run || {};
  const route = packet.route || {};
  const runnerPlan = packet.runner_plan || {};
  const runnerRun = runnerRunState(packet);
  const evidenceGate = gates.find((gate) => gate.id === "evidence") || {};

  title.textContent = packet.packet_id || "Packet detail";
  status.textContent = packet.status || "unknown";
  exportButton.disabled = false;

  if (!["overview", "context", "gates", "evidence", "handoff"].includes(state.packetDetailTab)) {
    state.packetDetailTab = "overview";
  }

  const overview = detailPanel("overview", "Packet overview");
  const summary = document.createElement("div");
  summary.className = "detail-grid";
  summary.append(
    detailRow("Stage", packet.stage),
    detailRow("Agent", packet.agent_name),
    detailRow("Lane", `${lane.status || "unknown"} / ${lane.execution || "unknown"}`),
    detailRow("Route", `${route.status || "unknown"} / ${route.recommended_lane_name || packet.agent_name}`),
    detailRow("Gate run", `${gateRun.status || "unknown"} (${gateRun.completed || 0}/${gateRun.total || 0})`),
    detailRow("Execution", `${executionBoundary.status || "unknown"} / ${executionBoundary.mode || "unknown"}`),
    detailRow("Runner adapter", `${runnerPlan.adapter_id || "unknown"} / ${runnerPlan.launch_supported ? "launch ready" : "launch unavailable"}`),
    detailRow("Runner result", `${runnerRun.status || "not-started"} / local ${Boolean(runnerRun.local_execution)}`),
    detailRow("Handoff", `${handoff.status || "unknown"} / ${handoff.ready ? "ready" : "not ready"}`),
    detailRow("Evidence", evidenceGate.status || "unknown"),
    detailRow("Export", handoffExport ? `${handoffExport.filename} / sanitized` : "none"),
    detailRow("Remote execution", String(Boolean(executionBoundary.remote_execution || lane.remote_execution)))
  );
  overview.appendChild(summary);

  const context = detailPanel("context", "Context and route");
  const routeBlock = document.createElement("section");
  routeBlock.className = "detail-block";
  const routeTitle = document.createElement("strong");
  routeTitle.textContent = "Route";
  const routeBody = document.createElement("p");
  const routeWarnings = route.warnings && route.warnings.length ? ` Checks: ${route.warnings.join(" ")}` : "";
  routeBody.textContent = `${route.summary || "No route decision recorded."} ${route.policy || ""}${routeWarnings}`;
  routeBlock.append(routeTitle, routeBody);

  const task = document.createElement("section");
  task.className = "detail-block";
  const taskTitle = document.createElement("strong");
  taskTitle.textContent = "Task";
  const taskBody = document.createElement("p");
  taskBody.textContent = packet.task || "";
  task.append(taskTitle, taskBody);

  context.append(routeBlock, task);

  const handoffPanel = detailPanel("handoff", "Handoff and export");
  const next = document.createElement("section");
  next.className = "detail-block";
  const nextTitle = document.createElement("strong");
  nextTitle.textContent = "Next";
  const nextBody = document.createElement("p");
  nextBody.textContent = handoff.next_action || executionBoundary.next_action || gateRun.next_action || "";
  next.append(nextTitle, nextBody);
  const handoffBlock = document.createElement("section");
  handoffBlock.className = "detail-block";
  const handoffTitle = document.createElement("strong");
  handoffTitle.textContent = "Handoff";
  const handoffBody = document.createElement("p");
  handoffBody.textContent = handoffExport
    ? `${handoffExport.filename} is ready as a sanitized local export.`
    : handoff.ready
      ? "Packet is ready for handoff. Export when the operator wants a sanitized note."
      : handoff.status || "Handoff is waiting for the execution boundary.";
  handoffBlock.append(handoffTitle, handoffBody);
  handoffPanel.append(next, handoffBlock);

  const gatesPanel = detailPanel("gates", "Readiness gates");
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
  gatesPanel.appendChild(gateList);

  const evidencePanel = detailPanel("evidence", "Evidence posture");
  const evidenceBlock = document.createElement("section");
  evidenceBlock.className = "detail-block";
  const evidenceTitle = document.createElement("strong");
  evidenceTitle.textContent = packet.attach_evidence ? "Evidence represented" : "Evidence optional";
  const evidenceBody = document.createElement("p");
  evidenceBody.textContent = packet.attach_evidence
    ? "AgentLedger is represented as a local placeholder for this packet. No recorder or remote agent has been executed."
    : "AgentLedger stays out of this packet unless the operator attaches evidence or uses flight recorder mode.";
  evidenceBlock.append(evidenceTitle, evidenceBody);
  evidencePanel.appendChild(evidenceBlock);

  detail.append(overview, context, gatesPanel, evidencePanel, handoffPanel);
  applyPacketDetailTab();
  updatePacketAdvanceButtons(packet);
  renderMissionMap(packet);
  renderMissionPath(packet);
  renderTutorial(packet);
  renderMissionHome(state.data);
  if (state.data) renderGates(state.data);
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

function updateLocalTime() {
  const localTime = $("#local-time");
  if (!localTime) return;
  localTime.textContent = `${new Date().toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  })} local time`;
}

function renderHeader(data) {
  $("#repo-input").value = data.repo;
  $("#repo-name").textContent = data.repo_name;
  document.title = `Hamiltonian | ${data.repo_name}`;
  setText("#simple-workspace-name", data.repo_name);
  const simpleWorkspace = $("#simple-workspace-name");
  if (simpleWorkspace) simpleWorkspace.title = data.repo;
  $("#git-state").textContent = data.git_available ? "available" : "not a git repo";
  $("#agent-count").textContent = `${data.agents.length} lanes`;
  $("#gate-count").textContent = `${data.gates.length} gates`;
  $("#generated-at").textContent = new Date(data.generated_at).toLocaleString();
  updateLocalTime();
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
  renderCreatePacketScreen(state.data);
}

function renderCreatePacketScreen(data) {
  const screen = $("#cockpit");
  if (!screen) return;
  const taskInput = $("#task-input");
  const agentSelect = $("#agent-select");
  const task = taskInput?.value.trim() || "";
  const routes = data?.route_recommendations || [];
  const selectedRoute = routes.find((route) => route.lane_id === agentSelect?.value) || routes[0] || null;
  const selectedLane = agentSelect?.selectedOptions?.[0]?.textContent || selectedRoute?.lane_name || "Waiting for task";
  const recorder = state.cockpitMode === "recorder";
  const evidenceRequested = recorder || state.packetMode === "record";

  screen.dataset.cockpitMode = state.cockpitMode;
  screen.dataset.evidence = evidenceRequested ? "requested" : "optional";
  setText("#create-task-count", `${task.length}/600`);
  setText("#create-route-title", selectedRoute?.lane_name || selectedLane);
  setText("#create-route-fit", selectedRoute?.status || "Local advice");
  setText(
    "#create-route-body",
    selectedRoute?.summary ||
      (task
        ? "Route advice is waiting for the next local refresh."
        : "Write a task and Hamiltonian will refresh local route recommendations."),
  );
  setText("#create-evidence-title", evidenceRequested ? "Evidence attached on creation" : "Evidence optional");
  setText(
    "#create-evidence-body",
    evidenceRequested
      ? "AgentLedger is represented locally as a placeholder for this packet only."
      : "AgentLedger stays out unless you attach evidence or use recorder mode.",
  );
  setText("#create-boundary-mode", recorder ? "Recorder packet" : "Normal orchestration");
  setText(
    "#create-boundary-body",
    recorder
      ? "Recorder mode captures maximum local evidence. Remote execution remains off."
      : "Remote execution is off. Packet creation writes local state only.",
  );
}

function compactText(value, maxLength = 120) {
  const text = String(value || "").trim();
  if (!text) return "";
  return text.length > maxLength ? `${text.slice(0, maxLength - 3)}...` : text;
}

function isRecorderPacket(packet) {
  if (!packet?.packet_id) return false;
  const evidenceStatus = String(packet.evidence_status || "").toLowerCase();
  return Boolean(
    normalizeStage(packet.stage) === "record" ||
      packet.mode === "recorder" ||
      packet.attach_evidence ||
      evidenceStatus.includes("represented") ||
      evidenceStatus.includes("simulated"),
  );
}

function recorderPacketForDisplay(data) {
  const candidates = [state.selectedPacket, state.lastPacket, ...(data?.recent_packets || [])];
  return candidates.find(isRecorderPacket) || null;
}

function syncRecorderTaskCount() {
  const input = $("#recorder-task-input");
  const count = $("#recorder-task-count");
  if (count) count.textContent = `${input?.value.length || 0}/600`;
}

function recorderCaptureRows(packet, task) {
  const hasTask = Boolean(task);
  return [
    {
      label: "Inputs",
      status: packet ? "recorded" : hasTask ? "ready" : "waiting",
      detail: packet
        ? "Task prompt and operator note were saved locally."
        : hasTask
          ? "Ready to write into a local recorder packet."
          : "Write a recorder note before creating the packet.",
    },
    {
      label: "Context",
      status: packet ? "recorded" : "local",
      detail: packet
        ? "Packet context is available on this machine."
        : "Context will stay inside the local packet store.",
    },
    {
      label: "Tool calls",
      status: packet ? "represented" : "waiting",
      detail: packet
        ? "Tool activity is represented as sanitized local packet evidence."
        : "No tool activity is represented until the packet is recorded.",
    },
    {
      label: "Evidence ledger",
      status: packet?.attach_evidence ? "represented" : "off",
      detail: packet?.attach_evidence
        ? "AgentLedger is represented locally only for this packet."
        : "No AgentLedger representation exists until evidence is selected.",
    },
  ];
}

function renderRecorderEvidenceList(packet, task) {
  const list = $("#recorder-evidence-list");
  if (!list) return;
  clear(list);
  recorderCaptureRows(packet, task).forEach((item) => {
    const row = document.createElement("article");
    row.className = `recorder-evidence-row recorder-evidence-${statusClass(item.status)}`;
    const body = document.createElement("div");
    const label = document.createElement("strong");
    label.textContent = item.label;
    const detail = document.createElement("p");
    detail.textContent = item.detail;
    body.append(label, detail);
    row.append(body, pill(item.status));
    list.appendChild(row);
  });
}

function renderRecorderProofBundle(packet) {
  const bundle = $("#recorder-proof-bundle");
  if (!bundle) return;
  clear(bundle);
  if (!packet) {
    const empty = document.createElement("div");
    empty.className = "recorder-proof-empty";
    const title = document.createElement("strong");
    title.textContent = "No live bundle yet";
    const body = document.createElement("p");
    body.textContent = "Create a recorder packet to produce a local proof bundle placeholder.";
    empty.append(title, body);
    bundle.appendChild(empty);
    return;
  }

  [
    ["Packet ID", packet.packet_id],
    ["Evidence", packet.attach_evidence ? "AgentLedger represented locally" : "Evidence not attached"],
    ["Boundary", "Local-only. Remote execution off."],
    ["Export", packet.export?.filename || "Not exported yet"],
  ].forEach(([label, value]) => {
    const row = document.createElement("div");
    row.className = "recorder-proof-row";
    const key = document.createElement("span");
    key.textContent = label;
    const val = document.createElement("strong");
    val.textContent = value;
    row.append(key, val);
    bundle.appendChild(row);
  });
}

function renderFlightRecorder(data) {
  const screen = $("#recorder-panel");
  if (!screen) return;
  const packet = recorderPacketForDisplay(data);
  const recorderInput = $("#recorder-task-input");
  const taskInput = $("#task-input");

  if (recorderInput && document.activeElement !== recorderInput && !recorderInput.value) {
    const sourceTask = taskInput?.value.trim() || packet?.task || packet?.task_excerpt || "";
    if (sourceTask) recorderInput.value = compactText(sourceTask, 600);
  }

  const task = recorderInput?.value.trim() || taskInput?.value.trim() || "";
  const armed = state.cockpitMode === "recorder";
  const captured = Boolean(packet?.packet_id);
  const taskObjective = compactText(packet?.task || packet?.task_excerpt || task, 118);
  const stageLabel = packet ? STAGE_LABELS[normalizeStage(packet.stage)]?.title || packet.stage || "Record" : "Record";

  screen.dataset.recorderMode = armed ? "active" : "inactive";
  screen.dataset.recorderPacket = captured ? "captured" : "empty";
  screen.dataset.packetId = packet?.packet_id || "";
  syncRecorderTaskCount();

  setText("#recorder-screen-title", captured ? "Recorder packet captured" : "Maximum evidence capture");
  setText("#recorder-status-badge", captured ? "Captured" : armed ? "Armed" : "Inactive");
  setText(
    "#recorder-status-title",
    captured ? "Flight recorder packet is saved" : armed ? "Recorder mode armed" : "Recorder mode inactive",
  );
  setText(
    "#recorder-status-body",
    captured
      ? "The packet contains local evidence placeholders only. Nothing has executed remotely."
      : armed
        ? "Create the packet when the mission needs a full local trace."
        : "Switch to recorder mode when the packet needs a fuller local trace.",
  );

  const wave = $(".recorder-waveform");
  if (wave) wave.classList.toggle("recorder-waveform-active", armed || captured);

  const armButton = $("#recorder-arm-button");
  if (armButton) armButton.textContent = armed ? "Recorder mode active" : "Switch to recorder mode";

  setText("#recorder-packet-stage", captured ? stageLabel : armed ? "Ready" : "Waiting");
  setText("#recorder-packet-title", captured ? homeTaskTitle(packet) : task ? "Ready to record" : "No recorder packet yet");
  setText("#recorder-packet-stage-copy", stageLabel);
  setText(
    "#recorder-packet-objective",
    taskObjective || "Create a local evidence packet when the work requires it.",
  );
  setText(
    "#recorder-packet-evidence",
    packet?.attach_evidence ? "AgentLedger represented locally only." : "Evidence attaches when recorder mode creates the packet.",
  );
  setText("#recorder-packet-updated", formatHomeTime(packet?.updated_at || packet?.created_at));
  setText("#recorder-packet-code", captured ? homePacketCode(packet) : "M-FR");
  setText("#recorder-evidence-stamp", packet?.attach_evidence ? "Evidence attached" : "Evidence matters");
  setText("#recorder-packet-id", captured ? `Packet ID ${packet.packet_id}` : "Recorder packet not created");

  const createButton = $("#recorder-create-button");
  if (createButton) createButton.textContent = captured ? "Record another packet" : "Record flight packet";

  const openButton = $("#recorder-open-packet-button");
  if (openButton) {
    openButton.disabled = !captured;
    openButton.textContent = captured ? "Open recorder packet" : "Open recorder packet";
  }

  setText(
    "#recorder-footer-note",
    captured
      ? `Saved locally as ${packet.packet_id}. Remote execution remains off.`
      : "Recorder mode is slower and stores more local packet metadata.",
  );

  renderRecorderEvidenceList(packet, task);
  renderRecorderProofBundle(packet);
}

function handoffPacketForDisplay(data) {
  if (state.selectedPacket?.packet_id) return state.selectedPacket;
  if (state.lastPacket?.packet_id) return state.lastPacket;
  return (data?.recent_packets || [])[0] || null;
}

function handoffExportForPacket(packet) {
  if (!packet?.packet_id) return null;
  if (state.lastExport && state.selectedPacket?.packet_id === packet.packet_id) return state.lastExport;
  if (packet.has_handoff_export || packet.handoff_export_filename) {
    return {
      filename: packet.handoff_export_filename || "handoff-export.md",
      sanitized: true,
    };
  }
  return packet.exports?.handoff_markdown || packet.export || null;
}

function handoffIsReady(packet) {
  if (!packet?.packet_id) return false;
  const handoff = packet.handoff || {};
  return Boolean(handoff.ready || handoffExportForPacket(packet));
}

function handoffGateStatus(packet) {
  const gateRun = packet?.gate_run || {};
  if (Number(gateRun.blocked || 0) > 0) return "blocked";
  if (Number(gateRun.completed || 0) > 0 && Number(gateRun.total || 0) > 0) {
    return `${gateRun.completed}/${gateRun.total} checked`;
  }
  return gateRun.status || "waiting";
}

function handoffReadinessRows(packet) {
  if (!packet) {
    return [
      { label: "Readiness gates", status: "waiting", detail: "Open or create a packet first." },
      { label: "Execution boundary", status: "off", detail: "No local or remote execution is prepared." },
      { label: "Handoff package", status: "not ready", detail: "A packet must reach handoff before export." },
      { label: "Sanitized export", status: "waiting", detail: "No markdown export has been written." },
    ];
  }

  const handoff = packet.handoff || {};
  const executionBoundary = packet.execution_boundary || {};
  const exportInfo = handoffExportForPacket(packet);
  return [
    {
      label: "Readiness gates",
      status: handoffGateStatus(packet),
      detail: packet.gate_run?.next_action || "Local memory, intent, and cost checks are recorded in the packet.",
    },
    {
      label: "Execution boundary",
      status: executionBoundary.remote_execution ? "blocked" : executionBoundary.status || "manual only",
      detail: executionBoundary.remote_execution
        ? "External execution is blocked for this local prototype."
        : "Remote execution is off; this is an operator approval boundary.",
    },
    {
      label: "Handoff package",
      status: handoff.ready ? "ready" : handoff.status || "not ready",
      detail: handoff.summary || handoff.next_action || "Prepare handoff after the execution boundary.",
    },
    {
      label: "Sanitized export",
      status: exportInfo ? "complete" : handoff.ready ? "ready" : "waiting",
      detail: exportInfo?.filename
        ? `${exportInfo.filename} is written locally and sanitized.`
        : handoff.ready
          ? "Ready to write a sanitized local markdown handoff."
          : "Export remains locked until the handoff package is ready.",
    },
  ];
}

function handoffSummaryRows(packet, exportInfo) {
  if (!packet) {
    return [
      ["Evidence items", "Waiting", "Evidence is only represented after a packet exists."],
      ["Sources", "Local packet store", "No source bundle has been selected."],
      ["Packet size", "Pending", "Size appears after export."],
      ["Integrity check", "Waiting", "Sanitization runs during local export."],
    ];
  }

  const evidence = packet.attach_evidence
    ? "AgentLedger represented locally"
    : "Not attached";
  const exportBytes = Number(exportInfo?.size_bytes || exportInfo?.bytes || 0);
  const estimatedBytes = JSON.stringify({
    packet_id: packet.packet_id,
    task: packet.task || packet.task_excerpt || "",
    gates: packet.gates || [],
    handoff: packet.handoff || {},
  }).length;
  return [
    [
      "Evidence items",
      evidence,
      packet.attach_evidence
        ? "The packet carries a local placeholder only."
        : "AgentLedger is not represented for this packet.",
    ],
    [
      "Sources",
      `${(packet.gates || []).length || 0} gate records`,
      "Summary is assembled from local packet state, gate records, route, and handoff metadata.",
    ],
    [
      "Packet size",
      formatPacketSize(exportBytes || estimatedBytes),
      exportInfo ? "Export size is from the sanitized local file." : "Estimated from local packet data before export.",
    ],
    [
      "Integrity check",
      exportInfo?.sanitized ? "Passed" : handoffIsReady(packet) ? "Ready" : "Waiting",
      exportInfo?.sanitized
        ? "Private paths and sensitive-looking values are removed before handoff."
        : "The sanitizer runs only when the operator exports.",
    ],
  ];
}

function formatPacketSize(bytes) {
  if (!bytes || Number.isNaN(bytes)) return "Pending";
  if (bytes < 1024) return `${bytes} B`;
  return `${(bytes / 1024).toFixed(1)} KB`;
}

function renderHandoffReadinessList(packet) {
  const list = $("#handoff-readiness-list");
  if (!list) return;
  clear(list);
  handoffReadinessRows(packet).forEach((item) => {
    const row = document.createElement("article");
    row.className = `handoff-readiness-row gate-tone-${gateToneName(item.status)}`;
    const body = document.createElement("div");
    const label = document.createElement("strong");
    label.textContent = item.label;
    const detail = document.createElement("p");
    detail.textContent = item.detail;
    body.append(label, detail);
    row.append(body, pill(item.status));
    list.appendChild(row);
  });
}

function renderHandoffSummary(packet, exportInfo) {
  const summary = $("#handoff-export-summary");
  if (!summary) return;
  clear(summary);
  handoffSummaryRows(packet, exportInfo).forEach(([label, value, detail]) => {
    const row = document.createElement("article");
    row.className = "handoff-summary-row";
    const body = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = label;
    const copy = document.createElement("p");
    copy.textContent = detail;
    body.append(title, copy);
    const val = document.createElement("span");
    val.textContent = value;
    row.append(body, val);
    summary.appendChild(row);
  });
}

function handoffPrimaryState(packet) {
  if (!packet?.packet_id) {
    return {
      label: "Create packet",
      title: "Open or create a packet",
      body: "Select an existing local packet or create a new one before export.",
      disabled: false,
      run: () => revealSection("cockpit"),
    };
  }

  const exportInfo = handoffExportForPacket(packet);
  if (exportInfo) {
    return {
      label: "Export again",
      title: "Export complete",
      body: `${exportInfo.filename || "handoff-export.md"} is available as a sanitized local file.`,
      disabled: false,
      run: exportHandoffPacket,
    };
  }
  if (handoffIsReady(packet)) {
    return {
      label: "Export packet",
      title: "Ready to export",
      body: "Write the sanitized handoff markdown locally. No public link or remote runner is created.",
      disabled: false,
      run: exportHandoffPacket,
    };
  }

  const selected = state.selectedPacket?.packet_id === packet.packet_id;
  const canPrepare = selected && !packetActionLockReason(packet, "handoff");
  if (canPrepare) {
    return {
      label: "Prepare handoff",
      title: "Prepare handoff",
      body: "Move this packet to the local operator-handoff state before export.",
      disabled: false,
      run: prepareHandoffPacket,
    };
  }
  if (!selected) {
    return {
      label: "Open packet",
      title: "Open packet first",
      body: "Load the packet into Mission Control before preparing its handoff.",
      disabled: false,
      run: openHandoffPacket,
    };
  }
  const reason = packetActionLockReason(packet, "handoff") || "Handoff is not available from this packet state.";
  return {
    label: "Blocked",
    title: "Handoff blocked",
    body: reason,
    disabled: true,
    run: null,
  };
}

function renderHandoffExport(data) {
  const screen = $("#handoff-panel");
  if (!screen) return;
  const packet = handoffPacketForDisplay(data);
  const exportInfo = handoffExportForPacket(packet);
  const ready = handoffIsReady(packet);
  const primary = handoffPrimaryState(packet);
  const stageLabel = packet ? STAGE_LABELS[normalizeStage(packet.stage)]?.title || packet.stage || "Packet" : "Waiting";

  screen.dataset.handoffState = exportInfo ? "exported" : ready ? "ready" : packet ? "waiting" : "empty";
  screen.dataset.packetId = packet?.packet_id || "";
  setText("#handoff-screen-title", exportInfo ? "Export complete" : ready ? "Packet ready for handoff" : "Handoff ready / Export");
  setText("#handoff-ready-badge", exportInfo ? "Exported" : ready ? "Ready" : packet ? "Waiting" : "Empty");
  setText(
    "#handoff-ready-title",
    exportInfo ? "Sanitized handoff written" : ready ? "Packet ready for handoff" : packet ? "Handoff not ready yet" : "No packet selected",
  );
  setText(
    "#handoff-ready-body",
    exportInfo
      ? `${exportInfo.filename || "handoff-export.md"} is stored with the local packet.`
      : ready
        ? "The packet can be exported as a sanitized local handoff. Remote execution remains off."
        : packet
          ? (packet.handoff?.next_action || "Prepare execution and handoff before exporting.")
          : "Open a packet before exporting a sanitized local handoff.",
  );

  setText("#handoff-packet-stage", stageLabel);
  setText("#handoff-packet-title", homeTaskTitle(packet));
  setText("#handoff-packet-stage-copy", stageLabel);
  setText("#handoff-packet-objective", compactText(packet?.task || packet?.task_excerpt || "Open or prepare a packet for operator review.", 118));
  setText(
    "#handoff-packet-evidence",
    packet?.attach_evidence ? "AgentLedger represented locally only." : "AgentLedger not attached.",
  );
  setText("#handoff-packet-updated", formatHomeTime(packet?.updated_at || packet?.created_at));
  setText("#handoff-packet-code", homePacketCode(packet));
  setText("#handoff-evidence-stamp", packet?.attach_evidence ? "Evidence attached" : "Evidence optional");
  setText("#handoff-packet-id", packet?.packet_id ? `Packet ID ${packet.packet_id}` : "Packet ID not selected");

  setText("#handoff-next-title", primary.title);
  setText("#handoff-next-body", primary.body);
  const primaryButton = $("#handoff-primary-button");
  if (primaryButton) {
    primaryButton.textContent = primary.label;
    primaryButton.disabled = primary.disabled;
    primaryButton.onclick = primary.run;
  }

  const exportButton = $("#handoff-export-button");
  if (exportButton) {
    const canExport = Boolean(packet?.packet_id && ready);
    exportButton.textContent = exportInfo ? "Export again" : canExport ? "Export packet" : primary.label === "Prepare handoff" ? "Prepare handoff" : "Export locked";
    exportButton.disabled = !canExport && primary.label !== "Prepare handoff";
    exportButton.onclick = primary.label === "Prepare handoff" ? prepareHandoffPacket : exportHandoffPacket;
  }

  const openButton = $("#handoff-open-packet-button");
  if (openButton) {
    openButton.disabled = !packet?.packet_id;
    openButton.onclick = openHandoffPacket;
  }

  setText("#handoff-summary-state", exportInfo ? "Exported" : ready ? "Ready" : packet ? "Pending" : "Waiting");
  setText("#handoff-evidence-state", packet?.attach_evidence ? "Represented" : "Optional");
  setText(
    "#handoff-evidence-body",
    packet?.attach_evidence
      ? "AgentLedger is represented as a local placeholder for this packet only. No recorder or remote agent has executed."
      : "AgentLedger stays out unless evidence is selected. This export can remain evidence-light.",
  );
  setText(
    "#handoff-footer-note",
    exportInfo
      ? `Exported locally as ${exportInfo.filename || "handoff-export.md"}.`
      : packet
        ? "Handoff exports are sanitized local files. Share links and vault sync are disabled."
        : "Open a packet to prepare a local handoff export.",
  );

  renderHandoffReadinessList(packet);
  renderHandoffSummary(packet, exportInfo);
}

function openHandoffPacket() {
  const packet = handoffPacketForDisplay(state.data);
  if (!packet?.packet_id) return;
  loadPacketDetail(packet.packet_id).catch((error) => {
    setText("#handoff-footer-note", error.message);
  });
}

async function prepareHandoffPacket() {
  const packet = handoffPacketForDisplay(state.data);
  if (!packet?.packet_id) return;
  if (state.selectedPacket?.packet_id !== packet.packet_id) {
    state.selectedPacket = packet;
    renderPacketDetail(packet);
  }
  setText("#handoff-footer-note", "Preparing local handoff package...");
  await advanceSelectedPacket("handoff");
  revealSection("handoff-panel");
  renderHandoffExport(state.data);
}

async function exportHandoffPacket() {
  const packet = handoffPacketForDisplay(state.data);
  if (!packet?.packet_id) return;
  if (state.selectedPacket?.packet_id !== packet.packet_id) {
    state.selectedPacket = packet;
    renderPacketDetail(packet);
  }
  if (!handoffIsReady(state.selectedPacket)) {
    await prepareHandoffPacket();
  }
  setText("#handoff-footer-note", "Writing sanitized local handoff export...");
  await exportSelectedPacket();
  revealSection("handoff-panel");
  renderHandoffExport(state.data);
}

function handoffBackTarget() {
  return state.selectedPacket?.packet_id ? "packet-detail-panel" : "mission-home";
}

function initHandoffExportControls() {
  const backButton = $("#handoff-back-packet");
  if (backButton) {
    backButton.addEventListener("click", () => revealSection(handoffBackTarget()));
  }

  const shareButton = $("#handoff-share-link-button");
  if (shareButton) {
    shareButton.title = "Public sharing is disabled in the local prototype.";
  }
  const vaultButton = $("#handoff-save-vault-button");
  if (vaultButton) {
    vaultButton.title = "Secure vault sync is represented only in this prototype.";
  }
}

function applyCockpitMode() {
  state.cockpitMode = activeCockpitMode();
  const recorder = state.cockpitMode === "recorder";
  const orchestrateTools = $("#orchestrate-tools");
  const recorderTools = $("#recorder-tools");
  const laneControl = $("#lane-control");
  const recorderIntro = $("#recorder-intro");
  const cockpitTitle = $("#cockpit-title");
  const missionPanel = $("#mission");

  if (orchestrateTools) orchestrateTools.hidden = recorder;
  if (recorderTools) recorderTools.hidden = !recorder;
  if (laneControl) laneControl.hidden = recorder;
  if (recorderIntro) recorderIntro.hidden = !recorder;

  if (cockpitTitle) {
    cockpitTitle.textContent = recorder ? "Flight recorder packet" : "Define the mission packet";
  }

  if (recorder) {
    state.packetMode = "record";
    const taskInput = $("#task-input");
    if (taskInput && !taskInput.value) {
      taskInput.placeholder = "Capture decision trace, context, and operator notes.";
    }
    if (missionPanel) missionPanel.hidden = true;
  } else {
    if (state.packetMode === "record" && !state.lastPacket?.attach_evidence) {
      state.packetMode = "draft";
    }
    if ($("#task-input")) {
      $("#task-input").placeholder = "Patch the repo, run the proof, and prepare a handoff.";
    }
    if (missionPanel) missionPanel.hidden = false;
  }

  renderPacket();
  renderMissionHome(state.data);
  renderCreatePacketScreen(state.data);
  renderFlightRecorder(state.data);
  renderHandoffExport(state.data);
}

function _queryRepoParams() {
  const params = new URLSearchParams();
  const repo = $("#repo-input").value || state.repo;
  if (repo) params.set("repo", repo);
  return params;
}

function canAdvanceTo(currentStage, targetStage) {
  const current = STAGE_RANK[normalizeStage(currentStage)] ?? -1;
  const target = STAGE_RANK[normalizeStage(targetStage)] ?? -1;
  return target > current;
}

function packetActionLockReason(packet, targetStage, plan = buildAdvancePlan(packet)) {
  if (!packet) return "Select a packet first.";
  if (state.cockpitMode === "recorder") return "Recorder mode creates a new evidence packet.";
  if (packetRequiresLaneDecision(packet) && targetStage === "gate") {
    return "Choose or keep a lane before running gates.";
  }
  if (plan.blocked) return plan.blockedMessage || "Packet is blocked by gates.";
  if (targetStage === "handoff" && ACTIVE_RUN_STATES.has(packet.runner_run?.status)) {
    return "Wait for the local runner to finish or cancel it before handoff.";
  }
  if (!canAdvanceTo(packet.stage, targetStage)) {
    return `${STAGE_LABELS[targetStage].title} is not ahead of the current packet stage.`;
  }
  if (!plan.allowed.has(targetStage)) {
    if (targetStage === "execute") return "Run gates before preparing execution.";
    if (targetStage === "handoff") return "Prepare execution before handoff.";
    if (targetStage === "record") return "Run gates before attaching evidence.";
    return "Complete the previous mission step first.";
  }
  return "";
}

function setButtonState(button, { disabled, reason = "", suggested = false, label }) {
  if (!button) return;
  button.textContent = label || button.textContent;
  button.disabled = Boolean(disabled);
  button.classList.toggle("next-action", Boolean(suggested && !disabled));
  button.classList.toggle("locked-action", Boolean(disabled && reason));
  button.title = reason || "";
  if (reason) {
    button.setAttribute("aria-label", `${button.textContent}: ${reason}`);
  } else {
    button.setAttribute("aria-label", button.textContent);
  }
}

function packetCommandState(packet) {
  if (!packet) {
    return {
      title: "No packet selected",
      detail: "Open or draft a packet.",
      label: "Select packet",
      disabled: true,
      run: null,
    };
  }
  if (state.cockpitMode === "recorder") {
    return {
      title: "Recorder mode",
      detail: "Create a new recorder packet from Flight Recorder.",
      label: "Recorder only",
      disabled: true,
      run: null,
    };
  }
  const runnerPlan = packet.runner_plan || {};
  const runnerRun = packet.runner_run || {};
  const runnerActive = ACTIVE_RUN_STATES.has(runnerRun.status);
  const runnerCanLaunch =
    packet.stage === "execute" &&
    runnerPlan.launch_supported === true &&
    Number(packet.gate_run?.blocked || 0) === 0 &&
    Number(packet.gate_run?.warnings || 0) === 0;
  if (runnerActive) {
    return {
      title: "Local run in progress",
      detail: runnerRun.summary || `${packetRunnerLabel(packet)} is running inside the bounded workspace.`,
      label: "Run active",
      disabled: true,
      run: null,
    };
  }
  if (runnerCanLaunch && runnerRun.status !== "succeeded") {
    return {
      title: runnerRun.status && runnerRun.status !== "not-started" ? "Retry bounded run" : "Launch bounded run",
      detail: `Start ${packetRunnerLabel(packet)} locally with a timeout and remote command execution off.`,
      label: runnerRun.status && runnerRun.status !== "not-started" ? "Retry local run" : "Launch local run",
      disabled: false,
      run: () => launchSelectedRunner().catch((error) => setText("#runner-control-summary", error.message)),
    };
  }
  const current = mapStage(packet);
  const currentStep = MAP_STEPS.find((step) => step.id === current) || MAP_STEPS[0];
  const action = mapActionFor(current, packet);
  return {
    title: action.label,
    detail: currentStep.summary,
    label: action.label,
    disabled: false,
    run: () => runMapAction(current, packet),
  };
}

function updatePacketCommand(packet) {
  const command = $("#packet-command");
  const title = $("#packet-command-title");
  const detail = $("#packet-command-detail");
  const button = $("#packet-primary-action");
  if (!command || !title || !detail || !button) return;
  const stateForPacket = packetCommandState(packet);
  title.textContent = stateForPacket.title;
  detail.textContent = stateForPacket.detail;
  button.textContent = stateForPacket.label;
  button.disabled = stateForPacket.disabled;
  button.onclick = stateForPacket.run;
  command.classList.toggle("packet-command-disabled", stateForPacket.disabled);
}

function updatePacketAdvanceButtons(packet) {
  const status = $("#packet-detail-status");
  updatePacketCommand(packet);
  if (state.cockpitMode === "recorder") {
    PACKET_ACTIONS.forEach((action) => {
      setButtonState($(action.selector), {
        disabled: true,
        reason: "Recorder mode creates a new evidence packet.",
        label: action.label,
      });
    });
    if (status) status.textContent = "Flight recorder: create a new packet to capture a record.";
    return;
  }

  if (!packet) {
    PACKET_ACTIONS.forEach((action) => {
      setButtonState($(action.selector), {
        disabled: true,
        reason: "Select a packet first.",
        label: action.label,
      });
    });
    return;
  }

  const plan = buildAdvancePlan(packet);
  const statusMessage = plan.blocked && plan.blockedMessage ? plan.blockedMessage : "";
  const primaryStage = packetRequiresLaneDecision(packet) ? null : plan.nextRecommended;

  PACKET_ACTIONS.forEach((action) => {
    const reason = packetActionLockReason(packet, action.stage, plan);
    setButtonState($(action.selector), {
      disabled: Boolean(reason),
      reason,
      suggested: action.stage === primaryStage,
      label: action.label,
    });
  });
  if (status && statusMessage) {
    status.textContent = statusMessage;
    return;
  }
  if (status && status.textContent.startsWith("Blocked by ")) {
    status.textContent = packet.status || "unknown";
  }
}

function runnerRunState(packet) {
  return packet?.runner_run || {
    status: "not-started",
    local_execution: false,
    remote_execution: false,
    events: [],
    last_message: "",
    summary: "No local runner has started for this packet.",
  };
}

function packetRunnerLabel(packet) {
  if (packet?.agent_id === "hermes") return "Hermes Agent";
  if (packet?.agent_id === "codex") return "Codex";
  return packet?.agent_name || packet?.lane?.name || "Local runner";
}

function runnerLaunchReason(packet) {
  if (!packet?.packet_id) return "Select a packet first.";
  if (packet.stage !== "execute") return "Prepare this packet to execute stage first.";
  if (Number(packet.gate_run?.blocked || 0) > 0) return "Blocked gates prevent launch.";
  if (Number(packet.gate_run?.warnings || 0) > 0) return "Clear gate warnings before launch.";
  if (!packet.runner_plan?.launch_supported) {
    return packet.runner_plan?.adapter_detail || "The selected local adapter is unavailable.";
  }
  if (ACTIVE_RUN_STATES.has(packet.runner_run?.status)) return "A local run is already active.";
  return "";
}

function setRunnerBadge(status) {
  const badge = $("#runner-status-badge");
  if (!badge) return;
  const text = String(status || "not-started");
  const tone = statusTone(text);
  badge.className = `pill ${tone.className}`;
  badge.textContent = text.replaceAll("-", " ");
  badge.title = tone.meaning;
}

function renderRunnerEvents(run) {
  const list = $("#runner-event-list");
  if (!list) return;
  clear(list);
  const events = Array.isArray(run?.events) ? run.events.slice(-12) : [];
  if (!events.length) {
    const row = document.createElement("div");
    row.className = "runner-event-row";
    const status = document.createElement("strong");
    status.textContent = run?.status || "waiting";
    const summary = document.createElement("span");
    summary.textContent = run?.status === "not-started" ? "No runner events yet." : run?.summary || "Waiting for local status.";
    row.append(status, summary);
    list.appendChild(row);
    return;
  }
  events.forEach((event) => {
    const row = document.createElement("div");
    row.className = "runner-event-row";
    const status = document.createElement("strong");
    status.textContent = event.status || event.type || "event";
    const summary = document.createElement("span");
    summary.textContent = event.summary || event.type || "Local runner event";
    row.append(status, summary);
    list.appendChild(row);
  });
}

function renderRunnerControl(packet) {
  const control = $("#packet-runner-control");
  if (!control) return;
  const plan = packet?.runner_plan || {};
  const run = runnerRunState(packet);
  const status = run.status || "not-started";
  const active = ACTIVE_RUN_STATES.has(status);
  const launchReason = runnerLaunchReason(packet);
  const launchButton = $("#runner-launch-button");
  const cancelButton = $("#runner-cancel-button");
  const timeoutInput = $("#runner-timeout-input");
  const finalMessage = $("#runner-final-message");
  const runnerLabel = packetRunnerLabel(packet);

  control.dataset.runState = status;
  control.dataset.packetId = packet?.packet_id || "";
  setRunnerBadge(status);
  setText(
    "#runner-control-title",
    active ? `${runnerLabel} run active` : status === "succeeded" ? `${runnerLabel} run complete` : plan.launch_supported ? `${runnerLabel} adapter ready` : `${runnerLabel} adapter waiting`,
  );
  setText(
    "#runner-adapter-state",
    plan.adapter_available ? `${plan.adapter_id || "local-adapter"} ready` : plan.adapter_detail || "Unavailable",
  );
  setText("#runner-sandbox-state", plan.sandbox_policy || "workspace-write");
  setText("#runner-boundary-state", run.remote_execution ? "External execution detected" : "Local process only");
  setText("#runner-control-summary", run.status !== "not-started" ? run.summary : plan.summary || run.summary);
  setText(
    "#runner-control-note",
    run.run_id
      ? `Run ${run.run_id}. ${Number(run.duration_seconds || 0).toFixed(1)}s. Remote command execution remains off.`
      : packet?.agent_id === "hermes"
        ? "Local workspace process. Hermes uses its existing provider configuration; gateways and remote command backends remain off."
        : "Local workspace process. Codex model access uses the existing CLI session; remote command execution remains off.",
  );

  if (launchButton) {
    launchButton.disabled = Boolean(launchReason);
    launchButton.title = launchReason;
    launchButton.textContent = ["failed", "timed-out", "cancelled", "interrupted"].includes(status)
      ? "Retry local run"
      : "Launch local run";
  }
  if (cancelButton) {
    cancelButton.disabled = !active;
    cancelButton.title = active ? "Stop the bounded local process tree" : "No local run is active";
  }
  if (timeoutInput) {
    timeoutInput.disabled = active;
    if (run.timeout_seconds && document.activeElement !== timeoutInput) timeoutInput.value = String(run.timeout_seconds);
  }
  renderRunnerEvents(run);
  if (finalMessage) {
    finalMessage.textContent = run.last_message || "";
    finalMessage.hidden = !run.last_message;
  }
}

function clearRunnerPoll() {
  window.clearTimeout(state.runnerPollTimer);
  state.runnerPollTimer = null;
}

async function refreshSelectedRunnerRun(scheduleNext = true) {
  const packet = state.selectedPacket;
  if (!packet?.packet_id) return;
  const seq = state.runnerPollSeq + 1;
  state.runnerPollSeq = seq;
  const params = _queryRepoParams();
  const response = await fetch(`/api/packets/${encodeURIComponent(packet.packet_id)}/run?${params.toString()}`);
  const data = await response.json();
  if (!response.ok || data.error) throw new Error(data.error || "Runner status request failed");
  if (seq !== state.runnerPollSeq || state.selectedPacket?.packet_id !== packet.packet_id) return;
  state.selectedPacket.runner_run = data.run;
  renderRunnerControl(state.selectedPacket);
  renderPacketMissionControl(state.selectedPacket);
  updatePacketCommand(state.selectedPacket);
  updatePacketAdvanceButtons(state.selectedPacket);
  clearRunnerPoll();
  if (scheduleNext && ACTIVE_RUN_STATES.has(data.run?.status)) {
    state.runnerPollTimer = window.setTimeout(() => {
      refreshSelectedRunnerRun(true).catch((error) => {
        setText("#runner-control-summary", error.message);
      });
    }, 700);
  }
}

async function launchSelectedRunner() {
  const packet = state.selectedPacket;
  const reason = runnerLaunchReason(packet);
  if (reason) {
    setText("#runner-control-summary", reason);
    return;
  }
  const timeoutInput = $("#runner-timeout-input");
  const timeoutSeconds = Number(timeoutInput?.value || 900);
  if (!Number.isInteger(timeoutSeconds) || timeoutSeconds < 5 || timeoutSeconds > 3600) {
    setText("#runner-control-summary", "Timeout must be a whole number from 5 to 3600 seconds.");
    timeoutInput?.focus();
    return;
  }
  clearRunnerPoll();
  setText("#runner-control-summary", `Starting the bounded local ${packetRunnerLabel(packet)} process...`);
  const params = _queryRepoParams();
  const response = await fetch(`/api/packets/${encodeURIComponent(packet.packet_id)}/run?${params.toString()}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ timeout_seconds: timeoutSeconds }),
  });
  const data = await response.json();
  if (!response.ok || data.error) throw new Error(data.error || "Runner launch failed");
  state.selectedPacket.runner_run = data.run;
  renderRunnerControl(state.selectedPacket);
  updatePacketAdvanceButtons(state.selectedPacket);
  await refreshSelectedRunnerRun(true);
}

async function cancelSelectedRunner() {
  const packet = state.selectedPacket;
  if (!packet?.packet_id || !ACTIVE_RUN_STATES.has(packet.runner_run?.status)) return;
  setText("#runner-control-summary", "Cancelling the local process tree...");
  const params = _queryRepoParams();
  const response = await fetch(
    `/api/packets/${encodeURIComponent(packet.packet_id)}/run/cancel?${params.toString()}`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" },
  );
  const data = await response.json();
  if (!response.ok || data.error) throw new Error(data.error || "Runner cancellation failed");
  state.selectedPacket.runner_run = data.run;
  renderRunnerControl(state.selectedPacket);
  await refreshSelectedRunnerRun(true);
}

function initRunnerControls() {
  const launchButton = $("#runner-launch-button");
  const cancelButton = $("#runner-cancel-button");
  if (launchButton) {
    launchButton.addEventListener("click", () => {
      launchSelectedRunner().catch((error) => setText("#runner-control-summary", error.message));
    });
  }
  if (cancelButton) {
    cancelButton.addEventListener("click", () => {
      cancelSelectedRunner().catch((error) => setText("#runner-control-summary", error.message));
    });
  }
}

async function advanceSelectedPacket(targetStage) {
  const packet = state.selectedPacket;
  if (!packet || !packet.packet_id) {
    $("#packet-detail-status").textContent = "Select a packet first";
    return;
  }
  if (!canAdvanceTo(packet.stage, targetStage)) {
    $("#packet-detail-status").textContent = `Cannot advance packet from ${packet.stage || "draft"} to ${targetStage}`;
    return;
  }

  $("#packet-detail-status").textContent = `Advancing packet to ${targetStage}...`;
  const params = _queryRepoParams();
  const response = await fetch(
    `/api/packets/${encodeURIComponent(packet.packet_id)}/advance?${params.toString()}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        stage: targetStage,
        attach_evidence: targetStage === "record",
      }),
    },
  );
  const data = await response.json();
  if (!response.ok || data.error) throw new Error(data.error || "Packet advance failed");
  state.selectedPacket = data.packet;
  await load(state.repo);
  $("#packet-detail-status").textContent = `Advanced to ${targetStage}`;
}

async function selectPacketLane(agentId) {
  const packet = state.selectedPacket;
  if (!packet || !packet.packet_id) {
    throw new Error("Select a packet first");
  }
  const params = _queryRepoParams();
  const response = await fetch(
    `/api/packets/${encodeURIComponent(packet.packet_id)}/lane?${params.toString()}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ agent_id: agentId }),
    },
  );
  const data = await response.json();
  if (!response.ok || data.error) throw new Error(data.error || "Packet lane selection failed");
  return data.packet;
}

function setHomeCockpitMode(mode) {
  const target = mode === "recorder" ? $("#mode-recorder") : $("#mode-orchestrate");
  if (!target) return;
  target.checked = true;
  applyCockpitMode();
  scheduleLiveRouteUpdate(0);
}

function initMissionHomeControls() {
  const form = $("#simple-run-form");
  if (form) {
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      runSimpleMission().catch((error) => {
        setSimpleRunState("error", "The job could not start", error.message, {
          packetId: state.simpleRun.packetId,
        });
      });
    });
  }

  const taskInput = $("#simple-task-input");
  if (taskInput) {
    taskInput.addEventListener("input", () => {
      setText("#simple-task-count", `${taskInput.value.length}/600`);
      if (state.simpleRun.status === "error" && !state.simpleRun.packetId) {
        state.simpleRun = { status: "idle", title: "Ready", body: "", packetId: null, result: "" };
        renderSimpleRunExperience();
      }
    });
  }

  const openPacket = $("#simple-open-packet");
  if (openPacket) {
    openPacket.addEventListener("click", () => {
      if (!state.simpleRun.packetId) return;
      loadPacketDetail(state.simpleRun.packetId).catch((error) => {
        setSimpleRunState("error", "Could not open job details", error.message, {
          packetId: state.simpleRun.packetId,
        });
      });
    });
  }

  const manualButton = $("#simple-open-manual");
  if (manualButton) {
    manualButton.addEventListener("click", () => {
      const manualInput = $("#task-input");
      if (manualInput && taskInput?.value.trim()) {
        manualInput.value = taskInput.value;
        manualInput.dispatchEvent(new Event("input", { bubbles: true }));
      }
      revealSection("cockpit");
      manualInput?.focus();
    });
  }

  const viewAll = $("#home-view-all-packets");
  if (viewAll) viewAll.addEventListener("click", () => revealSection("runs"));
}

function initGoalControls() {
  const goalButton = $("#simple-goal-button");
  if (goalButton) goalButton.addEventListener("click", openGoalBuilder);

  const closeButton = $("#goal-dialog-close");
  if (closeButton) closeButton.addEventListener("click", () => $("#goal-dialog")?.close());

  const maintenanceButton = $("#goal-type-maintenance");
  if (maintenanceButton) maintenanceButton.addEventListener("click", () => selectGoalType("maintenance"));

  const expansionButton = $("#goal-type-expansion");
  if (expansionButton) expansionButton.addEventListener("click", () => selectGoalType("expansion"));

  const expansionInput = $("#goal-expansion-input");
  if (expansionInput) {
    expansionInput.addEventListener("input", () => {
      if (state.goalDraft) {
        state.goalDraft.preview = null;
        state.goalDraft.saved = null;
      }
      renderGoalBuilder();
      scheduleGoalPreview();
    });
  }

  const saveButton = $("#goal-save-button");
  if (saveButton) {
    saveButton.addEventListener("click", () => {
      ensureGoalSaved().catch((error) => setText("#goal-dialog-status", error.message));
    });
  }

  const copyButton = $("#goal-copy-button");
  if (copyButton) {
    copyButton.addEventListener("click", () => {
      copyCodexGoal().catch((error) => setText("#goal-dialog-status", error.message));
    });
  }

  const openButton = $("#goal-open-codex-button");
  if (openButton) {
    openButton.addEventListener("click", () => {
      openGoalInCodex().catch((error) => setText("#goal-dialog-status", error.message));
    });
  }

  const reviewButton = $("#goal-review-button");
  if (reviewButton) {
    reviewButton.addEventListener("click", () => {
      reviewCompletedGoal().catch((error) => setText("#goal-dialog-status", error.message));
    });
  }
}

function initCreatePacketControls() {
  const backHome = $("#create-back-home");
  if (backHome) {
    backHome.addEventListener("click", () => {
      revealSection("mission-home");
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  }

  const reviewRoutes = $("#create-review-routes");
  if (reviewRoutes) {
    reviewRoutes.addEventListener("click", () => {
      refreshLiveRoutes().catch((error) => console.warn(error));
      revealSection("routes");
    });
  }

  const useRecorder = $("#create-use-recorder");
  if (useRecorder) {
    useRecorder.addEventListener("click", () => {
      setHomeCockpitMode("recorder");
      const taskInput = $("#task-input");
      if (taskInput) taskInput.focus();
    });
  }
}

function recorderBackTarget() {
  return state.selectedPacket?.packet_id ? "packet-detail-panel" : "mission-home";
}

async function createRecorderPacketFromScreen() {
  const recorderInput = $("#recorder-task-input");
  const taskInput = $("#task-input");
  const task = recorderInput?.value.trim() || taskInput?.value.trim();
  if (!task) {
    setText("#recorder-status-badge", "Waiting");
    setText("#recorder-status-title", "Write the recorder note first");
    setText("#recorder-status-body", "Recorder packets need a bounded note before Hamiltonian can save them locally.");
    setText("#recorder-footer-note", "Add the mission note, then record the packet.");
    recorderInput?.focus();
    return;
  }

  if (recorderInput && !recorderInput.value.trim()) recorderInput.value = task;
  if (taskInput) taskInput.value = task;
  setHomeCockpitMode("recorder");
  renderFlightRecorder(state.data);
  setText("#recorder-status-badge", "Saving");
  setText("#recorder-status-title", "Saving local recorder packet");
  setText("#recorder-status-body", "Hamiltonian is writing the packet locally with evidence placeholders.");
  await submitPacket("record", { task });
  renderFlightRecorder(state.data);
}

function openRecorderPacket() {
  const packet = recorderPacketForDisplay(state.data);
  if (!packet?.packet_id) return;
  loadPacketDetail(packet.packet_id).catch((error) => {
    setText("#recorder-footer-note", error.message);
  });
}

function initFlightRecorderControls() {
  const backButton = $("#recorder-back-packet");
  if (backButton) {
    backButton.addEventListener("click", () => revealSection(recorderBackTarget()));
  }

  const armButton = $("#recorder-arm-button");
  if (armButton) {
    armButton.addEventListener("click", () => {
      setHomeCockpitMode("recorder");
      revealSection("recorder-panel");
      renderFlightRecorder(state.data);
    });
  }

  const createButton = $("#recorder-create-button");
  if (createButton) {
    createButton.addEventListener("click", () => {
      createRecorderPacketFromScreen().catch((error) => {
        setText("#recorder-status-badge", "Error");
        setText("#recorder-status-title", "Recorder packet failed");
        setText("#recorder-status-body", error.message);
        setText("#recorder-footer-note", error.message);
      });
    });
  }

  const openButton = $("#recorder-open-packet-button");
  if (openButton) openButton.addEventListener("click", openRecorderPacket);

  const recorderInput = $("#recorder-task-input");
  if (recorderInput) {
    recorderInput.addEventListener("input", () => {
      syncRecorderTaskCount();
      renderFlightRecorder(state.data);
    });
  }
}

function initRouteSelectionControls() {
  const backButton = $("#route-back-packet");
  if (backButton) {
    backButton.addEventListener("click", () => revealSection(routeBackTarget()));
  }

  const cancelButton = $("#route-cancel-button");
  if (cancelButton) {
    cancelButton.addEventListener("click", () => revealSection(routeBackTarget()));
  }
}

function render(data) {
  state.data = data;
  renderHeader(data);
  renderAgents(data);
  renderLifecycle(data);
  renderGates(data);
  renderIntegrations(data);
  renderAdvancedSettings(data);
  renderRoutes(data);
  renderRecentPackets(data);
  renderPacketDetail(state.selectedPacket);
  renderMissionMap(state.selectedPacket);
  renderMissionPath(state.selectedPacket);
  renderTutorial(state.selectedPacket);
  renderNextActions(data);
  applyCockpitMode();
  renderMissionHome(data);
  renderCreatePacketScreen(data);
  renderFlightRecorder(data);
  renderHandoffExport(data);
}

async function load(repo) {
  const params = new URLSearchParams();
  if (repo) params.set("repo", repo);
  window.clearTimeout(state.goalHistoryTimer);
  const [response, healthResponse, goalsResponse] = await Promise.all([
    fetch(`/api/state?${params.toString()}`),
    fetch("/api/health"),
    fetch(`/api/goals?${params.toString()}`),
  ]);
  const [data, health, goalsPayload] = await Promise.all([
    response.json(),
    healthResponse.json(),
    goalsResponse.json(),
  ]);
  if (!response.ok || data.error) throw new Error(data.error || "State request failed");
  if (healthResponse.ok && !health.error) state.appInfo = health;
  state.goals = goalsResponse.ok && !goalsPayload.error ? goalsPayload.goals || [] : [];
  state.repo = data.repo;
  render(data);
  state.goalHistoryTimer = window.setTimeout(() => {
    refreshGoalHistory().catch((error) => setText("#goal-history-summary", error.message));
  }, 10000);
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
  if (state.lastExport && state.lastExport.packet_id && state.lastExport.packet_id !== data.packet.packet_id) {
    state.lastExport = null;
  }
  renderPacketDetail(data.packet);
  revealSection("packet-detail-panel");
  clearRunnerPoll();
  refreshSelectedRunnerRun(true).catch((error) => setText("#runner-control-summary", error.message));
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
  state.lastPacket = data.packet;
  state.lastExport = data.export;
  renderPacketDetail(data.packet);
  renderHandoffExport(state.data);
  $("#packet-detail-status").textContent = `Exported ${data.export.filename}`;
}

async function submitPacket(stageName, options = {}) {
  const task = String(options.task || $("#task-input").value || "").trim();
  if (!task) {
    $("#packet-preview").textContent = "Write a task before creating a packet.";
    return;
  }
  const recorderMode = state.cockpitMode === "recorder";
  state.packetMode = recorderMode ? "record" : stageName;
  state.lastPacket = null;
  state.lastExport = null;
  $("#packet-preview").textContent = "Saving packet...";
  const repo = $("#repo-input").value || state.repo;
  const modeStage = recorderMode ? "record" : stageName;
  const response = await fetch("/api/packets", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      repo,
      task,
      agent_id: recorderMode ? "codex" : $("#agent-select").value || "codex",
      stage: modeStage,
      attach_evidence: recorderMode ? true : stageName === "record",
      mode: recorderMode ? "recorder" : "orchestrate",
    }),
  });
  const data = await response.json();
  if (!response.ok || data.error) throw new Error(data.error || "Packet request failed");
  state.lastPacket = data.packet;
  state.selectedPacket = data.packet;
  await load(repo);
  await refreshLiveRoutes().catch((error) => console.warn(error));
  renderFlightRecorder(state.data);
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

$("#recorder-button").addEventListener("click", () => {
  submitPacket("record").catch((error) => {
    $("#packet-preview").textContent = error.message;
  });
});

$("#mode-orchestrate").addEventListener("change", () => {
  if ($("#mode-orchestrate").checked) {
    applyCockpitMode();
    scheduleLiveRouteUpdate(0);
  }
});

$("#mode-recorder").addEventListener("change", () => {
  if ($("#mode-recorder").checked) {
    applyCockpitMode();
    scheduleLiveRouteUpdate(0);
  }
});

$("#guide-toggle").addEventListener("click", () => {
  if (state.guideOpen) {
    closeGuide();
  } else {
    openGuide();
  }
});

$("#guide-close").addEventListener("click", closeGuide);

document.addEventListener("keydown", handleGlobalKeydown);

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

$("#packet-gate-button").addEventListener("click", () => {
  advanceSelectedPacket("gate").catch((error) => {
    $("#packet-detail-status").textContent = error.message;
  });
});

$("#packet-execute-button").addEventListener("click", () => {
  advanceSelectedPacket("execute").catch((error) => {
    $("#packet-detail-status").textContent = error.message;
  });
});

$("#packet-handoff-button").addEventListener("click", () => {
  advanceSelectedPacket("handoff").catch((error) => {
    $("#packet-detail-status").textContent = error.message;
  });
});

$("#packet-record-button").addEventListener("click", () => {
  advanceSelectedPacket("record").catch((error) => {
    $("#packet-detail-status").textContent = error.message;
  });
});

$("#packet-export-button").addEventListener("click", () => {
  exportSelectedPacket().catch((error) => {
    $("#packet-detail-status").textContent = error.message;
  });
});

$("#task-input").addEventListener("input", () => {
  state.lastPacket = null;
  state.lastExport = null;
  if (state.cockpitMode !== "recorder" && state.packetMode === "record") {
    state.packetMode = "draft";
  }
  renderPacket();
  renderFlightRecorder(state.data);
  scheduleLiveRouteUpdate();
});
$("#agent-select").addEventListener("change", () => {
  renderPacket();
  scheduleLiveRouteUpdate(0);
});

initMissionHomeControls();
initGoalControls();
initCreatePacketControls();
initFlightRecorderControls();
initHandoffExportControls();
initAdvancedSettingsControls();
initRouteSelectionControls();
initPacketDetailControls();
initGateViewControls();
initRunnerControls();
initPageNavigation();
updateLocalTime();
window.setInterval(updateLocalTime, 1000);

load(state.repo).catch((error) => {
  $("#packet-preview").textContent = error.message;
});
