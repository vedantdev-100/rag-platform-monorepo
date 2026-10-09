import { useTheme } from '../store/theme'
export function ThemeToggle(){const {theme,toggle}=useTheme();return <button className="theme-toggle" type="button" onClick={toggle} aria-label="Dark mode" aria-pressed={theme==='dark'}>{theme==='dark'?'☀ Light mode':'☾ Dark mode'}</button>}
