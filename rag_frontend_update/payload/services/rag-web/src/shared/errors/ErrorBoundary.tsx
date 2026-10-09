import { Component } from 'react'
import type { ReactNode,ErrorInfo } from 'react'
import { logFailure } from '../logging/logger'
export class ErrorBoundary extends Component<{children:ReactNode},{failed:boolean}>{
 state={failed:false};static getDerivedStateFromError(){return {failed:true}}
 componentDidCatch(_error:Error,_info:ErrorInfo){logFailure('render')}
 render(){return this.state.failed?<main className="auth"><div><h1>Something went wrong</h1><button onClick={()=>window.location.reload()}>Reload workspace</button></div></main>:this.props.children}
}
