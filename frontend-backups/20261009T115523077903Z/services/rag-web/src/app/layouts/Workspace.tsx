import { useEffect,useState } from 'react'
import { Link,NavLink,Outlet,useNavigate } from 'react-router'
import { useSession } from '../../features/auth/store/session'
import { logout } from '../../features/auth/api/auth'
import { useChats } from '../../features/chat/store/chat'
import { chatApi } from '../../features/chat/api/chat'
import { explain } from '../../shared/errors/errors'
export function Workspace(){
 const user=useSession(s=>s.user)!;const chats=useChats();const navigate=useNavigate();const [error,setError]=useState('');const [open,setOpen]=useState(false);const [working,setWorking]=useState(false)
 async function load(append=false){const r=await chatApi.list(append?useChats.getState().items.length:0,useChats.getState().archived);useChats.getState().set(append?[...useChats.getState().items,...r.items]:r.items,r.has_more)}
 useEffect(()=>{let active=true;chatApi.list(0,chats.archived).then(r=>{if(active)chats.set(r.items,r.has_more)}).catch(e=>{if(active)setError(explain(e))});return()=>{active=false}},[chats.archived,user.id])
 async function change(id:string,action:'rename'|'archive'|'delete'){setError('');setWorking(true);try{
 if(action==='rename'){const title=window.prompt('Conversation name');if(!title?.trim())return;await chatApi.update(id,{title:title.trim().slice(0,200)})}
 if(action==='archive')await chatApi.update(id,{archived:!chats.archived})
 if(action==='delete'){if(!window.confirm('Delete this conversation and its messages? Documents remain available.'))return;await chatApi.remove(id)}
 await load();navigate('/chat')
 }catch(e){setError(explain(e))}finally{setWorking(false)}}
 return <div className="workspace"><button className="mobile-menu" onClick={()=>setOpen(!open)} aria-label="Toggle navigation">☰</button><aside className={'sidebar '+(open?'open':'')}><Link to="/chat" className="brand" onClick={()=>setOpen(false)}>◈ Workspace</Link><Link className="new-chat" to="/chat" onClick={()=>setOpen(false)}>＋ New chat</Link><div className="row"><span className="eyebrow">YOUR CONVERSATIONS</span><button className="small" onClick={()=>useChats.setState({archived:!chats.archived})}>{chats.archived?'Active':'Archived'}</button></div>
 <nav className="chat-list">{chats.items.map(c=><div className="chat-link" key={c.id}><NavLink to={'/chat/'+c.id} onClick={()=>setOpen(false)}>{c.title}</NavLink><details><summary aria-label={'Actions for '+c.title}>···</summary><div><button disabled={working} onClick={()=>change(c.id,'rename')}>Rename</button><button disabled={working} onClick={()=>change(c.id,'archive')}>{c.archived?'Restore':'Archive'}</button><button disabled={working} onClick={()=>change(c.id,'delete')}>Delete</button></div></details></div>)}{chats.hasMore&&<button onClick={()=>load(true).catch(e=>setError(explain(e)))}>Load more</button>}</nav>
 {error&&<p className="error" role="alert">{error}</p>}<footer>{user.role==='admin'&&<Link to="/admin/users" onClick={()=>setOpen(false)}>Users administration</Link>}<span className="user-name">{user.full_name||user.email}</span><button disabled={working} onClick={async()=>{setWorking(true);try{await logout();useChats.setState({items:[],hasMore:false,archived:false});navigate('/login')}catch(e){setError(explain(e))}finally{setWorking(false)}}}>Sign out</button></footer></aside><div className="workspace-main"><Outlet/></div></div>
}
