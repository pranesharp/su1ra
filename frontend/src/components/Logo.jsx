export default function Logo({ size = 20 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 128 128" aria-hidden="true" style={{ flexShrink: 0 }}>
      <rect x="3" y="3" width="122" height="122" rx="20" fill="#0b0b0e" stroke="#26262c" strokeWidth="5" />
      <rect x="32" y="32" width="64" height="64" fill="var(--accent)" />
      <text
        x="64"
        y="67"
        textAnchor="middle"
        dominantBaseline="middle"
        fontFamily="ui-monospace, Menlo, Consolas, monospace"
        fontWeight="800"
        fontSize="36"
        fill="#ffffff"
      >
        1s
      </text>
    </svg>
  )
}
