import { useEffect,useRef,useState } from 'react'
import { documentApi } from '../api/documents'
import type { Document } from '../types'
import type { Conversation } from '../../chat/types'
import { chatApi } from '../../chat/api/chat'
import { consumeSSE } from '../../../shared/api/sse'
import { explain } from '../../../shared/errors/errors'
export function DocumentPanel({conversation,onChange,disabled}:{conversation:Conversation;onChange:(c:Conversation)=>void;disabled:boolean}){
 const [docs,setDocs]=useState<Document[]>([]);const [more,setMore]=useState(false);const [busy,setBusy]=useState(false);const [status,setStatus]=useState('');const [error,setError]=useState('');const alive=useRef(true);const stream=useRef<AbortController|null>(null)
 async function list(offset=0){const r=await documentApi.list(offset);if(!alive.current)return;setDocs(old=>offset?[...old,...r.documents]:r.documents);setMore(r.documents.length===50)}
 useEffect(()=>{alive.current=true;list().catch(e=>setError(explain(e)));return()=>{alive.current=false;stream.current?.abort()}},[])
 async function select(documentId?:string,all?:boolean){setBusy(true);setError('');try{
 const fresh=await chatApi.get(conversation.id);const ids=new Set(fresh.document_ids??[])
 if(documentId){if(ids.has(documentId))ids.delete(documentId);else ids.add(documentId)}
 const updated=await chatApi.select(conversation.id,all?'all_owner':'selected',all?[]:[...ids]);if(alive.current)onChange(updated)
 }catch(e){if(alive.current)setError(explain(e))}finally{if(alive.current)setBusy(false)}}
 async function upload(file:File){setBusy(true);setError('');setStatus('Uploading…');try{
 const doc=await documentApi.upload(file);if(!alive.current)return;setStatus('Processing '+file.name)
 const ac=new AbortController();stream.current=ac;let terminal=false
 try{await consumeSSE(await documentApi.events(doc.id,ac.signal),({event,data})=>{const d=data as Document;if(event==='error')throw new Error('Status stream interrupted');if(d.status&&alive.current)setStatus(d.status);if(event==='done')terminal=true})}catch(e){if(ac.signal.aborted)throw e;/* Read authoritative status if stream failed. */}
 if(!alive.current)return
 const final=await documentApi.status(doc.id)
 if(final.status==='ingested'){
 const fresh=await chatApi.get(conversation.id)
 if(fresh.document_scope==='selected'){const updated=await chatApi.select(conversation.id,'selected',[...new Set([...(fresh.document_ids??[]),doc.id])]);if(alive.current)onChange(updated)}
 setStatus('Ready · added to this conversation')
 }else if(final.status==='failed'){setError('Ingestion failed. Check the document and retry the upload.')}else{setStatus('Still processing. Refresh the document list and select it when ready.'+(terminal?'':''))}
 await list()
 }catch(e){if(alive.current)setError(explain(e))}finally{if(alive.current)setBusy(false)}}
 return <section className="document-panel"><div className="row"><h2>Documents</h2><button disabled={busy} onClick={()=>list().catch(e=>setError(explain(e)))}>Refresh</button></div><p className="muted small">Choose the evidence for this conversation.</p>
 <label className="check"><input type="checkbox" checked={conversation.document_scope==='all_owner'} disabled={busy||disabled} onChange={e=>void select(undefined,e.target.checked)}/>All my ingested documents</label>
 <label className="upload">{busy?'Working…':'＋ Upload document'}<input type="file" disabled={busy||disabled} accept=".pdf,.docx,.pptx,.html,.htm,.md,.txt" onChange={e=>{const f=e.target.files?.[0];if(f)void upload(f);e.target.value=''}}/></label>
 <div role="status" className="small muted">{status}</div>{error&&<p className="error" role="alert">{error}</p>}
 <div className="document-list">{docs.map(d=><label className="check" key={d.id}><input type="checkbox" disabled={busy||disabled||d.status!=='ingested'||conversation.document_scope==='all_owner'} checked={conversation.document_scope==='all_owner'?d.status==='ingested':!!conversation.document_ids?.includes(d.id)} onChange={()=>void select(d.id)}/><span>{d.title}<small>{d.status}</small></span></label>)}</div>
 {more&&<button disabled={busy} onClick={()=>list(docs.length).catch(e=>setError(explain(e)))}>Load more documents</button>}
 <p className="muted small">Selection changes are saved immediately. Use one tab when editing a chat’s selection.</p></section>
}
