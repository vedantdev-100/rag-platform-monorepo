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
