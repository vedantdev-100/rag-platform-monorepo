import { Navigate,Outlet,useLocation } from 'react-router'
import { useSession } from '../../features/auth/store/session'
export function Protected({admin=false}:{admin?:boolean}){
 const {ready,user}=useSession();const location=useLocation()
 if(!ready)return <div className="auth" role="status">Restoring your session…</div>
 if(!user)return <Navigate to="/login" state={{from:location.pathname}} replace/>
 if(admin&&user.role!=='admin')return <main className="admin"><h1>Access restricted</h1><p>This page is available to administrators only.</p></main>
 return <Outlet/>
}
