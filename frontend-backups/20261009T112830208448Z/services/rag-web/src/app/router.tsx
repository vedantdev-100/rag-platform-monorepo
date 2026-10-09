import { Navigate, Route, Routes } from 'react-router'
import { ChatScreen } from '../features/chat/screens/ChatScreen'

function Placeholder({ title }: { title: string }) {
    return (
        <main className="mx-auto max-w-lg px-6 py-16">
            <h1 className="text-2xl font-semibold">{title}</h1>
            <p className="mt-3 text-neutral-500">
                Screen implementation follows in the next step.
            </p>
        </main>
    )
}

export function AppRoutes() {
    return (
        <Routes>
            <Route path="/" element={<Navigate to="/chat" replace />} />
            <Route path="/login" element={<Placeholder title="Login" />} />
            <Route path="/signup" element={<Placeholder title="Signup" />} />

            <Route path="/chat" element={<ChatScreen />} />
            <Route
                path="/chat/:conversationId"
                element={<ChatScreen />}
            />

            <Route
                path="/admin/users"
                element={<Placeholder title="Admin users — not connected" />}
            />

            <Route path="*" element={<Placeholder title="Page not found" />} />
        </Routes>
    )
}