import { useState, useCallback, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { generateSetList } from '../api/setlistApi'
import ThreeDKnowledgeGraph from '../components/ThreeDKnowledgeGraph'
import RecommendationPanel from '../components/RecommendationPanel'
import AquariumLoading from '../components/AquariumLoading'

const NUM_AQUARIUM_STEPS = 6

export default function GraphPage() {
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [selectedId, setSelectedId] = useState(null)
  const [showEdgeLabels, setShowEdgeLabels] = useState(false)
  const [activeTab, setActiveTab] = useState('primary')
  const [hoveredNode, setHoveredNode] = useState(null)
  const [loading, setLoading] = useState(true)
  const [stepIndex, setStepIndex] = useState(0)
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    const prompt = sessionStorage.getItem('sla_prompt') || 'dreamy aquarium set list'
    let filters = {}
    try { filters = JSON.parse(sessionStorage.getItem('sla_filters') || '{}') } catch {}

    function onProgress() {
      if (!mountedRef.current) return
      setStepIndex(prev => Math.min(prev + 1, NUM_AQUARIUM_STEPS - 1))
    }

    generateSetList({ prompt, filters }, onProgress).then(result => {
      if (mountedRef.current) {
        setData(result)
        setLoading(false)
      }
    }).catch(err => {
      if (mountedRef.current) {
        setError(err.message || 'Failed to generate set list.')
        setLoading(false)
      }
    })

    return () => { mountedRef.current = false }
  }, [])

  // Single source of truth for graph focus.
  // Resolves songId → graph node ID (exact match, then title fallback for
  // alternative-list songs that aren't directly in the graph) then toggles selection.
  const focusSongNode = useCallback((songId) => {
    setSelectedId(prev => {
      let graphId = data?.graph.nodes.find(n => n.id === songId)?.id
      if (!graphId && data) {
        const allTracks = [...(data.recommendations ?? []), ...(data.alternativeRecommendations ?? [])]
        const title = allTracks.find(t => t.id === songId)?.title
        if (title) graphId = data.graph.nodes.find(n => n.title === title)?.id
      }
      const next = graphId ?? songId
      return prev === next ? null : next
    })
  }, [data])

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
          <AquariumLoading stepIndex={stepIndex} />
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
            onNodeClick={focusSongNode}
            onNodeHover={setHoveredNode}
          />
        ) : null}

        {/* Controls overlay */}
        <div className="graph-controls">
          <div className="glass-panel-dark graph-controls-panel">
            <div className="graph-title">Song Aquarium</div>
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

        {hoveredNode && (
          <div className="glass-panel-dark node-hover-bar" aria-live="polite">
            {hoveredNode.bpm > 0 && <span><strong>BPM</strong> {Math.round(hoveredNode.bpm)}</span>}
            {hoveredNode.musical_key && <span><strong>Key</strong> {hoveredNode.musical_key}</span>}
            {hoveredNode.genre && <span><strong>Genre</strong> {hoveredNode.genre}</span>}
            {hoveredNode.moods?.length > 0 && <span><strong>Moods</strong> {hoveredNode.moods.join(', ')}</span>}
          </div>
        )}
      </div>

      {data && (
        <RecommendationPanel
          recommendations={activeList}
          selectedId={selectedId}
          onSelectSong={focusSongNode}
          activeTab={activeTab}
          onTabChange={setActiveTab}
          counterfactualExplanation={data.counterfactualExplanation}
        />
      )}
    </div>
  )
}
