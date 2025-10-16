import React from 'react';
import { GoogleLogin } from '@react-oauth/google';
import brLogo from '../assets/br.png';

function Login({ onLoginSuccess = () => { } }) {
  const VITE_APP_API_URL = import.meta.env.VITE_APP_API_URL;
  // Existing Google handler
  const handleGoogleSuccess = ({ credential }) => {
    if (!credential) {
      console.error('No ID token (credential) from Google.');
      return;
    }
    let payload = {};
    try {
      payload = JSON.parse(atob(credential.split('.')[1]));
    } catch { }
    onLoginSuccess({
      email: payload.email,
      name: payload.name,
      picture: payload.picture,
      token: credential
    });
  };

  // Multi-step onboarding flow for unauthenticated users
  const [step, setStep] = React.useState(0);
  const [submitting, setSubmitting] = React.useState(false);

  // Unified onboarding answers
  const [answers, setAnswers] = React.useState({
    experience: '',
    goal: '',
    interests: [],
    watchlist: []
  });

  // Email captured during ticker selection step
  const [email, setEmail] = React.useState('');
  const [emailError, setEmailError] = React.useState('');
  const [registerMessage, setRegisterMessage] = React.useState('');

  // Ticker search (mirrors Onboarding.jsx)
  const [tickers, setTickers] = React.useState([]);
  const [q, setQ] = React.useState('');
  const [suggestions, setSuggestions] = React.useState([]);
  const [activeIdx, setActiveIdx] = React.useState(-1);
  const [focused, setFocused] = React.useState(false);
  const [viaNavSignIn, setViaNavSignIn] = React.useState(false);

  const topStocks = React.useMemo(() => ([
    { ticker: 'AAPL', name: 'Apple Inc.', logo: 'https://raw.githubusercontent.com/davidepalazzo/ticker-logos/refs/heads/main/ticker_icons/AAPL.png' },
    { ticker: 'MSFT', name: 'Microsoft Corporation', logo: 'https://raw.githubusercontent.com/davidepalazzo/ticker-logos/refs/heads/main/ticker_icons/MSFT.png' },
    { ticker: 'NVDA', name: 'NVIDIA Corporation', logo: 'https://raw.githubusercontent.com/davidepalazzo/ticker-logos/refs/heads/main/ticker_icons/NVDA.png' },
    { ticker: 'GOOGL', name: 'Alphabet Inc.', logo: 'https://raw.githubusercontent.com/davidepalazzo/ticker-logos/refs/heads/main/ticker_icons/GOOGL.png' },
    { ticker: 'AMZN', name: 'Amazon.com Inc.', logo: 'https://raw.githubusercontent.com/davidepalazzo/ticker-logos/refs/heads/main/ticker_icons/AMZN.png' }
  ]), []);

  React.useEffect(() => {
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
      e.preventDefault();
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

  const validEmail = (v) => /^[^@]+@[^@]+\.[^@]+$/.test((v || '').trim());

  const canNext = React.useMemo(() => {
    if (step === 1) return !!(answers.experience && answers.goal);
    if (step === 2) return true;
    if (step === 3) return validEmail(email);
    return true;
  }, [step, answers, email]);

  const goBack = () => {
    // If we're on step 4 and came via nav sign-in, go back to step 0
    if (step === 4 && viaNavSignIn) {
      setStep(0);
    } else {
      setStep(s => Math.max(s - 1, 0));
    }
  };

  const resetAll = () => {
    setStep(0);
    setSubmitting(false);
    setAnswers({ experience: '', goal: '', interests: [], watchlist: [] });
    setEmail('');
    setEmailError('');
    setRegisterMessage('');
    setQ('');
    setSuggestions([]);
    setActiveIdx(-1);
    setFocused(false);
    setViaNavSignIn(false);
  };

  // Build a logo URL for any ticker; used as fallback if s.logo is missing
  const getLogoUrl = (ticker = '') =>
    `https://raw.githubusercontent.com/davidepalazzo/ticker-logos/refs/heads/main/ticker_icons/${encodeURIComponent(ticker.trim().toUpperCase())}.png`;


  const handleContinue = async () => {
    setRegisterMessage('');
    if (step < 3) {
      setStep(s => Math.min(s + 1, 4));
      return;
    }
    // Step 3 -> attempt unauthenticated registration
    if (!validEmail(email)) {
      setEmailError('Please enter a valid email.');
      return;
    }
    setEmailError('');
    setSubmitting(true);
    try {
      const res = await fetch(`${VITE_APP_API_URL}/api/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email.trim(), answers })
      });
      const data = await res.json().catch(() => ({}));
      if (res.status === 201) {
        setRegisterMessage('Registered! Sign in to access your personalized report.');
        setStep(4);
      } else if (res.status === 409) {
        setRegisterMessage('Email already exists. Please sign in to continue.');
        setStep(4);
      } else if (res.status === 400) {
        setEmailError(data?.error || 'Invalid email.');
      } else {
        setEmailError(data?.error || 'Registration failed. Please try again.');
      }
    } catch {
      setEmailError('Network error. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-[100dvh] w-full overflow-y-auto flex flex-col bg-white">
      <main className={`flex-1 w-full max-w-3xl mx-auto px-4 sm:px-6 md:px-8 py-8 ${step === 0 ? 'mt-20' : ''}`}>
        {step === 0 ? (
          <section className="w-full">
            <div className="mx-auto flex items-center justify-center gap-2 mb-4">
              {brLogo ? (
                <img src={brLogo} alt="BR" className="h-8 w-8 object-contain" />
              ) : (
                <span className="text-gray-900 font-bold">BR</span>
              )}
              <span className="font-sans text-2xl md:text-4xl font-bold text-gray-900 tracking-tight">BullRun</span>
            </div>

            <div className="flex flex-col items-center text-center">
              <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-gray-100 text-gray-700 text-xs font-medium">
                <span className="w-1.5 h-1.5 rounded-full bg-green-600"></span>
                AI-Powered Investment Intelligence
              </div>
              <h1 className="mt-10 font-sans text-2xl md:text-4xl font-semibold text-gray-900 tracking-tight">
                Let&apos;s Transform Your Investing Journey
              </h1>
              <p className="mt-3 text-base md:text-lg text-gray-600 max-w-3xl">
                Take 2 minutes to share your goals and challenges. We&apos;ll create a personalized
                investment experience that helps you make smarter decisions with confidence.
              </p>
            </div>

            <div className="mt-10 flex justify-center gap-4">
              <button
                type="button"
                onClick={() => { setViaNavSignIn(true); setStep(4); }}
                className="px-3 py-1.5 bg-green-600 text-white text-sm font-semibold rounded-md hover:bg-green-700 cursor-pointer inline-flex items-center gap-2"
              >
                Sign in <span aria-hidden="true">→</span>
              </button>

              <button
                type="button"
                onClick={() => setStep(1)}

                className="px-3 py-1.5 bg-green-600 text-white text-sm font-semibold rounded-md hover:bg-green-700 cursor-pointer inline-flex items-center gap-2"
              >
                Get Started <span aria-hidden="true">→</span>
              </button>
            </div>
          </section>
        ) : (
          <>
            {/* Brand (steps 1–4) */}
            <div className="mb-6 w-full">
              <div className={`md:flex flex-col md:flex-row mx-auto flex items-center justify-center gap-2 ${step === 4 ? 'mt-10' : ''}`}>
                {brLogo ? (
                  <img src={brLogo} alt="BR" className="h-7 w-7 object-contain" />
                ) : (
                  <span className="text-gray-900 font-bold">BR</span>
                )}
                <h1 className="font-sans text-xl md:text-3xl font-semibold text-gray-900 tracking-tight text-center md:text-left">
                  AI-powered financial intelligence built around you
                </h1>
              </div>
            </div>
          </>
        )}

        <div className="w-full">
          {(step >= 1 && !(step === 4 && viaNavSignIn)) && (
            <div className="mb-8">
              <div className="flex items-center justify-between">
                {[1, 2, 3, 4].map((stepNum, idx) => (
                  <React.Fragment key={stepNum}>
                    <div className="flex flex-col items-center flex-1">
                      <div
                        className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium transition-colors
                        ${step >= stepNum ? 'bg-green-600 text-white' : 'bg-gray-200 text-gray-600'}`}
                      >
                        {stepNum}
                      </div>
                      <div className={`hidden md:block md:text-[11px] mt-1 font-medium ${step >= stepNum ? 'text-green-700' : 'text-gray-400'}`}>
                        {stepNum === 1 ? 'About You' : stepNum === 2 ? 'Interests' : stepNum === 3 ? 'Tickers' : 'Let\'s Go!'}
                      </div>
                    </div>
                    {idx < 3 && (
                      <div className={`h-0.5 flex-1 mx-2 transition-colors ${step > stepNum ? 'bg-green-600' : 'bg-gray-200'}`} />
                    )}
                  </React.Fragment>
                ))}
              </div>
            </div>
          )}

          {/* Step content (unchanged) */}
          {step === 1 && (
            <div className="space-y-6">
              <div className="space-y-3">
                <label className="block text-xs font-medium text-gray-700">How familiar are you with investing?</label>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                  {[
                    { key: 'beginner', label: 'Beginner', emoji: '🐣' },
                    { key: 'intermediate', label: 'Intermediate', emoji: '💼' },
                    { key: 'expert', label: 'Expert', emoji: '🦅' }
                  ].map(opt => (
                    <button
                      key={opt.key}
                      type="button"
                      onClick={() => setAnswers(a => ({ ...a, experience: opt.key }))}
                      className={`px-3 py-2 rounded-md text-sm border transition-colors text-left cursor-pointer
                        ${answers.experience === opt.key
                          ? 'border-green-600 text-green-700 bg-green-50'
                          : 'border-gray-300 text-gray-700 hover:bg-gray-50'}`}
                    >
                      <span className="mr-1">{opt.emoji}</span>{opt.label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="space-y-3">
                <label className="block text-xs font-medium text-gray-700">What's your main goal?</label>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                  {[
                    { key: 'informed', label: 'Stay informed' },
                    { key: 'ideas', label: 'Find ideas' },
                    { key: 'trends', label: 'Understand trends' }
                  ].map(opt => (
                    <button
                      key={opt.key}
                      type="button"
                      onClick={() => setAnswers(a => ({ ...a, goal: opt.key }))}
                      className={`px-3 py-2 rounded-md text-sm border transition-colors text-left cursor-pointer
                        ${answers.goal === opt.key
                          ? 'border-green-600 text-green-700 bg-green-50'
                          : 'border-gray-300 text-gray-700 hover:bg-gray-50'}`}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}

          {step === 2 && (
            <div className="space-y-4">
              <label className="block text-xs font-medium text-gray-700">
                Are there any topics or markets you want your brief to focus on?
              </label>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {interestOptions.map(opt => {
                  const active = answers.interests.includes(opt.key);
                  return (
                    <button
                      key={opt.key}
                      type="button"
                      onClick={() => toggleInterest(opt.key)}
                      className={`px-3 py-2 rounded-md text-sm border flex items-center gap-2 transition-colors text-left cursor-pointer
                        ${active ? 'border-green-600 text-green-700 bg-green-50' : 'border-gray-300 text-gray-700 hover:bg-gray-50'}`}
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
            <div className="space-y-6">
              <div className="space-y-3">
                <label className="block text-xs font-medium text-gray-700">Want us to track any specific stocks or assets for you?</label>

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
                    <ul className="absolute z-50 mt-2 w-full bg-white border border-gray-200 rounded-md shadow-lg overflow-auto max-h-48">
                      {suggestions.map((s, idx) => (
                        <li key={s.ticker}>
                          <button
                            type="button"
                            onMouseEnter={() => setActiveIdx(idx)}
                            onClick={() => addTicker(s.ticker)}
                            className={`w-full px-3 py-2 text-left text-sm transition-colors cursor-pointer ${idx === activeIdx ? 'bg-gray-50' : 'bg-white'}`}
                          >
                            <div className="flex items-center gap-2">
                              <div className="w-8 h-8 bg-black rounded flex items-center justify-center flex-shrink-0">
                                <img
                                  src={s.logo || getLogoUrl(s.ticker)}
                                  alt={s.ticker}
                                  className="w-6 h-6 object-contain"
                                  onError={(e) => {
                                    e.currentTarget.style.display = 'none';
                                    e.currentTarget.parentElement.innerHTML = `<span class="text-white text-xs font-semibold">${(s.ticker || '?')[0]}</span>`;
                                  }}
                                />
                              </div>
                              <div className="flex flex-col min-w-0">
                                <span className="font-semibold text-gray-900">{s.ticker}</span>
                                <span className="text-gray-500 text-xs truncate">{s.name}</span>
                              </div>
                            </div>
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

              {/* Email capture */}
              <div className="space-y-2">
                <label className="block text-xs font-medium text-gray-700">Your email</label>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => { setEmail(e.target.value); setEmailError(''); }}
                  placeholder="you@email.com"
                  className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-green-500"
                />
                {!!emailError && <div className="text-xs text-red-600 mt-1">{emailError}</div>}
              </div>
            </div>
          )}

          {step === 4 && (
            <div className="space-y-4 text-center">
              {!!registerMessage && (
                <div className="text-sm font-medium text-green-700">{registerMessage}</div>
              )}
              <div className="flex justify-center">
                <GoogleLogin onSuccess={handleGoogleSuccess} onError={() => console.error('Google login failed')} />
              </div>
              <div className="text-xs text-gray-500">
                You’ll be signed in and your personalized brief will be ready.
              </div>
            </div>
          )}

          {(step >= 1) && (
            <div className="flex items-center justify-between pt-8">
              <button
                type="button"
                onClick={goBack}
                disabled={step === 0}
                className="px-3 py-2 text-sm rounded-md border border-gray-300 text-gray-700 hover:bg-gray-50 disabled:opacity-60 cursor-pointer"
              >
                Back
              </button>

              {step < 4 ? (
                <button
                  type="button"
                  onClick={handleContinue}
                  disabled={!canNext || submitting}
                  className="px-3 py-2 bg-green-600 text-white text-sm font-semibold rounded-md hover:bg-green-700 disabled:opacity-60 cursor-pointer"
                >
                  {submitting ? 'Saving...' : 'Continue'}
                </button>
              ) : (
                <div />
              )}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

export default Login;