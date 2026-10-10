import { useEffect,useRef,useState } from 'react'
import { advanceStreamText } from '../utils/streamText'
export function useSmoothDraft(target:string){
 const [displayed,setDisplayed]=useState('');const value=useRef('')
 useEffect(()=>{
  if(!target){value.current='';setDisplayed('');return}
  if(window.matchMedia('(prefers-reduced-motion: reduce)').matches){value.current=target;setDisplayed(target);return}
  let frame=0
  function tick(){value.current=advanceStreamText(value.current,target);setDisplayed(value.current);if(value.current!==target)frame=requestAnimationFrame(tick)}
  frame=requestAnimationFrame(tick)
  return()=>cancelAnimationFrame(frame)
 },[target])
 return target?displayed:''
}
