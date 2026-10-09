import { json,request } from '../../../shared/api/http'
import type { Document,Excerpt } from '../types'
export const documentApi={
 list:(offset=0)=>json<{documents:Document[]}>('rag',`/documents?limit=50&offset=${offset}`),
 upload:(file:File)=>{const form=new FormData();form.append('file',file);return json<Document>('rag','/documents',{method:'POST',body:form})},
 status:(id:string)=>json<Document>('rag','/documents/'+id),
 events:(id:string,signal:AbortSignal)=>request('rag',`/documents/${id}/events`,{headers:{Accept:'text/event-stream'},signal}),
 excerpt:(doc:string,chunk:string)=>json<Excerpt>('rag',`/documents/${doc}/chunks/${chunk}`),
}
