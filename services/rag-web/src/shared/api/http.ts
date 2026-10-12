import { withDeadline } from './deadline'
import { useChats } from '../../features/chat/store/chat'
import { config } from '../../config/env'
import { useSession } from '../../features/auth/store/session'
import type { Tokens } from '../../features/auth/types'
import { ApiError } from '../errors/errors'
import { logFailure } from '../logging/logger'
let refreshTask: Promise<string> | null = null
let epoch=0
const reads=new Map<string,Promise<unknown>>()
export function beginLogout(){epoch++;reads.clear();useSession.setState({signingOut:true})}
export async function settleRefreshBeforeLogout(){await refreshTask?.catch(()=>{})}
export function clearSession(){epoch++;reads.clear();useChats.setState({items:[],hasMore:false,archived:false});useSession.getState().set(null,null)}
export async function check(response: Response) {
 if(response.ok) return response
 let code='request_failed'
 try {const data=await response.json();const detail=data.detail;code=typeof detail==='string'?detail:(Array.isArray(detail)?'Please check the submitted fields.':detail?.code||data.code||code)}catch{/* non-JSON error */}
 logFailure('api',response.status);throw new ApiError(response.status,code)
}
export async function refresh():Promise<string>{
 if(useSession.getState().signingOut)throw new ApiError(409,'signing_out')
 if(!refreshTask){const started=epoch;refreshTask=(async()=>{
  const data=await withDeadline(async signal=>{
   const r=await check(await fetch(config.auth+config.prefix+'/auth/browser/refresh',{method:'POST',credentials:'include',signal}))
   return await r.json() as Tokens
  },12000)
  if(started!==epoch) throw new ApiError(401,'session_changed')
  useSession.setState({token:data.access_token});return data.access_token
 })().catch(e=>{if(started===epoch)clearSession();throw e}).finally(()=>{refreshTask=null})}
 return refreshTask
}
export async function request(service:'rag'|'auth',path:string,init:RequestInit={},retry=true):Promise<Response>{
 if(useSession.getState().signingOut)throw new ApiError(409,'signing_out')
 const started=epoch
 const headers=new Headers(init.headers)
 const token=useSession.getState().token
 if(token)headers.set('Authorization',`Bearer ${token}`)
 if(typeof init.body==='string')headers.set('Content-Type','application/json')
 const r=await fetch(config[service]+config.prefix+path,{...init,headers,credentials:service==='auth'?'include':'omit'})
 if(started!==epoch||useSession.getState().signingOut){await r.body?.cancel().catch(()=>{});throw new ApiError(409,'session_changed')}
 if(r.status===401&&retry){await refresh();return request(service,path,init,false)}
 return check(r)
}
export async function json<T>(service:'rag'|'auth',path:string,init:RequestInit={}):Promise<T>{
 const started=epoch
 const read=(init.method??'GET').toUpperCase()==='GET'
 const key=JSON.stringify([started,service,path,Array.from(new Headers(init.headers).entries())])
 async function execute(signal?:AbortSignal){
  const r=await request(service,path,{...init,signal:signal??init.signal});const data=r.status===204?undefined:await r.json()
  if(started!==epoch)throw new ApiError(409,'session_changed')
  return data as T
 }
 // Uploads keep their own cancellation policy; bounded deadlines apply to finite JSON reads.
 const task=()=>init.body instanceof FormData?execute():withDeadline(execute,read?15000:30000,init.signal??undefined)
 if(!read||init.signal)return task()
 const existing=reads.get(key);if(existing)return existing as Promise<T>
 const promise=task().finally(()=>{if(reads.get(key)===promise)reads.delete(key)})
 reads.set(key,promise);return promise
}
export const body=(data:unknown)=>JSON.stringify(data)
