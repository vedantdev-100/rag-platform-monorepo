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
 async function send(query:string,replay?:Turn){
 if(locked.current)return
 locked.current=true;setBusy(true);setError('');setDraft('');setPhase('Starting');setRunId(null)
 const turn=replay??{query,client_message_id:crypto.randomUUID(),top_k:5}
 setRetry(turn)
 const ac=new AbortController();controller.current=ac
 let terminal=false;let saved:Run|null=null;let knownRunId:string|null=null;let explicitFailure=false
 function applyRun(result:Run){
  saved=result
  if(!mounted.current)return
  setDraft('');setRetry(null);setRunId(result.status==='running'?result.run_id:null)
  setMessages(old=>[...old.filter(m=>m.run_id!==result.run_id),...result.messages].sort((a,b)=>a.sequence-b.sequence))
  if(result.status==='completed')setError('')
  else if(result.status==='failed'||result.status==='cancelled')setError(result.error_code?.replaceAll('_',' ')||result.status)
 }
 try{
  await consumeSSE(await chatApi.stream(id,turn,ac.signal),({event,data})=>{
   if(!mounted.current)return true
   const d=data as Record<string,unknown>
   if(event==='start'){knownRunId=String(d.run_id);setRunId(knownRunId);setPhase('Finding evidence')}
   else if(event==='delta'){setDraft(old=>old+String(d.text??''));setPhase('Writing · provisional')}
   else if(event==='done'||event==='replay'){
    const result=data as Run
    if(result.conversation_id!==id||result.client_message_id!==turn.client_message_id||!Array.isArray(result.messages))throw new Error('Invalid completion')
    terminal=true;knownRunId=result.run_id;applyRun(result);return true
   }
   else if(event==='error'){terminal=true;explicitFailure=true;setDraft('');setRetry(null);throw new ApiError(400,String(d.code??'generation_failed'))}
   else if(event==='fallback')setPhase('Switching provider')
   else if(event==='status')setPhase('Processing')
  })
  if(!terminal&&!ac.signal.aborted)throw new Error('Stream interrupted')
 }catch(e){
  if(mounted.current){
   setDraft('')
   // Only reconcile this exact run, never infer success from older answers.
   if(knownRunId&&!explicitFailure){
    try{const result=await chatApi.run(id,knownRunId);if(result.client_message_id===turn.client_message_id&&result.conversation_id===id)applyRun(result)}catch{/* Preserve the original stream error. */}
   }
   if(!saved){if(e instanceof ApiError)setRetry(null);setError(explain(e))}
  }
 }finally{
  if(mounted.current){
   setPhase('')
   try{await load()}catch{
    if(mounted.current)setError(saved?'The run was saved, but conversation history could not refresh. Reload to sync.':'Could not refresh conversation history. Use Recover last submission or reload to check its status.')
   }
   if(mounted.current)setBusy(false)
  }
  locked.current=false;controller.current=null
 }
 }
 async function stop(){if(!runId){controller.current?.abort();return}try{await chatApi.cancel(id,runId);controller.current?.abort()}catch(e){setError(explain(e))}}
 return {conversation,setConversation,messages,before,loading,error,setError,busy,draft,phase,runId,retry,pending,load,older,send,stop}
}
