---
type: skill
title: Using session.unlock
description: Unlock for the current authorized work through the existing native session
  lock; trust only its verified result.
obsidience:
  tool: '[[Tools/session.unlock]]'
---

## Runtime

This optional capability is not granted by the shipped Executive. Enable it only after the local owner explicitly chooses voice/session unlock.

Call `session.unlock` once with `{}` when the owner asks to unlock the computer,
or when the current authorized work needs an unlocked desktop. No password or
prerequisite screenshot is needed. Report success only from its completed,
`locked:false` result. If `displays_awake:false`, distinguish successful
unlock from unverified screen wake. Stop on failed or uncertain delivery; do not replay.

## Reference

When explicitly enabled by this installation's owner, Voice and Chat use the
same operation. Normal spoken commands require Voice mode on. An audible
“unlock the computer” command does not provide speaker identity verification. Keep the native password prompt as the manual alternative.
After unlocking, obtain the fresh observation needed for any requested input;
unlocking does not itself authorize clicks, focus, launch or placement.
