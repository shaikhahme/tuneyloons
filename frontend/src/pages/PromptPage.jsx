import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import FilterChip from '../components/FilterChip'

const FILTER_CHIPS = [
  { label: 'Dreamy',        type: 'mood',      value: 'dreamy' },
  { label: 'Warm',          type: 'mood',      value: 'warm' },
  { label: 'Energetic',     type: 'mood',      value: 'energetic' },
  { label: 'Nostalgic',     type: 'mood',      value: 'nostalgic' },
  { label: 'Electronic',    type: 'mainGenre', value: 'electronic' },
  { label: 'Pop',           type: 'mainGenre', value: 'pop' },
  { label: 'Medium Fast',   type: 'tempo',     value: 'mediumFast' },
  { label: 'Female Vocals', type: 'vocals',    value: 'female' },
  { label: 'Instrumental',  type: 'vocals',    value: 'instrumental' },
]

const EXAMPLE_PROMPT =
  'Build me a warm, nostalgic, medium-fast set list for a beachside evening event. Start calm and acoustic, gradually become upbeat, and end with something emotional but feel-good.'

export default function PromptPage() {
  const navigate = useNavigate()
  const [prompt, setPrompt] = useState('')
  const [activeChips, setActiveChips] = useState(new Set())
  const [loading, setLoading] = useState(false)

  function toggleChip(value) {
    setActiveChips(prev => {
      const next = new Set(prev)
      if (next.has(value)) next.delete(value)
      else next.add(value)
      return next
    })
  }

  async function handleGenerate() {
    if (!prompt.trim()) return
    setLoading(true)
    // Store prompt + chips in sessionStorage for GraphPage
    const filters = {}
    activeChips.forEach(v => {
      const chip = FILTER_CHIPS.find(c => c.value === v)
      if (!chip) return
      if (!filters[chip.type]) filters[chip.type] = []
      filters[chip.type].push(v)
    })
    sessionStorage.setItem('sla_prompt', prompt)
    sessionStorage.setItem('sla_filters', JSON.stringify(filters))
    navigate('/graph')
  }

  function handleExample() {
    setPrompt(EXAMPLE_PROMPT)
  }

  return (
    <main className="page1-wrapper">
      <div className="glass-panel prompt-card">
        <div className="app-logo-row">
          <span className="logo-icon" aria-hidden="true">🐠</span>
          <h1 className="app-title">Song Aquarium</h1>
        </div>

        <p className="app-subtitle">
          Describe the mood, flow, genre, and energy of your ideal set list.
          The app will turn your idea into a connected song map.
        </p>

        <textarea
          className="prompt-textarea"
          placeholder="Example: Build me a warm, nostalgic, medium-fast set list for a beachside evening event. Start calm and acoustic, gradually become upbeat, and end with something emotional but feel-good."
          value={prompt}
          onChange={e => setPrompt(e.target.value)}
          rows={5}
          aria-label="Describe your set list"
        />

        <div>
          <div className="chips-section-label">Optional vibes</div>
          <div className="chips-wrap">
            {FILTER_CHIPS.map(chip => (
              <FilterChip
                key={chip.value}
                label={chip.label}
                type={chip.type}
                active={activeChips.has(chip.value)}
                onToggle={() => toggleChip(chip.value)}
              />
            ))}
          </div>
        </div>

        <div className="btn-row">
          <button
            className="btn-primary"
            onClick={handleGenerate}
            disabled={!prompt.trim() || loading}
            type="button"
          >
            {loading ? 'Generating...' : 'Generate Set List Map'}
          </button>
          <button
            className="btn-secondary"
            onClick={handleExample}
            type="button"
          >
            Try Example Prompt
          </button>
        </div>
      </div>
    </main>
  )
}
