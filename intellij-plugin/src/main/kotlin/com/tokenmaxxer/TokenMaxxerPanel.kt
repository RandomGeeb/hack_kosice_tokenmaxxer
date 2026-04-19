package com.tokenmaxxer

import com.google.gson.Gson
import com.google.gson.annotations.SerializedName
import com.google.gson.reflect.TypeToken
import com.intellij.openapi.Disposable
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.project.Project
import com.intellij.openapi.util.Disposer
import com.intellij.ui.jcef.JBCefBrowser
import com.intellij.ui.jcef.JBCefJSQuery
import com.intellij.util.concurrency.AppExecutorUtil
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit
import java.util.concurrent.TimeoutException
import javax.swing.JComponent
import kotlin.math.PI
import kotlin.math.max

private data class Component(val label: String, val tokens: Int, val pct: Double)
private data class Skill(val name: String, val tokens: Int)
private data class SkillGroup(val prefix: String, val total: Int, val skills: List<Skill>)
private data class TokenError(val error: String)
private data class TokenData(
    @SerializedName("pct_of_context") val pctOfContext: Double,
    val total: Int,
    @SerializedName("context_window") val contextWindow: Int,
    @SerializedName("using_estimates") val usingEstimates: Boolean,
    val components: List<Component>,
    @SerializedName("skill_groups") val skillGroups: List<SkillGroup>?
)
private data class SessionListItem(
    @SerializedName("session_id") val sessionId: String,
    @SerializedName("started_at") val startedAt: String,
    @SerializedName("last_active") val lastActive: String,
    @SerializedName("is_active") val isActive: Boolean,
    @SerializedName("has_data") val hasData: Boolean
)

class TokenMaxxerPanel(private val project: Project) : Disposable {

    private val browser = JBCefBrowser()
    private val gson = Gson()
    private var pollFuture: ScheduledFuture<*>? = null
    private val cliScript: String

    @Volatile private var selectedSessionId: String? = null
    private val jsQuery: JBCefJSQuery

    val component: JComponent get() = browser.component

    init {
        cliScript = extractCli()

        jsQuery = JBCefJSQuery.create(browser)
        jsQuery.addHandler { sessionId ->
            selectedSessionId = sessionId.takeIf { it.isNotBlank() }
            AppExecutorUtil.getAppExecutorService().submit { refresh() }
            null
        }

        browser.loadHTML(loadingHtml())
        Disposer.register(project, this)
    }

    private fun extractCli(): String {
        val tmpDir = java.io.File(System.getProperty("java.io.tmpdir"), "tokenmaxxer-plugin")
        tmpDir.mkdirs()

        val cliFile = java.io.File(tmpDir, "cli.py")
        javaClass.getResourceAsStream("/cli.py")?.use { it.copyTo(cliFile.outputStream()) }

        val pkgDir = java.io.File(tmpDir, "tokenmaxxer")
        pkgDir.mkdirs()
        listOf("__init__.py", "analyzer.py", "session_state.py", "visualizer.py", "db.py").forEach { name ->
            val dest = java.io.File(pkgDir, name)
            val stream = javaClass.getResourceAsStream("/tokenmaxxer/$name")
                ?: throw IllegalStateException("Missing plugin resource: tokenmaxxer/$name")
            stream.use { it.copyTo(dest.outputStream()) }
        }

        return cliFile.absolutePath
    }

    fun start() {
        AppExecutorUtil.getAppExecutorService().submit { refresh() }
        pollFuture = AppExecutorUtil.getAppScheduledExecutorService()
            .scheduleWithFixedDelay({ refresh() }, 10, 10, TimeUnit.SECONDS)
    }

    private fun resolvePython(): String {
        val isWindows = System.getProperty("os.name").lowercase().contains("win")
        if (isWindows) return "python"
        return try {
            Runtime.getRuntime().exec(arrayOf("python3", "--version")).waitFor()
            "python3"
        } catch (_: Exception) {
            "python"
        }
    }

    private fun runCli(cwd: String, vararg extraArgs: String): String {
        val cmd = mutableListOf(resolvePython(), cliScript, "--cwd", cwd) + extraArgs.toList()
        val process = ProcessBuilder(cmd).redirectErrorStream(true).start()
        val outputFuture = AppExecutorUtil.getAppExecutorService().submit<String> {
            process.inputStream.bufferedReader().readText()
        }
        val output = try {
            outputFuture.get(15, TimeUnit.SECONDS)
        } catch (e: TimeoutException) {
            process.destroyForcibly()
            throw IllegalStateException("CLI timed out after 15s")
        }
        process.waitFor(5, TimeUnit.SECONDS)
        return output
    }

