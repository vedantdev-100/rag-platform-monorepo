export class RequestTimeout extends Error{constructor(){super('request_timeout');this.name='RequestTimeout'}}
export async function withDeadline<T>(operation:(signal:AbortSignal)=>Promise<T>,milliseconds:number,external?:AbortSignal):Promise<T>{
 const controller=new AbortController();let timedOut=false
 const abort=()=>controller.abort();if(external?.aborted)abort();else external?.addEventListener('abort',abort,{once:true})
 const timer=setTimeout(()=>{timedOut=true;controller.abort()},milliseconds)
 try{return await operation(controller.signal)}catch(e){if(timedOut)throw new RequestTimeout();throw e}finally{clearTimeout(timer);external?.removeEventListener('abort',abort)}
}
