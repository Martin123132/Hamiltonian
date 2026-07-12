#!/usr/bin/env node

import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import net from "node:net";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";


const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptDir, "..");
const qaRoot = path.resolve(
  process.env.HAMILTONIAN_QA_ROOT ||
    (process.platform === "win32" ? "D:\\Codex\\Temp\\Hamiltonian" : path.join(projectRoot, ".hamiltonian", "qa")),
);


function assert(condition, message) {
  if (!condition) throw new Error(message);
}


async function freePort() {
  return await new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      server.close((error) => (error ? reject(error) : resolve(port)));
    });
  });
}


async function waitForHttp(url, label, timeoutMs = 20000) {
  const deadline = Date.now() + timeoutMs;
  let lastError = null;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return await response.json().catch(() => ({}));
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 150));
  }
  throw new Error(`${label} did not become ready${lastError ? `: ${lastError.message}` : ""}`);
}


async function runProcess(command, args, cwd) {
  await new Promise((resolve, reject) => {
    const child = spawn(command, args, { cwd, windowsHide: true, stdio: "ignore" });
    child.once("error", reject);
    child.once("exit", (code) => (code === 0 ? resolve() : reject(new Error(`${command} exited ${code}`))));
  });
}


function edgePath() {
  const candidates = [
    process.env.HAMILTONIAN_BROWSER,
    "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
    "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
  ].filter(Boolean);
  const found = candidates.find((candidate) => existsSync(candidate));
  if (!found) throw new Error("No supported Edge or Chrome executable found. Set HAMILTONIAN_BROWSER.");
  return found;
}


class CdpClient {
  constructor(url) {
    this.url = url;
    this.socket = null;
    this.nextId = 1;
    this.pending = new Map();
  }

  async connect() {
    this.socket = new WebSocket(this.url);
    await new Promise((resolve, reject) => {
      this.socket.addEventListener("open", resolve, { once: true });
      this.socket.addEventListener("error", reject, { once: true });
    });
    this.socket.addEventListener("message", (event) => {
      const message = JSON.parse(String(event.data));
      if (!message.id) return;
      const pending = this.pending.get(message.id);
      if (!pending) return;
      this.pending.delete(message.id);
      if (message.error) {
        pending.reject(new Error(`${message.error.message} (${message.error.code})`));
      } else {
        pending.resolve(message.result || {});
      }
    });
  }

  async send(method, params = {}) {
    assert(this.socket?.readyState === WebSocket.OPEN, "CDP socket is not open");
    const id = this.nextId++;
    return await new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }

  close() {
    this.socket?.close();
  }
}


async function evaluate(client, expression) {
  const response = await client.send("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
    userGesture: true,
  });
  if (response.exceptionDetails) {
    const detail = response.exceptionDetails.exception?.description || response.exceptionDetails.text;
    throw new Error(`Browser evaluation failed: ${detail}`);
  }
  return response.result?.value;
}


async function captureJpeg(client, outputPath) {
  const screenshot = await client.send("Page.captureScreenshot", {
    format: "jpeg",
    quality: 88,
    captureBeyondViewport: false,
  });
  await writeFile(outputPath, Buffer.from(screenshot.data, "base64"));
  return outputPath;
}


