import { config } from '../../../config/env'
import { body,check,json,refresh,clearSession } from '../../../shared/api/http'
import { useSession } from '../store/session'
import type { Tokens,User } from '../types'
export async function login(email:string,password:string){
 const r=await check(await fetch(config.auth+config.prefix+'/auth/browser/login',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:body({email,password})}))
 const t:Tokens=await r.json();useSession.setState({token:t.access_token})
 try{const user=await json<User>('auth','/users/me');useSession.getState().set(t.access_token,user)}catch(e){clearSession();throw e}
}
export async function signup(email:string,password:string,full_name:string){
 await check(await fetch(config.auth+config.prefix+'/auth/register',{method:'POST',headers:{'Content-Type':'application/json'},body:body({email,password,full_name})}))
}
let boot:Promise<void>|undefined
export function restore(){return boot??=(async()=>{try{await refresh();const user=await json<User>('auth','/users/me');useSession.getState().set(useSession.getState().token,user)}catch{clearSession()}})()}
export async function logout(){await check(await fetch(config.auth+config.prefix+'/auth/browser/logout',{method:'POST',credentials:'include'}));clearSession()}
