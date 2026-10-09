export const acceptedFiles='.pdf,.docx,.pptx,.html,.htm,.md,.txt'
export function fileProblem(file:{name:string;size:number}):string|null{
 if(file.size===0)return 'This file is empty.'
 if(!/\.(pdf|docx|pptx|html?|md|txt)$/i.test(file.name))return 'Use PDF, DOCX, PPTX, HTML, Markdown or text.'
 return null
}

export function appendDocument(ids:string[]|null,id:string){return [...new Set([...(ids??[]),id])]}