const journeyExpression = String.raw`
(async () => {
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const waitFor = async (check, label, timeout = 20000) => {
    const deadline = Date.now() + timeout;
    let lastError = null;
    while (Date.now() < deadline) {
      try {
        const value = await check();
        if (value) return value;
      } catch (error) {
        lastError = error;
      }
      await sleep(100);
    }
    throw new Error('Timed out waiting for ' + label + (lastError ? ': ' + lastError.message : ''));
  };
  const q = (selector) => document.querySelector(selector);
  const click = (selector) => {
    const node = q(selector);
    if (!node) throw new Error('Missing control: ' + selector);
    if (node.disabled) throw new Error('Disabled control: ' + selector + ' (' + (node.title || node.textContent.trim()) + ')');
    node.click();
  };
  const setValue = (selector, value) => {
    const node = q(selector);
    if (!node) throw new Error('Missing input: ' + selector);
    node.value = value;
    node.dispatchEvent(new Event('input', { bubbles: true }));
    node.dispatchEvent(new Event('change', { bubbles: true }));
  };
  const activePage = (page) => q('[data-page-target="' + page + '"]')?.getAttribute('aria-current') === 'page';

  await waitFor(() => q('#repo-name')?.textContent !== 'Loading', 'initial cockpit state');
  const visibleNav = [...document.querySelectorAll('.nav [data-page-target]')].filter(
    (node) => getComputedStyle(node).display !== 'none',
  );
  if (visibleNav.length !== 4) throw new Error('Expected four primary navigation choices, found ' + visibleNav.length);
  if (q('#simple-run-options')?.open) throw new Error('Advanced run options should start closed');

  setValue('#simple-task-input', 'Implement a bounded local cockpit journey and report the result.');
  click('[data-testid="simple-run"]');
  await waitFor(
    () => ['starting', 'running', 'succeeded'].includes(q('[data-testid="simple-status"]')?.dataset.status),
    'simple local run start',
  );
  await waitFor(() => q('[data-testid="simple-status"]')?.dataset.status === 'succeeded', 'simple local run success', 30000);
  const packetId = q('#mission-home')?.dataset.packetId;
  if (!packetId) throw new Error('Simple run did not expose its packet id');
  if (!q('#simple-run-result')?.textContent.includes('Repository health: **B')) {
    throw new Error('Simple run did not display the final result');
  }

  const repo = q('#repo-input').value;
  const packetResponse = await fetch('/api/packets/' + encodeURIComponent(packetId) + '?repo=' + encodeURIComponent(repo));
  const packetPayload = await packetResponse.json();
  const packet = packetPayload.packet;
  if (!packetResponse.ok) throw new Error(packetPayload.error || 'Packet detail API failed');
  if (packet.stage !== 'execute') throw new Error('Expected execute stage, got ' + packet.stage);
  if (packet.runner_plan?.launch_supported !== true) throw new Error('Runner launch was not enabled');
  if (packet.runner_run?.status !== 'succeeded') throw new Error('Local runner result was not persisted');
  if (packet.runner_run?.local_execution !== true) throw new Error('Local execution was not recorded');
  if (packet.runner_run?.remote_execution !== false) throw new Error('Remote execution unexpectedly enabled');
  if (packet.attach_evidence !== false) throw new Error('Evidence should remain optional on the main path');

  const hermesCreateResponse = await fetch('/api/packets', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      repo,
      task: 'Review this bounded local packet and return a concise result.',
      agent_id: 'hermes',
      stage: 'execute',
      attach_evidence: false,
    }),
  });
  const hermesCreatePayload = await hermesCreateResponse.json();
  if (!hermesCreateResponse.ok) throw new Error(hermesCreatePayload.error || 'Hermes packet creation failed');
  const hermesPacketId = hermesCreatePayload.packet.packet_id;
  if (hermesCreatePayload.packet.runner_plan?.mode !== 'local-hermes-one-shot') {
    throw new Error('Hermes packet did not expose the one-shot adapter');
  }
  const hermesLaunchResponse = await fetch(
    '/api/packets/' + encodeURIComponent(hermesPacketId) + '/run?repo=' + encodeURIComponent(repo),
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ timeout_seconds: 20 }),
    },
  );
  const hermesLaunchPayload = await hermesLaunchResponse.json();
  if (!hermesLaunchResponse.ok) throw new Error(hermesLaunchPayload.error || 'Hermes launch failed');
  let hermesRun = hermesLaunchPayload.run;
  await waitFor(async () => {
    const response = await fetch(
      '/api/packets/' + encodeURIComponent(hermesPacketId) + '/run?repo=' + encodeURIComponent(repo),
    );
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Hermes run poll failed');
    hermesRun = payload.run;
    return !['starting', 'running', 'cancelling'].includes(hermesRun.status);
  }, 'Hermes local run', 30000);
  if (hermesRun.status !== 'succeeded') throw new Error('Hermes local run did not succeed');
  if (hermesRun.remote_execution !== false) throw new Error('Hermes enabled remote command execution');
  if (hermesRun.last_message !== 'Synthetic Hermes Agent browser run completed locally.') {
    throw new Error('Hermes final response was not persisted');
  }
  await loadPacketDetail(hermesPacketId);
  await waitFor(
    () => q('#runner-control-title')?.textContent === 'Hermes Agent run complete',
    'Hermes packet detail state',
  );
  if (q('#runner-sandbox-state')?.textContent !== 'hermes-safe-mode-checkpoints') {
    throw new Error('Hermes safety policy was not rendered');
  }
  click('[data-page-target="start"]');
  await waitFor(() => activePage('start'), 'simple home after Hermes run');

  click('[data-page-target="recorder"]');
  await waitFor(() => activePage('recorder'), 'Recorder page');
  setValue('#recorder-task-input', 'Capture a local evidence trace for the simple journey.');
  click('#recorder-create-button');
  await waitFor(() => q('#recorder-panel')?.dataset.recorderPacket === 'captured', 'recorder packet');
  const recorderId = q('#recorder-panel')?.dataset.packetId;
  if (!recorderId || recorderId === packetId) throw new Error('Recorder packet id was not created separately');
  const recorderResponse = await fetch('/api/packets/' + encodeURIComponent(recorderId) + '?repo=' + encodeURIComponent(repo));
  const recorderPayload = await recorderResponse.json();
  if (!recorderResponse.ok) throw new Error(recorderPayload.error || 'Recorder detail API failed');
  if (recorderPayload.packet.attach_evidence !== true) throw new Error('Recorder packet did not select evidence');

  click('[data-page-target="start"]');
  await waitFor(() => activePage('start'), 'simple home');
  setValue('#simple-task-input', 'WAIT_FOR_CANCEL');
  click('[data-testid="simple-run"]');
  await waitFor(() => q('[data-testid="simple-status"]')?.dataset.status === 'running', 'simple cancellation run active');
  const cancelPacketId = q('#mission-home')?.dataset.packetId;
  click('[data-testid="simple-run"]');
  await waitFor(() => q('[data-testid="simple-status"]')?.dataset.status === 'cancelled', 'simple local run cancelled', 30000);

  setValue('#simple-task-input', 'Return a concise completion message for visual QA.');
  click('[data-testid="simple-run"]');
  await waitFor(() => q('[data-testid="simple-status"]')?.dataset.status === 'succeeded', 'final simple local run success', 30000);
  const visualPacketId = q('#mission-home')?.dataset.packetId;

  click('[data-testid="get-codex-goal"]');
  await waitFor(() => q('#goal-dialog')?.open, 'Codex goal dialog');
  await waitFor(() => q('[data-testid="goal-preview"]')?.textContent.includes('B to B+'), 'maintenance grade target');
  click('#goal-save-button');
  await waitFor(() => q('#goal-dialog-status')?.textContent.includes('Saved locally'), 'saved maintenance goal');
  const goalsResponse = await fetch('/api/goals?repo=' + encodeURIComponent(repo));
  const goalsPayload = await goalsResponse.json();
  if (!goalsResponse.ok || !goalsPayload.goals?.length) throw new Error('Saved maintenance goal missing from API');
  const maintenanceGoalId = goalsPayload.goals[0].goal_id;

  click('#goal-type-expansion');
  setValue('#goal-expansion-input', 'Users can compare two benchmark runs side by side.');
  await waitFor(
    () => q('[data-testid="goal-preview"]')?.textContent.includes('Users can compare two benchmark runs side by side.'),
    'expansion goal preview',
  );
  if (q('#goal-open-codex-button')?.disabled) throw new Error('Open in Codex should be available for a valid goal');
  click('#goal-dialog-close');

  return {
    ok: true,
    primary_navigation_items: visibleNav.length,
    packet_id: packetId,
    runner_status: packet.runner_run.status,
    remote_execution: packet.runner_run.remote_execution,
    evidence_main: packet.attach_evidence,
    hermes_packet_id: hermesPacketId,
    hermes_status: hermesRun.status,
    hermes_remote_execution: hermesRun.remote_execution,
    recorder_packet_id: recorderId,
    evidence_recorder: recorderPayload.packet.attach_evidence,
    cancellation_packet_id: cancelPacketId,
    cancellation_status: 'cancelled',
    visual_packet_id: visualPacketId,
    visual_status: q('[data-testid="simple-status"]')?.dataset.status,
    maintenance_goal_id: maintenanceGoalId,
    maintenance_target: 'B+',
    expansion_preview: true,
  };
})()
`;


