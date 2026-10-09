export interface StreamEvent {event:string;data:unknown}
export async function consumeSSE(response:Response,onEvent:(e:StreamEvent)=>boolean|void){
 if(!response.headers.get('content-type')?.includes('text/event-stream'))throw new Error('Expected SSE')
 if(!response.body)throw new Error('Missing stream')
 const reader=response.body.getReader();const decoder=new TextDecoder();let buffer='';let name='message';let data:string[]=[];let stopped=false
 function line(text:string){
  if(text===''){if(data.length)stopped=onEvent({event:name,data:JSON.parse(data.join('\n'))})===true;name='message';data=[];return}
  if(text.startsWith(':'))return
  const colon=text.indexOf(':');const key=colon<0?text:text.slice(0,colon);let value=colon<0?'':text.slice(colon+1);if(value.startsWith(' '))value=value.slice(1)
  if(key==='event')name=value;if(key==='data')data.push(value)
 }
 try{while(true){const {value,done}=await reader.read();buffer+=decoder.decode(value,{stream:!done})
  while(!stopped){const i=buffer.search(/[\r\n]/);if(i<0)break;if(buffer[i]==='\r'&&i===buffer.length-1&&!done)break;const n=buffer[i]==='\r'&&buffer[i+1]==='\n'?2:1;line(buffer.slice(0,i));buffer=buffer.slice(i+n)}
  if(done||stopped)break
 }}finally{await reader.cancel().catch(()=>{});reader.releaseLock()}
}
