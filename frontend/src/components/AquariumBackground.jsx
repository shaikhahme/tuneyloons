import { useMemo } from 'react'

const BUBBLE_CONFIG = [
  { size: 18, left: 5,  delay: 0,   duration: 13 },
  { size: 10, left: 12, delay: 2.5, duration: 9  },
  { size: 26, left: 22, delay: 5,   duration: 16 },
  { size: 7,  left: 33, delay: 1,   duration: 10 },
  { size: 14, left: 44, delay: 7,   duration: 14 },
  { size: 21, left: 55, delay: 3,   duration: 12 },
  { size: 8,  left: 63, delay: 8.5, duration: 15 },
  { size: 16, left: 72, delay: 0.5, duration: 9  },
  { size: 12, left: 82, delay: 4,   duration: 17 },
  { size: 23, left: 90, delay: 6,   duration: 13 },
  { size: 6,  left: 18, delay: 9.5, duration: 11 },
  { size: 11, left: 50, delay: 11,  duration: 10 },
  { size: 4,  left: 38, delay: 13,  duration: 8  },
  { size: 9,  left: 68, delay: 14,  duration: 12 },
  { size: 15, left: 28, delay: 16,  duration: 14 },
]

const RAY_CONFIG = [
  { left: 10, delay: 0,   duration: 11, opacity: 0.07 },
  { left: 24, delay: 3.5, duration: 15, opacity: 0.045 },
  { left: 40, delay: 6,   duration: 12, opacity: 0.08 },
  { left: 56, delay: 1.5, duration: 14, opacity: 0.05 },
  { left: 70, delay: 4,   duration: 10, opacity: 0.065 },
  { left: 85, delay: 7.5, duration: 13, opacity: 0.04 },
]

export default function AquariumBackground() {
  const bubbles = useMemo(() => BUBBLE_CONFIG, [])
  const rays    = useMemo(() => RAY_CONFIG, [])

  return (
    <div className="bubbles-container" aria-hidden="true">
      {rays.map((r, i) => (
        <div
          key={'ray-' + i}
          className="light-ray"
          style={{
            left: r.left + '%',
            opacity: r.opacity,
            animationDelay: r.delay + 's',
            animationDuration: r.duration + 's',
          }}
        />
      ))}
      {bubbles.map((b, i) => (
        <div
          key={'bubble-' + i}
          className="bubble"
          style={{
            width:             b.size + 'px',
            height:            b.size + 'px',
            left:              b.left + '%',
            animationDelay:    b.delay + 's',
            animationDuration: b.duration + 's',
          }}
        />
      ))}
    </div>
  )
}
