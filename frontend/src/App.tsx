import { Navigate, Route, Routes } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import Investigation from './pages/Investigation'

/**
 * Three screens: the case list, the results of an investigation, and the
 * graph of one.
 *
 * Results and graph are separate routes rather than a toggle inside one page.
 * They answer different questions - "what came back from each source" and
 * "how do these connect" - and an analyst moving between them wants the back
 * button, a bookmark and a link they can paste to someone else.
 */
export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Dashboard />} />
      <Route path="/investigations/:id" element={<Investigation view="list" />} />
      <Route
        path="/investigations/:id/graph"
        element={<Investigation view="graph" />}
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