    private fun refresh() {
        val cwd = project.basePath ?: return
        try {
            // Fetch all sessions
            val sessionsJson = runCli(cwd, "--list-sessions", "--json")
            val sessionType = object : TypeToken<List<SessionListItem>>() {}.type
            val sessions: List<SessionListItem> = try {
                gson.fromJson(sessionsJson, sessionType) ?: emptyList()
            } catch (_: Exception) { emptyList() }

            // Determine which session to display
            val displayId = selectedSessionId
                ?.let { sel -> sessions.find { it.sessionId == sel && it.hasData }?.sessionId }
                ?: sessions.find { it.isActive && it.hasData }?.sessionId
                ?: sessions.firstOrNull { it.hasData }?.sessionId

            if (displayId == null) {
                ApplicationManager.getApplication().invokeLater { browser.loadHTML(noSessionHtml()) }
                return
            }

            val output = runCli(cwd, "--json", "--no-api", "--session", displayId)
            if (!output.trimStart().startsWith("{")) throw IllegalStateException(output.take(300))

            val errCheck = gson.fromJson(output, TokenError::class.java)
            if (errCheck?.error != null) {
                ApplicationManager.getApplication().invokeLater { browser.loadHTML(noSessionHtml()) }
                return
            }

            val data = gson.fromJson(output, TokenData::class.java)
            val html = buildHtml(data, sessions, displayId)
            ApplicationManager.getApplication().invokeLater { browser.loadHTML(html) }
        } catch (e: Throwable) {
            ApplicationManager.getApplication().invokeLater { browser.loadHTML(errorHtml(e.message ?: "Unknown error")) }
        }
    }

    private fun sessionLabel(s: SessionListItem): String {
        val shortId = s.sessionId.take(8)
        val timeStr = (s.lastActive.ifBlank { s.startedAt }).take(16).replace("T", " ")
        val suffix = if (s.isActive) " · active" else ""
        return "$shortId · $timeStr$suffix"
    }

