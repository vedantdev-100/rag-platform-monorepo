import { ThemeToggle } from '../../../shared/components/ThemeToggle'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link,Navigate,useLocation,useNavigate } from 'react-router'
import { login,signup } from '../api/auth'
import { useSession } from '../store/session'
import { explain } from '../../../shared/errors/errors'
export function AuthScreen({register=false}:{register?:boolean}){
 const user=useSession(s=>s.user);const navigate=useNavigate();const location=useLocation()
 const [error,setError]=useState('');const [busy,setBusy]=useState(false);const [notice,setNotice]=useState('')
 if(user)return <Navigate to="/chat" replace/>
 async function submit(e:FormEvent<HTMLFormElement>){e.preventDefault();setBusy(true);setError('');const form=new FormData(e.currentTarget)
 try{const email=String(form.get('email'));const password=String(form.get('password'))
 if(register){await signup(email,password,String(form.get('name')));setNotice('Account created. Sign in to continue.');navigate('/login',{state:{registered:true}})}
 else{await login(email,password);const next=location.state?.from; navigate(typeof next==='string'&&next.startsWith('/chat')?next:'/chat',{replace:true})}
 }catch(e){setError(explain(e))}finally{setBusy(false)}}
 return <div className="auth"><div className="auth-theme"><ThemeToggle/></div><div className="auth-card"><span className="brand">◈ RAG Workspace</span><h1>{register?'Create your account':'Welcome back'}</h1><p className="muted">Your documents. A clearer conversation.</p><form onSubmit={submit}>
 {register&&<label>Full name<input name="name" autoComplete="name" maxLength={200}/></label>}
 <label>Email<input name="email" type="email" autoComplete="email" required/></label>
 <label>Password<input name="password" type="password" autoComplete={register?'new-password':'current-password'} minLength={register?8:1} maxLength={128} required/></label>
 {(notice||location.state?.registered)&&<p role="status">Account created. Sign in to continue.</p>}{error&&<p className="error" role="alert">{error}</p>}
 <button className="primary" disabled={busy}>{busy?'Please wait…':register?'Create account':'Sign in'}</button></form>
 <p className="muted">{register?'Already have an account?':'New here?'} <Link to={register?'/login':'/signup'}>{register?'Sign in':'Create account'}</Link></p></div></div>
}
