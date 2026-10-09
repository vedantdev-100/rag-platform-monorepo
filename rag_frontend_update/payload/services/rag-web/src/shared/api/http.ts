import { useChats } from '../../features/chat/store/chat'
import { config } from '../../config/env'
import { useSession } from '../../features/auth/store/session'
import type { Tokens } from '../../features/auth/types'
import { ApiError } from '../errors/errors'
import { logFailure } from '../logging/logger'
let refreshTask: Promise<string> | null = null
let epoch=0
export function clearSession(){epoch++;useChats.setState({items:[],hasMore:false,archived:false});useSession.getState().set(null,null)}
export async function check(response: Response) {
 if(response.ok) return response
 let code='request_failed'
 try {const data=await response.json();const detail=data.detail;code=typeof detail==='string'?detail:(Array.isArray(detail)?'Please check the submitted fields.':detail?.code||data.code||code)}catch{/* non-JSON error */}
 logFailure('api',response.status);throw new ApiError(response.status,code)
}
export async function refresh():Promise<string>{
 if(!refreshTask){const started=epoch;refreshTask=(async()=>{
  const r=await check(await fetch(config.auth+config.prefix+'/auth/browser/refresh',{method:'POST',credentials:'include'}))
  const data:Tokens=await r.json()
  if(started!==epoch) throw new ApiError(401,'session_changed')
  useSession.setState({token:data.access_token});return data.access_token
 })().catch(e=>{if(started===epoch)clearSession();throw e}).finally(()=>{refreshTask=null})}
 return refreshTask
}
export async function request(service:'rag'|'auth',path:string,init:RequestInit={},retry=true):Promise<Response>{
 const headers=new Headers(init.headers)
 const token=useSession.getState().token
 if(token)headers.set('Authorization',`Bearer ${token}`)
 if(typeof init.body==='string')headers.set('Content-Type','application/json')
 const r=await fetch(config[service]+config.prefix+path,{...init,headers,credentials:service==='auth'?'include':'omit'})
 if(r.status===401&&retry){await refresh();return request(service,path,init,false)}
 return check(r)
}
export async function json<T>(service:'rag'|'auth',path:string,init:RequestInit={}):Promise<T>{
 const r=await request(service,path,init);return r.status===204?undefined as T:r.json()
}
export const body=(data:unknown)=>JSON.stringify(data)
