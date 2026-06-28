import WhyTooltip from './WhyTooltip'

function getTagChips(tags) {
  const chips = []
  if (tags.moodAdvanced && tags.moodAdvanced.length > 0) {
    chips.push({ label: tags.moodAdvanced[0], cls: 'mood-chip' })
  }
  if (tags.mainGenre && tags.mainGenre.length > 0) {
    chips.push({ label: tags.mainGenre[0], cls: '' })
  }
  return chips
}

export default function RecommendationPanel({
  recommendations,
  selectedId,
  onSelectSong,
  activeTab,
  onTabChange,
  counterfactualExplanation,
}) {
  const isPrimary = activeTab === 'primary'

  return (
    <div className="right-panel glass-panel-dark">
      <div className="panel-header">
        <div className="panel-title">Set List</div>
        <div className="panel-tabs">
          <button
            className={'panel-tab' + (isPrimary ? ' active' : '')}
            onClick={() => onTabChange('primary')}
            type="button"
          >
            Recommended
          </button>
          <button
            className={'panel-tab' + (!isPrimary ? ' active' : '')}
            onClick={() => onTabChange('alternative')}
            type="button"
          >
            Alternative
          </button>
        </div>
        {!isPrimary && counterfactualExplanation && (
          <div className="counterfactual-banner">
            {counterfactualExplanation}
          </div>
        )}
      </div>

      {recommendations.map((song, idx) => {
        const chips = getTagChips(song.tags)
        const isSelected = selectedId === song.id
        return (
          <div
            key={song.id}
            className={'song-row' + (isSelected ? ' selected' : '')}
            onClick={() => onSelectSong(song.id)}
            role="button"
            tabIndex={0}
            aria-pressed={isSelected}
            onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') onSelectSong(song.id) }}
          >
            <span className="song-num">{idx + 1}</span>
            <div className="song-info">
              <div className="song-name">{song.title}</div>
              <div className="song-artist">{song.artist}</div>
              <div className="song-chips">
                {chips.map((c, ci) => (
                  <span key={ci} className={'mini-chip ' + c.cls}>{c.label}</span>
                ))}
              </div>
              <div className="confidence-bar-bg">
                <div className="confidence-bar-fill" style={{ width: (song.confidence * 100) + '%' }} />
              </div>
            </div>
            <WhyTooltip reason={song.reason} />
          </div>
        )
      })}
    </div>
  )
}
