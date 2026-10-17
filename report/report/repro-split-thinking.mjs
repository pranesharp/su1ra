// Harness for ChatView.splitThinking — run with: node report/report/repro-split-thinking.mjs
// Extracts the REAL function from frontend/src/components/ChatView.jsx (no drift)
// and asserts which parts are think vs content. Markers are the backend's own
// <think> / </think> wrappers (ollama.py stream_chat, stored verbatim in app.db).

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..')
const src = readFileSync(join(root, 'frontend', 'src', 'components', 'ChatView.jsx'), 'utf8')

const start = src.indexOf('export function splitThinking')
if (start === -1) throw new Error('splitThinking not found in ChatView.jsx')
const end = src.indexOf('\n}\n', start)
if (end === -1) throw new Error('could not find end of splitThinking')
const fnSrc = src.slice(start, end + 3).replace('export function', 'function')
const splitThinking = new Function(`${fnSrc}; return splitThinking`)()

let failed = 0
let n = 0
function check(name, content, strictClose, expected) {
  n++
  let got
  try {
    got = splitThinking(content, strictClose)
  } catch (e) {
    console.log(`FAIL ${name}: threw ${e}`)
    failed++
    return
  }
  const norm = (p) => ({ think: p.think, text: p.text })
  const ok =
    got.length === expected.length &&
    got.every((p, i) => norm(p).think === expected[i].think && norm(p).text === expected[i].text)
  if (ok) {
    console.log(`PASS ${name}`)
  } else {
    failed++
    console.log(`FAIL ${name}`)
    console.log(`  content: ${JSON.stringify(content)}  strictClose=${strictClose}`)
    console.log(`  expected: ${JSON.stringify(expected)}`)
    console.log(`  got:      ${JSON.stringify(got.map(norm))}`)
  }
}

// 1. well-formed closed block (backend shape: "<think>\nR\n</think>\n\nA") —
//    think text must NOT start with stray "g>" litter, answer must NOT start
//    with stray ">\n" litter (the +8/+7 slice leak from the broken rewrite).
check(
  'closed block, no slice litter',
  '<think>\nReasoning line\n</think>\n\nYes, the answer.',
  true,
  [
    { think: true, text: '\nReasoning line\n' },
    { think: false, text: '\n\nYes, the answer.' },
  ],
)
check('closed block, same while streaming', '<think>\nReasoning line\n</think>\n\nYes, the answer.', false, [
  { think: true, text: '\nReasoning line\n' },
  { think: false, text: '\n\nYes, the answer.' },
])

// 2. reopened think after content (multi-block)
check(
  'reopened think after content',
  'Part one.\n<think>\nmore reasoning\n</think>\n\nPart two.',
  true,
  [
    { think: false, text: 'Part one.\n' },
    { think: true, text: '\nmore reasoning\n' },
    { think: false, text: '\n\nPart two.' },
  ],
)

// 3. THE BUG: unclosed think + blank line + answer (MiniCPM preamble / build
//    tool-stranded opener). Final render must collapse the reasoning AND keep
//    the answer visible; streaming keeps the lenient collapse-all rule.
check(
  'unclosed think + blank line + answer (final)',
  '<think>\nLet me work this out step by step.\n\nHere is the answer.',
  true,
  [
    { think: true, text: '\nLet me work this out step by step.' },
    { think: false, text: '\n\nHere is the answer.' },
  ],
)
check(
  'unclosed think + blank line + answer (streaming collapses all)',
  '<think>\nLet me work this out step by step.\n\nHere is the answer.',
  false,
  [{ think: true, text: '\nLet me work this out step by step.\n\nHere is the answer.' }],
)

// 3b. unclosed think with a MULTI-paragraph answer: the split lands on the
//     LAST blank line, so the tail paragraph of the answer stays visible.
check(
  'unclosed think, multi-paragraph answer (last blank line)',
  '<think>\nReasoning block.\n\nAnswer para one.\n\nAnswer para two.',
  true,
  [
    { think: true, text: '\nReasoning block.\n\nAnswer para one.' },
    { think: false, text: '\n\nAnswer para two.' },
  ],
)

