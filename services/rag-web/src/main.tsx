import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import App from './app/App'
import { ErrorBoundary } from './shared/errors/ErrorBoundary'
import './styles/globals.css'
createRoot(document.getElementById('root')!).render(<StrictMode><ErrorBoundary><BrowserRouter><App/></BrowserRouter></ErrorBoundary></StrictMode>)
