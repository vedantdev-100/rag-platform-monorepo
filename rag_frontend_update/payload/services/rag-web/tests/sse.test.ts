import { test } from 'node:test'
import assert from 'node:assert/strict'
import { consumeSSE } from '../src/shared/api/sse.ts'
function response(parts:string[]){const encoder=new TextEncoder();return new Response(new ReadableStream({start(c){for(const part of parts)c.enqueue(encoder.encode(part));c.close()}}),{headers:{'Content-Type':'text/event-stream'}})}
test('handles chunk boundaries, CRLF and heartbeats',async()=>{const seen:unknown[]=[];await consumeSSE(response([': heartbeat\r','\n\r\nevent: delta\r\ndata: {"text":','"hello"}\r','\n\r\nevent: done\ndata: {}\n\n']),e=>seen.push(e));assert.deepEqual(seen,[{event:'delta',data:{text:'hello'}},{event:'done',data:{}}])})
test('does not dispatch unterminated events',async()=>{const seen:unknown[]=[];await consumeSSE(response(['event: done\ndata: {}']),e=>seen.push(e));assert.equal(seen.length,0)})
test('supports multiline data',async()=>{const seen:unknown[]=[];await consumeSSE(response(['data: {\ndata: "a":1}\n\n']),e=>seen.push(e));assert.deepEqual(seen,[{event:'message',data:{a:1}}])})
test('rejects malformed JSON',async()=>{await assert.rejects(consumeSSE(response(['data: broken\n\n']),()=>{}))})
test('propagates consumer errors',async()=>{await assert.rejects(consumeSSE(response(['event: error\ndata: {}\n\n']),()=>{throw new Error('controlled')}),/controlled/)})
