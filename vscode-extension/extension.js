const vscode = require("vscode");
const { execFile } = require("child_process");
const path = require("path");

const REFRESH_MS = 10_000;
const CLI_SCRIPT = path.join(__dirname, "cli.py");

function getProjectRoot() {
  const folders = vscode.workspace.workspaceFolders;
  return folders && folders.length > 0 ? folders[0].uri.fsPath : null;
}

function runPython(args) {
  return new Promise((resolve, reject) => {
    const pythonBin = process.platform === "win32" ? "python" : "python3";
    execFile(pythonBin, args, (err, stdout) => {
      if (err && process.platform !== "win32") {
        // fallback to python on non-Windows too (e.g. some Linux setups)
        execFile("python", args, (err2, stdout2) => {
          if (err2) return reject(err2);
          resolve(stdout2);
        });
      } else if (err) {
        reject(err);
      } else {
        resolve(stdout);
      }
    });
  });
}

function fetchData(cwd) {
  return runPython([CLI_SCRIPT, "--json", "--no-api", "--cwd", cwd]).then((stdout) => {
    try {
      return JSON.parse(stdout);
    } catch (e) {
      throw e;
    }
  });
}

function getNoSessionContent() {
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline';" />
  <style>
    body {
      background: var(--vscode-sideBar-background, #1e1e1e);
      color: var(--vscode-foreground, #ccc);
      font-family: var(--vscode-font-family, -apple-system, sans-serif);
      font-size: 12px;
      padding: 24px 16px;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 8px;
      opacity: 0.5;
    }
    .icon { font-size: 28px; }
    .msg { text-align: center; line-height: 1.5; }
  </style>
</head>
<body>
  <div class="icon">⬡</div>
  <div class="msg">No active session.<br>Start a Claude Code session<br>to view token usage.</div>
</body>
</html>`;
}

function getWebviewContent(data) {
  const COLORS = [
    "#4FC3F7", "#81C784", "#FFD54F", "#CE93D8",
    "#FF8A65", "#F06292", "#4DB6AC", "#DCE775",
  ];

  const pct = data.pct_of_context;
  const accentColor = pct >= 90 ? "#F06292" : pct >= 70 ? "#FFD54F" : "#4FC3F7";

  // Build SVG donut chart using stroke-dasharray on a circle (r=40, circumference=251.2)
  const R = 40;
  const CIRC = 2 * Math.PI * R;
  const GAP = 2; // px gap between segments
  const total = data.components.reduce((s, c) => s + c.tokens, 0);

  let offset = 0; // start at top (-25% rotation applied via transform)
  const slices = data.components.map((c, i) => {
    const frac = total > 0 ? c.tokens / total : 0;
    const dash = Math.max(0, frac * CIRC - GAP);
    const slice = `<circle
      cx="50" cy="50" r="${R}"
      fill="none"
      stroke="${COLORS[i % COLORS.length]}"
      stroke-width="16"
      stroke-dasharray="${dash.toFixed(2)} ${CIRC.toFixed(2)}"
      stroke-dashoffset="${(-offset * CIRC).toFixed(2)}"
      stroke-linecap="butt"
    />`;
    offset += frac;
    return slice;
  }).join("\n");

  const rows = data.components.map((c, i) => {
    const color = COLORS[i % COLORS.length];
    if (c.label === "Global Skills" && data.skill_groups && data.skill_groups.length > 0) {
      return data.skill_groups.map(g => {
        const gPct = total > 0 ? (g.total / total * 100).toFixed(1) : "0.0";
        const skillRows = g.skills.map(s => {
          const sPct = total > 0 ? (s.tokens / total * 100).toFixed(1) : "0.0";
          return `<div class="skill-row">
            <span class="skill-name">${s.name}</span>
            <span class="tok">${s.tokens.toLocaleString()}</span>
            <span class="pct-val" style="color:${color}88">${sPct}%</span>
          </div>`;
        }).join("");
        return `<details class="skill-group">
          <summary class="row">
            <span class="group-arrow"></span>
            <span class="dot" style="background:${color}"></span>
            <span class="lbl">${g.prefix} <span class="group-count">(${g.skills.length})</span></span>
            <span class="tok">${g.total.toLocaleString()}</span>
            <span class="pct-val" style="color:${color}">${gPct}%</span>
          </summary>
          <div class="skill-list">${skillRows}</div>
        </details>`;
      }).join("");
    }
    return `<div class="row">
      <span class="dot" style="background:${color}"></span>
      <span class="lbl">${c.label}</span>
      <span class="tok">${c.tokens.toLocaleString()}</span>
      <span class="pct-val" style="color:${color}">${c.pct}%</span>
    </div>`;
  }).join("");

  const note = data.using_estimates
    ? `<p class="note">* Estimates only — set ANTHROPIC_API_KEY for exact counts.</p>`
    : "";

  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline';" />
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: var(--vscode-sideBar-background, #1e1e1e);
      color: var(--vscode-foreground, #ccc);
      font-family: var(--vscode-font-family, -apple-system, sans-serif);
      font-size: 12px;
      padding: 10px 12px 12px;
    }

    .eyebrow { font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.6px; opacity: 0.4; margin-bottom: 8px; }

    /* Donut + centre stat */
    .chart-area { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
    .donut-wrap { position: relative; flex-shrink: 0; width: 100px; height: 100px; }
    .donut-wrap svg { transform: rotate(-90deg); }
    .donut-centre {
      position: absolute; inset: 0;
      display: flex; flex-direction: column; align-items: center; justify-content: center;
      pointer-events: none;
    }
    .centre-pct { font-size: 18px; font-weight: 700; color: ${accentColor}; line-height: 1; }
    .centre-lbl { font-size: 9px; opacity: 0.4; margin-top: 2px; text-transform: uppercase; letter-spacing: 0.4px; }

    /* Side stats */
    .side-stats { display: flex; flex-direction: column; gap: 4px; }
    .side-total { font-size: 13px; font-weight: 600; }
    .side-sub { font-size: 10px; opacity: 0.4; }

    /* Context fill bar */
    .ctx-wrap { height: 4px; background: rgba(255,255,255,0.07); border-radius: 2px; overflow: hidden; margin-bottom: 12px; }
    .ctx-fill { height: 100%; width: ${pct}%; background: ${accentColor}; border-radius: 2px; }

    /* Legend rows */
    .divider { height: 1px; background: rgba(255,255,255,0.06); margin-bottom: 8px; }
    .row { display: flex; align-items: center; gap: 7px; padding: 3px 0; }
    .dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
    .lbl { flex: 1; font-size: 11px; opacity: 0.7; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .tok { font-size: 10px; opacity: 0.35; font-variant-numeric: tabular-nums; }
    .pct-val { font-size: 11px; font-weight: 600; min-width: 36px; text-align: right; }

    .note { margin-top: 10px; font-size: 10px; opacity: 0.3; }

    /* Collapsible skill groups */
    .skill-group { border: none; }
    .skill-group > summary { list-style: none; cursor: pointer; }
    .skill-group > summary::-webkit-details-marker { display: none; }
    .group-arrow { width: 10px; flex-shrink: 0; font-size: 8px; opacity: 0.5; }
    .group-arrow::before { content: "▶"; }
    .skill-group[open] > summary .group-arrow::before { content: "▼"; }
    .group-count { opacity: 0.35; font-size: 10px; }
    .skill-list { padding-left: 20px; }
    .skill-row { display: flex; align-items: center; gap: 7px; padding: 2px 0; }
    .skill-name { flex: 1; font-size: 10px; opacity: 0.55; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  </style>
</head>
<body>
  <div class="eyebrow">Token Usage</div>

  <div class="chart-area">
    <div class="donut-wrap">
      <svg viewBox="0 0 100 100" width="100" height="100">
        <!-- track -->
        <circle cx="50" cy="50" r="${R}" fill="none" stroke="rgba(255,255,255,0.07)" stroke-width="16"/>
        ${slices}
      </svg>
      <div class="donut-centre">
        <span class="centre-pct">${pct}%</span>
        <span class="centre-lbl">used</span>
      </div>
    </div>
    <div class="side-stats">
      <div class="side-total">${data.total.toLocaleString()}</div>
      <div class="side-sub">of ${data.context_window.toLocaleString()} tokens</div>
      <div class="side-sub" style="margin-top:4px">${data.components.length} components</div>
    </div>
  </div>

  <div class="ctx-wrap"><div class="ctx-fill"></div></div>

  <div class="divider"></div>
  ${rows}
  ${note}
</body>
</html>`;
}

class TokenMaxxerViewProvider {
  constructor() {
    this._view = null;
  }

  resolveWebviewView(webviewView) {
    this._view = webviewView;
    webviewView.webview.options = { enableScripts: true };

    const cwd = getProjectRoot();
    if (cwd) {
      this._refresh(cwd);
    } else {
      webviewView.webview.html = `<body style="padding:16px;font-family:monospace;color:#888">No workspace folder open.</body>`;
    }

    webviewView.onDidDispose(() => { this._view = null; });
  }

  async _refresh(cwd) {
    if (!this._view) return;
    try {
      const data = await fetchData(cwd);
      if (data.error) {
        this._view.webview.html = getNoSessionContent();
        return data;
      }
      this._view.webview.html = getWebviewContent(data);
      return data;
    } catch (e) {
      if (this._view) {
        this._view.webview.html = `<body style="padding:16px;font-family:monospace;color:#f44">
          Failed to fetch token data:<br><pre>${e.message}</pre>
        </body>`;
      }
    }
  }

  refresh(cwd) {
    return this._refresh(cwd);
  }

  get hasView() { return !!this._view; }
}

function activate(context) {
  const provider = new TokenMaxxerViewProvider();

  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider("tokenmaxxer.view", provider, {
      webviewOptions: { retainContextWhenHidden: true }
    })
  );

  const statusItem = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Left,
    100
  );
  statusItem.command = "tokenmaxxer.showChart";
  statusItem.tooltip = "Click to open token usage chart";
  statusItem.show();
  context.subscriptions.push(statusItem);

  function buildMiniBar(pct) {
    const filled = Math.round(pct / 10);
    return "▰".repeat(filled) + "▱".repeat(10 - filled);
  }

  async function updateStatusBar() {
    const cwd = getProjectRoot();
    if (!cwd) return;
    try {
      const data = await fetchData(cwd);
      if (data.error) {
        statusItem.text = `$(graph) ctx — no session`;
        if (provider.hasView) await provider.refresh(cwd);
        return;
      }
      const pct = data.pct_of_context;
      statusItem.text = `$(graph) ctx ${buildMiniBar(pct)} ${pct}%`;
      if (provider.hasView) await provider.refresh(cwd);
    } catch {
      statusItem.text = `$(graph) ctx —`;
    }
  }

  context.subscriptions.push(
    vscode.commands.registerCommand("tokenmaxxer.showChart", async () => {
      await vscode.commands.executeCommand("tokenmaxxer.view.focus");
      const cwd = getProjectRoot();
      if (cwd) await provider.refresh(cwd);
    })
  );

  updateStatusBar();
  const pollTimer = setInterval(updateStatusBar, REFRESH_MS);
  context.subscriptions.push({ dispose: () => clearInterval(pollTimer) });

  const watcher = vscode.workspace.createFileSystemWatcher("**/.claude/token_state.json");
  watcher.onDidChange(updateStatusBar);
  watcher.onDidCreate(updateStatusBar);
  context.subscriptions.push(watcher);
}

function deactivate() {}

module.exports = { activate, deactivate };
