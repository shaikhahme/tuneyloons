import { useMemo } from 'react'

const BUBBLE_CONFIG = [
  { size: 18, left: 5,  delay: 0,   duration: 12 },
  { size: 10, left: 12, delay: 2.5, duration: 9  },
  { size: 25, left: 22, delay: 5,   duration: 15 },
  { size: 8,  left: 35, delay: 1,   duration: 10 },
  { size: 14, left: 45, delay: 7,   duration: 13 },
  { size: 20, left: 55, delay: 3,   duration: 11 },
  { size: 9,  left: 63, delay: 8.5, duration: 14 },
  { size: 16, left: 72, delay: 0.5, duration: 8  },
  { size: 12, left: 82, delay: 4,   duration: 16 },
  { size: 22, left: 90, delay: 6,   duration: 12 },
  { size: 7,  left: 18, delay: 9,   duration: 10 },
  { size: 11, left: 50, delay: 11,  duration: 9  },
]

export default function AquariumBackground() {
  const bubbles = useMemo(() => BUBBLE_CONFIG, [])

  return (
    <div className="bubbles-container" aria-hidden="true">
      {bubbles.map((b, i) => (
        <div
          key={i}
          className="bubble"
          style={{
            width: b.size + 'px',
            height: b.size + 'px',
            left: b.left + '%',
            animationDelay: b.delay + 's',
            animationDuration: b.duration + 's',
          }}
        />
      ))}
    </div>
  )
}
