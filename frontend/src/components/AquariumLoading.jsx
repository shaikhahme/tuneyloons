const AQUARIUM_STEPS = [
  'Filling with water & calibrating the environment…',
  'Introducing the fauna…',
  'Neutralizing the pH…',
  'Curating your bubble collection…',
  'Setting the mood & ambiance…',
  'Mapping connections through the glass…',
]

function CheckIcon() {
  return (
    <svg className="step-check" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <polyline points="2.5,8.5 6,12 13.5,4" />
    </svg>
  )
}

function BubbleIcon() {
  return <span className="step-bubble-icon" aria-hidden="true" />
}

function DotIcon() {
  return <span className="step-dot" aria-hidden="true" />
}

export default function AquariumLoading({ stepIndex = 0 }) {
  return (
    <div className="loading-overlay" role="status" aria-live="polite" aria-label="Loading Song Aquarium">
      <div className="aquarium-loading-card">

        <div className="loading-title-row">
          <span className="loading-title-bubble" aria-hidden="true" />
          <span className="loading-title-text">Building your Song Aquarium</span>
        </div>

        <ol className="aquarium-steps" aria-label="Progress">
          {AQUARIUM_STEPS.map((text, i) => {
            const state = i < stepIndex ? 'done' : i === stepIndex ? 'active' : 'pending'
            return (
              <li key={i} className={`aquarium-step aquarium-step--${state}`}>
                <span className="aquarium-step-icon">
                  {state === 'done'   && <CheckIcon key={'ck-' + i} />}
                  {state === 'active' && <BubbleIcon />}
                  {state === 'pending' && <DotIcon />}
                </span>
                <span className="aquarium-step-text">{text}</span>
              </li>
            )
          })}
        </ol>

      </div>
    </div>
  )
}
