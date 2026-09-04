import { Navigate, Route, Routes } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import Investigation from './pages/Investigation'

/** Two screens: the case list, and the investigation workspace. */
export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Dashboard />} />
      <Route path="/investigations/:id" element={<Investigation />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
