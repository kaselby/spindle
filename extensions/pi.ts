/**
 * Spindle for pi (and omp, which reads the same package.json manifest).
 *
 * - Puts this plugin's bin/ on PATH, so the bash tool can run `thread`.
 *   pi's bash tool builds its environment from process.env on every call.
 * - Injects the thread-store snapshot once, as the first message of a new
 *   session, wrapped in <system-reminder> tags. It is never refreshed: not on
 *   resume, /reload, or after compaction.
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { spawn } from "node:child_process";
import { accessSync, constants } from "node:fs";
import { delimiter, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

// omp loads this same package; its standing instructions live somewhere else (see spindle/setup.py).
const HARNESS = process.title === "omp" || (process.argv[1] ?? "").includes("oh-my-pi") ? "omp" : "pi";
const CONVERSATION = new Set(["message", "custom_message", "compaction", "branch_summary"]);
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const NO_UV =
  "<system-reminder>\nSpindle is installed but can't run: it needs uv (https://docs.astral.sh/uv/). " +
  "Install it with: curl -LsSf https://astral.sh/uv/install.sh | sh\n</system-reminder>";
// pi waits for session_start handlers before the session begins, so the snapshot
// must never wait on the network or run long. --offline makes uv use only what is
// already installed or cached; the first `thread` command (online) finishes setup.
const SNAPSHOT_TIMEOUT_MS = 10_000;
const NOT_READY =
  "<system-reminder>\nSpindle's thread snapshot couldn't be built at session start, so no thread list " +
  "is shown here. If Spindle was just installed, it is finishing its install in the background (this " +
  "needs network access) and the next session will have the list; if it hasn't been set up yet, suggest " +
  "the spindle-setup skill to the user. `thread list` works now and shows the active threads.\n</system-reminder>";

/** Usually a fresh install: build the environment in the background, online, so the
 * next session has it. Detached, so session start never waits on it. */
function buildInBackground() {
  try {
    spawn("uv", ["sync", "--quiet", "--frozen", "--no-dev", "--project", ROOT], {
      detached: true,
      stdio: "ignore",
    }).unref();
  } catch {}
}

function onPath(name: string): boolean {
  for (const dir of (process.env.PATH ?? "").split(delimiter)) {
    if (!dir) continue;
    try {
      accessSync(join(dir, name), constants.X_OK);
      return true;
    } catch {}
  }
  return false;
}

/**
 * The harness session for `thread` (see src/spindle/identity.py): <harness>-<last 8
 * of the session id>, set on every session_start (new, resume, fork). pi and omp
 * don't export their session id, so the extension does. Kiln and THREAD_SESSION
 * outrank it there. The end of the id, not the start: pi and omp use UUIDv7,
 * which begins with a timestamp.
 */
function setHarnessSession(sessionId: string | undefined) {
  const hex = (sessionId ?? "").replace(/-/g, "");
  if (hex) process.env.SPINDLE_HARNESS_SESSION = `${HARNESS}-${hex.slice(-8)}`;
}

export default function spindle(pi: ExtensionAPI) {
  const bin = join(ROOT, "bin");
  const path = process.env.PATH ?? "";
  if (!path.split(delimiter).includes(bin)) process.env.PATH = path ? `${bin}${delimiter}${path}` : bin;

  pi.on("session_start", async (_event, ctx) => {
    setHarnessSession(ctx.sessionManager.getSessionId());
    if (ctx.cwd) process.env.SPINDLE_PROJECT = ctx.cwd; // the launch folder, for project-scoped stores
    // Only a brand-new session gets the snapshot. A new session already holds
    // setup entries (model_change, thinking_level_change), so look for
    // conversation instead: any, including our own earlier message, means
    // resume or /reload, and the snapshot stays as it was.
    if (ctx.sessionManager.getEntries().some((e: { type: string }) => CONVERSATION.has(e.type))) return;
    let content = NO_UV;
    if (onPath("uv")) {
      const result = await pi.exec(
        "uv",
        ["run", "--offline", "--quiet", "--frozen", "--no-dev", "--project", ROOT, "python", "-m", "spindle.context", "--wrap", "--harness", HARNESS],
        { timeout: SNAPSHOT_TIMEOUT_MS },
      );
      // Check killed first: pi reports a process killed by the timeout as code 0.
      const ok = result.code === 0 && !result.killed;
      // Empty output with success means there is nothing to say (no store, setup done).
      if (ok && !result.stdout.trim()) return;
      content = ok ? result.stdout.trim() : NOT_READY;
      if (!ok) buildInBackground();
    }
    // With pi idle this appends straight to the session, ahead of the first prompt.
    pi.sendMessage({ customType: "spindle-index", content, display: false });
  });
}
