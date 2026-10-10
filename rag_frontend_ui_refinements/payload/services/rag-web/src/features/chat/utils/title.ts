export function shortChatTitle(question:string,limit=44):string{
 const text=question.replace(/\s+/g,' ').trim();const chars=Array.from(text)
 if(chars.length<=limit)return text||'New chat'
 const cut=chars.slice(0,limit-1).join('');const space=cut.lastIndexOf(' ')
 return (space>=Math.floor(limit*.6)?cut.slice(0,space):cut).trimEnd()+'…'
}
