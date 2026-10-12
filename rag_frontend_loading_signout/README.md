# Loading and sign-out update

Apply after the palette/account update delivered previously. Extract at repository root:

```bash
python rag_frontend_loading_signout/apply.py --check
python rag_frontend_loading_signout/apply.py --apply
cd services/rag-web
npm test
npm run build
npm run dev
```

Stop the previous Vite process before restarting. The installer backs up changed files. No new dependencies, backend migration or env settings are required.

## Changes

- Lazy route bundles load login, chat, artifacts and administration as needed. The measured main production JS bundle decreased from about 454 KB (141 KB gzip) to about 255 KB (81 KB gzip). This is a bundle-size measurement, not a measured end-to-end latency improvement.
- Initial session restoration and route loading display a themed loading surface immediately.
- Simultaneous identical JSON GET requests share a single in-flight promise, reducing duplicate requests from mounts. Completed results are not cached, so subsequent history reads still fetch fresh server state. Caller-cancellable reads do not share a request. Reads are isolated by session epoch and cleared on session changes.
- Refresh is bounded to 12 seconds; finite JSON GET reads to 15 seconds and other JSON calls to 30 seconds. Document uploads and active SSE keep their existing cancellation policies. Raw login/signup requests remain unchanged.
- Clicking Sign out sets a global signingOut flag immediately. The whole application becomes inert to mouse/keyboard interaction, and a focused full-screen overlay shows an accent-colored orbit animation. It respects reduced motion.
- Double-clicks share the same logout task. New protected requests/refreshes are blocked during logout. An already-running refresh is allowed to settle before the logout call so the browser's rotated refresh cookie is used.
- The logout call itself is bounded to 10 seconds. If an earlier refresh is already pending, the total overlay wait can be up to roughly 22 seconds. A successful server response clears session and navigates to login. A timeout/failure removes the overlay and presents an error, leaving available session state for retry. A timed-out server operation may still finish remotely; the UI does not claim confirmed server logout in this situation.

## Backend latency

The reviewed auth implementation scans stored refresh-token hashes with bcrypt for both refresh and logout. As the candidate count grows, server processing can become slow. This update does not change that backend algorithm. Full page reload still needs server refresh and /users/me before protected content appears.

For persistent delays, open browser DevTools -> Network and record only the status and duration for:

- POST /api/v1/auth/browser/refresh
- GET /api/v1/users/me
- POST /api/v1/auth/browser/logout
- GET /api/v1/conversations
- GET /api/v1/conversations/<id>/messages

If auth dominates, a separate backend update should use an indexed opaque refresh-token identifier to locate one record, verify its secret, and rotate/revoke transactionally, with migration and compatibility for existing cookies. Do not bypass cookie revocation or store access/refresh tokens in localStorage to make the UI appear faster.

## Verify locally

1. Reload login and a saved chat. Confirm the loading surface appears immediately and session restoration completes or fails within its deadline.
2. Inspect Network for duplicate identical GET requests during mounts.
3. Click the avatar -> Sign out. Immediately try clicking the sidebar, typing, tabbing and dropping a file. Workspace controls should be inactive beneath the overlay.
4. Check successful logout reaches login and the old token cannot access protected backend routes.
5. Test a simulated offline logout. The overlay should stop with a retryable error, not claim successful server revocation.
6. Test the system reduced-motion preference.

Verification: strict TypeScript and production build passed; sixteen unit checks passed. The new checks validate deadlines, abort propagation and caller cancellation. Browser behavior and real backend latency need local verification. No local browser measurement is claimed.
