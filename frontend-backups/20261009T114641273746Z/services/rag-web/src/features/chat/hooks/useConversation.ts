import { useEffect,useRef,useState } from 'react'
import { chatApi } from '../api/chat'
import type { Conversation,Message,Run,Turn } from '../types'
import { consumeSSE } from '../../../shared/api/sse'
import { ApiError,explain } from '../../../shared/errors/errors'
export function useConversation(id:string){
 const [conversation,setConversation]=useState<Conversation|null>(null);const [messages,setMessages]=useState<Message[]>([])
 const [before,setBefore]=useState<number|null>(null);const [loading,setLoading]=useState(true);const [error,setError]=useState('')
 const [busy,setBusy]=useState(false);const [draft,setDraft]=useState('');const [phase,setPhase]=useState('');const [runId,setRunId]=useState<string|null>(null)
 const [retry,setRetry]=useState<Turn|null>(null);const controller=useRef<AbortController|null>(null);const mounted=useRef(true);const locked=useRef(false)
 async function load(){const [c,p]=await Promise.all([chatApi.get(id),chatApi.history(id)]);if(!mounted.current)return;setConversation(c);setMessages(p.items.sort((a,b)=>a.sequence-b.sequence));setBefore(p.has_more?p.next_before:null)}
 useEffect(()=>{mounted.current=true;load().catch(e=>{if(mounted.current)setError(explain(e))}).finally(()=>{if(mounted.current)setLoading(false)});return()=>{mounted.current=false;controller.current?.abort()}},[id])
 // Recover saved state for a pending turn after reload or a lost connection.
 const pending=messages.find(m=>m.status==='pending')?.run_id
 useEffect(()=>{if(!pending||busy)return;let active=true;const timer=setInterval(()=>{chatApi.run(id,pending).then(r=>{if(active&&r.status!=='running')void load().catch(e=>setError(explain(e)))}).catch(e=>{if(active)setError(explain(e))})},2500);return()=>{active=false;clearInterval(timer)}},[id,pending,busy])
 async function older(){if(!before)return;try{const p=await chatApi.history(id,before);if(!mounted.current)return;setMessages(old=>[...p.items,...old].filter((m,i,a)=>a.findIndex(v=>v.id===m.id)===i).sort((a,b)=>a.sequence-b.sequence));setBefore(p.has_more?p.next_before:null)}catch(e){setError(explain(e))}}
 async function send(query:string,replay?:Turn){if(locked.current)return;locked.current=true;setBusy(true);setError('');setDraft('');setPhase('Starting');setRunId(null)
 const turn=replay??{query,client_message_id:crypto.randomUUID(),top_k:5};setRetry(turn);const ac=new AbortController();controller.current=ac;let terminal=false
 try{await consumeSSE(await chatApi.stream(id,turn,ac.signal),({event,data})=>{
 if(!mounted.current)return
 const d=data as Record<string,unknown>
 if(event==='start'){setRunId(String(d.run_id));setPhase('Finding evidence')}
 else if(event==='delta'){setDraft(old=>old+String(d.text??''));setPhase('Writing · provisional')}
 else if(event==='done'||event==='replay'){terminal=true;const result=data as Run;setDraft('');setPhase(result.status==='completed'?'Complete':result.status);setRetry(null);setRunId(result.status==='running'?result.run_id:null);if(result.status==='failed'||result.status==='cancelled')setError(result.error_code?.replaceAll('_',' ')||result.status)}
 else if(event==='error'){terminal=true;setDraft('');setRetry(null);throw new ApiError(400,String(d.code??'generation_failed'))}
 else if(event==='fallback')setPhase('Switching provider')
 else if(event==='status')setPhase('Processing')
 });if(!terminal)throw new Error('Stream interrupted')
 }catch(e){if(mounted.current){setDraft('');if(e instanceof ApiError)setRetry(null);setError(explain(e))}}
 finally{locked.current=false;if(mounted.current){setBusy(false);setPhase('');await load().catch(e=>setError(explain(e)))}controller.current=null}
 }
 async function stop(){if(!runId){controller.current?.abort();return}try{await chatApi.cancel(id,runId);controller.current?.abort()}catch(e){setError(explain(e))}}
 return {conversation,setConversation,messages,before,loading,error,setError,busy,draft,phase,runId,retry,pending,load,older,send,stop}
}
