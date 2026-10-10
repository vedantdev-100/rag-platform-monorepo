export function userInitials(name:string|null,email:string):string{
 const words=(name?.trim()||email.split('@')[0]).split(/\s+/).filter(Boolean)
 return (words.length>1?Array.from(words[0])[0]+Array.from(words[words.length-1])[0]:Array.from(words[0]||'?').slice(0,2).join('')).toUpperCase()
}
