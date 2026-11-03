import React, { useState, useRef, useEffect, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import { useQueryClient } from '@tanstack/react-query';
import remarkGfm from 'remark-gfm';
import {
  MessageSquare, Send, ChevronRight, ChevronLeft, Loader2, Check, X, Plus,
  LineChart, Newspaper, FileText, Briefcase, ListPlus, ArrowLeftRight, AlertTriangle, ThumbsUp, ThumbsDown, History, Trash2,
} from 'lucide-react';
import { AGENT_API_URL, streamAgent } from '../lib/agentStream';

const THREAD_KEY = 'br_chat_thread';
// Latency, tokens and trace id are for us, not users: shown locally, or on the live site with ?debug=1
// (remembered in this browser; ?debug=0 turns it off).
const DEV_INFO = (() => {
  try {
    const q = new URLSearchParams(window.location.search).get('debug');
    if (q !== null) window.localStorage.setItem('br_debug', q === '1' ? '1' : '0');
    return import.meta.env.DEV || window.localStorage.getItem('br_debug') === '1';
  } catch {
    return import.meta.env.DEV;
  }
})();
const now = () => new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
const uid = () => Math.random().toString(36).slice(2);

const WELCOME = {
  id: 'welcome',
  role: 'bot',
  text: "Hi! I'm **Spade**, BullRun's research agent. I can pull live quotes and news, search company filings (10-K, 10-Q, 8-K) with citations, analyse your portfolio, and update your watchlist or holdings (with your approval).",
  time: now(),
};

const SUGGESTIONS = [
  'How is my portfolio doing today?',
  'Why is NVDA moving?',
  "What risks does AAPL flag in its 10-K?",
  'Add AMD to my watchlist',
  'I bought 10 more NVDA',
];

const TOOL_META = {
  get_quote: { icon: LineChart, label: (a) => `Quote ${a?.ticker ?? ''}` },
  compare_tickers: { icon: LineChart, label: (a) => `Comparing ${(a?.tickers || []).join(', ')}` },
  get_news: { icon: Newspaper, label: (a) => `News for ${a?.ticker ?? ''}` },
  search_filings: { icon: FileText, label: (a) => `Searching ${a?.ticker ? a.ticker + ' ' : ''}filings` },
  get_portfolio: { icon: Briefcase, label: () => 'Reading your portfolio' },
  update_watchlist: { icon: ListPlus, label: () => 'Watchlist update' },
  update_holdings: { icon: ArrowLeftRight, label: () => 'Holdings update' },
};

const money = (n) => (n == null ? '—' : `$${Number(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`);
const sharesText = (p) => (p ? `${p.quantity} sh · avg ${money(p.avgCost)}` : 'none');

function HoldingsChanges({ changes }) {
  return (
    <div className="space-y-1">
      {(changes || []).map((c) => (
        <div key={c.symbol}>
          <div>
            {c.action === 'buy' ? 'Bought' : 'Sold'} <b>{c.shares} {c.symbol}</b> at <b>{money(c.price)}</b>
            {c.price_source === 'current price' && <span className="italic"> (current price)</span>}
          </div>
          <div className="text-amber-800">{sharesText(c.before)} → <b>{c.after ? sharesText(c.after) : 'sold out'}</b></div>
        </div>
      ))}
      <div className="text-amber-700 italic">Cash balance is not changed.</div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Presentational pieces
// ---------------------------------------------------------------------------
function ToolSteps({ steps }) {
  if (!steps?.length) return null;
  return (
    <div className="flex flex-wrap gap-1 mb-1.5">
      {steps.map((s) => {
        const meta = TOOL_META[s.name] || { icon: LineChart, label: () => s.name };
        const Icon = meta.icon;
        return (
          <span
            key={s.id}
            title={s.summary || ''}
            className={`inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-full border ${
              s.status === 'error' ? 'border-red-200 bg-red-50 text-red-700'
                : s.status === 'done' ? 'border-green-200 bg-green-50 text-green-800'
                : 'border-gray-200 bg-white text-gray-600'}`}
          >
            {s.status === 'running' ? <Loader2 className="w-2.5 h-2.5 animate-spin" /> : <Icon className="w-2.5 h-2.5" />}
            {meta.label(s.args)}
            {s.status === 'done' && s.summary && <span className="text-gray-500">· {s.summary}</span>}
          </span>
        );
      })}
    </div>
  );
}

function ApprovalCard({ approval, onDecide }) {
  if (!approval) return null;
  const pending = approval.state === 'pending';
  return (
    <div className="mt-2 border border-amber-200 bg-amber-50 rounded-md p-2 text-[11px] text-amber-900">
      {approval.type === 'approve_holdings' ? (
        <>
          <div className="font-semibold mb-1">Update your holdings?</div>
          <HoldingsChanges changes={approval.changes} />
        </>
      ) : (
        <>
          <div className="font-semibold mb-1">Approve watchlist change?</div>
          {approval.add?.length > 0 && <div>Add: <b>{approval.add.join(', ')}</b></div>}
          {approval.remove?.length > 0 && <div>Remove: <b>{approval.remove.join(', ')}</b></div>}
        </>
      )}
      {pending ? (
        <div className="flex gap-1.5 mt-2">
          <button onClick={() => onDecide(true)}
            className="inline-flex items-center gap-1 px-2 py-1 rounded bg-green-600 text-white hover:bg-green-700 cursor-pointer">
            <Check className="w-3 h-3" /> Approve
          </button>
          <button onClick={() => onDecide(false)}
            className="inline-flex items-center gap-1 px-2 py-1 rounded border border-gray-300 bg-white hover:bg-gray-50 cursor-pointer">
            <X className="w-3 h-3" /> Decline
          </button>
        </div>
      ) : (
        <div className="mt-1 italic">{approval.state === 'approved' ? 'Approved' : 'Declined'}</div>
      )}
    </div>
  );
}

function Citations({ citations, text }) {
  if (!citations?.length) return null;
  // Only list passages the answer actually cites (all of them if it cites none), grouped by filing.
  const cited = new Set((text || '').match(/\[S\d+\]/g)?.map((x) => x.slice(1, -1)) || []);
  const seen = new Set();
  const used = citations.filter((c) => (!cited.size || cited.has(c.id)) && !seen.has(c.id) && seen.add(c.id));
  const docs = [];
  for (const c of used) {
    const key = c.url || `${c.ticker}|${c.form}|${c.filed}`; // two 8-Ks can share a date
    let d = docs.find((x) => x.key === key);
    if (!d) docs.push((d = { key, title: `${c.ticker} ${c.form} filed ${c.filed}`, url: c.url, passages: [] }));
    d.passages.push(c);
  }
  return (
    <div className="mt-2 pt-1.5 border-t border-gray-200 space-y-1.5">
      <div className="text-[10px] font-semibold text-gray-500">Sources</div>
      {docs.map((d) => (
        <div key={d.key}>
          <a href={d.url} target="_blank" rel="noreferrer" className="text-[10px] font-medium text-green-700 hover:underline">
            {d.title} ↗
          </a>
          {d.passages.map((c) => (
            <p key={c.id} className="text-[10px] text-gray-500 leading-snug pl-2" title={c.snippet}>
              <span className="font-semibold text-gray-600">[{c.id}]</span> {c.section}
              {c.snippet ? <span className="italic"> · “{c.snippet}”</span> : null}
            </p>
          ))}
        </div>
      ))}
    </div>
  );
}

function Feedback({ msg, onRate }) {
  if (msg.role !== 'bot' || !msg.runId || msg.streaming) return null;
  const btn = (score, Icon, label) => (
    <button onClick={() => onRate(msg, score)} disabled={msg.rating != null} aria-label={label} title={label}
      className={`p-0.5 rounded cursor-pointer disabled:cursor-default ${msg.rating === score ? 'text-green-700' : 'text-gray-400 hover:text-gray-600'}`}>
      <Icon className="w-3 h-3" />
    </button>
  );
  return (
    <span className="inline-flex items-center gap-0.5 ml-1 align-middle">
      {btn(1, ThumbsUp, 'Helpful')}
      {btn(0, ThumbsDown, 'Not helpful')}
    </span>
  );
}

function Bubble({ msg, onDecide, onRate }) {
  const isUser = msg.role === 'user';
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div className="max-w-[88%]">
        {!isUser && (
          <div className="flex items-center gap-1.5 mb-1">
            <div className="w-5 h-5 bg-green-600 rounded-full flex items-center justify-center">
              <span className="text-white text-[8px] font-bold">BR</span>
            </div>
            <span className="text-[10px] font-medium text-gray-700">Spade</span>
          </div>
        )}
        <div className={`px-3 py-2 rounded-lg ${isUser ? 'bg-green-600 text-white ml-auto' : 'bg-gray-100 text-gray-800'}`}>
          {!isUser && <ToolSteps steps={msg.steps} />}
          {msg.error && (
            <div className="flex items-center gap-1 text-[11px] text-red-700"><AlertTriangle className="w-3 h-3" />{msg.error}</div>
          )}
          {msg.text ? (
            <div className="text-xs leading-relaxed prose-chat">
              {/* react-markdown renders safely: no raw HTML from the model reaches the DOM. */}
              <ReactMarkdown remarkPlugins={[remarkGfm]}
                components={{
                  a: (p) => <a {...p} target="_blank" rel="noreferrer" className="underline" />,
                  table: (p) => <table {...p} className="text-[10px] my-1 border-collapse" />,
                  th: (p) => <th {...p} className="border border-gray-300 px-1 text-left" />,
                  td: (p) => <td {...p} className="border border-gray-300 px-1" />,
                  ul: (p) => <ul {...p} className="list-disc ml-4" />,
                  ol: (p) => <ol {...p} className="list-decimal ml-4" />,
                }}>
                {msg.text}
              </ReactMarkdown>
            </div>
          ) : msg.streaming && !msg.approval ? (
            <div className="flex items-center gap-2">
              <Loader2 className="w-3 h-3 animate-spin text-green-600" />
              <span className="text-xs text-gray-500">Spade is researching...</span>
            </div>
          ) : null}
          {!isUser && <ApprovalCard approval={msg.approval} onDecide={onDecide} />}
          {!isUser && <Citations citations={msg.citations} text={msg.text} />}
        </div>
        <p className="text-[9px] text-gray-400 mt-0.5 px-1">
          {msg.time}
          {DEV_INFO && msg.meta && ` · ${(msg.meta.latency_ms / 1000).toFixed(1)}s · ${msg.meta.usage.input_tokens + msg.meta.usage.output_tokens} tokens`}
          {DEV_INFO && msg.runId && !msg.streaming && <span title={`Trace ${msg.runId}`}> · ref {msg.runId.slice(0, 8)}</span>}
          <Feedback msg={msg} onRate={onRate} />
        </p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------
function Chatbot({ isOpen, setIsOpen, user }) {
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState([WELCOME]);
  const [busy, setBusy] = useState(false);
  const [threadId, setThreadId] = useState(() => {
    try { return sessionStorage.getItem(THREAD_KEY) || null; } catch { return null; }
  });
  const [showHistory, setShowHistory] = useState(false);
  const [threads, setThreads] = useState([]);
  const endRef = useRef(null);
  const abortRef = useRef(null);
  const authHeaders = user?.token ? { Authorization: `Bearer ${user.token}` } : {};

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);
  useEffect(() => () => abortRef.current?.abort(), []);

  const loadThread = useCallback((id) => {
    fetch(`${AGENT_API_URL}/api/agent/threads/${id}`, { headers: authHeaders })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        setMessages([WELCOME, ...(data?.messages || []).map((m) => ({
          id: uid(), role: m.role === 'user' ? 'user' : 'bot', text: m.text, time: '',
        }))]);
      })
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.token]);

  // Restore the open conversation after a page reload.
  useEffect(() => {
    if (threadId && messages.length === 1) loadThread(threadId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.token]);

  const openHistory = () => {
    setShowHistory((v) => !v);
    fetch(`${AGENT_API_URL}/api/agent/threads`, { headers: authHeaders })
      .then((r) => (r.ok ? r.json() : { threads: [] }))
      .then((data) => setThreads(data.threads || []))
      .catch(() => setThreads([]));
  };

  const openThread = (id) => {
    abortRef.current?.abort();
    setThreadId(id);
    try { sessionStorage.setItem(THREAD_KEY, id); } catch { /* storage unavailable */ }
    setShowHistory(false);
    setMessages([WELCOME]);
    loadThread(id);
  };

  const deleteThread = (id) => {
    setThreads((prev) => prev.filter((x) => x.id !== id));
    fetch(`${AGENT_API_URL}/api/agent/threads/${id}`, { method: 'DELETE', headers: authHeaders }).catch(() => {});
    if (id === threadId) newChat();
  };

  const queryClient = useQueryClient();

  const patch = useCallback((id, fn) => {
    setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, ...fn(m) } : m)));
  }, []);

  const handlerFor = useCallback((botId) => (event, data) => {
    switch (event) {
      case 'thread':
        setThreadId(data.thread_id);
        if (data.run_id) patch(botId, () => ({ runId: data.run_id }));
        try { sessionStorage.setItem(THREAD_KEY, data.thread_id); } catch { /* storage unavailable */ }
        break;
      case 'token':
        patch(botId, (m) => ({ text: (m.text || '') + data.text }));
        break;
      case 'tool_start':
        patch(botId, (m) => ({ steps: [...(m.steps || []), { ...data, status: 'running' }] }));
        break;
      case 'tool_end':
        patch(botId, (m) => ({
          steps: (m.steps || []).map((s) => (s.id === data.id
            ? { ...s, status: data.status === 'error' || data.summary?.startsWith('error') ? 'error' : 'done', summary: data.summary }
            : s)),
        }));
        // Spade changed the watchlist: refresh the dashboard cards
        if (data.name === 'update_watchlist' && data.summary === 'applied') {
          queryClient.invalidateQueries({ queryKey: ['market-summary'] });
        }
        // ...or the holdings: refresh the Portfolio page and dashboard too
        if (data.name === 'update_holdings' && data.summary === 'applied') {
          queryClient.invalidateQueries({ queryKey: ['portfolio-summary'] });
          queryClient.invalidateQueries({ queryKey: ['market-summary'] });
        }
        break;
      case 'approval_required':
        patch(botId, () => ({ approval: { ...data, state: 'pending' }, streaming: false }));
        break;
      case 'final':
        patch(botId, (m) => ({
          text: data.text, streaming: false, meta: data,
          citations: [...(m.citations || []), ...(data.citations || [])],
        }));
        break;
      case 'title':
        setThreads((prev) => prev.map((th) => (th.id === data.thread_id ? { ...th, title: data.title } : th)));
        break;
      case 'error':
        patch(botId, () => ({ error: data.message || 'Something went wrong', streaming: false }));
        break;
      default:
        break;
    }
  }, [patch, queryClient]);

  const run = useCallback(async (path, body, botId) => {
    setBusy(true);
    abortRef.current = new AbortController();
    try {
      await streamAgent(path, body, user?.token, handlerFor(botId), abortRef.current.signal);
    } catch (e) {
      if (e.name !== 'AbortError') patch(botId, () => ({ error: "Sorry, I'm having trouble connecting.", streaming: false }));
    } finally {
      patch(botId, () => ({ streaming: false }));
      setBusy(false);
    }
  }, [user, handlerFor, patch]);

  const send = useCallback((text) => {
    const msg = (text ?? input).trim();
    if (!msg || busy) return;
    setInput('');
    const botId = uid();
    setMessages((prev) => [
      ...prev.map((m) => (m.approval?.state === 'pending' ? { ...m, approval: { ...m.approval, state: 'declined' } } : m)),
      { id: uid(), role: 'user', text: msg, time: now() },
      { id: botId, role: 'bot', text: '', time: now(), streaming: true, steps: [] },
    ]);
    run('/api/agent/chat', { message: msg, thread_id: threadId }, botId);
  }, [input, busy, threadId, run]);

  const decide = useCallback((botId) => (approved) => {
    patch(botId, (m) => ({ approval: { ...m.approval, state: approved ? 'approved' : 'declined' }, streaming: true, text: '' }));
    run('/api/agent/resume', { thread_id: threadId, approved }, botId);
  }, [patch, run, threadId]);

  const rate = useCallback(async (msg, score) => {
    patch(msg.id, () => ({ rating: score }));
    try {
      await fetch(`${AGENT_API_URL}/api/agent/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(user?.token ? { Authorization: `Bearer ${user.token}` } : {}) },
        body: JSON.stringify({ run_id: msg.runId, score }),
      });
    } catch { /* feedback is best-effort */ }
  }, [patch, user]);

  const newChat = () => {
    abortRef.current?.abort();
    setMessages([WELCOME]);
    setThreadId(null);
    setShowHistory(false);
    try { sessionStorage.removeItem(THREAD_KEY); } catch { /* ignore */ }
  };

  const Header = ({ subtitle }) => (
    <div className="px-4 py-3 border-b border-gray-200">
      <div className="flex items-center justify-between gap-2.5">
        <div className="flex items-center gap-2.5">
          <div className="w-9 h-9 bg-gradient-to-br from-green-400 to-green-600 rounded-md flex items-center justify-center flex-shrink-0">
            <MessageSquare className="w-4 h-4 text-white" />
          </div>
          <div className="min-w-0">
            <h3 className="font-bold text-gray-900 text-xs">Spade · Research Agent</h3>
            <p className="text-[10px] text-gray-500 leading-tight">{subtitle}</p>
          </div>
        </div>
        <div className="flex items-center gap-0.5">
          <button onClick={openHistory} title="Your chats" aria-label="Your chats"
            className={`p-1 rounded cursor-pointer ${showHistory ? 'text-green-700 bg-green-50' : 'text-gray-400 hover:text-gray-600 hover:bg-gray-100'}`}>
            <History className="w-3.5 h-3.5" />
          </button>
          <button onClick={newChat} title="New chat" aria-label="New chat"
            className="p-1 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded cursor-pointer">
            <Plus className="w-3.5 h-3.5" />
          </button>
          <button onClick={() => setIsOpen(false)} title="Collapse" aria-label="Collapse chat"
            className="p-1 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded cursor-pointer">
            <ChevronRight className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>
  );

  const ago = (iso) => {
    const s = (Date.now() - new Date(iso).getTime()) / 1000;
    if (!iso || Number.isNaN(s)) return '';
    if (s < 3600) return `${Math.max(1, Math.round(s / 60))}m ago`;
    if (s < 86400) return `${Math.round(s / 3600)}h ago`;
    return new Date(iso).toLocaleDateString();
  };

  const HistoryList = (
    <div className="flex-1 overflow-y-auto p-2">
      <button onClick={newChat}
        className="w-full flex items-center gap-1.5 text-xs px-2.5 py-2 mb-1 rounded-md text-green-800 hover:bg-green-50 cursor-pointer">
        <Plus className="w-3.5 h-3.5" /> New chat
      </button>
      {threads.length === 0 && <p className="text-[11px] text-gray-400 px-2.5 py-2">No saved chats yet.</p>}
      {threads.map((th) => (
        <div key={th.id}
          className={`group flex items-center gap-2 px-2.5 py-2 rounded-md ${th.id === threadId ? 'bg-green-50' : 'hover:bg-gray-50'}`}>
          <button onClick={() => openThread(th.id)} className="min-w-0 flex-1 text-left cursor-pointer">
            <p className="text-xs text-gray-800 truncate">{th.title}</p>
            <p className="text-[10px] text-gray-400">{ago(th.updated_at)}</p>
          </button>
          <button onClick={() => deleteThread(th.id)} title="Delete chat" aria-label="Delete chat"
            className="p-1 text-gray-400 hover:text-red-500 cursor-pointer">
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </div>
      ))}
    </div>
  );

  const Body = showHistory ? HistoryList : (
    <>
      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {messages.map((m) => <Bubble key={m.id} msg={m} onDecide={decide(m.id)} onRate={rate} />)}
        {messages.length === 1 && (
          <div className="flex flex-wrap gap-1.5 pt-1">
            {SUGGESTIONS.map((s) => (
              <button key={s} onClick={() => send(s)}
                className="text-[10px] px-2 py-1 rounded-full border border-green-200 text-green-800 bg-green-50 hover:bg-green-100 cursor-pointer">
                {s}
              </button>
            ))}
          </div>
        )}
        <div ref={endRef} />
      </div>
      <p className="px-3 pb-1.5 text-[10px] text-gray-500 text-center">
        Spade is AI and can make mistakes. For research only, not financial advice.
      </p>
      <div className="p-3 border-t border-gray-200">
        <div className="flex gap-1.5">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && send()}
            placeholder={busy ? 'Spade is working...' : 'Ask about markets, filings or your portfolio'}
            disabled={busy}
            className="flex-1 px-3 py-2 text-xs border border-gray-200 rounded-md focus:outline-none focus:ring-1 focus:ring-green-600 focus:border-transparent disabled:bg-gray-50"
          />
          <button onClick={() => send()} disabled={busy} aria-label="Send"
            className="p-2 bg-green-600 text-white rounded-md hover:bg-green-700 disabled:opacity-50 transition-colors flex items-center justify-center cursor-pointer">
            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
          </button>
        </div>
      </div>
    </>
  );

  return (
    <>
      {/* MOBILE: CLOSED TAB */}
      {!isOpen && (
        <div className="md:hidden fixed right-0 top-[68%] translate-y-0 z-40">
          <button onClick={() => setIsOpen(true)} title="Open Chat" aria-label="Open chat"
            className="px-2 py-4 bg-white border border-gray-200 rounded-l-2xl shadow hover:bg-gray-50 active:scale-[0.98] transition cursor-pointer animate-nudge-slow">
            <MessageSquare className="w-5 h-5 text-green-600" />
          </button>
        </div>
      )}

      {/* MOBILE: OPEN OVERLAY */}
      {isOpen && (
        <div className="md:hidden fixed inset-0 z-50 bg-white border-l border-gray-200 flex flex-col animate-slide-in-right">
          <Header subtitle="Your AI research analyst" />
          {Body}
        </div>
      )}

      {/* DESKTOP: PERSISTENT RAIL */}
      <div className={`hidden md:flex bg-white border-l border-gray-200 h-full flex-col transition-all duration-300 ease-out ${isOpen ? 'w-[400px]' : 'w-12'}`}>
        {isOpen ? (
          <>
            <Header subtitle="Quotes · news · SEC filings · your portfolio" />
            {Body}
          </>
        ) : (
          <div className="flex-1 flex items-start justify-center pt-4">
            <button onClick={() => setIsOpen(true)} title="Open Chat" aria-label="Open chat"
              className="p-2 text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded transition-colors cursor-pointer">
              <ChevronLeft className="w-4 h-4" />
            </button>
          </div>
        )}
      </div>
    </>
  );
}

export default Chatbot;
