import { useEffect,useRef,useState } from 'react'
import { useNavigate,useParams } from 'react-router'
import { useConversation } from '../hooks/useConversation'
import { MessageView } from '../components/MessageView'
import { DocumentPanel } from '../../documents/components/DocumentPanel'
import { documentApi } from '../../documents/api/documents'
import type { Excerpt } from '../../documents/types'
import type { Source } from '../types'
import { chatApi } from '../api/chat'
import { useChats } from '../store/chat'
import { explain } from '../../../shared/errors/errors'
export function ChatScreen(){const {conversationId}=useParams();return conversationId?<ConversationScreen key={conversationId} id={conversationId}/>:<NewChat/>}
function NewChat(){const navigate=useNavigate();const [busy,setBusy]=useState(false);const [error,setError]=useState('');async function create(){setBusy(true);try{const c=await chatApi.create();useChats.setState(s=>({items:[c,...s.items]}));navigate('/chat/'+c.id)}catch(e){setError(explain(e));setBusy(false)}}return <main className="welcome"><span className="brand">◈</span><h1>What would you like to explore?</h1><p className="muted">Start a conversation, add your documents, and ask away.</p><button className="primary" disabled={busy} onClick={create}>Start a new chat</button>{error&&<p role="alert" className="error">{error}</p>}</main>}
function ConversationScreen({id}:{id:string}){
 const c=useConversation(id);const [query,setQuery]=useState('');const [showDocs,setShowDocs]=useState(false);const [excerpt,setExcerpt]=useState<Excerpt|null>(null);const [sourceError,setSourceError]=useState('');const [sourceLoading,setSourceLoading]=useState(false)
 const modal=useRef<HTMLDialogElement>(null);const end=useRef<HTMLDivElement>(null)
 useEffect(()=>{if(c.busy)end.current?.scrollIntoView({behavior:'smooth'})},[c.draft,c.busy])
 async function source(s:Source){setExcerpt(null);setSourceError('');setSourceLoading(true);modal.current?.showModal();try{setExcerpt(await documentApi.excerpt(s.document_id,s.chunk_id))}catch(e){setSourceError(explain(e))}finally{setSourceLoading(false)}}
 if(c.loading)return <main className="welcome" role="status">Loading conversation…</main>
 if(!c.conversation)return <main className="welcome"><p className="error">{c.error||'Conversation unavailable'}</p></main>
 const blocked=c.busy||!!c.pending||!!c.retry||c.conversation.archived
 return <div className="chat-shell"><header className="chat-header"><div><strong>{c.conversation.title}</strong><small className="muted">{c.conversation.archived?'Archived conversation':c.conversation.document_scope==='all_owner'?'All your documents':`${c.conversation.document_ids?.length??0} selected documents`}</small></div><button onClick={()=>setShowDocs(v=>!v)} aria-expanded={showDocs}>Documents</button></header>
 <div className="chat-body"><div className="conversation"><div className="messages">{c.before&&<button onClick={()=>void c.older()}>Load older messages</button>}
 {!c.messages.length&&<div className="chat-empty"><h1>Let’s start with your documents</h1><p className="muted">Choose Documents above to upload or select your evidence.</p></div>}
 {c.messages.map(m=><MessageView key={m.id} message={m} onSource={source}/>)}
 {c.busy&&<article className="message assistant"><span role="status" className="muted small">{c.phase}</span><p className="stream-text">{c.draft}</p></article>}<div ref={end}/></div>
 <div className="composer-area">{c.error&&<div role="alert" className="error">{c.error}</div>}{c.retry&&!c.busy&&<button onClick={()=>void c.send(c.retry!.query,c.retry!)}>Recover last submission</button>}
 {!!c.pending&&!c.busy&&<div className="row"><small>Waiting for the saved run to finish…</small><button onClick={()=>chatApi.cancel(id,c.pending!).then(()=>c.load()).catch(e=>c.setError(explain(e)))}>Stop saved run</button></div>}
 <form className="composer" onSubmit={e=>{e.preventDefault();if(!query.trim()||blocked)return;const text=query.trim();setQuery('');void c.send(text)}}><textarea aria-label="Message" placeholder="Ask about your documents…" value={query} maxLength={2000} disabled={blocked} onChange={e=>setQuery(e.target.value)} rows={2} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();e.currentTarget.form?.requestSubmit()}}}/><div className="composer-actions"><span className="muted small">Enter to send · Shift + Enter for a new line</span>{c.busy?<button type="button" onClick={()=>void c.stop()}>■ Stop</button>:<button className="send" disabled={blocked||!query.trim()} aria-label="Send message">↑</button>}</div></form><p className="disclaimer">Answers can be incomplete. Check the cited sources.</p></div></div>
 {showDocs&&<DocumentPanel conversation={c.conversation} onChange={c.setConversation} disabled={blocked}/>}</div>
 <dialog ref={modal} className="source-modal"><div className="row"><h2>{excerpt?.title||'Source excerpt'}</h2><button onClick={()=>modal.current?.close()}>Close</button></div>{sourceLoading&&<p role="status">Loading source…</p>}{sourceError&&<p role="alert">{sourceError}</p>}<pre>{excerpt?.content}</pre>{excerpt?.truncated&&<small>Excerpt truncated by the backend.</small>}</dialog></div>
}
