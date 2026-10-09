# RAG frontend setup

Complete standalone React/Vite project for services/rag-web, targeting the conversation backend delivered in this conversation. No backend files are changed.

## 1. Apply

Extract this ZIP at your repository root. It creates rag_frontend_update/ without immediately overwriting the frontend. From your repo root, in Git Bash or WSL:

```bash
python rag_frontend_update/apply.py --check
python rag_frontend_update/apply.py --apply
cd services/rag-web
node --version
npm ci
```

Use Node 22.18+ or Node 24+. Node 24 was used for verification. Dependencies are pinned with a lockfile. No additional application libraries beyond the agreed stack were added.

The installer backs up overwritten files under frontend-backups/<timestamp>. Review the preview if you made further frontend edits. It preserves .env.local, unrelated files and backends. Repeat application is safe. Unused original Vite src/App.tsx, src/App.css and src/index.css may remain: the entry point now imports src/app/App.tsx and styles/globals.css.

## 2. Configuration

Keep your existing .env.local. If absent:

```bash
cp .env.example .env.local
```

```dotenv
VITE_RAG_BASE_URL=http://localhost:8000
VITE_AUTH_BASE_URL=http://localhost:8001
VITE_API_PREFIX=/api/v1
```

Open http://localhost:5173. Use localhost consistently, not a mix with 127.0.0.1. Restart Vite after env edits. Never put provider keys in VITE_* variables.

Allowed origins are already configured. Confirm auth allows credentials from this origin and Authorization/Content-Type headers. Local HTTP uses AUTH_BROWSER_COOKIE_SECURE=false; production HTTPS uses true. The current SameSite=Lax cookie requires same-site UI/auth hosting; unrelated domains require a separately reviewed cookie and CSRF arrangement.

## 3. Run

```bash
npm run typecheck
npm test
npm run build
npm run dev
```

Tests use Node's built-in runner. Use typecheck instead of the original scaffold lint script; this package does not include an ESLint policy.

## 4. Verify locally

1. Open /signup, register, then sign in. Signup goes to login; it does not assume registration returns tokens.
2. Start a chat. Its URL becomes /chat/<backend UUID>.
3. Open Documents and upload atlas_generation.txt. Watch ingestion status. Once ingested, the frontend fetches current selection, appends the ID and sends the full list. All-owner mode needs no link update.
4. Ask “Who owns Atlas?”. Verify provisional streamed text becomes a saved validated answer.
5. Ask a follow-up; confirm history is used by the backend.
6. Click S1 to load an authenticated source excerpt.
7. Refresh or open the deep link in another tab; saved messages load after session restoration.
8. Create a second chat; verify message and document isolation.
9. Click Stop during generation and inspect the saved run. Navigating away aborts streaming under the backend cancel-on-disconnect policy.
10. Disconnect during generation. Partial text is discarded. Reconnect and select Recover last submission: the original UUID and body are reused. It does not resume individual tokens. Pending runs are polled after reload.
11. Rename, archive, restore and delete test chats using the sidebar menu. Chat deletion preserves documents.
12. Sign out; protected URLs redirect to login.
13. Sign in as admin to see Users. A regular user gets Access restricted at /admin/users.

## Behavior and limitations

- Browser login/refresh/logout endpoints are used. Access tokens are in memory only; refresh tokens remain in HttpOnly cookies. Concurrent 401 responses in one tab share a refresh request.
- Backend authorization remains mandatory. The admin route guard is only a UI control.
- The admin screen intentionally shows no invented users or API: the all-users endpoint is not available yet.
- Selection updates fetch and send the full list. The replace-only API cannot prevent concurrent edits across tabs/devices; use one tab per chat for selection changes. Atomic backend add/remove endpoints would resolve this.
- Upload one file at a time and keep the document panel open until completion. Closing it stops status observation, not the accepted backend upload. Reopen, refresh and select completed documents if necessary.
- If document SSE fails, authoritative status is fetched once. For a still-processing document, refresh later and select it when ready.
- Uploads are not automatically retried; an uncertain response could otherwise duplicate a document.
- Retry UUIDs are in memory. Reload recovers saved messages and pending run status, but cannot recover a previously unacknowledged UUID that was never persisted locally.
- Cross-tab refresh-token rotation coordination is not implemented; simultaneous refreshes may require signing in again.
- API failures appear near the action. Render failures show a reload fallback. Diagnostic logs contain only area/status/time, not tokens, documents or chat content. No external logging service is used.
- Markdown does not render raw HTML. Remote images are replaced with text. Links open with noopener/noreferrer.
- Citations are clickable chips. Syntax highlighting, drag/drop, document deletion UI and editing/regenerating messages are not included.
- RAG evaluation endpoints and backend generation behavior remain unchanged.

## Architecture

src/app composes guards, routes and layout. Features auth, chat, documents and admin own their API adapters, types, components, hooks and screens. Zustand manages session and conversation-list state. Local state handles forms, dialogs and transient streaming text. Empty feature folders are extension points.

shared/api contains HTTP, coordinated token refresh and SSE parsing. shared/errors contains normalization and the render boundary. shared/logging holds sanitized diagnostics. config/env.ts owns API configuration.

Chat screens are keyed by conversation ID. Leaving a chat aborts its stream so late events do not update another chat. done and replay fetch the saved backend messages and clear provisional text. EOF without a terminal event is interrupted, not successful.

## Production

```bash
npm ci
npm run build
```

Serve dist/ with an SPA fallback so deep links work. For Nginx: `try_files $uri $uri/ /index.html;`. Set production URLs before building; Vite embeds public env values. This delivery does not deploy or change Docker Compose.

## Rollback

Stop Vite. Restore REPLACED files from the installer backup and remove only ADDED files listed in manifest.txt. Run npm ci with the restored lockfile. Backend data and .env.local are untouched.

## Verification

Strict TypeScript and production Vite build passed. Five SSE parser tests passed (fragmented CRLF/heartbeat, incomplete events, multiline data, malformed JSON, consumer errors). Installer checks cover preview, repeat application, backups and env preservation.

Headless browser testing could not run because the browser download failed in this environment. No live backend, browser authentication, provider generation or visual QA is claimed. Run the local checklist before rollout.
