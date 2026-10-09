import { useRef,useState } from 'react'
import type { DragEvent } from 'react'
export function useFileDrop(onFiles:(files:File[])=>void,disabled:boolean){const depth=useRef(0);const [dragging,setDragging]=useState(false)
 const isFile=(e:DragEvent)=>Array.from(e.dataTransfer.types).includes('Files')
 return {dragging,handlers:{onDragEnter:(e:DragEvent)=>{if(!isFile(e))return;e.preventDefault();depth.current++;setDragging(true)},onDragOver:(e:DragEvent)=>{if(!isFile(e))return;e.preventDefault();e.dataTransfer.dropEffect=disabled?'none':'copy'},onDragLeave:(e:DragEvent)=>{e.preventDefault();depth.current=Math.max(0,depth.current-1);if(!depth.current)setDragging(false)},onDrop:(e:DragEvent)=>{e.preventDefault();depth.current=0;setDragging(false);if(!disabled&&e.dataTransfer.files.length)onFiles(Array.from(e.dataTransfer.files))}}}
}
