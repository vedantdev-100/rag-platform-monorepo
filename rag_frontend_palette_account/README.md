# Palette, account menu and chat feedback

Apply after rag_frontend_ui_refinements from the previous delivery. Extract this ZIP at repository root:

```bash
python rag_frontend_palette_account/apply.py --check
python rag_frontend_palette_account/apply.py --apply
cd services/rag-web
npm test
npm run build
npm run dev
```

Stop Vite before restarting. The installer backs up changed files and preserves .env.local. No new libraries, backend code or database migrations are introduced.

## Included

- Accent #109E7D is used for button text/borders, the filled Send circle, focus borders and active upload glow.
- Dark chat background is #141414. Dark sidebar, modals and popovers are #0F0F0F. The existing light-mode option remains available with the same accent.
- The sidebar footer contains the user's name and an initials avatar. Its menu contains Profile, Settings and Sign out, and closes on outside click/Escape. Profile displays the signed-in account details; Settings controls the browser theme. These screens do not pretend to edit account properties without an update API.
- Submitting a question immediately renders its local user bubble with a sending state. Stream acknowledgement binds it to the real backend message/run IDs. Saved history replaces the temporary bubble, so completion does not duplicate the question. An unaccepted failed submission remains marked failed while on the page.
- Streaming text catches up over a few animation frames while preserving every character. It does not delay the network stream or final validated answer, and follows the system reduced-motion preference.
- Citation failure messages explain why the answer was rejected instead of showing only invalid_citations.

## Citation errors

The reviewed backend requires a normal generated answer to include at least one reference matching [S1], [S2], etc. Every referenced label must occur among the sources supplied for that answer. Missing labels, mismatched syntax or invented labels such as [S9] cause invalid_citations. The exact INSUFFICIENT_CONTEXT abstention is handled separately. This is a structural reference check, not proof that every claim is supported by its cited excerpt.

A streamed answer is provisional until validation. It may appear briefly and then be rejected; rejected assistant text must not be treated as a completed answer. Send a NEW message to retry generation; replaying the same client_message_id returns the existing failed run rather than regenerating it. Select relevant ingested documents and ask a focused question. If failures persist, preserve the run ID and check backend generation logs/model behavior; do not disable validation or add artificial source labels in the frontend.

## Increase uploads: example 50 MiB

In services/rag-service/.env:

```dotenv
RAG_MAX_UPLOAD_MB=50
```

The worker reads that same service .env. Its parser also checks this limit, so recreate both API and worker.

In docker-compose.docling.yml, update the docling-serve environment entry:

```yaml
DOCLING_SERVE_MAX_FILE_SIZE: "52428800"
```

The value is bytes: 50 * 1024 * 1024. The previous reviewed configuration was 26214400 (25 MiB).

After active uploads/generation finish, from repository root:

```bash
source scripts/dc-step12.sh
dc12 config --quiet
dc12 up -d --force-recreate docling-serve rag-service rag-worker
dc12 ps
dc12 exec rag-service python -c "from app.core.config import get_settings; print(get_settings().RAG_MAX_UPLOAD_MB)"
dc12 exec rag-worker python -c "from app.core.config import get_settings; print(get_settings().RAG_MAX_UPLOAD_MB)"
```

Both printed limits should be 50. Wait for Docling and application services to become healthy before testing a new upload. No image rebuild is needed for these environment changes.

If your deployment has a reverse proxy, increase its request-body limit too. The supplied direct localhost setup does not have a frontend byte-size cap beyond rejecting empty/unsupported files. Larger files increase memory use and processing time; an increased byte limit does not remove parser timeouts or other resource constraints.

## Verify locally

1. Enable dark mode: inspect the chat/sidebar/modal palette and Send circle.
2. Open the avatar menu, Profile and Settings; dismiss each outside or with Escape. Verify Sign out ends the session.
3. Send a question and verify the user bubble appears before the provider starts responding. Confirm completion and reload do not duplicate it.
4. Try a network failure and recovery with the same submission ID. Confirm the failed/pending question remains identifiable.
5. Observe streaming text and then the final saved answer. Try the system reduced-motion setting.
6. Upload a document and verify the green accent glow stops when ready or failed.

Verification: TypeScript/production build and 13 unit checks passed. The added checks cover Unicode-safe stream convergence and avatar initials; previous stream, selection and title checks remain. Browser/live-provider behavior still needs your local verification.
