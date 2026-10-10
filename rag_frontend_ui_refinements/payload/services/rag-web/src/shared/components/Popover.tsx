import { useEffect,useId,useRef,useState } from 'react'
import { createPortal } from 'react-dom'
import type { CSSProperties,ReactNode } from 'react'
export function Popover({label,trigger,children,className='',panelClass='',disabled=false}:{label:string;trigger:ReactNode;children:(close:()=>void)=>ReactNode;className?:string;panelClass?:string;disabled?:boolean}){
 const [open,setOpen]=useState(false);const [position,setPosition]=useState<CSSProperties>({visibility:'hidden'});const button=useRef<HTMLButtonElement>(null);const panel=useRef<HTMLDivElement>(null);const id=useId()
 useEffect(()=>{if(!open)return
 function place(){const b=button.current?.getBoundingClientRect();const p=panel.current;if(!b||!p)return;const width=Math.min(p.offsetWidth,window.innerWidth-24);const height=Math.min(p.offsetHeight,window.innerHeight-24);const above=b.bottom+height+8>window.innerHeight&&b.top>window.innerHeight/2;setPosition({left:Math.max(12,Math.min(b.right-width,window.innerWidth-width-12)),top:above?Math.max(12,b.top-height-8):Math.min(b.bottom+8,window.innerHeight-height-12),maxHeight:window.innerHeight-24,visibility:'visible'})}
 const close=()=>setOpen(false)
 function pointer(e:PointerEvent){if(!panel.current?.contains(e.target as Node)&&!button.current?.contains(e.target as Node))close()}
 function key(e:KeyboardEvent){if(e.key==='Escape'){e.preventDefault();close();button.current?.focus()}}
 place();const frame=requestAnimationFrame(()=>{place();panel.current?.focus()});const observer=new ResizeObserver(place);if(panel.current)observer.observe(panel.current)
 document.addEventListener('pointerdown',pointer);document.addEventListener('keydown',key);window.addEventListener('resize',place);window.addEventListener('scroll',place,true)
 return()=>{cancelAnimationFrame(frame);observer.disconnect();document.removeEventListener('pointerdown',pointer);document.removeEventListener('keydown',key);window.removeEventListener('resize',place);window.removeEventListener('scroll',place,true)}
 },[open])
 return <><button ref={button} type="button" className={className} aria-label={label} aria-expanded={open} aria-controls={open?id:undefined} aria-haspopup="dialog" disabled={disabled} onClick={()=>setOpen(v=>!v)}>{trigger}</button>{open&&createPortal(<div ref={panel} tabIndex={-1} id={id} role="dialog" aria-label={label} className={'popover '+panelClass} style={position} onBlur={e=>{const next=e.relatedTarget as Node|null;if(next&&!e.currentTarget.contains(next)&&!button.current?.contains(next))setOpen(false)}}>{children(()=>setOpen(false))}</div>,document.body)}</>
}
