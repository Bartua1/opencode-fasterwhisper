import { spawn, type ChildProcess } from "child_process"
import { existsSync } from "fs"
import { join } from "path"
import { homedir } from "os"

export interface DaemonListenParams {
  responseFile: string
  messageFile?: string
  summary?: string
  language?: string
  inputDevice?: string
}

export type DaemonLogFn = (
  level: "debug" | "info" | "warn" | "error",
  message: string,
) => void

export function findDaemonScript(cwd?: string): string | undefined {
  if (
    process.env.WHISPER_DAEMON_PATH &&
    existsSync(process.env.WHISPER_DAEMON_PATH)
  ) {
    return process.env.WHISPER_DAEMON_PATH
  }
  const candidates = [
    join(process.cwd(), "scripts", "whisper_daemon.py"),
    cwd ? join(cwd, "scripts", "whisper_daemon.py") : "",
    join(homedir(), ".config", "opencode", "scripts", "whisper_daemon.py"),
  ].filter(Boolean)

  for (const candidate of candidates) {
    if (existsSync(candidate)) return candidate
  }
  return undefined
}

export class WhisperDaemonManager {
  private proc: ChildProcess | null = null
  private scriptPath: string | undefined
  private log: DaemonLogFn
  private isReady = false
  private isBusy = false
  private restartCount = 0
  private maxRestarts = 3
  private intentionalStop = false

  constructor(cwd?: string, logFn?: DaemonLogFn) {
    this.scriptPath = findDaemonScript(cwd)
    this.log = logFn || (() => {})
  }

  public isAvailable(): boolean {
    return !!this.proc && !this.proc.killed && this.proc.exitCode === null
  }

  public start(): boolean {
    if (process.env.WHISPER_NO_DAEMON === "1" || process.env.WHISPER_NO_DAEMON === "true") {
      this.log("info", "Daemon disabled via WHISPER_NO_DAEMON environment variable")
      return false
    }

    if (!this.scriptPath) {
      this.log("info", "No whisper_daemon.py found; daemon mode unavailable")
      return false
    }

    if (this.isAvailable()) {
      return true
    }

    this.intentionalStop = false
    const pythonBin =
      process.env.PYTHON_BIN ||
      (process.platform === "win32" ? "python" : "python3")

    const daemonArgs = [
      this.scriptPath,
      "--parent-pid",
      String(process.pid),
    ]

    const model = process.env.WHISPER_MODEL
    if (model) daemonArgs.push("--model", model)

    const device = process.env.WHISPER_DEVICE
    if (device) daemonArgs.push("--device", device)

    const computeType = process.env.WHISPER_COMPUTE_TYPE
    if (computeType) daemonArgs.push("--compute-type", computeType)

    this.log(
      "info",
      `Starting background Whisper daemon: ${pythonBin} ${daemonArgs.join(" ")}`,
    )

    try {
      this.proc = spawn(pythonBin, daemonArgs, {
        stdio: ["pipe", "pipe", "pipe"],
        env: {
          ...process.env,
          PYTHONIOENCODING: "utf-8",
          PYTHONUNBUFFERED: "1",
        },
      })

      this.proc.stdout?.setEncoding("utf8")
      this.proc.stderr?.setEncoding("utf8")

      let stdoutBuffer = ""
      this.proc.stdout?.on("data", (chunk: string) => {
        stdoutBuffer += chunk
        const lines = stdoutBuffer.split("\n")
        stdoutBuffer = lines.pop() || ""

        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed) continue
          try {
            const data = JSON.parse(trimmed)
            if (data.status === "ready") {
              this.isReady = true
              this.log("info", `Whisper daemon model is warm in RAM (${data.model || "base"})`)
            } else if (data.status === "listening") {
              this.isBusy = true
            } else if (data.status === "transcribed" || data.status === "no_speech" || data.status === "cancelled" || data.status === "error") {
              this.isBusy = false
            }
          } catch {
            this.log("debug", `Daemon stdout: ${trimmed}`)
          }
        }
      })

      this.proc.stderr?.on("data", (chunk: string) => {
        const text = chunk.trim()
        if (text) {
          this.log("debug", text)
        }
      })

      this.proc.on("error", (err) => {
        this.log("error", `Whisper daemon spawn error: ${err}`)
      })

      this.proc.on("exit", (code, signal) => {
        this.log(
          "info",
          `Whisper daemon exited with code=${code} signal=${signal}`,
        )
        this.proc = null
        this.isReady = false
        this.isBusy = false

        if (!this.intentionalStop && this.restartCount < this.maxRestarts) {
          this.restartCount++
          this.log(
            "info",
            `Attempting daemon restart (${this.restartCount}/${this.maxRestarts})...`,
          )
          setTimeout(() => this.start(), 1500)
        }
      })

      // Clean teardown on parent exit
      const exitHandler = () => this.stop()
      process.once("exit", exitHandler)
      process.once("SIGINT", exitHandler)
      process.once("SIGTERM", exitHandler)

      return true
    } catch (err) {
      this.log("error", `Failed to spawn whisper daemon: ${err}`)
      return false
    }
  }

  public sendListen(params: DaemonListenParams): boolean {
    if (!this.isAvailable()) {
      this.log("warn", "Cannot send listen: daemon is not running")
      return false
    }

    try {
      const payload = {
        cmd: "listen",
        response_file: params.responseFile,
        message_file: params.messageFile,
        summary: params.summary,
        language: params.language,
        input_device: params.inputDevice,
      }
      this.proc?.stdin?.write(JSON.stringify(payload) + "\n")
      this.log("info", `Sent listen command to daemon (responseFile=${params.responseFile})`)
      return true
    } catch (err) {
      this.log("error", `Failed to write listen command to daemon: ${err}`)
      return false
    }
  }

  public cancel(): boolean {
    if (!this.isAvailable()) return false
    try {
      this.proc?.stdin?.write(JSON.stringify({ cmd: "cancel" }) + "\n")
      this.log("info", "Sent cancel command to daemon")
      return true
    } catch (err) {
      this.log("error", `Failed to send cancel to daemon: ${err}`)
      return false
    }
  }

  public stop(): void {
    this.intentionalStop = true
    if (!this.proc) return
    try {
      this.proc.stdin?.write(JSON.stringify({ cmd: "quit" }) + "\n")
      setTimeout(() => {
        try {
          if (this.proc && !this.proc.killed) {
            this.proc.kill()
          }
        } catch {}
      }, 500)
    } catch {
      try {
        this.proc.kill()
      } catch {}
    }
  }
}