// 4. unclosed think with NO answer / no blank line — collapse the whole thing.
check('unclosed think, no answer (final)', '<think>\nOnly reasoning, no answer', true, [
  { think: true, text: '\nOnly reasoning, no answer' },
])
check('unclosed think, no answer (streaming)', '<think>\nOnly reasoning, no answer', false, [
  { think: true, text: '\nOnly reasoning, no answer' },
])
// Multi-paragraph reasoning with no answer: last blank line splits, so the
// final paragraph surfaces as content — the documented trade-off of the
// last-boundary rule (leaks one paragraph rather than hiding a real answer).
check('unclosed multi-paragraph reasoning, no answer (final)', '<think>\nP1\n\nP2\n\nP3', true, [
  { think: true, text: '\nP1\n\nP2' },
  { think: false, text: '\n\nP3' },
])
check('unclosed multi-paragraph reasoning, no answer (streaming)', '<think>\nP1\n\nP2\n\nP3', false, [
  { think: true, text: '\nP1\n\nP2\n\nP3' },
])

// 5. prose that merely contains " thinking" mid-sentence — plain English is
//    untouched (the markers are the <think> wrappers, not the word).
check('prose with " thinking" mid-sentence', 'I was thinking about it, thinking hard.', true, [
  { think: false, text: 'I was thinking about it, thinking hard.' },
])
// A literal <think> in prose (unclosed, no blank line): tail collapses.
check('stray <think> in prose, unclosed', 'before the marker <think> stray tail', true, [
  { think: false, text: 'before the marker ' },
  { think: true, text: ' stray tail' },
])

// 6. think-only message (backend done-shape "\n</think>" with nothing after)
check('think-only message', '<think>\nJust reasoning\n</think>', true, [
  { think: true, text: '\nJust reasoning\n' },
])
check('think-only, empty answer after close', '<think>\nJust reasoning\n</think>\n\n', true, [
  { think: true, text: '\nJust reasoning\n' },
])

// 7. empty / null content
check('empty string', '', true, [])
check('null content', null, true, [])

// 8. default arg: splitThinking(content) === splitThinking(content, false)
{
  const c = '<think>\nR\n\nA'
  const a = splitThinking(c)
  const b = splitThinking(c, false)
  if (JSON.stringify(a) === JSON.stringify(b)) console.log('PASS default strictClose=false')
  else {
    failed++
    console.log(`FAIL default strictClose=false: ${JSON.stringify(a)} vs ${JSON.stringify(b)}`)
  }
  n++
}

// 9. artifact bridge (App.jsx): non-think parts joined must keep the answer
//    reachable for extractLastPythonBlock/extractLastHtmlBlock.
{
  const partial = '<think>\nI will build it.\n\n<html><body>hi</body></html>'
  const visible = splitThinking(partial, true)
    .filter((p) => !p.think)
    .map((p) => p.text)
    .join('\n')
  if (visible.includes('<html>')) {
    console.log('PASS artifact bridge keeps answer reachable')
  } else {
    failed++
    console.log(`FAIL artifact bridge keeps answer reachable: visible=${JSON.stringify(visible)}`)
  }
  n++
}

// 10. no raw markers ever survive into rendered parts (closed or split paths)
{
  const samples = [
    '<think>\nR\n</think>\n\nA',
    '<think>\nR\n\nA',
    'x <think> y',
    '<think>\nR\n</think>',
  ]
  const bad = samples.flatMap((c) => splitThinking(c, true)).filter((p) => /[<>]think/.test(p.text))
  if (bad.length === 0) console.log('PASS no raw markers in any output part')
  else {
    failed++
    console.log(`FAIL no raw markers: ${JSON.stringify(bad)}`)
  }
  n++
}

console.log(`\n${n - failed}/${n} passed`)
process.exit(failed ? 1 : 0)
