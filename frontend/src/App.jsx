import { Routes, Route } from 'react-router-dom'
import PromptPage from './pages/PromptPage'
import GraphPage from './pages/GraphPage'
import AquariumBackground from './components/AquariumBackground'

export default function App() {
  return (
    <>
      <div className="ocean-bg" />
      <AquariumBackground />
      <Routes>
        <Route path="/" element={<PromptPage />} />
        <Route path="/graph" element={<GraphPage />} />
      </Routes>
    </>
  )
}
