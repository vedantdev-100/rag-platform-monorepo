import { json,body,request } from '../../../shared/api/http'
import type { Conversation,Page,Turn,Run } from '../types'
const path=(id:string)=>'/conversations/'+encodeURIComponent(id)
export const chatApi={
 list:(offset=0,archived=false)=>json<{items:Conversation[];has_more:boolean}>('rag',`/conversations?limit=30&offset=${offset}&archived=${archived}`),
 create:()=>json<Conversation>('rag','/conversations',{method:'POST',body:body({title:'New chat',document_scope:'selected'})}),
 get:(id:string)=>json<Conversation>('rag',path(id)),
 history:(id:string,before?:number)=>json<Page>('rag',path(id)+'/messages?limit=50'+(before?'&before='+before:'')),
 update:(id:string,data:Partial<Conversation>)=>json<Conversation>('rag',path(id),{method:'PATCH',body:body(data)}),
 remove:(id:string)=>json<void>('rag',path(id),{method:'DELETE'}),
 select:(id:string,document_scope:Conversation['document_scope'],document_ids:string[])=>json<Conversation>('rag',path(id)+'/documents',{method:'PUT',body:body({document_scope,document_ids})}),
 stream:(id:string,turn:Turn,signal:AbortSignal)=>request('rag',path(id)+'/messages/stream',{method:'POST',body:body(turn),headers:{Accept:'text/event-stream'},signal}),
 run:(id:string,run:string)=>json<Run>('rag',path(id)+'/runs/'+run),
 cancel:(id:string,run:string)=>json<void>('rag',path(id)+'/runs/'+run+'/cancel',{method:'POST'}),
}
