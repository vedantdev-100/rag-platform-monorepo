import { useEffect } from 'react'
import { restore } from '../features/auth/api/auth'
import { useSession } from '../features/auth/store/session'
import { AppRoutes } from './router'
import { LoadingScreen } from '../shared/components/LoadingScreen'
import { SignoutOverlay } from '../features/auth/components/SignoutOverlay'
export default function App(){
 const ready=useSession(s=>s.ready);const signingOut=useSession(s=>s.signingOut)
 useEffect(()=>{void restore()},[])
 return <><div inert={signingOut} aria-hidden={signingOut||undefined}>{ready?<AppRoutes/>:<LoadingScreen/>}</div>{signingOut&&<SignoutOverlay/>}</>
}
