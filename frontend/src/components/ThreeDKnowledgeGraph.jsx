import { useRef, useEffect, useState, useCallback } from 'react'

let ForceGraph3D = null

async function loadForceGraph() {
  if (ForceGraph3D) return ForceGraph3D
  const mod = await import('react-force-graph-3d')
  ForceGraph3D = mod.default
  return ForceGraph3D
}

export default function ThreeDKnowledgeGraph({
  graphData,
  selectedId,
  showEdgeLabels,
  onNodeClick,
}) {
  const containerRef = useRef(null)
  const graphRef = useRef(null)
  const mountedRef = useRef(true)
  const [FG, setFG] = useState(null)
  const [dims, setDims] = useState({ width: 800, height: 600 })

  // react-force-graph-3d requires { nodes, links } — convert edges → links
  const fgData = graphData
    ? { nodes: graphData.nodes, links: graphData.links || graphData.edges || [] }
    : { nodes: [], links: [] }

  // Compute neighbor sets for dimming (use fgData.links, not graphData.edges)
  const { neighborIds, connectedEdges } = (() => {
    if (!selectedId) return { neighborIds: new Set(), connectedEdges: new Set() }
    const neighbors = new Set()
    const edges = new Set()
    fgData.links.forEach(e => {
      const src = typeof e.source === 'object' ? e.source.id : e.source
      const tgt = typeof e.target === 'object' ? e.target.id : e.target
      if (src === selectedId || tgt === selectedId) {
        neighbors.add(src)
        neighbors.add(tgt)
        edges.add(src + '->' + tgt)
      }
    })
    return { neighborIds: neighbors, connectedEdges: edges }
  })()

  // Load ForceGraph3D async
  useEffect(() => {
    mountedRef.current = true
    loadForceGraph().then(fg => {
      if (mountedRef.current) setFG(() => fg)
    })
    return () => { mountedRef.current = false }
  }, [])

  // Update container dims on resize
  useEffect(() => {
    const update = () => {
      if (containerRef.current) {
        setDims({
          width: containerRef.current.clientWidth,
          height: containerRef.current.clientHeight,
        })
      }
    }
    update()
    window.addEventListener('resize', update)
    return () => window.removeEventListener('resize', update)
  }, [])

  const nodeColor = useCallback((node) => {
    if (!selectedId) return '#47B5FF'
    if (node.id === selectedId) return '#A5F1E9'
    if (neighborIds.has(node.id)) return '#47B5FF'
    return '#1a4060'
  }, [selectedId, neighborIds])

  const nodeVal = useCallback((node) => {
    return 4 + node.confidence * 8
  }, [])

  const linkColor = useCallback((link) => {
    if (!selectedId) return 'rgba(71,181,255,0.35)'
    const src = typeof link.source === 'object' ? link.source.id : link.source
    const tgt = typeof link.target === 'object' ? link.target.id : link.target
    const key = src + '->' + tgt
    if (connectedEdges.has(key)) return 'rgba(165,241,233,0.85)'
    return 'rgba(71,181,255,0.08)'
  }, [selectedId, connectedEdges])

  const linkWidth = useCallback((link) => {
    if (!selectedId) return link.strength * 2
    const src = typeof link.source === 'object' ? link.source.id : link.source
    const tgt = typeof link.target === 'object' ? link.target.id : link.target
    const key = src + '->' + tgt
    if (connectedEdges.has(key)) return link.strength * 3
    return 0.3
  }, [selectedId, connectedEdges])

  const linkLabel = useCallback((link) => {
    return showEdgeLabels ? link.label : ''
  }, [showEdgeLabels])

  const handleNodeClick = useCallback((node) => {
    onNodeClick(node.id)
    // Camera zoom to node
    if (graphRef.current) {
      try {
        const dist = 120
        const coords = node
        graphRef.current.cameraPosition(
          { x: coords.x, y: coords.y, z: coords.z + dist },
          coords,
          800
        )
      } catch (e) {
        // ignore camera errors
      }
    }
  }, [onNodeClick])

  if (!FG) {
    return (
      <div className="loading-overlay">
        <div className="loading-bubble" />
        <div className="loading-text">Generating your song map...</div>
      </div>
    )
  }

  return (
    <div ref={containerRef} className="graph-canvas-host">
      <FG
        ref={graphRef}
        graphData={fgData}
        width={dims.width}
        height={dims.height}
        backgroundColor="rgba(0,0,0,0)"
        nodeId="id"
        nodeLabel="title"
        nodeColor={nodeColor}
        nodeVal={nodeVal}
        nodeOpacity={0.9}
        linkColor={linkColor}
        linkWidth={linkWidth}
        linkLabel={linkLabel}
        linkDirectionalParticles={2}
        linkDirectionalParticleWidth={1.5}
        linkDirectionalParticleColor={() => '#A5F1E9'}
        onNodeClick={handleNodeClick}
        nodeThreeObjectExtend={false}
      />
    </div>
  )
}
