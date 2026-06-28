import { useRef, useEffect, useState, useCallback } from 'react'
import * as THREE from 'three'

let ForceGraph3D = null
let SpriteText = null

async function loadForceGraph() {
  if (ForceGraph3D) return ForceGraph3D
  const [fgMod, stMod] = await Promise.all([
    import('react-force-graph-3d'),
    import('three-spritetext'),
  ])
  ForceGraph3D = fgMod.default
  SpriteText = stMod.default
  return ForceGraph3D
}

const ZOOM_IN_DIST  = 150
const NUM_CURVE_PTS = 40
const ORBIT_RADIUS  = 90   // world-units between selected node and orbiting neighbors

// Position spring constants
const POS_K    = 0.072  // stiffness — higher = snappier
const POS_DAMP = 0.82   // damping   — higher = less bounce

// Scale spring constants
const SCL_K    = 0.10
const SCL_DAMP = 0.78

export default function ThreeDKnowledgeGraph({
  graphData,
  selectedId,
  showEdgeLabels,
  onNodeClick,
  onNodeHover,
}) {
  const containerRef = useRef(null)
  const graphRef     = useRef(null)
  const mountedRef   = useRef(true)
  const [FG, setFG]  = useState(null)
  const [dims, setDims] = useState({ width: 800, height: 600 })

  // Stable ref to fgData — lets effects read current data without dep-array churn
  const fgDataRef = useRef({ nodes: [], links: [] })

  // rAF-readable refs for selection state
  const selectedIdRef     = useRef(selectedId)
  const connectedEdgesRef = useRef(new Set())
  const neighborIdsRef    = useRef(new Set())

  // Spring state — mutated every frame by the rAF loop, set by the orbit effect
  // orbitRef.fixed:     Map<nodeId, {x,y,z}>  — nodes pinned at a world position
  // orbitRef.springing: Map<nodeId, {px,py,pz,vx,vy,vz,tx,ty,tz}> — nodes easing to target
  const orbitRef = useRef({ fixed: new Map(), springing: new Map() })

  // scaleRef: Map<nodeId, {cur, tgt, vel}> — per-node visual scale springs
  const scaleRef = useRef(new Map())

  // react-force-graph-3d requires { nodes, links }
  const fgData = graphData
    ? { nodes: graphData.nodes, links: graphData.links || graphData.edges || [] }
    : { nodes: [], links: [] }

  // Keep stable ref in sync
  useEffect(() => { fgDataRef.current = fgData })

  // Derive neighbor sets for material dimming
  const { neighborIds, connectedEdges } = (() => {
    if (!selectedId) return { neighborIds: new Set(), connectedEdges: new Set() }
    const neighbors = new Set()
    const edges     = new Set()
    fgData.links.forEach(e => {
      const src = typeof e.source === 'object' ? e.source.id : e.source
      const tgt = typeof e.target === 'object' ? e.target.id : e.target
      if (src === selectedId || tgt === selectedId) {
        neighbors.add(src); neighbors.add(tgt)
        edges.add(src + '->' + tgt)
      }
    })
    return { neighborIds: neighbors, connectedEdges: edges }
  })()

  useEffect(() => { selectedIdRef.current     = selectedId     }, [selectedId])
  useEffect(() => { connectedEdgesRef.current = connectedEdges }, [connectedEdges])
  useEffect(() => { neighborIdsRef.current    = neighborIds    }, [neighborIds])

  // Load ForceGraph3D async
  useEffect(() => {
    mountedRef.current = true
    loadForceGraph().then(fg => { if (mountedRef.current) setFG(() => fg) })
    return () => { mountedRef.current = false }
  }, [])

  // Container resize
  useEffect(() => {
    const update = () => {
      if (containerRef.current)
        setDims({ width: containerRef.current.clientWidth, height: containerRef.current.clientHeight })
    }
    update()
    window.addEventListener('resize', update)
    return () => window.removeEventListener('resize', update)
  }, [])

  // Scene lighting — once after FG mounts
  useEffect(() => {
    if (!FG || !graphRef.current) return
    const scene = graphRef.current.scene()
    if (!scene) return
    const ambient = new THREE.AmbientLight(0x224466, 1.5)
    const key     = new THREE.PointLight(0x7FEFFF, 3.5, 700)
    key.position.set(160, 160, 160)
    const fill    = new THREE.PointLight(0x0033AA, 1.8, 500)
    fill.position.set(-160, -80, -130)
    const rim     = new THREE.PointLight(0xCCFFFF, 1.2, 400)
    rim.position.set(0, 220, -120)
    scene.add(ambient, key, fill, rim)
  }, [FG])

  // Initialise scale spring for each node when data arrives
  useEffect(() => {
    scaleRef.current.clear()
    fgData.nodes.forEach(node => {
      scaleRef.current.set(node.id, { cur: 1.0, tgt: 1.0, vel: 0 })
    })
  }, [fgData.nodes]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Orbital focus effect ─────────────────────────────────────────────────
  // Fires on every selectedId change. Computes circular orbit layout for
  // immediate neighbors and smooth-targets the camera toward the selection.

  useEffect(() => {
    const graph = graphRef.current
    const { nodes, links } = fgDataRef.current

    // Always clear previous orbit state so released nodes become free again
    orbitRef.current.fixed.clear()
    orbitRef.current.springing.clear()

    // Reset all scale targets to 1
    scaleRef.current.forEach(s => { s.tgt = 1.0 })

    if (!selectedId || !graph) return

    const selectedNode = nodes.find(n => n.id === selectedId)
    if (!selectedNode || selectedNode.x == null) return

    // Pin selected node at its current position
    const sx = selectedNode.x, sy = selectedNode.y, sz = selectedNode.z
    orbitRef.current.fixed.set(selectedId, { x: sx, y: sy, z: sz })
    const selScale = scaleRef.current.get(selectedId)
    if (selScale) selScale.tgt = 1.38

    // Resolve immediate neighbors
    const neighborIdSet = new Set()
    links.forEach(link => {
      const src = typeof link.source === 'object' ? link.source.id : link.source
      const tgt = typeof link.target === 'object' ? link.target.id : link.target
      if (src === selectedId) neighborIdSet.add(tgt)
      if (tgt === selectedId) neighborIdSet.add(src)
    })
    const neighborNodes = nodes.filter(n => neighborIdSet.has(n.id))
    const N = neighborNodes.length

    // Arrange neighbors in a slightly tilted elliptical orbit
    neighborNodes.forEach((nbr, i) => {
      const angle = (2 * Math.PI * i) / Math.max(N, 1)
      const tx = sx + Math.cos(angle) * ORBIT_RADIUS
      const ty = sy + Math.sin(angle) * ORBIT_RADIUS * 0.60
      const tz = sz + Math.sin(angle * 2 + 0.5) * ORBIT_RADIUS * 0.28
      orbitRef.current.springing.set(nbr.id, {
        px: nbr.x ?? sx, py: nbr.y ?? sy, pz: nbr.z ?? sz,
        vx: 0, vy: 0, vz: 0,
        tx, ty, tz,
      })
      const ns = scaleRef.current.get(nbr.id)
      if (ns) ns.tgt = 1.06
    })

    // Dim unrelated nodes
    nodes.forEach(node => {
      if (node.id !== selectedId && !neighborIdSet.has(node.id)) {
        const ns = scaleRef.current.get(node.id)
        if (ns) ns.tgt = 0.62
      }
    })

    // Camera: slide to face the selected node from its current approach angle
    const cam = graph.camera()
    if (cam) {
      const nodeVec = new THREE.Vector3(sx, sy, sz)
      const dir     = nodeVec.clone().sub(cam.position).normalize()
      const newPos  = nodeVec.clone().sub(dir.multiplyScalar(ORBIT_RADIUS * 2.7))
      graph.cameraPosition(
        { x: newPos.x, y: newPos.y, z: newPos.z },
        { x: sx, y: sy, z: sz },
        1100,
      )
    }

    // Mildly reheat simulation so freed nodes re-settle naturally
    try { graph.d3ReheatSimulation() } catch (_) {}

  }, [selectedId, FG]) // FG in deps ensures graph is ready on first selection

  // ── Node visual objects ──────────────────────────────────────────────────

  const nodeVal = useCallback((node) => 4 + (node.confidence || 0.5) * 8, [])

  const nodeThreeObject = useCallback((node) => {
    const radius = Math.cbrt(4 + (node.confidence || 0.5) * 8) * 3.8
    const group  = new THREE.Group()
    node._group  = group  // stored so rAF can apply scale spring

    // Back-face shell adds interior depth illusion
    group.add(new THREE.Mesh(
      new THREE.SphereGeometry(radius, 32, 32),
      new THREE.MeshPhongMaterial({ color: 0x001833, transparent: true, opacity: 0.18, side: THREE.BackSide, depthWrite: false }),
    ))

    // Main translucent bubble wall
    const mainMat = new THREE.MeshPhongMaterial({
      color: 0x47D9FF, emissive: new THREE.Color(0x003344),
      shininess: 420, specular: new THREE.Color(0xCCFFFF),
      transparent: true, opacity: 0.20, side: THREE.FrontSide, depthWrite: false,
    })
    node._sphereMat = mainMat
    group.add(new THREE.Mesh(new THREE.SphereGeometry(radius, 32, 32), mainMat))

    // Rim glow halo
    const rimMat = new THREE.MeshBasicMaterial({
      color: 0x7FEFFF, transparent: true, opacity: 0.10, side: THREE.BackSide, depthWrite: false,
    })
    node._rimMat = rimMat
    group.add(new THREE.Mesh(new THREE.SphereGeometry(radius * 1.07, 24, 24), rimMat))

    // Glossy top-left highlight
    const hl = new THREE.Mesh(
      new THREE.SphereGeometry(radius * 0.25, 16, 16),
      new THREE.MeshBasicMaterial({ color: 0xFFFFFF, transparent: true, opacity: 0.72, depthWrite: false }),
    )
    hl.position.set(-radius * 0.36, radius * 0.38, radius * 0.68)
    hl.renderOrder = 2
    group.add(hl)

    // Inner air bubble (Y2K detail)
    const air = new THREE.Mesh(
      new THREE.SphereGeometry(radius * 0.10, 8, 8),
      new THREE.MeshBasicMaterial({ color: 0xEEFFFF, transparent: true, opacity: 0.42, depthWrite: false }),
    )
    air.position.set(radius * 0.28, -radius * 0.28, radius * 0.50)
    group.add(air)

    // Sprites
    const applyOverlay = s => {
      s.renderOrder = 999
      s.material.depthTest = false; s.material.depthWrite = false; s.material.needsUpdate = true
    }

    const farSprite = new SpriteText(node.title || node.id)
    Object.assign(farSprite, { color: 'rgba(210,244,255,0.92)', textHeight: 4, backgroundColor: 'rgba(0,14,38,0.60)', padding: 2, borderRadius: 3, fontFace: 'Comfortaa, Nunito, sans-serif' })
    applyOverlay(farSprite)

    const meta = [node.bpm ? `${Math.round(node.bpm)} BPM` : null, node.musical_key || null].filter(Boolean).join('  ·  ')
    const nearSprite = new SpriteText(meta ? `${node.title || node.id}\n${meta}` : (node.title || node.id))
    Object.assign(nearSprite, { color: 'rgba(220,248,255,0.97)', textHeight: 4, backgroundColor: 'rgba(0,14,38,0.76)', padding: 3, borderRadius: 4, fontFace: 'Comfortaa, Nunito, sans-serif', visible: false })
    applyOverlay(nearSprite)

    node._farSprite = farSprite; node._nearSprite = nearSprite

    const sg = new THREE.Group()
    sg.renderOrder = 999
    sg.add(farSprite, nearSprite)
    group.add(sg)

    return group
  }, [])

  // ── Curved arc edges ─────────────────────────────────────────────────────

  const linkThreeObject = useCallback((link) => {
    const positions = new Float32Array(NUM_CURVE_PTS * 3)
    const geo = new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.BufferAttribute(positions, 3))
    const mat = new THREE.LineBasicMaterial({ color: 0x7FEFFF, transparent: true, opacity: 0.22, depthWrite: false })
    link._arcMat = mat
    return new THREE.Line(geo, mat)
  }, [])

  const linkPositionUpdate = useCallback((lineObj, { start, end }) => {
    const A = new THREE.Vector3(start.x, start.y, start.z)
    const B = new THREE.Vector3(end.x, end.y, end.z)
    const mid = new THREE.Vector3().addVectors(A, B).multiplyScalar(0.5)
    const midLen = mid.length()
    const arcH   = Math.max(12, A.distanceTo(B) * 0.35)
    const ctrl = midLen < 0.5
      ? (Math.abs(A.x) < 0.9 ? new THREE.Vector3(1, 0, 0) : new THREE.Vector3(0, 1, 0)).multiplyScalar(arcH)
      : mid.clone().normalize().multiplyScalar(midLen + arcH)
    const pts = new THREE.QuadraticBezierCurve3(A, ctrl, B).getPoints(NUM_CURVE_PTS - 1)
    const arr = lineObj.geometry.attributes.position.array
    pts.forEach((p, i) => { arr[i*3] = p.x; arr[i*3+1] = p.y; arr[i*3+2] = p.z })
    lineObj.geometry.attributes.position.needsUpdate = true
    lineObj.geometry.computeBoundingSphere()
    return true
  }, [])

  const linkLabel = useCallback((link) => showEdgeLabels ? link.label : '', [showEdgeLabels])

  // ── Master rAF loop ───────────────────────────────────────────────────────
  // Runs every frame: position springs → scale springs → sprites → materials

  useEffect(() => {
    if (!FG) return
    let animId
    const tick = () => {
      if (graphRef.current) {
        const camera = graphRef.current.camera()
        if (camera) {
          const cp        = camera.position
          const selId     = selectedIdRef.current
          const connEdges = connectedEdgesRef.current
          const nbrs      = neighborIdsRef.current
          const orbit     = orbitRef.current

          fgData.nodes.forEach(node => {

            // ── Position spring ──────────────────────────────────────────
            if (orbit.fixed.has(node.id)) {
              const fp = orbit.fixed.get(node.id)
              // Write to both .x and .fx so the THREE object and force sim stay in sync
              node.fx = fp.x; node.x = fp.x
              node.fy = fp.y; node.y = fp.y
              node.fz = fp.z; node.z = fp.z
            } else if (orbit.springing.has(node.id)) {
              const s = orbit.springing.get(node.id)
              s.vx += (s.tx - s.px) * POS_K; s.vx *= POS_DAMP
              s.vy += (s.ty - s.py) * POS_K; s.vy *= POS_DAMP
              s.vz += (s.tz - s.pz) * POS_K; s.vz *= POS_DAMP
              s.px += s.vx; s.py += s.vy; s.pz += s.vz
              node.fx = s.px; node.x = s.px
              node.fy = s.py; node.y = s.py
              node.fz = s.pz; node.z = s.pz
            } else {
              // Free: let force simulation own this node
              node.fx = undefined; node.fy = undefined; node.fz = undefined
            }

            // ── Scale spring ─────────────────────────────────────────────
            const ss = scaleRef.current.get(node.id)
            if (ss && node._group) {
              ss.vel += (ss.tgt - ss.cur) * SCL_K
              ss.vel *= SCL_DAMP
              ss.cur  = Math.max(0.05, ss.cur + ss.vel)
              node._group.scale.setScalar(ss.cur)
            }

            // ── Sprite zoom-switching ────────────────────────────────────
            if (node._farSprite && node._nearSprite) {
              const dx = (node.x || 0) - cp.x, dy = (node.y || 0) - cp.y, dz = (node.z || 0) - cp.z
              const dist = Math.sqrt(dx*dx + dy*dy + dz*dz)
              const near = dist < ZOOM_IN_DIST
              node._farSprite.visible  = !near
              node._nearSprite.visible = near
              if (near) node._nearSprite.textHeight = Math.max(1.5, (dist / ZOOM_IN_DIST) * 5)
            }

            // ── Sphere material per selection state ──────────────────────
            if (node._sphereMat && node._rimMat) {
              if (!selId) {
                node._sphereMat.color.setHex(0x47D9FF); node._sphereMat.opacity = 0.20
                node._sphereMat.emissive.setHex(0x003344); node._rimMat.opacity = 0.10
              } else if (node.id === selId) {
                node._sphereMat.color.setHex(0x7FEFFF); node._sphereMat.opacity = 0.55
                node._sphereMat.emissive.setHex(0x006677); node._rimMat.opacity = 0.42
              } else if (nbrs.has(node.id)) {
                node._sphereMat.color.setHex(0x47D9FF); node._sphereMat.opacity = 0.28
                node._sphereMat.emissive.setHex(0x002233); node._rimMat.opacity = 0.14
              } else {
                node._sphereMat.color.setHex(0x001133); node._sphereMat.opacity = 0.06
                node._sphereMat.emissive.setHex(0x000000); node._rimMat.opacity = 0.02
              }
            }
          })

          // ── Arc edge colours ──────────────────────────────────────────
          fgData.links.forEach(link => {
            if (!link._arcMat) return
            const src = typeof link.source === 'object' ? link.source.id : link.source
            const tgt = typeof link.target === 'object' ? link.target.id : link.target
            const key = `${src}->${tgt}`
            if (!selId) {
              link._arcMat.color.setHex(0x7FEFFF); link._arcMat.opacity = 0.22
            } else if (connEdges.has(key)) {
              link._arcMat.color.setHex(0xC9F7FF); link._arcMat.opacity = 0.90
            } else {
              link._arcMat.color.setHex(0x7FEFFF); link._arcMat.opacity = 0.04
            }
          })
        }
      }
      animId = requestAnimationFrame(tick)
    }
    animId = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(animId)
  }, [FG, fgData.nodes, fgData.links]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!FG) {
    return (
      <div className="loading-overlay">
        <div className="loading-bubble" />
        <div className="loading-text">Generating your song map…</div>
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
        nodeVal={nodeVal}
        nodeThreeObject={nodeThreeObject}
        nodeThreeObjectExtend={false}
        linkThreeObject={linkThreeObject}
        linkPositionUpdate={linkPositionUpdate}
        linkThreeObjectExtend={false}
        linkLabel={linkLabel}
        onNodeClick={(node) => onNodeClick(node.id)}
        onNodeHover={(node) => onNodeHover?.(node ?? null)}
      />
    </div>
  )
}
