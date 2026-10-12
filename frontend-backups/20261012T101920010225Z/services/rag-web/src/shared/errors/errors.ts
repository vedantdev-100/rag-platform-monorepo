export class ApiError extends Error {
 constructor(public status: number, public code: string) { super(code) }
}
export function explain(e: unknown): string {
 if (e instanceof ApiError) {
  if (e.code === 'invalid_citations') return 'The answer did not include valid references to the retrieved sources. Send a new message to try again.'
  if (e.status === 401) return 'Your session expired. Please sign in again.'
  if (e.status === 403) return 'You do not have permission for this action.'
  if (e.status === 404) return 'This item is unavailable or has been deleted.'
  if (e.status === 429) return 'Too many requests. Please wait and try again.'
  return e.code.replaceAll('_',' ')
 }
 return e instanceof Error && e.name === 'AbortError' ? 'Request stopped.' : 'Unable to complete the request. Check your connection and try again.'
}
