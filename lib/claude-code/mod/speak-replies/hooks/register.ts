import type { Register } from 'claude-code'

const SPEAK = '@HOME@/.local/share/claude-tts/speak.py'

const INSTRUCTION =
  'Voice mode: the user hears a short sound and a spoken line after each reply. End every reply with one line ' +
  '<spoken type="KIND">…</spoken>: one or two plain sentences (under 200 characters, no code, paths or markdown) ' +
  'saying what happened or what you need from the user, in the language of the reply. KIND is the one that best ' +
  'captures the core of the reply: yes (agreeing, confirming), no (declining, cannot, disagree), problem ' +
  '(error, failure, warning, something is wrong), success (task done, tests pass), uploaded (sent, pushed, ' +
  'published), downloaded (fetched, installed, received), question (you are asking the user something), ' +
  'collaborate (you are blocked and need the user to do or decide something), info (anything neutral).'

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'speak', description: 'Toggle spoken replies, or set volume: /speak 0-100' })

    return next(e)
  })

  on('command.run', { command: 'speak' }, async ($, e) => {
    const arg = String((e as any).args ?? (e as any).arguments ?? '').trim()
    const ran = await $.process.run(['python3', SPEAK, ...(arg ? ['--volume', arg] : ['--toggle'])])

    return { text: `Spoken replies: ${ran.stdout.trim() || 'toggled'}.` }
  }).catch(() => ({ text: 'Could not toggle spoken replies.' }))

  on('turn.complete', async ($, e, next) => {
    if (e.agentId === undefined && !e.isAborted && e.answer.trim() !== '') {
      await $.process.run(['python3', SPEAK], { stdin: e.answer, timeoutMs: 10_000 }).catch(() => undefined)
    }

    return next(e)
  })

  on('prompt.submit', async ($, e, next) => {
    await $.process.run(['python3', SPEAK, '--stop']).catch(() => undefined)

    return next(e)
  }).catch(($, e, next) => next(e))

  on('prompt.compose', async ($, e, next) => {
    const { sections } = await next(e)

    return { sections: [...sections, { id: 'speak-replies:spoken', text: INSTRUCTION, scope: 'session' }] }
  })
}
