import { userInitials } from '../../features/auth/utils/initials'
import { ThemeToggle } from '../../shared/components/ThemeToggle'
import { Modal } from '../../shared/components/Modal'
import { Popover } from '../../shared/components/Popover'
import { useEffect,useState } from 'react'
import { Link,NavLink,Outlet,useLocation,useNavigate } from 'react-router'
import { useSession } from '../../features/auth/store/session'
import { logout } from '../../features/auth/api/auth'
import { useChats } from '../../features/chat/store/chat'
import { chatApi } from '../../features/chat/api/chat'
import type { Conversation } from '../../features/chat/types'
import { explain } from '../../shared/errors/errors'
export function Workspace(){
 const user=useSession(s=>s.user)!;const chats=useChats();const navigate=useNavigate();const location=useLocation()
 const [error,setError]=useState('');const [open,setOpen]=useState(()=>window.matchMedia('(min-width: 641px)').matches);const [working,setWorking]=useState(false)
 const [userModal,setUserModal]=useState<'profile'|'settings'|null>(null)
 const [action,setAction]=useState<{chat:Conversation;kind:'rename'|'delete'}|null>(null);const [title,setTitle]=useState('');const [modalError,setModalError]=useState('')
 async function load(append=false){const r=await chatApi.list(append?useChats.getState().items.length:0,useChats.getState().archived);useChats.getState().set(append?[...useChats.getState().items,...r.items]:r.items,r.has_more)}
 useEffect(()=>{let active=true;chatApi.list(0,chats.archived).then(r=>{if(active)chats.set(r.items,r.has_more)}).catch(e=>{if(active)setError(explain(e))});return()=>{active=false}},[chats.archived,user.id])
 useEffect(()=>{if(window.matchMedia('(max-width:640px)').matches)setOpen(false)},[location.pathname])
 async function archive(chat:Conversation){setWorking(true);try{await chatApi.update(chat.id,{archived:!chat.archived});await load();if(location.pathname==='/chat/'+chat.id)navigate('/chat')}catch(e){setError(explain(e))}finally{setWorking(false)}}
 async function confirm(){if(!action)return;const selected=action;setWorking(true);setModalError('');try{
 if(selected.kind==='rename'){await chatApi.update(selected.chat.id,{title:title.trim()})}else{await chatApi.remove(selected.chat.id)}
 await load();setAction(null);if(selected.kind==='delete'&&location.pathname==='/chat/'+selected.chat.id)navigate('/chat')
 }catch(e){setModalError(explain(e));setError(explain(e))}finally{setWorking(false)}}
 return <div className={'workspace '+(open?'sidebar-visible':'sidebar-hidden')}><button className="sidebar-toggle" onClick={()=>setOpen(!open)} aria-label={open?'Collapse sidebar':'Expand sidebar'} aria-expanded={open} aria-controls="primary-sidebar">☰</button>{open&&<button className="sidebar-backdrop" aria-label="Close sidebar" onClick={()=>setOpen(false)}/>}
 <aside id="primary-sidebar" className="sidebar"><Link to="/chat" className="brand">◈ Workspace</Link><div className="sidebar-links"><Link className="new-chat" to="/chat">＋ New chat</Link><NavLink className="artifacts-link" to="/artifacts">▤ Artifacts</NavLink></div><div className="row"><span className="eyebrow">YOUR CONVERSATIONS</span><button className="small" onClick={()=>useChats.setState({archived:!chats.archived})}>{chats.archived?'Active':'Archived'}</button></div>
 <nav className="chat-list">{chats.items.map(c=><div className="chat-link" key={c.id}><NavLink to={'/chat/'+c.id}>{c.title}</NavLink><Popover label={'Actions for '+c.title} trigger="···" className="chat-actions-trigger" panelClass="actions-popover">{close=><><button disabled={working} onClick={()=>{close();setTitle(c.title);setModalError('');setAction({chat:c,kind:'rename'})}}>Rename</button><button disabled={working} onClick={()=>{close();void archive(c)}}>{c.archived?'Restore':'Archive'}</button><button className="danger-text" disabled={working} onClick={()=>{close();setModalError('');setAction({chat:c,kind:'delete'})}}>Delete</button></>}</Popover></div>)}{chats.hasMore&&<button onClick={()=>load(true).catch(e=>setError(explain(e)))}>Load more</button>}</nav>
 {error&&<p className="error" role="alert">{error}</p>}<footer>{user.role==='admin'&&<Link to="/admin/users">Users administration</Link>}<Popover label="Account menu" className="account-trigger" panelClass="account-popover" trigger={<><span className="avatar" aria-hidden="true">{userInitials(user.full_name,user.email)}</span><span className="account-name">{user.full_name||user.email}</span><span aria-hidden="true">⌄</span></>}>{close=><><button onClick={()=>{close();setUserModal('profile')}}>Profile</button><button onClick={()=>{close();setUserModal('settings')}}>Settings</button><button disabled={working} onClick={async()=>{close();setWorking(true);try{await logout();useChats.setState({items:[],hasMore:false,archived:false});navigate('/login')}catch(e){setError(explain(e))}finally{setWorking(false)}}}>Sign out</button></>}</Popover></footer></aside><div className="workspace-main"><Outlet/></div>
 <Modal open={userModal==='profile'} title="Profile" onClose={()=>setUserModal(null)}><div className="profile-avatar avatar">{userInitials(user.full_name,user.email)}</div><dl className="profile-details"><dt>Name</dt><dd>{user.full_name||'Not provided'}</dd><dt>Email</dt><dd>{user.email}</dd><dt>Role</dt><dd>{user.role}</dd><dt>Account</dt><dd>{user.is_active?'Active':'Inactive'}</dd></dl></Modal>
 <Modal open={userModal==='settings'} title="Settings" onClose={()=>setUserModal(null)}><h3>Appearance</h3><p className="muted">Choose the theme for this browser.</p><ThemeToggle/><p className="small muted">Streaming follows your device’s reduced-motion preference.</p></Modal>
 <Modal open={!!action} title={action?.kind==='rename'?'Rename conversation':'Delete conversation?'} onClose={()=>setAction(null)}><form onSubmit={e=>{e.preventDefault();void confirm()}}>{action?.kind==='rename'?<label className="modal-label">Conversation name<input autoFocus value={title} maxLength={200} required onChange={e=>setTitle(e.target.value)}/></label>:<p>This deletes “{action?.chat.title}” and its messages. Your documents remain available.</p>}{modalError&&<p role="alert" className="error">{modalError}</p>}<div className="modal-actions"><button type="button" onClick={()=>setAction(null)}>Cancel</button><button className={action?.kind==='delete'?'danger-button':'primary'} disabled={working||(action?.kind==='rename'&&!title.trim())}>{working?'Saving…':action?.kind==='rename'?'Save name':'Delete chat'}</button></div></form></Modal></div>
}
