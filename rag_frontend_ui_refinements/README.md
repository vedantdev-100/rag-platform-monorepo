# Frontend UI refinements

Apply this update after the frontend setup, stream fix and dark-mode/upload update already delivered. No additional libraries are used.

Extract the ZIP at your repository root, then run:

```bash
python rag_frontend_ui_refinements/apply.py --check
python rag_frontend_ui_refinements/apply.py --apply
cd services/rag-web
npm test
npm run build
npm run dev
```

Stop an existing Vite process with Ctrl+C before restarting, then refresh the browser. The installer backs up overwritten files under frontend-backups/. It preserves .env.local and unrelated files. No backend deployment or migration is required.

## Included changes

1. Native rename prompts and delete confirmations have been replaced with dedicated modals. Source excerpts and artifact details use the same modal component. Inline API error messages remain inline.
2. Modals close on a backdrop click or Escape. Sidebar action menus and file popovers dismiss on outside click, Escape, or focus moving elsewhere. A click inside the surface does not dismiss it.
3. On the first new question, a conversation still named New chat is assigned a title of up to 44 Unicode characters, with whitespace normalized, word boundaries preferred and an ellipsis where needed. The frontend saves this title through PATCH /conversations/{id} before submitting the turn and updates the sidebar. Manually chosen names and existing chats are preserved.
4. Active upload cards have a subtle cyan border glow during queueing, upload, processing and attachment. The animation respects reduced-motion settings and stops when ready or failed.
5. A top-left toggle collapses/expands the primary sidebar on desktop. On mobile it opens an overlay; tapping outside closes it. New navigation closes the mobile sidebar.
6. The conversation title and old header have been removed from the chat top.
7. Artifacts appears directly below New chat in the sidebar and opens /artifacts, listing your owned documents, statuses and details. Search covers loaded pages; Load more fetches additional pages.
8. A floating Chat files picker sits at the top-right. The composer + button opens the same picker. Section 1 lists available documents; selecting one moves it to Section 2, In this conversation. Section 2 includes existing selections and pending uploads. Upload from device accepts multiple files. Successful ingestion automatically attaches files while preserving current selections.

Both file pickers operate on the same backend conversation selection. Removing a document from Section 2 removes its link to that chat; it does not delete the document. All-owner mode includes all owned ingested documents, including future uploads. Individual selection changes are unavailable until switching back to selected mode.

## Local checks

- Open a sidebar three-dot menu, then click elsewhere and verify it closes. Open Rename, edit a title and save; inspect the saved title via the API. Open Delete and dismiss it outside without deleting anything.
- Toggle the sidebar on a wide window, then try it on mobile. Click the mobile backdrop to close it.
- Confirm there is no title/header above the messages. Open Artifacts under New chat and inspect a document's details.
- In a new chat, submit a long first question. Confirm the sidebar title is short, the backend title matches it, and reload preserves it. Verify an existing custom name is not replaced.
- Open the top-right Chat files picker, select an existing ingested file and verify it moves to Section 2. Remove it and verify it returns to Section 1 without deleting it.
- Open the composer + picker and verify it shows the same selection. Upload a file, watch its card and cyan glow, then verify it appears selected once ready.
- Check the picker, modals and upload glow in both themes. Verify Escape and outside-click dismissal.

## Notes

The frontend names chats created through this UI using the existing backend rename API. Direct Postman/API turns still use the backend's existing naming behavior. Old chat titles are not rewritten.

The previous upload limits remain: the queue survives in-app navigation but not a page reload. Accepted uploads continue in the backend; after reload, use the picker to select a completed file if attachment had not finished. Use one tab at a time for changing a conversation's selection because the backend currently replaces the full list.

## Verification

Strict TypeScript and the production Vite build passed. Eleven unit checks passed, including stream completion, upload validation, selection merging and Unicode-aware title shortening. Native alert/confirm/prompt calls are absent from the frontend. Browser interaction and visual verification remain local; a browser binary was unavailable in the execution environment.

## Rollback

Restore REPLACED files from the installer backup and remove only ADDED files listed in its manifest.txt. Restart Vite. This update does not change backend data beyond ordinary user-triggered chat title and document-selection API requests.
