import { describe, it, expect, afterEach } from "bun:test"
import { WhisperDaemonManager, findDaemonScript } from "./daemon.js"

describe("WhisperDaemonManager", () => {
  let daemon: WhisperDaemonManager | null = null

  afterEach(() => {
    if (daemon) {
      daemon.stop()
      daemon = null
    }
  })

  it("finds daemon script", () => {
    const script = findDaemonScript()
    expect(script).toBeDefined()
    expect(script).toContain("whisper_daemon.py")
  })

  it("spawns and terminates cleanly", async () => {
    daemon = new WhisperDaemonManager()
    const started = daemon.start()
    expect(started).toBe(true)
    expect(daemon.isAvailable()).toBe(true)

    daemon.stop()
    await new Promise((r) => setTimeout(r, 600))
    expect(daemon.isAvailable()).toBe(false)
  })

  it("sends listen command without error", async () => {
    daemon = new WhisperDaemonManager()
    daemon.start()

    const sent = daemon.sendListen({
      responseFile: "/tmp/test-daemon-response.txt",
      language: "es",
    })
    expect(sent).toBe(true)

    // Cancel to avoid keeping recording
    daemon.cancel()
  })
})
