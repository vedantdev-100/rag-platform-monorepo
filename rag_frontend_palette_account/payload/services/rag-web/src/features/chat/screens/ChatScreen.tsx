import { useUploads,uploadsBusy } from '../../documents/store/uploads'
import { UploadCards } from '../../documents/components/UploadCards'
import { useFileDrop } from '../../documents/hooks/useFileDrop'
import { acceptedFiles } from '../../documents/utils/files'
import { useEffect,useRef,useState } from 'react'
import { useNavigate,useParams } from 'react-router'
import { useSmoothDraft } from '../hooks/useSmoothDraft'
import { useConversation } from '../hooks/useConversation'
import { MessageView } from '../components/MessageView'
import { DocumentPicker } from '../../documents/components/DocumentPicker'
import { Popover } from '../../../shared/components/Popover'
import { Modal } from '../../../shared/components/Modal'
import { documentApi } from '../../documents/api/documents'
import type { Excerpt } from '../../documents/types'
import type { Source } from '../types'
import { chatApi } from '../api/chat'
import { useChats } from '../store/chat'
import { explain } from '../../../shared/errors/errors'
export function ChatScreen(){const {conversationId}=useParams();return conversationId?<ConversationScreen key={conversationId} id={conversationId}/>:<NewChat/>}
function NewChat(){
 const navigate=useNavigate();const [busy,setBusy]=useState(false);const [error,setError]=useState('');const fileInput=useRef<HTMLInputElement>(null);const creating=useRef(false)
 async function create(files:File[]=[]){if(creating.current)return;creating.current=true;setBusy(true);try{const c=await chatApi.create();useChats.setState(s=>({items:[c,...s.items]}));if(files.length)useUploads.getState().enqueue(c.id,files);navigate('/chat/'+c.id)}catch(e){setError(explain(e));setBusy(false)}finally{creating.current=false}}
 const drop=useFileDrop(files=>void create(files),busy)
 return <main className="welcome drop-target" {...drop.handlers}>{drop.dragging&&<div className="drop-overlay">{busy?'Creating conversation…':'Drop documents to start a chat'}</div>}<span className="brand">◈</span><h1>What would you like to explore?</h1><p className="muted">Start a conversation, or drop your documents here.</p><div className="row"><button className="primary" disabled={busy} onClick={()=>void create()}>Start a new chat</button><button disabled={busy} onClick={()=>fileInput.current?.click()}>＋ Upload documents</button></div><input hidden ref={fileInput} type="file" multiple accept={acceptedFiles} onChange={e=>{const files=Array.from(e.target.files??[]);if(files.length)void create(files);e.target.value=''}}/>{error&&<p role="alert" className="error">{error}</p>}</main>
}
function ConversationScreen({id}:{id:string}){
 const c=useConversation(id);const smoothDraft=useSmoothDraft(c.draft);const [query,setQuery]=useState('');const [excerpt,setExcerpt]=useState<Excerpt|null>(null);const [sourceError,setSourceError]=useState('');const [sourceLoading,setSourceLoading]=useState(false)
 const jobs=useUploads(s=>s.jobs);const uploading=uploadsBusy(jobs,id)
 const uploadBlocked=c.busy||!!c.pending||!!c.retry||!c.conversation||!!c.conversation.archived
 const enqueue=(files:File[])=>{if(!uploadBlocked)useUploads.getState().enqueue(id,files)}
 const drop=useFileDrop(enqueue,uploadBlocked)
 const finished=jobs.filter(j=>j.conversationId===id&&j.stage==='ready').map(j=>j.id).join(',')
 useEffect(()=>{if(!finished)return;let live=true;chatApi.get(id).then(value=>{if(live)c.setConversation(value)}).catch(e=>{if(live)c.setError(explain(e))});return()=>{live=false}},[id,finished])
 const [sourceOpen,setSourceOpen]=useState(false);const end=useRef<HTMLDivElement>(null)
 useEffect(()=>{if(c.busy)end.current?.scrollIntoView({behavior:'smooth'})},[smoothDraft,c.busy,c.optimistic?.id])
 async function source(s:Source){setExcerpt(null);setSourceError('');setSourceLoading(true);setSourceOpen(true);try{setExcerpt(await documentApi.excerpt(s.document_id,s.chunk_id))}catch(e){setSourceError(explain(e))}finally{setSourceLoading(false)}}
 if(c.loading)return <main className="welcome" role="status">Loading conversation…</main>
 if(!c.conversation)return <main className="welcome"><p className="error">{c.error||'Conversation unavailable'}</p></main>
 const blocked=uploadBlocked||uploading
 return <div className="chat-shell drop-target" {...drop.handlers}>{drop.dragging&&<div className="drop-overlay">{uploadBlocked?'Wait for the current turn to finish':'Drop documents to add to this chat'}</div>}<div className="chat-floating-controls"><Popover label="Choose chat files" trigger={<>▤ Chat files <span aria-hidden="true">⌄</span></>} panelClass="files-popover">{()=> <DocumentPicker conversation={c.conversation!} onChange={c.setConversation} onUpload={enqueue} disabled={blocked}/>}</Popover></div>
 <div className="chat-body"><div className="conversation"><div className="messages">{c.before&&<button onClick={()=>void c.older()}>Load older messages</button>}
 {!c.messages.length&&!c.optimistic&&<div className="chat-empty"><h1>Let’s start with your documents</h1><p className="muted">Drop documents here, use + below, or choose existing documents.</p></div>}
 {c.messages.map(m=><MessageView key={m.id} message={m} onSource={source}/>)}
 {c.optimistic&&<MessageView message={c.optimistic} onSource={source}/>}
 {c.busy&&<article className="message assistant"><span role="status" className="muted small">{c.phase}</span><p className="stream-text">{smoothDraft}</p></article>}<div ref={end}/></div>
 <div className="composer-area">{c.error&&<div role="alert" className="error">{c.error}</div>}{c.retry&&!c.busy&&<button onClick={()=>void c.send(c.retry!.query,c.retry!)}>Recover last submission</button>}
 {!!c.pending&&!c.busy&&<div className="row"><small>Waiting for the saved run to finish…</small><button onClick={()=>chatApi.cancel(id,c.pending!).then(()=>c.load()).catch(e=>c.setError(explain(e)))}>Stop saved run</button></div>}
 <UploadCards conversationId={id}/><form className="composer" onSubmit={e=>{e.preventDefault();if(!query.trim()||blocked)return;const text=query.trim();setQuery('');void c.send(text)}}><textarea aria-label="Message" placeholder="Ask about your documents…" value={query} maxLength={2000} disabled={uploadBlocked} onChange={e=>setQuery(e.target.value)} rows={2} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();e.currentTarget.form?.requestSubmit()}}}/><div className="composer-actions"><Popover label="Add or select chat files" trigger="＋" className="attach-button" panelClass="files-popover">{()=> <DocumentPicker conversation={c.conversation!} onChange={c.setConversation} onUpload={enqueue} disabled={blocked}/>}</Popover><span className="muted small">Enter to send · Shift + Enter for a new line</span>{c.busy?<button type="button" onClick={()=>void c.stop()}>■ Stop</button>:<button className="send" disabled={blocked||!query.trim()} aria-label="Send message">↑</button>}</div></form><p className="disclaimer">Answers can be incomplete. Check the cited sources.</p></div></div>
 </div>
 <Modal open={sourceOpen} title={excerpt?.title||'Source excerpt'} onClose={()=>setSourceOpen(false)}>{sourceLoading&&<p role="status">Loading source…</p>}{sourceError&&<p role="alert">{sourceError}</p>}<pre className="source-content">{excerpt?.content}</pre>{excerpt?.truncated&&<small>Excerpt truncated by the backend.</small>}</Modal></div>
}
