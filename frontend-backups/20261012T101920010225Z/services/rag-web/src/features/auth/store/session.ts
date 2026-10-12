import { create } from 'zustand'
import type { User } from '../types'
interface Session {token:string|null;user:User|null;ready:boolean;set:(token:string|null,user:User|null)=>void}
export const useSession=create<Session>((set)=>({token:null,user:null,ready:false,set:(token,user)=>set({token,user,ready:true})}))
