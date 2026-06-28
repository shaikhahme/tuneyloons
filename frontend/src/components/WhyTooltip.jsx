import { useState } from 'react'

export default function WhyTooltip({ reason }) {
  const [visible, setVisible] = useState(false)

  return (
    <div style={{ position: 'relative', display: 'inline-block' }}>
      <button
        className="why-btn"
        onMouseEnter={() => setVisible(true)}
        onMouseLeave={() => setVisible(false)}
        onFocus={() => setVisible(true)}
        onBlur={() => setVisible(false)}
        aria-label="Why was this recommended?"
        type="button"
      >
        ?
      </button>
      {visible && (
        <div className="why-tooltip" role="tooltip">
          {reason}
        </div>
      )}
    </div>
  )
}
