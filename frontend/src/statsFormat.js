export function formatStats(s) {
  const lines = ['── stats ───────────────────────────']
  if (s.prompt_tokens) lines.push(`prompt   ${String(s.prompt_tokens).padStart(6)} tk${s.prompt_tps ? ` · ${s.prompt_tps} tk/s` : ''}`)
  if (s.think_tokens) lines.push(`think    ${String(s.think_tokens).padStart(6)} tk${s.think_tps ? ` · ${s.think_tps} tk/s` : ''}${s.think_time ? ` · ${s.think_time}s` : ''}`)
  if (s.output_tokens) lines.push(`output   ${String(s.output_tokens).padStart(6)} tk${s.output_tps ? ` · ${s.output_tps} tk/s` : ''}`)
  const tail = [
    s.ttft != null ? `ttft ${s.ttft}s` : null,
    s.total_time ? `total ${s.total_time}s` : null,
    s.eval_tps ? `avg ${s.eval_tps} tk/s` : null,
    s.model,
  ].filter(Boolean).join(' · ')
  lines.push(tail)
  return lines.join('\n')
}
