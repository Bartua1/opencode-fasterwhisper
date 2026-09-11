import { tmpdir } from "node:os"
import { join } from "node:path"

export const LOG_PREFIX = "[@superwhisper/opencode]"
export const MESSAGE_DIR =
  process.platform === "win32"
    ? join(tmpdir(), "superwhisper-agent")
    : "/tmp/superwhisper-agent"
export const POLL_INTERVAL_MS = 1_000
export const POLL_TIMEOUT_MS = 30 * 60 * 1_000

export interface DeeplinkParams {
  agent: string
  status: string
  sessionId: string
  summary: string
  messageFile: string
  responseFile: string
  cwd?: string
  project?: string
  branch?: string
  title?: string
}

export enum EndReason {
  END_TURN = "end_turn",
  STOP = "stop",
}
