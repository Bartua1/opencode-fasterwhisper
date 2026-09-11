export declare const LOG_PREFIX = "[opencode-faster-whisper]";
export declare const MESSAGE_DIR: string;
export declare const POLL_INTERVAL_MS = 1000;
export declare const POLL_TIMEOUT_MS: number;
export declare const DEFAULT_WHISPER_MODEL: string;
export declare const DEFAULT_WHISPER_DEVICE: string;
export declare const DEFAULT_WHISPER_COMPUTE_TYPE: string;
export interface DeeplinkParams {
    agent: string;
    status: string;
    sessionId: string;
    summary: string;
    messageFile: string;
    responseFile: string;
    cwd?: string;
    project?: string;
    branch?: string;
    title?: string;
}
export declare enum EndReason {
    END_TURN = "end_turn",
    STOP = "stop"
}
//# sourceMappingURL=types.d.ts.map