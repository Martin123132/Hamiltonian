const state = {
  repo: new URLSearchParams(window.location.search).get("repo") || "",
  data: null,
  packetMode: "draft",
  cockpitMode: "orchestrate",
  activePage: "start",
  lastPacket: null,
  selectedPacket: null,
  routeTimer: null,
  routeRequestSeq: 0,
  guideOpen: false,
  guideStage: null,
  mapCursorIndex: null,
  mapCursorStage: null,
  readinessFocus: null,
};
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
    anchor: "packet-detail-panel",
    summary: "Turn the packet into an operator-ready brief.",
  },
  {
    id: "record",
    title: "Attach proof",
    anchor: "mission",
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
    anchor: "packet-detail-panel",
  },
  record: {
    title: "Add proof when needed",
    body: "Attach evidence only when this run needs a recorder packet.",
    anchor: "packet-detail-panel",
  },
};
const TUTORIAL_ORDER = ["draft", "route", "gate", "execute", "handoff", "record"];
const PAGE_ORDER = ["start", "map", "learn", "routes", "packets", "advanced"];
const PAGE_ALIASES = {
  cockpit: "start",
  "mission-map": "map",
  tutorial: "learn",
  gates: "routes",
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
  const button = document.querySelector("#route-list .route .compact-button");
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
  if (packet?.packet_id && ["gate", "execute", "handoff", "record"].includes(normalized)) {
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
    route: ["#route-list .route-current", "#route-list .route .compact-button", "#route-list", "#routes"],
    gate: ["#packet-command", "#packet-gate-button", "#packet-detail-panel"],
    execute: ["#packet-command", "#packet-execute-button", "#packet-detail-panel"],
    handoff: ["#packet-command", "#packet-handoff-button", "#packet-detail-panel"],
    record: ["#packet-command", "#packet-record-button", "#packet-detail-panel"],
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

function renderRoutes(data) {
  const list = $("#route-list");
  const compass = $("#route-compass");
  clear(list);
  if (compass) clear(compass);
  const routes = data.route_recommendations || [];
  const activePacket = state.selectedPacket;
  if (routes.length === 0) {
    const empty = document.createElement("article");
    empty.className = "route";
    const title = document.createElement("strong");
    title.textContent = "No route recommendations";
    const detail = document.createElement("p");
    detail.textContent = "Refresh cockpit state to build local lane recommendations.";
    empty.append(title, detail, pill("empty"));
    list.appendChild(empty);
    if (compass) {
      const note = document.createElement("p");
      note.textContent = "No lane signal yet. Write a task or refresh cockpit state.";
      compass.appendChild(note);
    }
    return;
  }

  if (compass) {
    const lead = routes[0];
    const selected = activePacket?.agent_name || $("#agent-select").selectedOptions[0]?.textContent || "No active lane";
    const summary = document.createElement("div");
    const label = document.createElement("span");
    const title = document.createElement("strong");
    const detail = document.createElement("p");
    label.textContent = "Lane compass";
    title.textContent = `${lead.lane_name} is strongest right now`;
    detail.textContent = `Active lane: ${selected}. Route advice is local metadata only; gates still decide.`;
    summary.append(label, title, detail);
    compass.append(summary, pill(lead.status));
  }

  routes.forEach((route) => {
    const isActivePacketLane = Boolean(activePacket?.packet_id && activePacket.agent_id === route.lane_id);
    const activeLaneReviewed = isActivePacketLane && packetHasLaneDecision(activePacket);
    const scoreValue = Math.max(0, Math.min(100, Number(route.score || 0)));
    const row = document.createElement("article");
    row.className = "route";
    row.classList.toggle("route-current", isActivePacketLane);
    row.style.setProperty("--route-strength", `${scoreValue}%`);
    const body = document.createElement("div");
    body.className = "route-body";
    const kicker = document.createElement("span");
    kicker.className = "route-kicker";
    kicker.textContent = `Lane ${route.rank}`;
    const title = document.createElement("strong");
    title.textContent = route.lane_name;
    const summary = document.createElement("p");
    summary.textContent = route.summary;
    const reasons = document.createElement("p");
    reasons.textContent = `Why: ${(route.reasons || []).join("; ")}`;
    const boundary = document.createElement("p");
    boundary.className = "route-boundary";
    boundary.textContent = route.remote_execution ? "Boundary: remote execution represented only." : "Boundary: local-only lane; no remote runner is executed.";
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
    useButton.textContent = activePacket?.packet_id
      ? activeLaneReviewed
        ? "Current lane"
        : isActivePacketLane
          ? "Keep lane"
        : "Use for packet"
      : "Use lane";
    useButton.title = activePacket?.packet_id
      ? `Select ${route.lane_name} for the active packet`
      : `Select ${route.lane_name}`;
    useButton.disabled = activeLaneReviewed;
    useButton.addEventListener("click", () => {
      useRouteLane(route, useButton).catch((error) => {
        const status = $("#packet-detail-status");
        if (status) status.textContent = error.message;
      });
    });
    actions.append(score, strength, pill(route.status), useButton);
    row.append(body, actions);
    list.appendChild(row);
  });
}

async function useRouteLane(route, button) {
  const select = $("#agent-select");
  if ([...select.options].some((option) => option.value === route.lane_id)) {
    select.value = route.lane_id;
  }

  if (!state.selectedPacket?.packet_id || state.cockpitMode === "recorder") {
    state.lastPacket = null;
    renderPacket();
    scheduleLiveRouteUpdate(0);
    return;
  }

  if (button) {
    button.disabled = true;
    button.textContent = "Selecting...";
  }
  const packet = await selectPacketLane(route.lane_id);
  state.selectedPacket = packet;
  state.lastPacket = packet;
  await load(state.repo);
  await refreshLiveRoutes().catch((error) => console.warn(error));
  setActivePage("map", { updateHash: true, hash: "#map" });
  window.scrollTo({ top: 0, behavior: "smooth" });
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
    const routeLine = document.createElement("p");
    routeLine.textContent = `Route: ${route.status || "unknown"}; recommended ${route.recommended_lane_name || lane.name}.`;
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
    body.append(title, detail, meta, routeLine, execution, handoffLine, proof, next);
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
      status: executionBoundary.remote_execution ? "external" : "manual only",
      detail: executionBoundary.status || "No local or remote execution has been prepared.",
      explainerTitle: "Execution is a manual approval boundary",
      explainer: executionBoundary.remote_execution
        ? "This packet is warning that an external execution path is present, so it needs operator review."
        : "Hamiltonian prepares the approval surface only. It does not run a local command or call a remote agent here.",
      next:
        executionBoundary.status === "awaiting-approval"
          ? "Review the boundary before any manual run."
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

function renderPacketDetail(packet) {
  const title = $("#packet-detail-title");
  const status = $("#packet-detail-status");
  const detail = $("#packet-detail");
  const exportButton = $("#packet-export-button");
  const packetGateButton = $("#packet-gate-button");
  const packetExecuteButton = $("#packet-execute-button");
  const packetHandoffButton = $("#packet-handoff-button");
  const packetRecordButton = $("#packet-record-button");
  clear(detail);
  renderReadinessStrip(packet);

  if (!packet) {
    title.textContent = "No packet selected";
    status.textContent = "Waiting";
    exportButton.disabled = true;
    if (packetGateButton) packetGateButton.disabled = true;
    if (packetExecuteButton) packetExecuteButton.disabled = true;
    if (packetHandoffButton) packetHandoffButton.disabled = true;
    if (packetRecordButton) packetRecordButton.disabled = true;
    updatePacketAdvanceButtons(null);
    const empty = document.createElement("p");
    empty.className = "muted-line";
    empty.textContent = "No packet selected.";
    detail.appendChild(empty);
    renderMissionMap(null);
    renderTutorial(null);
    return;
  }

  const lane = packet.lane || {};
  const executionBoundary = packet.execution_boundary || {};
  const handoff = packet.handoff || {};
  const handoffExport = packet.exports?.handoff_markdown || null;
  const gates = packet.gates || [];
  const gateRun = packet.gate_run || {};
  const route = packet.route || {};
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
    detailRow("Route", `${route.status || "unknown"} / ${route.recommended_lane_name || packet.agent_name}`),
    detailRow("Gate run", `${gateRun.status || "unknown"} (${gateRun.completed || 0}/${gateRun.total || 0})`),
    detailRow("Execution", `${executionBoundary.status || "unknown"} / ${executionBoundary.mode || "unknown"}`),
    detailRow("Handoff", `${handoff.status || "unknown"} / ${handoff.ready ? "ready" : "not ready"}`),
    detailRow("Evidence", evidenceGate.status || "unknown"),
    detailRow("Export", handoffExport ? `${handoffExport.filename} / sanitized` : "none"),
    detailRow("Remote execution", String(Boolean(executionBoundary.remote_execution || lane.remote_execution)))
  );

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

  detail.append(summary, routeBlock, task, next, gateList);
  updatePacketAdvanceButtons(packet);
  renderMissionMap(packet);
  renderMissionPath(packet);
  renderTutorial(packet);
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
    cockpitTitle.textContent = recorder ? "Flight recorder" : "Assign bounded work";
  }

  if (recorder) {
    state.packetMode = "record";
    const taskInput = $("#task-input");
    if (taskInput && !taskInput.value) {
      taskInput.placeholder = "Capture decision trace, context, and operator notes.";
    }
    if (missionPanel) missionPanel.hidden = true;
  } else {
    if ($("#task-input")) {
      $("#task-input").placeholder = "Patch the repo, run the proof, and prepare a handoff.";
    }
    if (missionPanel) missionPanel.hidden = false;
  }

  renderPacket();
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
      detail: "Create a new recorder packet from Task control.",
      label: "Recorder only",
      disabled: true,
      run: null,
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

function render(data) {
  state.data = data;
  renderHeader(data);
  renderAgents(data);
  renderLifecycle(data);
  renderGates(data);
  renderIntegrations(data);
  renderRoutes(data);
  renderRecentPackets(data);
  renderPacketDetail(state.selectedPacket);
  renderMissionMap(state.selectedPacket);
  renderMissionPath(state.selectedPacket);
  renderTutorial(state.selectedPacket);
  renderNextActions(data);
  applyCockpitMode();
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
  revealSection("packet-detail-panel");
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
  const recorderMode = state.cockpitMode === "recorder";
  state.packetMode = recorderMode ? "record" : stageName;
  state.lastPacket = null;
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
  renderPacket();
  scheduleLiveRouteUpdate();
});
$("#agent-select").addEventListener("change", () => {
  renderPacket();
  scheduleLiveRouteUpdate(0);
});

initPageNavigation();

load(state.repo).catch((error) => {
  $("#packet-preview").textContent = error.message;
});
