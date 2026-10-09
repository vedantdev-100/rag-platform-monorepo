export const config = {
 rag: (import.meta.env.VITE_RAG_BASE_URL || 'http://localhost:8000').replace(/\/$/, ''),
 auth: (import.meta.env.VITE_AUTH_BASE_URL || 'http://localhost:8001').replace(/\/$/, ''),
 prefix: (import.meta.env.VITE_API_PREFIX || '/api/v1').replace(/\/$/, ''),
}
for (const base of [config.rag,config.auth]) { if (!['http:','https:'].includes(new URL(base).protocol)) throw new Error('Invalid API URL') }
