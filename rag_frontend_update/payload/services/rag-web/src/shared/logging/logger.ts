// Deliberately excludes bodies, URLs, tokens, document content and exception messages.
export function logFailure(area: string, status?: number) {
 console.warn('[rag-web]', {area, status, time: new Date().toISOString()})
}
