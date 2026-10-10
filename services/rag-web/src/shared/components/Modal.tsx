import { useEffect,useId,useRef } from 'react'
import type { ReactNode } from 'react'
export function Modal({open,title,onClose,children}:{open:boolean;title:string;onClose:()=>void;children:ReactNode}){
 const ref=useRef<HTMLDialogElement>(null);const label=useId();const outside=useRef(false)
 useEffect(()=>{const el=ref.current;if(!el)return;if(open&&!el.open)el.showModal();if(!open&&el.open)el.close();return()=>{if(el.open)el.close()}},[open])
 function isOutside(x:number,y:number){const r=ref.current!.getBoundingClientRect();return x<r.left||x>r.right||y<r.top||y>r.bottom}
 return <dialog ref={ref} className="app-modal" aria-labelledby={label} onCancel={e=>{e.preventDefault();onClose()}} onPointerDown={e=>{outside.current=isOutside(e.clientX,e.clientY)}} onClick={e=>{if(outside.current&&isOutside(e.clientX,e.clientY))onClose();outside.current=false}}><div className="modal-content"><div className="row"><h2 id={label}>{title}</h2><button type="button" aria-label="Close dialog" onClick={onClose}>×</button></div>{children}</div></dialog>
}
