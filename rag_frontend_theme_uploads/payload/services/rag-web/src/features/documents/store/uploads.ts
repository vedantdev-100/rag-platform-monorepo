import { create } from 'zustand'
import { documentApi } from '../api/documents'
import { chatApi } from '../../chat/api/chat'
import { useSession } from '../../auth/store/session'
import { consumeSSE } from '../../../shared/api/sse'
import { explain } from '../../../shared/errors/errors'
import { fileProblem,appendDocument } from '../utils/files'
export type UploadStage='queued'|'uploading'|'processing'|'selecting'|'ready'|'failed'
export interface UploadJob{id:string;conversationId:string;ownerId:string;name:string;stage:UploadStage;documentId?:string;error?:string}
interface Uploads{jobs:UploadJob[];enqueue:(conversationId:string,files:File[])=>void;dismiss:(id:string)=>void;retrySelection:(id:string)=>void}
const files=new Map<string,File>();let pumping=false;let current:AbortController|null=null
const active=(stage:UploadStage)=>!['ready','failed'].includes(stage)
export const useUploads=create<Uploads>((set,get)=>({jobs:[],enqueue:(conversationId,batch)=>{
 const ownerId=useSession.getState().user?.id;if(!ownerId)return
 const jobs=batch.map(file=>{const id=crypto.randomUUID();const error=fileProblem(file);if(!error)files.set(id,file);return {id,conversationId,ownerId,name:file.name,stage:error?'failed':'queued',error:error??undefined} as UploadJob})
 set({jobs:[...get().jobs,...jobs]});void pump()
},dismiss:id=>set({jobs:get().jobs.filter(j=>j.id!==id||active(j.stage))}),retrySelection:id=>{set({jobs:get().jobs.map(j=>j.id===id&&j.documentId?{...j,stage:'queued',error:undefined}:j)});void pump()}}))
export function uploadsBusy(jobs:UploadJob[],cid:string){return jobs.some(j=>j.conversationId===cid&&active(j.stage))}
function patch(id:string,change:Partial<UploadJob>){useUploads.setState(s=>({jobs:s.jobs.map(j=>j.id===id?{...j,...change}:j)}))}
function ensureOwner(job:UploadJob,signal:AbortSignal){if(signal.aborted||useSession.getState().user?.id!==job.ownerId)throw new Error('Session changed')}
function pause(ms:number,signal:AbortSignal){return new Promise<void>((resolve,reject)=>{const abort=()=>{clearTimeout(timer);reject(new DOMException('Aborted','AbortError'))};const timer=setTimeout(()=>{signal.removeEventListener('abort',abort);resolve()},ms);if(signal.aborted)abort();else signal.addEventListener('abort',abort,{once:true})})}
async function process(job:UploadJob,signal:AbortSignal){
 ensureOwner(job,signal)
 let docId=job.documentId
 if(!docId){patch(job.id,{stage:'uploading'});const file=files.get(job.id);if(!file)throw new Error('File unavailable');const doc=await documentApi.upload(file,signal);docId=doc.id;patch(job.id,{documentId:docId});files.delete(job.id)}
 ensureOwner(job,signal);patch(job.id,{stage:'processing'})
 // SSE provides immediate state changes; polling recovers interruptions without another upload.
 const observer=new AbortController();const abort=()=>observer.abort();signal.addEventListener('abort',abort,{once:true});const timer=setTimeout(abort,30000)
 try{await consumeSSE(await documentApi.events(docId,observer.signal),({event})=>event==='done'||event==='error')}catch{/* Read authoritative status below. */}finally{clearTimeout(timer);signal.removeEventListener('abort',abort)}
 let doc=await documentApi.status(docId);const deadline=Date.now()+15*60*1000
 while(doc.status!=='ingested'&&doc.status!=='failed'){
  ensureOwner(job,signal);if(Date.now()>deadline)throw new Error('processing_timeout');await pause(2500,signal);doc=await documentApi.status(docId)
 }
 ensureOwner(job,signal)
 if(doc.status==='failed'){patch(job.id,{stage:'failed',error:'Ingestion failed. Check the file before uploading it again.'});return}
 patch(job.id,{stage:'selecting'});const conversation=await chatApi.get(job.conversationId);ensureOwner(job,signal)
 if(conversation.document_scope==='selected')await chatApi.select(job.conversationId,'selected',appendDocument(conversation.document_ids,docId))
 ensureOwner(job,signal);patch(job.id,{stage:'ready',error:undefined})
}
async function pump(){if(pumping)return;pumping=true
 try{while(true){const job=useUploads.getState().jobs.find(j=>j.stage==='queued');if(!job)break;current=new AbortController();try{await process(job,current.signal)}catch(e){patch(job.id,{stage:'failed',error:e instanceof Error&&e.message==='processing_timeout'?'Still processing. Check status again shortly.':explain(e)})}finally{files.delete(job.id);current=null}}}finally{pumping=false}
}
useSession.subscribe((state,old)=>{if(old.user&&state.user?.id!==old.user.id){current?.abort();files.clear();useUploads.setState({jobs:[]})}})
