/**
 * Parse a structured question answer response from Superwhisper.
 * Expected format: {"answers":[["label1"],["label2","label3"]]}
 * Fallback: treat as comma-separated labels, one answer per question.
 */
export declare function parseQuestionResponse(response: string): string[][];
/**
 * Normalize question data to Superwhisper's expected format (multiSelect, not multiple).
 */
export declare function normalizeQuestions(questions: any[]): any[];
/**
 * Normalise a raw permission reply string into the enum OpenCode expects.
 */
/**
 * Normalise a raw permission reply string into the enum OpenCode expects.
 * Accepts numeric indices (matching suggestion order), keywords, or full labels.
 * Suggestion order: 1=Allow, 2=Always Allow, 3=Bypass permissions, 4=Deny
 */
export declare function normalizePermissionReply(raw: string): "once" | "always" | "reject" | "bypass";
//# sourceMappingURL=normalize.d.ts.map