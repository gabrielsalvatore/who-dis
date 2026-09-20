import { useEffect } from 'react'
import { CallerPanel } from './components/CallerPanel'
import { FamilyPanel } from './components/FamilyPanel'
import { useCall, useFamilyFeed } from './useCall'

function Header({ subtitle }: { subtitle: string }) {
  return (
    <header className="app-head">
      <div>
        <h1>WhoDis</h1>
        <p className="tagline">
          Screens suspicious conversations and gives a trusted family member the evidence to review.
        </p>
      </div>
      <p className="scope-note">{subtitle}</p>
    </header>
  )
}

/** Standalone family window, opened on a second screen or angled toward judges. */
function FamilyRoute() {
  const { call, health, offline } = useFamilyFeed(1000)
  return (
    <div className="app app-family">
      <Header subtitle="Family review window · updates automatically" />
      <FamilyPanel call={call} health={health} standalone offline={offline} />
    </div>
  )
}

function CallRoute() {
  const ctl = useCall()

  // Open with a live call so the demo can start immediately.
  useEffect(() => {
    void ctl.startCall()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="app">
      <Header subtitle="Turn-based browser voice prototype · synthetic scenarios only" />
      <main className="split">
        <CallerPanel ctl={ctl} />
        <FamilyPanel call={ctl.call} health={ctl.health} />
      </main>
      <footer className="app-foot">
        Prototype. Not a phone-network integration and not continuous live-call monitoring.
        WhoDis never verifies a caller's identity.
      </footer>
    </div>
  )
}

export default function App() {
  return window.location.pathname.startsWith('/family') ? <FamilyRoute /> : <CallRoute />
}
