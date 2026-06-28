export default function FilterChip({ label, type, active, onToggle }) {
  return (
    <button
      className={'filter-chip ' + type + (active ? ' active' : '')}
      onClick={onToggle}
      aria-pressed={active}
      type="button"
    >
      {label}
    </button>
  )
}
