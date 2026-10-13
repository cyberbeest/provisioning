import type { Register } from 'claude-code'

const SPEAK = '@HOME@/.local/share/claude-tts/speak.py'

const INSTRUCTION =
  'Voice mode: the user hears a short spoken line after each reply. End every reply with one line ' +
  '<spoken>…</spoken>: one or two plain sentences (under 200 characters, no code, paths or markdown) ' +
  'saying what happened or what you need from the user, in the language of the reply.'

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'voice', description: 'Toggle spoken replies on or off' })

    return next(e)
  })

  on('command.run', { command: 'voice' }, async $ => {
    const ran = await $.process.run(['python3', SPEAK, '--toggle'])

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
