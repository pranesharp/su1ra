export default function ArtifactPane({ width, code, tab, onTab, onClose, onDownload, path }) {
  return (
    <aside className="ide-pane" style={{ width }}>
      <div className="ide-head">
        <span className="hash">#</span>
        <span className="ide-title">{path ? path : 'artifact'}</span>
        <span style={{ flex: 1 }} />
        <button className={'term-btn' + (tab === 'preview' ? ' on' : '')} onClick={() => onTab('preview')}>
          preview
        </button>
        <button className={'term-btn' + (tab === 'code' ? ' on' : '')} onClick={() => onTab('code')}>
          code
        </button>
        <button className="term-btn" onClick={onDownload}>
          download
        </button>
        <button className="term-btn" onClick={onClose}>
          close
        </button>
      </div>
      {tab === 'preview' ? (
        <iframe className="artifact-frame" sandbox="allow-scripts" srcDoc={code} title="artifact preview" />
      ) : (
        <pre className="artifact-code">{code}</pre>
      )}
      <div className="ide-status">// sandboxed preview — scripts run isolated from the app</div>
    </aside>
  )
}