    private fun buildHtml(data: TokenData, sessions: List<SessionListItem>, displayedSessionId: String): String {
        val colors = listOf(
            "#4FC3F7", "#81C784", "#FFD54F", "#CE93D8",
            "#FF8A65", "#F06292", "#4DB6AC", "#DCE775"
        )
        val pct = data.pctOfContext
        val pctFmt = "%.1f".format(pct)
        val accentColor = if (pct >= 90) "#F06292" else if (pct >= 70) "#FFD54F" else "#4FC3F7"

        val r = 40.0
        val circ = 2 * PI * r
        val gap = 2.0
        val totalTokens = data.components.sumOf { it.tokens }.toDouble()

        var offset = 0.0
        val slices = data.components.mapIndexed { i, c ->
            val frac = if (totalTokens > 0) c.tokens / totalTokens else 0.0
            val dash = max(0.0, frac * circ - gap)
            val result = """<circle cx="50" cy="50" r="${"%.1f".format(r)}" fill="none" stroke="${colors[i % colors.size]}" stroke-width="16" stroke-dasharray="${"%.2f".format(dash)} ${"%.2f".format(circ)}" stroke-dashoffset="${"%.2f".format(-offset * circ)}" stroke-linecap="butt"/>"""
            offset += frac
            result
        }.joinToString("\n")

        val rows = data.components.mapIndexed { i, c ->
            val color = colors[i % colors.size]
            if (c.label == "Global Skills" && !data.skillGroups.isNullOrEmpty()) {
                data.skillGroups.joinToString("") { g ->
                    val gPct = if (totalTokens > 0) "%.1f".format(g.total / totalTokens * 100) else "0.0"
                    val skillRows = g.skills.joinToString("") { s ->
                        val sPct = if (totalTokens > 0) "%.1f".format(s.tokens / totalTokens * 100) else "0.0"
                        """<div class="skill-row"><span class="skill-name">${s.name}</span><span class="tok">${"%,d".format(s.tokens)}</span><span class="pct-val" style="color:${color}88">${sPct}%</span></div>"""
                    }
                    """<details class="skill-group"><summary class="row"><span class="group-arrow"></span><span class="dot" style="background:$color"></span><span class="lbl">${g.prefix} <span class="group-count">(${g.skills.size})</span></span><span class="tok">${"%,d".format(g.total)}</span><span class="pct-val" style="color:$color">${gPct}%</span></summary><div class="skill-list">$skillRows</div></details>"""
                }
            } else {
                """<div class="row"><span class="dot" style="background:$color"></span><span class="lbl">${c.label}</span><span class="tok">${"%,d".format(c.tokens)}</span><span class="pct-val" style="color:$color">${c.pct}%</span></div>"""
            }
        }.joinToString("")

        val note = if (data.usingEstimates) """<p class="note">* Estimates only — set ANTHROPIC_API_KEY for exact counts.</p>""" else ""

        // Session selector — only render if more than one session has data
        val sessionsWithData = sessions.filter { it.hasData }
        val injectJs = jsQuery.inject("document.getElementById('tm-session').value")
        val sessionSelectHtml = if (sessionsWithData.size > 1) {
            val options = sessionsWithData.joinToString("") { s ->
                val selected = if (s.sessionId == displayedSessionId) " selected" else ""
                """<option value="${s.sessionId}"$selected>${sessionLabel(s)}</option>"""
            }
            """<div class="session-wrap"><select class="session-select" id="tm-session">$options</select></div>
<script>document.getElementById('tm-session').addEventListener('change',function(){$injectJs});</script>"""
        } else ""

        return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #1e1f22; color: #bcbec4; font-family: 'JetBrains Mono', monospace; font-size: 12px; padding: 10px 12px 12px; }
.session-wrap { margin-bottom: 8px; }
.session-select { width: 100%; background: rgba(255,255,255,0.06); color: #ccc; border: 1px solid rgba(255,255,255,0.12); border-radius: 4px; padding: 4px 6px; font-size: 11px; cursor: pointer; }
.session-select:focus { outline: none; border-color: #4FC3F7; }
.eyebrow { font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.6px; opacity: 0.4; margin-bottom: 8px; }
.chart-area { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.donut-wrap { position: relative; flex-shrink: 0; width: 100px; height: 100px; }
.donut-wrap svg { transform: rotate(-90deg); }
.donut-centre { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; pointer-events: none; }
.centre-pct { font-size: 18px; font-weight: 700; color: $accentColor; line-height: 1; }
.centre-lbl { font-size: 9px; opacity: 0.4; margin-top: 2px; text-transform: uppercase; letter-spacing: 0.4px; }
.side-stats { display: flex; flex-direction: column; gap: 4px; }
.side-total { font-size: 13px; font-weight: 600; }
.side-sub { font-size: 10px; opacity: 0.4; }
.ctx-wrap { height: 4px; background: rgba(255,255,255,0.07); border-radius: 2px; overflow: hidden; margin-bottom: 12px; }
.ctx-fill { height: 100%; width: ${pctFmt}%; background: $accentColor; border-radius: 2px; }
.divider { height: 1px; background: rgba(255,255,255,0.06); margin-bottom: 8px; }
.row { display: flex; align-items: center; gap: 7px; padding: 3px 0; }
.dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.lbl { flex: 1; font-size: 11px; opacity: 0.7; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.tok { font-size: 10px; opacity: 0.35; font-variant-numeric: tabular-nums; }
.pct-val { font-size: 11px; font-weight: 600; min-width: 36px; text-align: right; }
.note { margin-top: 10px; font-size: 10px; opacity: 0.3; }
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
$sessionSelectHtml
<div class="eyebrow">Token Usage</div>
<div class="chart-area">
  <div class="donut-wrap">
    <svg viewBox="0 0 100 100" width="100" height="100">
      <circle cx="50" cy="50" r="${"%.1f".format(r)}" fill="none" stroke="rgba(255,255,255,0.07)" stroke-width="16"/>
      $slices
    </svg>
    <div class="donut-centre">
      <span class="centre-pct">${pctFmt}%</span>
      <span class="centre-lbl">used</span>
    </div>
  </div>
  <div class="side-stats">
    <div class="side-total">${"%,d".format(data.total)}</div>
    <div class="side-sub">of ${"%,d".format(data.contextWindow)} tokens</div>
    <div class="side-sub" style="margin-top:4px">${data.components.size} components</div>
  </div>
</div>
<div class="ctx-wrap"><div class="ctx-fill"></div></div>
<div class="divider"></div>
$rows
$note
</body>
</html>"""
    }

    private fun loadingHtml() =
        """<!DOCTYPE html><html><head><link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet"></head><body style="padding:16px;font-family:'JetBrains Mono',monospace;color:#6f737a;background:#1e1f22">Loading token data...</body></html>"""

    private fun noSessionHtml() =
        """<!DOCTYPE html><html><head><link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet"></head><body style="padding:24px 16px;font-family:'JetBrains Mono',monospace;color:#6f737a;background:#1e1f22;text-align:center">No active session.<br>Start a Claude Code session<br>to view token usage.</body></html>"""

    private fun errorHtml(msg: String) =
        """<!DOCTYPE html><html><head><link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet"></head><body style="padding:16px;font-family:'JetBrains Mono',monospace;color:#e05555;background:#1e1f22">Failed to fetch token data:<br><pre style="margin-top:8px;font-size:11px;opacity:0.7">${msg.replace("<", "&lt;")}</pre></body></html>"""

    override fun dispose() {
        pollFuture?.cancel(false)
        jsQuery.dispose()
        Disposer.dispose(browser)
    }
}
