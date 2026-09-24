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
    // Only a brand-new session gets the snapshot. A new session already holds
    // setup entries (model_change, thinking_level_change), so look for
    // conversation instead: any, including our own earlier message, means
    // resume or /reload, and the snapshot stays as it was.
    if (ctx.sessionManager.getEntries().some((e: { type: string }) => CONVERSATION.has(e.type))) return;
    let content = NO_UV;
    if (onPath("uv")) {
      const result = await pi.exec(
        "uv",
        ["run", "--quiet", "--frozen", "--no-dev", "--project", ROOT, "python", "-m", "spindle.context", "--wrap", "--harness", HARNESS],
        { timeout: 120_000 },
      );
      if (result.code !== 0 || !result.stdout.trim()) return;
      content = result.stdout.trim();
    }
    // With pi idle this appends straight to the session, ahead of the first prompt.
    pi.sendMessage({ customType: "spindle-index", content, display: false });
  });
}
