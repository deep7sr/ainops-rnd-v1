// The engineer's name, remembered on this computer for reviews and inventory changes (there is
// no login in the POC). Storage can be blocked (private window): then it is simply asked again.

const NAME_KEY = 'ainops.reviewer'

export function savedName(): string {
  try {
    return window.localStorage.getItem(NAME_KEY) ?? ''
  } catch {
    return ''
  }
}

export function rememberName(name: string) {
  try {
    window.localStorage.setItem(NAME_KEY, name)
  } catch {
    // blocked storage: nothing to do
  }
}
