import { test } from 'node:test'
import assert from 'node:assert/strict'
import { consumeSSE } from '../src/shared/api/sse.ts'
function response(parts:string[]){const encoder=new TextEncoder();return new Response(new ReadableStream({start(c){for(const part of parts)c.enqueue(encoder.encode(part));c.close()}}),{headers:{'Content-Type':'text/event-stream'}})}
test('handles chunk boundaries, CRLF and heartbeats',async()=>{const seen:unknown[]=[];await consumeSSE(response([': heartbeat\r','\n\r\nevent: delta\r\ndata: {"text":','"hello"}\r','\n\r\nevent: done\ndata: {}\n\n']),e=>seen.push(e));assert.deepEqual(seen,[{event:'delta',data:{text:'hello'}},{event:'done',data:{}}])})
test('does not dispatch unterminated events',async()=>{const seen:unknown[]=[];await consumeSSE(response(['event: done\ndata: {}']),e=>seen.push(e));assert.equal(seen.length,0)})
test('supports multiline data',async()=>{const seen:unknown[]=[];await consumeSSE(response(['data: {\ndata: "a":1}\n\n']),e=>seen.push(e));assert.deepEqual(seen,[{event:'message',data:{a:1}}])})
test('rejects malformed JSON',async()=>{await assert.rejects(consumeSSE(response(['data: broken\n\n']),()=>{}))})
test('propagates consumer errors',async()=>{await assert.rejects(consumeSSE(response(['event: error\ndata: {}\n\n']),()=>{throw new Error('controlled')}),/controlled/)})
test('terminal event stops reading before a later transport failure',async()=>{
 let cancelled=false
 const r=new Response(new ReadableStream({start(c){c.enqueue(new TextEncoder().encode('event: done\ndata: {"status":"completed"}\n\n'))},pull(){throw new Error('late transport failure')},cancel(){cancelled=true}}),{headers:{'Content-Type':'text/event-stream'}})
 const seen:unknown[]=[]
 await consumeSSE(r,e=>{seen.push(e);return e.event==='done'})
 assert.deepEqual(seen,[{event:'done',data:{status:'completed'}}])
})
test('ignores subsequent events after terminal callback',async()=>{
 const seen:unknown[]=[]
 await consumeSSE(response(['event: done\ndata: {}\n\nevent: error\ndata: {}\n\n']),e=>{seen.push(e.event);return true})
 assert.deepEqual(seen,['done'])
})

import { fileProblem,appendDocument } from '../src/features/documents/utils/files.ts'
test('rejects empty and unsupported uploads',()=>{assert.ok(fileProblem({name:'a.txt',size:0}));assert.ok(fileProblem({name:'a.exe',size:100}));assert.equal(fileProblem({name:'Report.PDF',size:100}),null)})
test('attachment preserves existing selections and deduplicates',()=>{assert.deepEqual(appendDocument(['a','b'],'c'),['a','b','c']);assert.deepEqual(appendDocument(['a','b'],'a'),['a','b']);assert.deepEqual(appendDocument(null,'a'),['a'])})
import { shortChatTitle } from '../src/features/chat/utils/title.ts'
test('chat title normalizes whitespace and preserves short questions',()=>{assert.equal(shortChatTitle('  Who owns\n Atlas?  '),'Who owns Atlas?');assert.equal(shortChatTitle('  '),'New chat')})
test('chat title remains short without breaking unicode characters',()=>{const title=shortChatTitle('Explain the ownership history of Atlas and describe all of the supporting documents');assert.ok(Array.from(title).length<=44);assert.ok(title.endsWith('…'));assert.ok(Array.from(shortChatTitle('😀'.repeat(60))).length<=44)})

import { advanceStreamText } from '../src/features/chat/utils/streamText.ts'
import { userInitials } from '../src/features/auth/utils/initials.ts'
test('stream easing converges exactly without splitting unicode',()=>{const target='Atlas 😀 ownership '+ 'evidence '.repeat(60);let current='';for(let i=0;i<20&&current!==target;i++){const next=advanceStreamText(current,target);assert.ok(target.startsWith(next));assert.ok(next.length>current.length);current=next}assert.equal(current,target);assert.equal(advanceStreamText(current,''),'')})
test('avatar initials use a name or email fallback',()=>{assert.equal(userInitials('Mira Shah','a@b.com'),'MS');assert.equal(userInitials(null,'mira@example.com'),'MI');assert.equal(userInitials('  Mira  ','a@b.com'),'MI')})
