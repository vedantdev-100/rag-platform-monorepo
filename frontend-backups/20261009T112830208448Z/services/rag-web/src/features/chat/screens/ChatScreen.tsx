import { Link, useParams } from 'react-router'

export function ChatScreen() {
    const { conversationId } = useParams<{
        conversationId: string
    }>()

    return (
        <main className="mx-auto max-w-3xl px-6 py-12">
            <Link to="/chat" className="text-sm text-neutral-500">
                New chat
            </Link>

            <h1 className="mt-8 text-2xl font-semibold">
                {conversationId ? 'Conversation' : 'What can I help with?'}
            </h1>

            <p className="mt-3 text-neutral-500">
                {conversationId
                    ? `Conversation ID: ${conversationId}`
                    : 'Upload documents and start a conversation.'}
            </p>
        </main>
    )
}