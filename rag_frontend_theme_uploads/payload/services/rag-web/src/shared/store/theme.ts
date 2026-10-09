import { create } from 'zustand'
type Theme='light'|'dark'
function initial():Theme{try{const stored=localStorage.getItem('rag-web-theme');if(stored==='light'||stored==='dark')return stored}catch{/* Storage may be disabled. */}return window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'}
function apply(theme:Theme){document.documentElement.dataset.theme=theme;document.documentElement.style.colorScheme=theme}
const theme=initial();apply(theme)
export const useTheme=create<{theme:Theme;toggle:()=>void}>((set,get)=>({theme,toggle:()=>{const next=get().theme==='dark'?'light':'dark';apply(next);try{localStorage.setItem('rag-web-theme',next)}catch{/* In-memory preference remains usable. */}set({theme:next})}}))
