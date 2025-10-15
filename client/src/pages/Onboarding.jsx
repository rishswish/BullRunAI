import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import brLogo from '../assets/br.png';

function Onboarding({ user, onProfile }) {
  const navigate = useNavigate();
  const VITE_APP_API_URL = import.meta.env.VITE_APP_API_URL;
  const [step, setStep] = useState(1);
  const [submitting, setSubmitting] = useState(false);

  // unified answers payload sent to the server on final submit
  const [answers, setAnswers] = useState({
    experience: '',   // beginner | intermediate | expert
    goal: '',         // informed | ideas | trends
    interests: [],    // ['us_stocks', 'crypto', ...]
    watchlist: []     // ['AAPL', 'TSLA', ...]
  });

  // --- Ticker search (reuses Navbar approach in a compact form) ---
  const [tickers, setTickers] = useState([]);
  const [q, setQ] = useState('');
  const [suggestions, setSuggestions] = useState([]);
  const [activeIdx, setActiveIdx] = useState(-1);
  const [focused, setFocused] = useState(false);

  // Top defaults like Navbar
  const topStocks = useMemo(() => ([
    { ticker: 'AAPL', name: 'Apple Inc.' },
    { ticker: 'MSFT', name: 'Microsoft Corporation' },
    { ticker: 'NVDA', name: 'NVIDIA Corporation' },
    { ticker: 'GOOGL', name: 'Alphabet Inc.' },
    { ticker: 'AMZN', name: 'Amazon.com Inc.' }
  ]), []);

  useEffect(() => {
    let cancelled = false;
    fetch('/tickers.json')
      .then((r) => r.json())
      .then((data) => {
        if (!cancelled) setTickers(Array.isArray(data) ? data : []);
      })
      .catch(() => { });
    return () => { cancelled = true; };
  }, []);

  const runSearch = (value) => {
    const query = value.trim();
    if (!query) {
      if (focused) {
        setSuggestions(topStocks);
        setActiveIdx(topStocks.length ? 0 : -1);
      } else {
        setSuggestions([]);
        setActiveIdx(-1);
      }
      return;
    }
    const qUpper = query.toUpperCase();
    const qLower = query.toLowerCase();
    const ranked = tickers
      .filter((t) =>
        t.ticker?.toUpperCase().includes(qUpper) ||
        t.name?.toLowerCase().includes(qLower)
      )
      .sort((a, b) => {
        const aRank = a.ticker?.toUpperCase().startsWith(qUpper) ? 0
          : a.ticker?.toUpperCase().includes(qUpper) ? 1
            : a.name?.toLowerCase().startsWith(qLower) ? 2 : 3;
        const bRank = b.ticker?.toUpperCase().startsWith(qUpper) ? 0
          : b.ticker?.toUpperCase().includes(qUpper) ? 1
            : b.name?.toLowerCase().startsWith(qLower) ? 2 : 3;
        if (aRank !== bRank) return aRank - bRank;
        return (a.ticker?.length || 0) - (b.ticker?.length || 0);
      })
      .slice(0, 6);
    setSuggestions(ranked);
    setActiveIdx(ranked.length ? 0 : -1);
  };

  const addTicker = (sym) => {
    const t = (sym || '').trim().toUpperCase();
    if (!t) return;
    setAnswers(a => {
      if (a.watchlist.includes(t)) return a;
      return { ...a, watchlist: [...a.watchlist, t] };
    });
    setQ('');
    setSuggestions([]);
    setActiveIdx(-1);
  };

  const removeTicker = (sym) => {
    setAnswers(a => ({ ...a, watchlist: a.watchlist.filter(x => x !== sym) }));
  };

  const onKeyDown = (e) => {
    if (e.key === 'Enter') {
      e.preventDefault(); // Always prevent form submission
      if (suggestions.length) {
        const s = suggestions[activeIdx] || suggestions[0];
        if (s) addTicker(s.ticker);
        else if (q.trim()) addTicker(q);
      } else if (q.trim()) {
        addTicker(q);
      }
      return;
    }

    if (!suggestions.length) return;

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIdx(i => Math.min(i + 1, suggestions.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIdx(i => Math.max(i - 1, 0));
    } else if (e.key === 'Escape') {
      setSuggestions([]);
      setActiveIdx(-1);
    }
  };

  const canNext = useMemo(() => {
    if (step === 1) return !!(answers.experience && answers.goal);
    return true;
  }, [step, answers]);

  const goNext = () => setStep(s => Math.min(s + 1, 3));
  const goBack = () => setStep(s => Math.max(s - 1, 1));

  const handleSubmit = async (e) => {
    e.preventDefault();

    setSubmitting(true);
    try {
      const res = await fetch(`${VITE_APP_API_URL}/api/user/onboarding`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${user.token}`
        },
        body: JSON.stringify({ answers })
      });
      const data = await res.json();
      if (res.ok) {
        if (onProfile) onProfile(data);
        navigate('/dashboard', { replace: true });
      }
    } finally {
      setSubmitting(false);
    }
  };

  // Interest options
  const interestOptions = [
    { key: 'us_stocks', label: 'U.S. Stocks', emoji: '🇺🇸' },
    { key: 'crypto', label: 'Crypto & Blockchain', emoji: '🪙' },
    { key: 'commodities', label: 'Commodities', emoji: '⛏️' },
    { key: 'real_estate', label: 'Real Estate', emoji: '🏠' },
    { key: 'tech_ai', label: 'Tech & AI', emoji: '🤖' },
    { key: 'macro', label: 'Macroeconomy', emoji: '📊' },
  ];
  const toggleInterest = (k) => {
    setAnswers(a => {
      const has = a.interests.includes(k);
      return {
        ...a,
        interests: has ? a.interests.filter(x => x !== k) : [...a.interests, k]
      };
    });
  };

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center px-4">
      <div className="bg-white w-full max-w-xl rounded-lg shadow-sm border border-gray-200 p-6">
        <form onSubmit={step === 3 ? handleSubmit : (e) => e.preventDefault()} onKeyDown={(e) => { if (step < 3 && e.key === 'Enter') e.preventDefault(); }} className="space-y-5">          <div className="flex items-center justify-between mb-6">
          {[1, 2, 3].map((stepNum, idx) => (
            <React.Fragment key={stepNum}>
              <div className="flex flex-col items-center flex-1">
                <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-semibold transition-colors ${step >= stepNum
                  ? 'bg-green-600 text-white'
                  : 'bg-gray-200 text-gray-500'
                  }`}>
                  {stepNum}
                </div>
                <div className={`hidden md:block text-xs mt-1 font-medium ${step >= stepNum ? 'text-green-700' : 'text-gray-400'
                  }`}>
                  {stepNum === 1 ? 'About You' : stepNum === 2 ? 'Interests' : 'Watchlist'}
                </div>
              </div>
              {idx < 2 && (
                <div className={`h-0.5 flex-1 mx-2 transition-colors ${step > stepNum ? 'bg-green-600' : 'bg-gray-200'
                  }`} />
              )}
            </React.Fragment>
          ))}
        </div>

          {/* Step-specific heading */}
          <div className="mb-6">
            {step === 1 && (
              <h2 className="text-lg font-semibold text-gray-900">Tell us about yourself</h2>
            )}
            {step === 2 && (
              <h2 className="text-lg font-semibold text-gray-900">What interests you?</h2>
            )}
            {step === 3 && (
              <h2 className="text-lg font-semibold text-gray-900">Build your watchlist</h2>
            )}
          </div>

          {step === 1 && (
            <div className="space-y-4">

              <div className="space-y-2">
                <label className="block text-xs font-medium text-gray-700">How familiar are you with investing?</label>
                <div className="grid grid-cols-3 gap-2">
                  {[
                    { key: 'beginner', label: 'Beginner', emoji: '🐣' },
                    { key: 'intermediate', label: 'Intermediate', emoji: '💼' },
                    { key: 'expert', label: 'Expert', emoji: '🦅' }
                  ].map(opt => (
                    <button
                      key={opt.key}
                      type="button"
                      onClick={() => setAnswers(a => ({ ...a, experience: opt.key }))}
                      className={`px-3 py-2 rounded-md text-sm border transition-colors cursor-pointer ${answers.experience === opt.key ? 'border-green-600 text-green-700 bg-green-50' : 'border-gray-300 text-gray-700 hover:bg-gray-50'
                        }`}
                    >
                      <span className="mr-1">{opt.emoji}</span>{opt.label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="space-y-2">
                <label className="block text-xs font-medium text-gray-700">What's your main goal?</label>
                <div className="grid grid-cols-3 gap-2">
                  {[
                    { key: 'informed', label: 'Stay informed' },
                    { key: 'ideas', label: 'Find ideas' },
                    { key: 'trends', label: 'Understand trends' }
                  ].map(opt => (
                    <button
                      key={opt.key}
                      type="button"
                      onClick={() => setAnswers(a => ({ ...a, goal: opt.key }))}
                      className={`px-3 py-2 rounded-md text-sm border transition-colors cursor-pointer ${answers.goal === opt.key ? 'border-green-600 text-green-700 bg-green-50' : 'border-gray-300 text-gray-700 hover:bg-gray-50'
                        }`}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}

          {step === 2 && (
            <div className="space-y-3">
              <label className="block text-xs font-medium text-gray-700">Are there any topics or markets you want your brief to focus on?</label>
              <div className="grid grid-cols-2 gap-2">
                {interestOptions.map(opt => {
                  const active = answers.interests.includes(opt.key);
                  return (
                    <button
                      key={opt.key}
                      type="button"
                      onClick={() => toggleInterest(opt.key)}
                      className={`px-3 py-2 rounded-md text-sm border flex items-center gap-2 transition-colors cursor-pointer ${active ? 'border-green-600 text-green-700 bg-green-50' : 'border-gray-300 text-gray-700 hover:bg-gray-50'
                        }`}
                    >
                      <span>{opt.emoji}</span>
                      <span>{opt.label}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {step === 3 && (
            <div className="space-y-3">
              <label className="block text-xs font-medium text-gray-700">Want us to track any specific stocks or assets for you?</label>
              <div className="text-xs text-gray-500">Example: AAPL, TSLA, BTC-USD</div>

              <div className="relative">
                <input
                  type="text"
                  value={q}
                  onChange={(e) => { setQ(e.target.value); runSearch(e.target.value); }}
                  onKeyDown={onKeyDown}
                  onFocus={() => { setFocused(true); if (!q.trim()) { setSuggestions(topStocks); setActiveIdx(topStocks.length ? 0 : -1); } }}
                  onBlur={() => { setTimeout(() => { setFocused(false); setSuggestions([]); setActiveIdx(-1); }, 150); }}
                  placeholder="Type a ticker or name..."
                  className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-green-500 cursor-pointer"
                />
                {!!suggestions.length && (
                  <ul className="absolute z-50 mt-2 w-full bg-white border border-gray-200 rounded-md shadow-lg overflow-hidden">
                    {suggestions.map((s, idx) => (
                      <li key={s.ticker}>
                        <button
                          type="button"
                          onMouseEnter={() => setActiveIdx(idx)}
                          onClick={() => addTicker(s.ticker)}
                          className={`w-full px-3 py-2 text-left text-sm transition-colors cursor-pointer ${idx === activeIdx ? 'bg-gray-50' : 'bg-white'}`}
                        >
                          <span className="font-semibold text-gray-900">{s.ticker}</span>
                          <span className="text-gray-500 ml-2">{s.name}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              {!!answers.watchlist.length && (
                <div className="flex flex-wrap gap-2">
                  {answers.watchlist.map(t => (
                    <span key={t} className="inline-flex items-center gap-1 px-2 py-1 rounded-full bg-gray-100 text-gray-700 text-xs border border-gray-200">
                      {t}
                      <button type="button" onClick={() => removeTicker(t)} className="text-gray-500 hover:text-gray-700 cursor-pointer">×</button>
                    </span>
                  ))}
                </div>
              )}
            </div>
          )}

          <div className="flex items-center justify-between pt-2">
            <button
              type="button"
              onClick={goBack}
              disabled={step === 1}
              className="px-3 py-2 text-sm rounded-md border border-gray-300 text-gray-700 hover:bg-gray-50 disabled:opacity-60 cursor-pointer"
            >
              Back
            </button>

            {step < 3 ? (
              <button
                type="button"
                onClick={goNext}
                disabled={!canNext}
                className="px-3 py-2 bg-green-600 text-white text-sm font-semibold rounded-md hover:bg-green-700 disabled:opacity-60 cursor-pointer"
              >
                Continue
              </button>
            ) : (
              (
                <button
                  type="submit"
                  disabled={submitting}
                  className="px-3 py-2 bg-green-600 text-white text-sm font-semibold rounded-md hover:bg-green-700 disabled:opacity-60 cursor-pointer"
                >
                  {submitting ? 'Saving...' : 'Finish'}
                </button>
              )
            )}
          </div>
        </form>
      </div>
    </div>
  );
}

export default Onboarding;