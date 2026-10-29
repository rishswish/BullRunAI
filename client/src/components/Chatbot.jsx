import React, { useState, useRef, useEffect, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  MessageSquare, Send, ChevronRight, ChevronLeft, Loader2, Check, X, Plus,
  LineChart, Newspaper, FileText, Briefcase, ListPlus, AlertTriangle, ThumbsUp, ThumbsDown,
} from 'lucide-react';
import { AGENT_API_URL, streamAgent } from '../lib/agentStream';

const THREAD_KEY = 'br_chat_thread';
const now = () => new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
const uid = () => Math.random().toString(36).slice(2);

const WELCOME = {
  id: 'welcome',
  role: 'bot',
  text: "Hi! I'm **Spade**, BullRun's research agent. I can pull live quotes and news, search company 10-K/10-Q filings with citations, analyse your portfolio, and update your watchlist (with your approval).",
  time: now(),
};

const SUGGESTIONS = [
  'How is my portfolio doing today?',
  'Why is NVDA moving?',
  "What risks does AAPL flag in its 10-K?",
  'Add AMD to my watchlist',
];

const TOOL_META = {
  get_quote: { icon: LineChart, label: (a) => `Quote ${a?.ticker ?? ''}` },
  compare_tickers: { icon: LineChart, label: (a) => `Comparing ${(a?.tickers || []).join(', ')}` },
  get_news: { icon: Newspaper, label: (a) => `News for ${a?.ticker ?? ''}` },
  search_filings: { icon: FileText, label: (a) => `Searching ${a?.ticker ? a.ticker + ' ' : ''}filings` },
  get_portfolio: { icon: Briefcase, label: () => 'Reading your portfolio' },
  update_watchlist: { icon: ListPlus, label: () => 'Watchlist update' },
};

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
      <div className="font-semibold mb-1">Approve watchlist change?</div>
      {approval.add?.length > 0 && <div>Add: <b>{approval.add.join(', ')}</b></div>}
      {approval.remove?.length > 0 && <div>Remove: <b>{approval.remove.join(', ')}</b></div>}
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

function Citations({ citations }) {
  if (!citations?.length) return null;
  const seen = new Set();
  const unique = citations.filter((c) => !seen.has(c.id) && seen.add(c.id));
  return (
    <div className="mt-2 pt-1.5 border-t border-gray-200 space-y-0.5">
      <div className="text-[10px] font-semibold text-gray-500">Sources</div>
      {unique.map((c) => (
        <a key={c.id} href={c.url} target="_blank" rel="noreferrer"
          className="block text-[10px] text-green-700 hover:underline truncate">
          [{c.id}] {c.ticker} {c.form} ({c.filed}), {c.section}
        </a>
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
          {!isUser && <Citations citations={msg.citations} />}
        </div>
        <p className="text-[9px] text-gray-400 mt-0.5 px-1">
          {msg.time}
          {msg.meta && ` · ${(msg.meta.latency_ms / 1000).toFixed(1)}s · ${msg.meta.usage.input_tokens + msg.meta.usage.output_tokens} tokens`}
          {msg.runId && !msg.streaming && <span title={`Trace ${msg.runId}`}> · ref {msg.runId.slice(0, 8)}</span>}
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
  const endRef = useRef(null);
  const abortRef = useRef(null);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);
  useEffect(() => () => abortRef.current?.abort(), []);

  // Restore the conversation after a page reload (memory lives server-side in the checkpointer).
  useEffect(() => {
    if (!threadId || messages.length > 1) return;
    fetch(`${AGENT_API_URL}/api/agent/threads/${threadId}`, {
      headers: user?.token ? { Authorization: `Bearer ${user.token}` } : {},
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!data?.messages?.length) return;
        setMessages([WELCOME, ...data.messages.map((m) => ({
          id: uid(), role: m.role === 'user' ? 'user' : 'bot', text: m.text, time: '',
        }))]);
      })
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.token]);

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
      case 'error':
        patch(botId, () => ({ error: data.message || 'Something went wrong', streaming: false }));
        break;
      default:
        break;
    }
  }, [patch]);

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

  const Body = (
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
        <p className="text-[9px] text-gray-400 mt-1">Educational research, not financial advice.</p>
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
