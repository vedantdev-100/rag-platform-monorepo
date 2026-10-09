import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Message,Source } from '../types'
export function MessageView({message,onSource}:{message:Message;onSource:(s:Source)=>void}){
 return <article className={'message '+message.role}><div className="message-label">{message.role==='user'?'You':'Workspace'}</div><div className="prose"><ReactMarkdown remarkPlugins={[remarkGfm]} components={{img:({alt})=><span>[Image: {alt}]</span>,a:({href,children})=><a href={href} target="_blank" rel="noopener noreferrer">{children}</a>}}>{message.content||`Response ${message.status}`}</ReactMarkdown></div>
 <div className="sources">{message.answer?.sources.map(s=><button key={s.label} onClick={()=>onSource(s)}>{s.label} ↗</button>)}</div>{message.status!=='completed'&&<small className="muted">{message.status}</small>}</article>
}
