// Catch up within a few frames, preserving Unicode code points and exact text.
export function advanceStreamText(displayed:string,target:string):string{
 if(!target.startsWith(displayed))return target
 const remaining=Array.from(target.slice(displayed.length))
 if(!remaining.length)return target
 return displayed+remaining.slice(0,Math.max(8,Math.ceil(remaining.length/2))).join('')
}
