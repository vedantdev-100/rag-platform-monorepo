import { ArtifactsScreen } from '../features/documents/screens/ArtifactsScreen'
import { Navigate,Route,Routes } from 'react-router'
import { Protected } from './guards/Protected'
import { Workspace } from './layouts/Workspace'
import { AuthScreen } from '../features/auth/screens/AuthScreen'
import { ChatScreen } from '../features/chat/screens/ChatScreen'
import { AdminScreen } from '../features/admin/screens/AdminScreen'
export function AppRoutes(){return <Routes><Route path="/" element={<Navigate to="/chat" replace/>}/><Route path="/login" element={<AuthScreen/>}/><Route path="/signup" element={<AuthScreen register/>}/><Route element={<Protected/>}><Route element={<Workspace/>}><Route path="/artifacts" element={<ArtifactsScreen/>}/><Route path="/chat" element={<ChatScreen/>}/><Route path="/chat/:conversationId" element={<ChatScreen/>}/><Route element={<Protected admin/>}><Route path="/admin/users" element={<AdminScreen/>}/></Route></Route></Route><Route path="*" element={<main className="welcome"><h1>Page not found</h1><a href="/chat">Return to chat</a></main>}/></Routes>}
