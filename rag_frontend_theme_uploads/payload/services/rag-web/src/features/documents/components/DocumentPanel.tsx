import { useEffect,useRef,useState } from 'react'
import { documentApi } from '../api/documents'
import type { Document } from '../types'
import type { Conversation } from '../../chat/types'
import { chatApi } from '../../chat/api/chat'

import { explain } from '../../../shared/errors/errors'
export function DocumentPanel({conversation,onChange,disabled,onUpload}:{conversation:Conversation;onChange:(c:Conversation)=>void;disabled:boolean;onUpload:(files:File[])=>void}){
 const [docs,setDocs]=useState<Document[]>([]);const [more,setMore]=useState(false);const [busy,setBusy]=useState(false);const [error,setError]=useState('');const alive=useRef(true)
 async function list(offset=0){const r=await documentApi.list(offset);if(!alive.current)return;setDocs(old=>offset?[...old,...r.documents]:r.documents);setMore(r.documents.length===50)}
 useEffect(()=>{alive.current=true;list().catch(e=>setError(explain(e)));return()=>{alive.current=false}},[])
 async function select(documentId?:string,all?:boolean){setBusy(true);setError('');try{
 const fresh=await chatApi.get(conversation.id);const ids=new Set(fresh.document_ids??[])
 if(documentId){if(ids.has(documentId))ids.delete(documentId);else ids.add(documentId)}
 const updated=await chatApi.select(conversation.id,all?'all_owner':'selected',all?[]:[...ids]);if(alive.current)onChange(updated)
 }catch(e){if(alive.current)setError(explain(e))}finally{if(alive.current)setBusy(false)}}
 return <section className="document-panel"><div className="row"><h2>Documents</h2><button disabled={busy} onClick={()=>list().catch(e=>setError(explain(e)))}>Refresh</button></div><p className="muted small">Choose the evidence for this conversation.</p>
 <label className="check"><input type="checkbox" checked={conversation.document_scope==='all_owner'} disabled={busy||disabled} onChange={e=>void select(undefined,e.target.checked)}/>All my ingested documents</label>
 <label className="upload">{busy?'Working…':'＋ Upload document'}<input type="file" disabled={busy||disabled} accept=".pdf,.docx,.pptx,.html,.htm,.md,.txt" onChange={e=>{const f=e.target.files?.[0];if(f)onUpload([f]);e.target.value=''}}/></label>
 {error&&<p className="error" role="alert">{error}</p>}
 <div className="document-list">{docs.map(d=><label className="check" key={d.id}><input type="checkbox" disabled={busy||disabled||d.status!=='ingested'||conversation.document_scope==='all_owner'} checked={conversation.document_scope==='all_owner'?d.status==='ingested':!!conversation.document_ids?.includes(d.id)} onChange={()=>void select(d.id)}/><span>{d.title}<small>{d.status}</small></span></label>)}</div>
 {more&&<button disabled={busy} onClick={()=>list(docs.length).catch(e=>setError(explain(e)))}>Load more documents</button>}
 <p className="muted small">Selection changes are saved immediately. Use one tab when editing a chat’s selection.</p></section>
}
