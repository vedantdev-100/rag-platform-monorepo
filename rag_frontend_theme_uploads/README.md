# Dark mode and chat uploads

Extract at your repository root and run:

```bash
python rag_frontend_theme_uploads/apply.py --check
python rag_frontend_theme_uploads/apply.py --apply
cd services/rag-web
npm test
npm run build
npm run dev
```

Stop the previous Vite process before restarting. The preview lists overwritten files; the installer backs them up under frontend-backups/. No new dependencies, backend changes or environment changes are required. The earlier stream-completion fix is included.

## Features

- Light/dark toggle in the workspace sidebar and on login/signup. First visit uses the system preference. A chosen mode persists in browser localStorage; no chat content or tokens are stored there.
- Drag multiple supported files anywhere over an existing chat. Dropping onto the new-chat page creates a conversation and queues its files.
- A + button on the left side of the composer opens a multiple-file picker, opposite Send on the right.
- Upload cards show queued, uploading, processing, attaching, ready and failed states. No fabricated percentage is shown.
- Documents are processed sequentially and automatically appended to the latest selected list after ingestion. Existing IDs are preserved and deduplicated. In all-owner mode newly ingested files are already in scope, so no individual links are needed.
- You can type while uploads are pending. Sending waits until this conversation's queued uploads finish. Uploading is blocked during active generation or in archived conversations.
- Uploads continue when closing the Documents panel or switching conversations within the app. Progress is retained per conversation in memory. Signing out clears the queue and aborts active upload/status observation; it cannot undo an upload already accepted by the backend.
- SSE observes ingestion; interrupted status streams fall back to polling. After a long wait, a card offers Check status / attach again. This reuses the accepted document ID rather than uploading a second copy.

## Verify locally

1. Switch dark mode, open a citation dialog and the Documents panel, then refresh. Confirm the preference persists.
2. Open a chat that already has selected documents. Use + to upload two supported files. Observe sequential progress and ready cards. Confirm previous document selections remain.
3. Drag a file over the message area; the drop overlay should appear. Drop it and verify ingestion and automatic attachment.
4. Drop a file onto /chat without an existing conversation; verify a new dynamic chat URL is created.
5. Close the Documents panel or switch chats during ingestion, then return. Confirm the cards and selected documents update.
6. Try an empty/unsupported file. Confirm a readable error appears without an upload. Dismiss the card.
7. If selection fails for an accepted document, use Check status / attach again after resolving the cause.
8. Send a question after ingestion and check that the answer can cite the new document.

## Limits

The queue survives client-side navigation, not a browser reload or closing the tab. An accepted backend upload continues after reload, but its frontend attachment step may not have run: use Documents -> Refresh and select that file if needed. Unknown upload outcomes are not automatically retried, avoiding duplicate uploads. The backend's replace-only selection API still requires one tab at a time for editing a conversation's selected document set.

Progress/filename state is in memory only. A failed ingestion may require a corrected file and new upload. The status/attach retry button does not restart the worker's failed ingestion job.

Validation: TypeScript, Vite production build and nine unit checks passed. Checks cover the stream parser, terminal stream handling, file validation and selection merging. Browser/live-backend verification and visual inspection remain local because a browser binary was unavailable here.
