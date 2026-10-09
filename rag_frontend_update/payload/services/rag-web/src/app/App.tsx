import { useEffect } from 'react'
import { restore } from '../features/auth/api/auth'
import { useSession } from '../features/auth/store/session'
import { AppRoutes } from './router'
export default function App(){const ready=useSession(s=>s.ready);useEffect(()=>{void restore()},[]);return ready?<AppRoutes/>:<main className="auth" role="status">Restoring your session…</main>}
