/** Page-local monitoring. No model calls and no background scheduler. */
export function watchVisibleSnapshots(refresh: () => void, onVisibility: (visible: boolean) => void) {
  const changed = () => onVisibility(document.visibilityState === 'visible')
  changed()
  document.addEventListener('visibilitychange', changed)
  const timer = setInterval(() => {
    if (document.visibilityState === 'visible') refresh()
  }, 60000)
  return () => {
    clearInterval(timer)
    document.removeEventListener('visibilitychange', changed)
  }
}
