import { existsSync } from "node:fs";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const API_ORIGIN = "http://127.0.0.1:8477";
const HEALTH_URL = `${API_ORIGIN}/health`;
const META_URL = `${API_ORIGIN}/api/meta`;

function uvicornInvocation(): { command: string; args: string[] } {
  const venvUvicorn = path.join(ROOT, ".venv/bin/uvicorn");
  if (existsSync(venvUvicorn)) {
    return { command: venvUvicorn, args: ["app.main:app", "--port", "8477"] };
  }
  return {
    command: "python",
    args: ["-m", "uvicorn", "app.main:app", "--port", "8477"],
  };
}

async function waitForReplayReady(timeoutMs: number): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const [health, meta] = await Promise.all([fetch(HEALTH_URL), fetch(META_URL)]);
      if (health.ok && meta.ok) {
        const body = (await meta.json()) as { has_data?: boolean };
        if (body.has_data) return;
      }
    } catch {
      // Server still starting or first sweep not finished.
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`Replay API did not publish sweep data at ${META_URL}`);
}

/** Start uvicorn in replay mode frozen at a virtual race minute. */
export class ReplayServer {
  private proc: ChildProcessWithoutNullStreams | null = null;

  static async start(offsetMinutes: number): Promise<ReplayServer> {
    const server = new ReplayServer();
    await server.start(offsetMinutes);
    return server;
  }

  private async start(offsetMinutes: number): Promise<void> {
    if (this.proc) {
      await this.stop();
    }

    const { command, args } = uvicornInvocation();

    this.proc = spawn(command, args, {
      cwd: ROOT,
      env: {
        ...process.env,
        GAPIQ_PROVIDER: "replay",
        GAPIQ_IGNORE_ACTIVE_WINDOWS: "true",
        GAPIQ_ROSTER_FILE: "roster.zofingen-2025.json",
        GAPIQ_REPLAY_OFFSET_SECONDS: String(offsetMinutes * 60),
        GAPIQ_REPLAY_SPEED: "0",
      },
      stdio: "pipe",
    });

    this.proc.stderr.on("data", (chunk: Buffer) => {
      if (process.env.DEBUG_REPLAY_SERVER) {
        process.stderr.write(chunk);
      }
    });

    const exited = new Promise<never>((_, reject) => {
      this.proc?.once("exit", (code) => {
        reject(new Error(`Replay API exited with code ${code ?? "unknown"}`));
      });
    });

    await Promise.race([waitForReplayReady(45_000), exited]);
  }

  async stop(): Promise<void> {
    const proc = this.proc;
    this.proc = null;
    if (!proc) return;

    proc.kill("SIGTERM");
    await new Promise<void>((resolve) => {
      const timer = setTimeout(() => {
        proc.kill("SIGKILL");
        resolve();
      }, 5_000);
      proc.once("exit", () => {
        clearTimeout(timer);
        resolve();
      });
    });
  }
}
