import { useState } from 'react'

function App() {
  const [activeTab, setActiveTab] = useState('live');

  return (
    <div className="dashboard-container">
      {/* Sidebar */}
      <aside className="sidebar">
        <div className="sidebar-header">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
          </svg>
          Ai-SSS Admin
        </div>
        <div className="sidebar-nav">
          <div className={`nav-item ${activeTab === 'live' ? 'active' : ''}`} onClick={() => setActiveTab('live')}>Live Feeds</div>
          <div className={`nav-item ${activeTab === 'events' ? 'active' : ''}`} onClick={() => setActiveTab('events')}>Event Logs</div>
          <div className={`nav-item ${activeTab === 'faces' ? 'active' : ''}`} onClick={() => setActiveTab('faces')}>Known Faces</div>
          <div className={`nav-item ${activeTab === 'settings' ? 'active' : ''}`} onClick={() => setActiveTab('settings')}>Settings</div>
        </div>
      </aside>

      {/* Main Content */}
      <main className="main-content">
        <header className="topbar">
          <h2>{activeTab === 'live' ? 'Live Camera Feeds' : 'System Overview'}</h2>
          <div>
            <span className="status-badge status-active">System Online</span>
          </div>
        </header>

        <div className="dashboard-grid">
          {/* Main Camera View */}
          <div className="panel" style={{ gridRow: '1 / span 2' }}>
            <div className="panel-header">Camera 01 - Main Entrance</div>
            <div className="panel-body" style={{ display: 'flex', flexDirection: 'column' }}>
              <div className="camera-feed">
                <p>Waiting for WebSocket connection to FastAPI backend...</p>
                {/* In the future, we render an <img> tag connected to /api/v1/video_feed */}
              </div>
              <div style={{ marginTop: '20px', display: 'flex', gap: '20px' }}>
                <div><strong>FPS:</strong> 30.1</div>
                <div><strong>Resolution:</strong> 1080p</div>
                <div><strong>Threat Level:</strong> Low</div>
              </div>
            </div>
          </div>

          {/* Recent Events Panel */}
          <div className="panel">
            <div className="panel-header">Recent Events</div>
            <div className="panel-body">
              <div className="log-entry">
                <span>Subject identified: Jane Doe</span>
                <span className="status-badge status-active">Clear</span>
              </div>
              <div className="log-entry">
                <span>Unknown vehicle detected</span>
                <span className="status-badge status-active" style={{ color: 'var(--text-muted)', backgroundColor: '#222' }}>Log</span>
              </div>
              <div className="log-entry">
                <span>Suspicious lingering detected</span>
                <span className="status-badge status-alert">Alert</span>
              </div>
            </div>
          </div>

          {/* System Metrics Panel */}
          <div className="panel">
            <div className="panel-header">System Metrics</div>
            <div className="panel-body">
              <div style={{ marginBottom: '10px' }}><strong>CPU Usage:</strong> 42%</div>
              <div style={{ marginBottom: '10px' }}><strong>Memory:</strong> 2.4 GB / 16 GB</div>
              <div style={{ marginBottom: '10px' }}><strong>GPU:</strong> RTX 4090 - 31%</div>
              <div style={{ marginTop: '20px', fontSize: '0.9rem', color: 'var(--text-muted)' }}>
                YOLOv8x Pipeline: Active<br/>
                Face Recognizer DB: Connected
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}

export default App
