function buildChipSuffix(filters) {
  const parts = []
  if (filters.mood?.length) parts.push('Mood: ' + filters.mood.join(', '))
  if (filters.mainGenre?.length) parts.push('Genre: ' + filters.mainGenre.join(', '))
  if (filters.tempo?.length) parts.push('Tempo: ' + filters.tempo.join(', '))
  if (filters.vocals?.length) parts.push('Vocals: ' + filters.vocals.join(', '))
  return parts.length ? ' [' + parts.join('; ') + ']' : ''
}

function mapPlaylist(playlist) {
  return playlist.map(item => ({
    id: item.track.id,
    title: item.track.title,
    artist: item.track.artist,
    confidence: item.score,
    tags: {
      moodAdvanced: item.track.moods || [],
      mainGenre: item.track.genre ? [item.track.genre] : [],
    },
    reason: [item.why_song, item.why_position].filter(Boolean).join(' '),
  }))
}

function bpmToTempo(bpm) {
  if (!bpm || bpm <= 0) return ''
  if (bpm < 90) return 'slow'
  if (bpm <= 120) return 'medium'
  return 'fast'
}

function computeEdgeDelta(src, tgt) {
  if (!src || !tgt) return ''
  const parts = []

  // BPM
  if (src.bpm > 0 && tgt.bpm > 0) {
    const d = Math.round(tgt.bpm - src.bpm)
    if (d !== 0) parts.push(`${d > 0 ? '+' : ''}${d}bpm`)
  }

  // Energy (only show if diff >= 0.05)
  const ed = tgt.energy - src.energy
  if (Math.abs(ed) >= 0.05) parts.push(`${ed > 0 ? '+' : ''}${ed.toFixed(2)} energy`)

  // Tempo (only if changed)
  const st = bpmToTempo(src.bpm), tt = bpmToTempo(tgt.bpm)
  if (st && tt && st !== tt) parts.push(`${st}→${tt}`)

  // Mood additions (+) and removals (-)
  const srcM = new Set(src.moods || [])
  const tgtM = new Set(tgt.moods || [])
  tgtM.forEach(m => { if (!srcM.has(m)) parts.push(`+${m}`) })
  srcM.forEach(m => { if (!tgtM.has(m)) parts.push(`-${m}`) })

  return parts.join(' · ')
}

function mapGraph(graph, playlist) {
  const scoreById = {}
  playlist.forEach(item => { scoreById[item.track.id] = item.score })

  const nodes = graph.nodes.map(node => ({
    id: node.id,
    title: node.label.replace(/^\d+\.\s*/, ''),
    artist: node.artist,
    confidence: scoreById[node.id] ?? 0.8,
    energy: node.energy,
    genre: node.genre,
    type: node.type,
    bpm: node.bpm ?? 0,
    musical_key: node.musical_key ?? '',
    moods: node.moods ?? [],
  }))

  const nodeById = {}
  nodes.forEach(n => { nodeById[n.id] = n })

  const edges = graph.edges.map(edge => {
    const delta = computeEdgeDelta(nodeById[edge.source], nodeById[edge.target])
    const llm = edge.transition_explanation || ''
    const label = llm
      ? (delta ? `${llm} (${delta})` : llm)
      : (delta ? `(${delta})` : edge.type || '')
    return {
      source: edge.source,
      target: edge.target,
      strength: edge.transition_score ?? 0.5,
      label,
    }
  })

  return { nodes, edges }
}

function mapResponse(raw) {
  return {
    graph: mapGraph(raw.graph, raw.playlist),
    recommendations: mapPlaylist(raw.playlist),
    alternativeRecommendations: mapPlaylist(raw.alternative_playlist),
    counterfactualExplanation: raw.counterfactual_explanation,
    intent: raw.intent,
  }
}

/**
 * Generate a set list via the SSE streaming endpoint.
 *
 * @param {{ prompt: string, filters: object }} params
 * @param {(message: string) => void} onProgress  — called for each progress event
 * @returns {Promise<object>}  mapped frontend data shape
 */
export async function generateSetList({ prompt, filters }, onProgress = () => {}) {
  const fullPrompt = prompt + buildChipSuffix(filters)

  const response = await fetch('/api/generate_playlist/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt: fullPrompt }),
  })

  if (!response.ok) {
    throw new Error('Backend error ' + response.status)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { value, done } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })

    // SSE events are delimited by double newline
    const events = buffer.split('\n\n')
    buffer = events.pop() // keep last partial event

    for (const block of events) {
      if (!block.trim()) continue
      let eventType = 'message'
      let eventData = ''

      for (const line of block.split('\n')) {
        if (line.startsWith('event: ')) eventType = line.slice(7).trim()
        else if (line.startsWith('data: ')) eventData = line.slice(6).trim()
      }

      if (!eventData) continue

      if (eventType === 'progress') {
        try { onProgress(JSON.parse(eventData).message) } catch {}
      } else if (eventType === 'result') {
        return mapResponse(JSON.parse(eventData))
      } else if (eventType === 'error') {
        let msg = eventData
        try { msg = JSON.parse(eventData).message } catch {}
        throw new Error(msg)
      }
    }
  }

  throw new Error('Stream ended without a result.')
}
