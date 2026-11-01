import { useEffect, useState } from 'react';
import { Check, Copy, ExternalLink, Plug, X } from 'lucide-react';

const MCP_URL = import.meta.env.VITE_MCP_URL;
const API = import.meta.env.VITE_APP_API_URL;

// Claude's documented install link: opens "Add custom connector" with the name and URL filled in.
const INSTALL_URL = MCP_URL
  ? `https://claude.ai/customize/connectors?modal=add-custom-connector&connectorName=BullRun&connectorUrl=${encodeURIComponent(MCP_URL)}`
  : null;

const STEPS = [
  'Click "Add to Claude" and confirm with Add (if asked how Claude should register, pick "Register automatically").',
  'Click Connect next to BullRun and sign in with the same Google account you use here.',
  'In a Claude chat, turn BullRun on from the + menu → Connectors, and ask away.',
];

const EXAMPLES = [
  "What's on my BullRun watchlist?",
  'How is my BullRun portfolio doing today?',
  'Add PLTR to my BullRun watchlist',
  "Using BullRun, summarize Apple's latest risk factors with citations",
];

export default function ClaudeConnectModal({ open, onClose, user }) {
  const [copied, setCopied] = useState(false);
  const [connection, setConnection] = useState(null);

  useEffect(() => {
    if (!open || !user?.token) return undefined;
    const check = () => fetch(`${API}/api/user`, { headers: { Authorization: `Bearer ${user.token}` } })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => setConnection(d?.mcpConnection || null))
      .catch(() => {});
    check();
    const id = setInterval(check, 5000); // flips to "Connected" once you finish signing in from Claude
    return () => clearInterval(id);
  }, [open, user?.token]);

  if (!open) return null;

  const copy = async () => {
    try {
      await window.navigator.clipboard.writeText(MCP_URL);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // clipboard blocked; the URL is selectable
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4" onClick={onClose} role="presentation">
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions, jsx-a11y/click-events-have-key-events */}
      <div className="w-full max-w-lg bg-white rounded-lg shadow-xl" onClick={(e) => e.stopPropagation()} role="dialog"
        aria-modal="true" aria-labelledby="claude-connect-title">
        <div className="flex items-start justify-between px-5 pt-5">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-md bg-green-50 text-green-700 flex items-center justify-center">
              <Plug className="w-4 h-4" />
            </div>
            <div>
              <h2 id="claude-connect-title" className="text-sm font-bold text-gray-900">Use BullRun in Claude</h2>
              <p className="text-[11px] text-gray-500">Your portfolio, watchlist and filings research, right inside Claude.</p>
            </div>
          </div>
          <button onClick={onClose} aria-label="Close" className="p-1 text-gray-400 hover:text-gray-600 cursor-pointer">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="px-5 py-4 space-y-4">
          <div className={`text-[11px] rounded-md px-3 py-2 ${connection ? 'bg-green-50 text-green-800' : 'bg-gray-50 text-gray-600'}`}>
            {connection
              ? <>Connected{connection.client ? ` from ${connection.client}` : ''} on {new Date(connection.at).toLocaleString()}.</>
              : 'Not connected yet. It takes about a minute.'}
          </div>

          {INSTALL_URL && (
            <a href={INSTALL_URL} target="_blank" rel="noreferrer"
              className="flex items-center justify-center gap-1.5 w-full py-2 text-sm font-semibold rounded-md bg-green-600 text-white hover:bg-green-700">
              <Plug className="w-4 h-4" /> {connection ? 'Add to Claude again' : 'Add to Claude'}
            </a>
          )}

          <ol className="space-y-1.5 text-xs text-gray-700 list-decimal pl-4">
            {STEPS.map((s) => <li key={s}>{s}</li>)}
          </ol>

          <div>
            <div className="text-[11px] font-medium text-gray-500 mb-1">Or add it by hand with this server URL</div>
            {MCP_URL ? (
              <div className="flex gap-1.5">
                <input readOnly value={MCP_URL} onFocus={(e) => e.target.select()}
                  className="flex-1 min-w-0 px-2 py-1.5 text-xs font-mono border border-gray-200 rounded-md bg-gray-50" />
                <button onClick={copy}
                  className="inline-flex items-center gap-1 px-2.5 py-1.5 text-xs rounded-md bg-green-600 text-white hover:bg-green-700 cursor-pointer">
                  {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
                  {copied ? 'Copied' : 'Copy'}
                </button>
              </div>
            ) : (
              <p className="text-xs text-gray-500">Available on the deployed app.</p>
            )}
          </div>

          <a href="https://claude.ai/customize/connectors" target="_blank" rel="noreferrer"
            className="inline-flex items-center gap-1 text-xs font-medium text-green-700 hover:underline">
            Open Claude connector settings <ExternalLink className="w-3 h-3" />
          </a>

          <div>
            <div className="text-[11px] font-medium text-gray-500 mb-1">Then try</div>
            <div className="flex flex-wrap gap-1.5">
              {EXAMPLES.map((q) => (
                <span key={q} className="text-[10px] px-2 py-1 rounded-full border border-green-200 text-green-800 bg-green-50">{q}</span>
              ))}
            </div>
          </div>

          <p className="text-[10px] text-gray-400 leading-snug">
            Claude only sees your own BullRun data after you sign in, and asks your permission before using BullRun&apos;s tools.
            You can disconnect anytime from Claude&apos;s connector settings.
          </p>
        </div>
      </div>
    </div>
  );
}
