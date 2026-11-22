import { useEffect, useState } from 'react'
import { routeFromHash, VIEW_HOME } from '../lib/nav'

/** The page (and view inside it) in the URL hash, so links and the back button work. */
export function useRoute() {
  const [route, setRoute] = useState(routeFromHash)
  useEffect(() => {
    const onHash = () => { setRoute(routeFromHash()) }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  // `id` may be a view (watchlist, detection): it opens the page that holds it.
  const setPage = (id, nextView = null) => {
    const home = VIEW_HOME[id] || id
    const v = nextView || (VIEW_HOME[id] ? id : null)
    setRoute({ page: home, view: v })
    window.history.pushState(null, '', `#/${home}${v ? `?view=${v}` : ''}`)
  }
  return { page: route.page, view: route.view, setPage }
}
