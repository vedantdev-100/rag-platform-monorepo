import { lazy,Suspense } from 'react'
import { Navigate,Route,Routes } from 'react-router'
import { Protected } from './guards/Protected'
import { LoadingScreen } from '../shared/components/LoadingScreen'
const Workspace=lazy(()=>import('./layouts/Workspace').then(m=>({default:m.Workspace})))
const AuthScreen=lazy(()=>import('../features/auth/screens/AuthScreen').then(m=>({default:m.AuthScreen})))
const ChatScreen=lazy(()=>import('../features/chat/screens/ChatScreen').then(m=>({default:m.ChatScreen})))
const ArtifactsScreen=lazy(()=>import('../features/documents/screens/ArtifactsScreen').then(m=>({default:m.ArtifactsScreen})))
const AdminScreen=lazy(()=>import('../features/admin/screens/AdminScreen').then(m=>({default:m.AdminScreen})))
export function AppRoutes(){return <Suspense fallback={<LoadingScreen/>}><Routes><Route path="/" element={<Navigate to="/chat" replace/>}/><Route path="/login" element={<AuthScreen/>}/><Route path="/signup" element={<AuthScreen register/>}/><Route element={<Protected/>}><Route element={<Workspace/>}><Route path="/artifacts" element={<ArtifactsScreen/>}/><Route path="/chat" element={<ChatScreen/>}/><Route path="/chat/:conversationId" element={<ChatScreen/>}/><Route element={<Protected admin/>}><Route path="/admin/users" element={<AdminScreen/>}/></Route></Route></Route><Route path="*" element={<main className="welcome"><h1>Page not found</h1><a href="/chat">Return to chat</a></main>}/></Routes></Suspense>}