const goalLifecycleExpression = String.raw`
(async () => {
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const waitFor = async (check, label, timeout = 30000) => {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      const value = check();
      if (value) return value;
      await sleep(100);
    }
    throw new Error('Timed out waiting for ' + label);
  };
  await refreshGoalHistory();
  const readyRow = await waitFor(
    () => [...document.querySelectorAll('[data-testid="goal-history-row"]')].find(
      (row) => row.querySelector('.goal-history-badge')?.dataset.status === 'ready-for-review',
    ),
    'review-ready goal history row',
  );
  const reviewButton = [...readyRow.querySelectorAll('button')].find((button) => button.textContent === 'Review now');
  if (!reviewButton) throw new Error('Review action was not shown for the valid receipt');
  reviewButton.click();
  await waitFor(() => document.querySelector('[data-testid="simple-status"]')?.dataset.status === 'succeeded', 'goal review completion');
  await refreshGoalHistory();
  const correctionRow = await waitFor(
    () => [...document.querySelectorAll('[data-testid="goal-history-row"]')].find(
      (row) => row.querySelector('.goal-history-badge')?.dataset.status === 'needs-correction',
    ),
    'incomplete review status',
  );
  const correctiveButton = [...correctionRow.querySelectorAll('button')].find(
    (button) => button.textContent === 'Create corrective goal',
  );
  if (!correctiveButton) throw new Error('Corrective goal action was not shown');
  correctiveButton.click();
  await waitFor(() => document.querySelector('#goal-dialog')?.open, 'corrective goal dialog');
  await waitFor(() => document.querySelector('#goal-target-label')?.textContent === 'Corrective goal', 'corrective goal preview');
  const repo = document.querySelector('#repo-input').value;
  const response = await fetch('/api/goals?repo=' + encodeURIComponent(repo));
  const payload = await response.json();
  const corrective = payload.goals.find((goal) => goal.goal_type === 'corrective');
  if (!corrective?.parent_goal_id) throw new Error('Corrective goal lineage was not persisted');
  return {
    review_status: 'incomplete',
    corrective_goal_id: corrective.goal_id,
    corrective_parent_goal_id: corrective.parent_goal_id,
    goal_history_rows: document.querySelectorAll('[data-testid="goal-history-row"]').length,
  };
})()
`;


