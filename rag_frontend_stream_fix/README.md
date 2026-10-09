# Stream completion fix

Extract at repository root, then run:

```bash
python rag_frontend_stream_fix/apply.py --check
python rag_frontend_stream_fix/apply.py --apply
cd services/rag-web
npm test
npm run build
npm run dev
```

Stop the existing Vite process with Ctrl+C before restarting. Refresh the browser after applying. No dependency, environment, database or backend changes are required. Existing overwritten files are backed up under frontend-backups/.

Changes:
- Stop consuming after a valid done/replay event instead of waiting for transport EOF.
- Apply the saved messages from the terminal event immediately.
- On transport interruption, check the exact known run ID and client message ID. Only authoritative saved completion counts as success.
- Preserve explicit server failure/cancellation errors.
- Distinguish a history refresh failure from a generation failure.
- Keep the submission locked until final synchronization completes.

Seven SSE parser tests and the TypeScript/production build passed. Live reproduction of your browser error was not possible here. This fixes a confirmed frontend completion-handling gap; it does not establish the precise network/backend cause of your incident.

Verify a new streamed message finishes without the generic error, reload preserves the same answer, and Stop still records cancellation. If the error persists, provide the stream request status, its final SSE event (event name and status/error code only), and any failed follow-up GET requests from browser DevTools Network. Do not share Authorization headers or cookies.
