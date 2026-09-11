export declare function extractFullText(message: any): string;
/**
 * Determine if a turn has truly ended. We do not want to prompt the user
 * with tool-calls that trigger session.idle.
 */
export declare function isEndTurn(message: any): boolean;
export declare function extractSummary(text: string): string;
//# sourceMappingURL=message.d.ts.map