async function main() {
  await mkdir(qaRoot, { recursive: true });
  const runDir = await mkdtemp(path.join(qaRoot, "browser-smoke-"));
  const workspace = path.join(runDir, "Hamiltonian-Demo");
  const browserProfile = path.join(runDir, "browser-profile");
  await mkdir(workspace, { recursive: true });
  await mkdir(browserProfile, { recursive: true });

  const appPort = await freePort();
  const debugPort = await freePort();
  const appUrl = `http://127.0.0.1:${appPort}/`;
  const python = process.env.PYTHON || "python";
  const pythonPath = [path.join(projectRoot, "src"), process.env.PYTHONPATH].filter(Boolean).join(path.delimiter);
  const fakeCodexPath = path.join(runDir, "fake_codex.py");
  const fakeHermesPath = path.join(runDir, "fake_hermes.py");
  await writeFile(
    fakeCodexPath,
    `from __future__ import annotations
import json
from pathlib import Path
import sys
import time

if "--version" in sys.argv:
    print("codex-cli 9.9.9-browser-test")
    raise SystemExit(0)

prompt = sys.argv[-1]
def emit(payload):
    print(json.dumps(payload), flush=True)

emit({"type": "thread.started", "thread_id": "browser-test"})
emit({"type": "turn.started"})
emit({"type": "item.started", "item": {"id": "item-1", "type": "command_execution", "command": "private", "status": "in_progress"}})
if "WAIT_FOR_CANCEL" in prompt:
    time.sleep(30)
if "--output-last-message" in sys.argv:
    output_index = sys.argv.index("--output-last-message") + 1
    message = """Repository health: **B - strong core.**

Medium finding: add focused regression coverage."""
    if "Review completed Codex goal" in prompt:
        message = """## Verdict

**Goal incomplete.**

Maintenance health grade: **B**

One focused trust regression remains."""
    Path(sys.argv[output_index]).write_text(message, encoding="utf-8")
emit({"type": "item.completed", "item": {"id": "item-1", "type": "agent_message", "text": "private", "status": "completed"}})
emit({"type": "turn.completed", "usage": {"input_tokens": 100, "cached_input_tokens": 60, "output_tokens": 20, "reasoning_output_tokens": 4}})
`,
    "utf8",
  );
  await writeFile(
    fakeHermesPath,
    `from __future__ import annotations
import sys

if "--version" in sys.argv:
    print("Hermes Agent 9.9.9-browser-test")
    raise SystemExit(0)
if "-z" not in sys.argv:
    raise SystemExit(2)
print("Synthetic Hermes Agent browser run completed locally.", flush=True)
`,
    "utf8",
  );
  await runProcess("git", ["init", "--quiet"], workspace);
  const codexCommand = JSON.stringify([python, fakeCodexPath]);
  const hermesCommand = JSON.stringify([python, fakeHermesPath]);
  let serverOutput = "";
  const server = spawn(
    python,
    ["-m", "hamiltonian", "cockpit", "--repo", workspace, "--host", "127.0.0.1", "--port", String(appPort)],
    {
      cwd: projectRoot,
      env: {
        ...process.env,
        PYTHONPATH: pythonPath,
        HAMILTONIAN_CODEX_COMMAND: codexCommand,
        HAMILTONIAN_HERMES_COMMAND: hermesCommand,
      },
      windowsHide: true,
    },
  );
  server.stdout.on("data", (chunk) => (serverOutput += chunk));
  server.stderr.on("data", (chunk) => (serverOutput += chunk));

  let browser = null;
  let client = null;
  try {
    await waitForHttp(`${appUrl}api/state`, "Hamiltonian cockpit");
    browser = spawn(
      edgePath(),
      [
        "--headless=new",
        "--disable-gpu",
        "--disable-extensions",
        "--no-first-run",
        "--no-default-browser-check",
        `--remote-debugging-port=${debugPort}`,
        `--user-data-dir=${browserProfile}`,
        "about:blank",
      ],
      { windowsHide: true },
    );
    await waitForHttp(`http://127.0.0.1:${debugPort}/json/version`, "headless browser");
    const tabResponse = await fetch(
      `http://127.0.0.1:${debugPort}/json/new?${encodeURIComponent(appUrl)}`,
      { method: "PUT" },
    );
    const tab = await tabResponse.json();
    assert(tab.webSocketDebuggerUrl, "Browser tab did not expose a debugging socket");

    client = new CdpClient(tab.webSocketDebuggerUrl);
    await client.connect();
    await client.send("Page.enable");
    await client.send("Runtime.enable");
    await client.send("Emulation.setDeviceMetricsOverride", {
      width: 1440,
      height: 900,
      deviceScaleFactor: 1,
      mobile: false,
    });
    await client.send("Page.navigate", { url: appUrl });
    await evaluate(client, "new Promise((resolve) => { if (document.readyState === 'complete') resolve(true); else window.addEventListener('load', () => resolve(true), { once: true }); })");

    const result = await evaluate(client, journeyExpression);
    const receiptPath = path.join(workspace, ".hamiltonian", "goals", result.maintenance_goal_id, "return.json");
    await writeFile(
      receiptPath,
      JSON.stringify(
        {
          goal_id: result.maintenance_goal_id,
          status: "ready-for-review",
          summary: "Maintenance work completed and tests passed.",
          files_changed: ["src/example.py"],
          tests: ["browser smoke: passed"],
          branch: "main",
          commit: "browser-qa",
          pushed: false,
          remaining_work: "Review in Hamiltonian.",
        },
        null,
        2,
      ),
      "utf8",
    );

    await evaluate(client, `(async () => {
      document.querySelector('#goal-dialog')?.close();
      await refreshGoalHistory();
      const titles = [
        'Repository health check',
        'Release readiness review',
        'Dependency and security audit',
        'Documentation quality review',
        'Capture a local evidence trace',
      ];
      document.querySelectorAll('[data-testid="home-recent-packet"] strong').forEach((node, index) => {
        if (titles[index]) node.textContent = titles[index];
      });
      document.querySelector('#home-goal-history')?.scrollIntoView({ block: 'start' });
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      return true;
    })()`);
    const readyPath = await captureJpeg(
      client,
      path.join(qaRoot, "hamiltonian-goal-ready-desktop.jpg"),
    );

    const goalLifecycle = await evaluate(client, goalLifecycleExpression);
    await evaluate(client, `(async () => {
      document.querySelector('#goal-dialog')?.close();
      await refreshGoalHistory();
      const titles = [
        'Repository health check',
        'Release readiness review',
        'Dependency and security audit',
        'Documentation quality review',
        'Capture a local evidence trace',
      ];
      document.querySelectorAll('[data-testid="home-recent-packet"] strong').forEach((node, index) => {
        if (titles[index]) node.textContent = titles[index];
      });
      document.querySelector('#home-goal-history')?.scrollIntoView({ block: 'start' });
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      return true;
    })()`);
    const lineagePath = await captureJpeg(
      client,
      path.join(qaRoot, "hamiltonian-corrective-lineage-desktop.jpg"),
    );

    await evaluate(client, `(async () => {
      window.scrollTo(0, 0);
      const input = document.querySelector('#simple-task-input');
      input.value = 'Run a read-only health check on this repository.';
      input.dispatchEvent(new Event('input', { bubbles: true }));
      setSimpleRunState('idle', 'Ready', '', { packetId: null, result: '' });
      const titles = [
        'Repository health check',
        'Release readiness review',
        'Dependency and security audit',
        'Documentation quality review',
        'Capture a local evidence trace',
      ];
      document.querySelectorAll('[data-testid="home-recent-packet"] strong').forEach((node, index) => {
        if (titles[index]) node.textContent = titles[index];
      });
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      return true;
    })()`);
    const homePath = await captureJpeg(
      client,
      path.join(qaRoot, "hamiltonian-mission-home-desktop.jpg"),
    );

    await evaluate(client, `(async () => {
      setSimpleRunState(
        'succeeded',
        'Health check complete',
        'Hamiltonian completed the local check and saved the result.',
        {
          packetId: ${JSON.stringify(result.visual_packet_id)},
          result: 'Repository health: **B - strong core.**\\n\\nTwo focused reliability improvements are ready for a Codex goal.',
        },
      );
      document.querySelector('#simple-run-status')?.scrollIntoView({ block: 'center' });
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      return true;
    })()`);
    const checkPath = await captureJpeg(
      client,
      path.join(qaRoot, "hamiltonian-health-check-desktop.jpg"),
    );

    await client.send("Emulation.setDeviceMetricsOverride", {
      width: 390,
      height: 844,
      deviceScaleFactor: 1,
      mobile: true,
    });
    await evaluate(client, `(async () => {
      window.scrollTo(0, 0);
      document.activeElement?.blur();
      document.querySelector('#goal-dialog')?.close();
      setSimpleRunState('idle', 'Ready', '', { packetId: null, result: '' });
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      return true;
    })()`);
    const mobilePath = await captureJpeg(
      client,
      path.join(qaRoot, "hamiltonian-mission-home-mobile.jpg"),
    );

    const launcherTemplate = await readFile(
      path.join(projectRoot, "src", "hamiltonian", "web", "desktop-launcher.html"),
      "utf8",
    );
    const launcherHtml = launcherTemplate.replace(
      "__HAMILTONIAN_RECENTS__",
      JSON.stringify([
        {
          name: "Benchmark Lab",
          path: "D:\\Projects\\Benchmark-Lab",
          last_opened: "2026-07-11T00:00:00Z",
          goal_summary: { total: 2, ready_for_review: 1, needs_correction: 0, complete: 1 },
        },
        {
          name: "Research Toolkit",
          path: "D:\\Projects\\Research-Toolkit",
          last_opened: "2026-07-10T00:00:00Z",
        },
      ]),
    ).replace("__HAMILTONIAN_VERSION__", "0.4.0");
    await client.send("Emulation.setDeviceMetricsOverride", {
      width: 1440,
      height: 900,
      deviceScaleFactor: 1,
      mobile: false,
    });
    await client.send("Page.navigate", {
      url: `data:text/html;base64,${Buffer.from(launcherHtml).toString("base64")}`,
    });
    await evaluate(client, "new Promise((resolve) => { if (document.readyState === 'complete') resolve(true); else window.addEventListener('load', () => resolve(true), { once: true }); })");
    await evaluate(client, "window.dispatchEvent(new Event('pywebviewready')); true");
    const launcherPath = await captureJpeg(
      client,
      path.join(qaRoot, "hamiltonian-desktop-launcher.jpg"),
    );

    console.log(JSON.stringify({
      ...result,
      ...goalLifecycle,
      screenshots: {
        mission_home: homePath,
        health_check: checkPath,
        goal_ready: readyPath,
        corrective_lineage: lineagePath,
        mobile: mobilePath,
        launcher: launcherPath,
      },
    }, null, 2));
    await client.send("Browser.close").catch(() => {});
  } catch (error) {
    if (serverOutput.trim()) console.error(serverOutput.trim());
    throw error;
  } finally {
    client?.close();
    browser?.kill();
    server.kill();
    const resolvedRoot = `${qaRoot}${path.sep}`;
    if (path.resolve(runDir).startsWith(resolvedRoot)) {
      await rm(runDir, { recursive: true, force: true, maxRetries: 4, retryDelay: 250 }).catch(() => {});
    }
  }
}


main().catch((error) => {
  console.error(error.stack || error.message || String(error));
  process.exitCode = 1;
});
