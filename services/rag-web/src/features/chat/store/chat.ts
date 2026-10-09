import { create } from 'zustand'
import type { Conversation } from '../types'
export const useChats=create<{items:Conversation[];hasMore:boolean;archived:boolean;set:(items:Conversation[],hasMore:boolean)=>void}>((set)=>({items:[],hasMore:false,archived:false,set:(items,hasMore)=>set({items,hasMore})}))
