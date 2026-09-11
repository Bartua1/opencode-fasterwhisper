import { mkdirSync, writeFileSync, renameSync, unlinkSync } from "fs"
import { randomUUID } from "crypto"
import { homedir } from "os"
import { join } from "path"

export interface InboxPayload {
  kind: "update" | "dismiss"
  sessionId?: string
  requestId?: string
  agent?: string
  status?: string
  summary?: string
  message?: string
  messageFile?: string
  responseFile?: string
  cwd?: string
  project?: string
  branch?: string
  title?: string
  hookPid?: number
}

function getDefaultInboxDir(): string {
  if (process.platform === "win32") {
    const appData =
      process.env.APPDATA || join(homedir(), "AppData", "Roaming")
    return join(appData, "superwhisper", "agent", "inbox")
  }
  return join(
    homedir(),
    "Library/Application Support/superwhisper/agent/inbox",
  )
}

let INBOX_DIR = getDefaultInboxDir()

export function __setInboxDirForTest(dir: string): void {
  INBOX_DIR = dir
}

export function writeInboxPayload(payload: InboxPayload): boolean {
  try {
    mkdirSync(INBOX_DIR, { recursive: true })
  } catch {
    return false
  }

  const base = randomUUID()
  const tmpPath = join(INBOX_DIR, `${base}.json.tmp`)
  const finalPath = join(INBOX_DIR, `${base}.json`)

  try {
    writeFileSync(tmpPath, JSON.stringify(payload))
    renameSync(tmpPath, finalPath)
    return true
  } catch {
    try {
      unlinkSync(tmpPath)
    } catch {}
    return false
  }
}

export async function isSuperwhisperRunning($: any): Promise<boolean> {
  try {
    if (process.platform === "win32") {
      const result = await $`tasklist /FI "IMAGENAME eq superwhisper.exe" /NH`.quiet()
      const text =
        typeof result?.text === "function"
          ? await result.text()
          : (result?.stdout?.toString() ?? "")
      return text.toLowerCase().includes("superwhisper")
    }
    const result = await $`pgrep -x superwhisper`.quiet()
    return result.exitCode === 0
  } catch {
    return false
  }
}

export async function fireAgentWake(scheme: string, $: any): Promise<void> {
  const url = `${scheme}://agent-wake`
  try {
    if (process.platform === "win32") {
      await $`cmd.exe /c start "" ${url}`.quiet()
    } else if (process.platform === "darwin") {
      await $`open ${url}`.quiet()
    } else {
      await $`xdg-open ${url}`.quiet()
    }
  } catch {
    // wake is best-effort
  }
}

export async function deliverAgentPayload(
  payload: InboxPayload,
  scheme: string,
  $: any,
): Promise<boolean> {
  const wrote = writeInboxPayload(payload)
  const running = await isSuperwhisperRunning($)
  if (!running) {
    await fireAgentWake(scheme, $)
  }
  return wrote
}
