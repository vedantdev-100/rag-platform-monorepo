export interface Conversation{id:string;title:string;archived:boolean;document_scope:'selected'|'all_owner';document_ids:string[]|null}
export interface Source{label:string;document_id:string;chunk_id:string}
export interface Message{id:string;run_id:string;sequence:number;role:'user'|'assistant';content:string;status:string;answer:{sources:Source[]}|null}
export interface Run{run_id:string;conversation_id:string;client_message_id:string;status:string;error_code:string|null;messages:Message[]}
export interface Turn{query:string;client_message_id:string;top_k:number}
export interface Page{items:Message[];has_more:boolean;next_before:number|null}
