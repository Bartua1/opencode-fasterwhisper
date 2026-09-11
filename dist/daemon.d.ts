export interface DaemonListenParams {
    responseFile: string;
    messageFile?: string;
    summary?: string;
    language?: string;
    inputDevice?: string;
}
export type DaemonLogFn = (level: "debug" | "info" | "warn" | "error", message: string) => void;
export declare function findDaemonScript(cwd?: string): string | undefined;
export declare class WhisperDaemonManager {
    private proc;
    private scriptPath;
    private log;
    private isReady;
    private isBusy;
    private restartCount;
    private maxRestarts;
    private intentionalStop;
    constructor(cwd?: string, logFn?: DaemonLogFn);
    isAvailable(): boolean;
    start(): boolean;
    sendListen(params: DaemonListenParams): boolean;
    cancel(): boolean;
    stop(): void;
}
//# sourceMappingURL=daemon.d.ts.map