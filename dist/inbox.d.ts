export interface InboxPayload {
    kind: "update" | "dismiss";
    sessionId?: string;
    requestId?: string;
    agent?: string;
    status?: string;
    summary?: string;
    message?: string;
    messageFile?: string;
    responseFile?: string;
    cwd?: string;
    project?: string;
    branch?: string;
    title?: string;
    hookPid?: number;
}
export declare function __setInboxDirForTest(dir: string): void;
export declare function writeInboxPayload(payload: InboxPayload): boolean;
export declare function isSuperwhisperRunning($: any): Promise<boolean>;
export declare function fireAgentWake(scheme: string, $: any): Promise<void>;
export declare function deliverAgentPayload(payload: InboxPayload, scheme: string, $: any): Promise<boolean>;
//# sourceMappingURL=inbox.d.ts.map