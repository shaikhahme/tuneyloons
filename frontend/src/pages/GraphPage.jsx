import { useState, useCallback, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { generateSetList } from '../api/setlistApi'
import ThreeDKnowledgeGraph from '../components/ThreeDKnowledgeGraph'
import RecommendationPanel from '../components/RecommendationPanel'

const PIPELINE_STEPS = [
  'Extracting your vibe\u2026',
  'Searching the catalog\u2026',
  'Curating tracks for your set\u2026',
  'Analysing audio features & writing explanations\u2026',
  'Mapping connections in the knowledge graph\u2026',
]

export default function GraphPage() {
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [selectedId, setSelectedId] = useState(null)
  const [showEdgeLabels, setShowEdgeLabels] = useState(false)
  const [activeTab, setActiveTab] = useState('primary')
  const [loading, setLoading] = useState(true)
  const [completedSteps, setCompletedSteps] = useState([])
  const [currentStep, setCurrentStep] = useState('')
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    const prompt = sessionStorage.getItem('sla_prompt') || 'dreamy aquarium set list'
    let filters = {}
    try { filters = JSON.parse(sessionStorage.getItem('sla_filters') || '{}') } catch {}

    function onProgress(message) {
      if (!mountedRef.current) return
      setCompletedSteps(prev => currentStep ? [...prev, currentStep] : prev)
      setCurrentStep(message)
    }

    generateSetList({ prompt, filters }, onProgress).then(result => {
      if (mountedRef.current) {
        setData(result)
        setLoading(false)
        setCurrentStep('')
      }
    }).catch(err => {
      if (mountedRef.current) {
        setError(err.message || 'Failed to generate set list.')
        setLoading(false)
        setCurrentStep('')
      }
    })

    return () => { mountedRef.current = false }
  }, [])

  const handleNodeClick = useCallback((id) => {
    setSelectedId(prev => prev === id ? null : id)
  }, [])

  const handleSelectSong = useCallback((id) => {
    setSelectedId(prev => prev === id ? null : id)
  }, [])

  const breadcrumb = (() => {
    if (!selectedId || !data) return null
    const node = data.graph.nodes.find(n => n.id === selectedId)
    if (!node) return null
    const neighbors = new Set()
    data.graph.edges.forEach(e => {
      const src = typeof e.source === 'object' ? e.source.id : e.source
      const tgt = typeof e.target === 'object' ? e.target.id : e.target
      if (src === selectedId) neighbors.add(tgt)
      if (tgt === selectedId) neighbors.add(src)
    })
    const neighborNames = [...neighbors]
      .map(id => data.graph.nodes.find(n => n.id === id))
      .filter(Boolean)
      .map(n => n.title)
      .join(', ')
    return 'Selected: ' + node.title + (neighborNames ? ' \u2192 ' + neighborNames : '')
  })()

  const activeList = data
    ? (activeTab === 'alternative' ? data.alternativeRecommendations : data.recommendations)
    : []

  return (
    <div className="page2-wrapper">
      <div className="graph-area">
        {loading ? (
          <div className="loading-overlay">
            <div className="pipeline-progress">
              <div className="pipeline-title">Building your set list\u2026</div>
              <div className="pipeline-steps">
                {completedSteps.map((step, i) => (
                  <div key={i} className="pipeline-step done">
                    <span className="step-icon">&#10003;</span>
                    <span className="step-text">{step}</span>
                  </div>
                ))}
                {currentStep ? (
                  <div className="pipeline-step active">
                    <span className="step-icon step-spinner" />
                    <span className="step-text">{currentStep}</span>
                  </div>
                ) : null}
                {PIPELINE_STEPS.filter(
                  s => !completedSteps.includes(s) && s !== currentStep
                ).map((step, i) => (
                  <div key={'pending-' + i} className="pipeline-step pending">
                    <span className="step-icon">&#8226;</span>
                    <span className="step-text">{step}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        ) : error ? (
          <div className="loading-overlay">
            <div className="loading-text">{error}</div>
            <button
              className="btn-secondary"
              style={{ marginTop: '16px' }}
              onClick={() => navigate('/')}
              type="button"
            >
              Go Back
            </button>
          </div>
        ) : data ? (
          <ThreeDKnowledgeGraph
            graphData={data.graph}
            selectedId={selectedId}
            showEdgeLabels={showEdgeLabels}
            onNodeClick={handleNodeClick}
          />
        ) : null}

        {/* Controls overlay */}
        <div className="graph-controls">
          <div className="glass-panel-dark graph-controls-panel">
            <div className="graph-title">Set List Aquarium</div>
            <div className="toggle-row">
              <div
                className={'toggle-switch' + (showEdgeLabels ? ' on' : '')}
                onClick={() => setShowEdgeLabels(v => !v)}
                role="switch"
                aria-checked={showEdgeLabels}
                tabIndex={0}
                onKeyDown={e => {
                  if (e.key === 'Enter' || e.key === ' ') setShowEdgeLabels(v => !v)
                }}
              >
                <div className="toggle-knob" />
              </div>
              <span>Show relationship labels</span>
            </div>
          </div>
          <button className="back-btn" onClick={() => navigate('/')} type="button">
            &larr; New Prompt
          </button>
        </div>

        {breadcrumb && (
          <div className="glass-panel-dark breadcrumb-bar" aria-live="polite">
            {breadcrumb}
          </div>
        )}
      </div>

      {data && (
        <RecommendationPanel
          recommendations={activeList}
          selectedId={selectedId}
          onSelectSong={handleSelectSong}
          activeTab={activeTab}
          onTabChange={setActiveTab}
          counterfactualExplanation={data.counterfactualExplanation}
        />
      )}
    </div>
  )
}
