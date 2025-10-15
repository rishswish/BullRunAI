import React, { useState, useEffect, useRef } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { Search, Sun, Bell, Calendar, X, Menu } from 'lucide-react';
import bullrunLogo from '../assets/br.png';

function Navbar({ onLogout, user, theme, onThemeChange }) {
  const location = useLocation();
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false); // profile dropdown
  const [themeOpen, setThemeOpen] = useState(false);
  const [showProModal, setShowProModal] = useState(false);

  // Mobile UI
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [mobileSearchOpen, setMobileSearchOpen] = useState(false);

  const menuRef = useRef(null);
  const themeRef = useRef(null);

  // Search state
  const searchRef = useRef(null);
  const [query, setQuery] = useState('');
  const [tickers, setTickers] = useState([]);
  const [suggestions, setSuggestions] = useState([]);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [searchFocused, setSearchFocused] = useState(false);
  const [showSuggestions, setShowSuggestions] = useState(false);

  // Top 5 Magnificent stocks to show as default
  const topStocks = [
    { ticker: 'AAPL', name: 'Apple Inc.', logo: 'https://raw.githubusercontent.com/davidepalazzo/ticker-logos/refs/heads/main/ticker_icons/AAPL.png' },
    { ticker: 'MSFT', name: 'Microsoft Corporation', logo: 'https://raw.githubusercontent.com/davidepalazzo/ticker-logos/refs/heads/main/ticker_icons/MSFT.png' },
    { ticker: 'NVDA', name: 'NVIDIA Corporation', logo: 'https://raw.githubusercontent.com/davidepalazzo/ticker-logos/refs/heads/main/ticker_icons/NVDA.png' },
    { ticker: 'GOOGL', name: 'Alphabet Inc.', logo: 'https://raw.githubusercontent.com/davidepalazzo/ticker-logos/refs/heads/main/ticker_icons/GOOGL.png' },
    { ticker: 'AMZN', name: 'Amazon.com Inc.', logo: 'https://raw.githubusercontent.com/davidepalazzo/ticker-logos/refs/heads/main/ticker_icons/AMZN.png' }
  ];

  useEffect(() => {
    const handleClickOutside = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setMenuOpen(false);
      }
      if (themeRef.current && !themeRef.current.contains(e.target)) {
        setThemeOpen(false);
      }
      if (searchRef.current && !searchRef.current.contains(e.target)) {
        setSuggestions([]);
        setActiveIndex(-1);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Close mobile panels on route change
  useEffect(() => {
    setMobileNavOpen(false);
    setMobileSearchOpen(false);
  }, [location.pathname]);

  // Load tickers from public
  useEffect(() => {
    let cancelled = false;
    fetch('/tickers.json')
      .then((r) => r.json())
      .then((data) => {
        if (!cancelled) setTickers(Array.isArray(data) ? data : []);
      })
      .catch(() => { });
    return () => {
      cancelled = true;
    };
  }, []);

  const runSearch = (value) => {
    const q = value.trim();
    if (!q) {
      // Show top stocks when empty and focused
      if (searchFocused) {
        setSuggestions(topStocks);
        setActiveIndex(0);
        setShowSuggestions(true);
      } else {
        setShowSuggestions(false);
        setTimeout(() => {
          setSuggestions([]);
          setActiveIndex(-1);
        }, 200); // Wait for animation to complete
      }
      return;
    }
    const qUpper = q.toUpperCase();
    const qLower = q.toLowerCase();

    const ranked = tickers
      .filter(
        (t) =>
          t.ticker?.toUpperCase().includes(qUpper) ||
          t.name?.toLowerCase().includes(qLower)
      )
      .sort((a, b) => {
        const aRank = a.ticker?.toUpperCase().startsWith(qUpper)
          ? 0
          : a.ticker?.toUpperCase().includes(qUpper)
            ? 1
            : a.name?.toLowerCase().startsWith(qLower)
              ? 2
              : 3;
        const bRank = b.ticker?.toUpperCase().startsWith(qUpper)
          ? 0
          : b.ticker?.toUpperCase().includes(qUpper)
            ? 1
            : b.name?.toLowerCase().startsWith(qLower)
              ? 2
              : 3;
        if (aRank !== bRank) return aRank - bRank;
        return (a.ticker?.length || 0) - (b.ticker?.length || 0);
      })
      .slice(0, 5);

    setSuggestions(ranked);
    setActiveIndex(ranked.length ? 0 : -1);
    setShowSuggestions(ranked.length > 0);
  };

  const onInputChange = (e) => {
    const v = e.target.value;
    setQuery(v);
    runSearch(v);
  };

  const onFocus = () => {
    setSearchFocused(true);
    if (!query.trim()) {
      setSuggestions(topStocks);
      setActiveIndex(0);
      setShowSuggestions(true);
    }
  };

  const onBlur = () => {
    // Delay to allow click events on suggestions
    setTimeout(() => {
      setSearchFocused(false);
      setShowSuggestions(false);
      setTimeout(() => setSuggestions([]), 200);
    }, 200);
  };

  const selectSuggestion = (s) => {
    setQuery('');
    setShowSuggestions(false);
    setTimeout(() => {
      setSuggestions([]);
      setActiveIndex(-1);
    }, 200);
    setMobileSearchOpen(false);
    setMobileNavOpen(false);
    navigate(`/dashboard/${encodeURIComponent(s.ticker)}`);
  };

  const onKeyDown = (e) => {
    if (!suggestions.length) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIndex((i) => Math.min(i + 1, suggestions.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const s = suggestions[activeIndex] || suggestions[0];
      if (s) selectSuggestion(s);
    } else if (e.key === 'Escape') {
      setShowSuggestions(false);
      setTimeout(() => {
        setSuggestions([]);
        setActiveIndex(-1);
      }, 200);
    }
  };

  return (
    <nav className="relative bg-white border-b border-gray-200 px-4 py-2 flex items-center justify-between sticky top-0 z-50">
      {/* Left side - Logo and Navigation */}
      <div className="flex items-center gap-2">
        {/* Mobile: Hamburger */}
        <button
          type="button"
          className="md:hidden p-1.5 text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-md transition-all duration-200 cursor-pointer"
          aria-label="Toggle menu"
          aria-expanded={mobileNavOpen}
          onClick={() => {
            setMobileNavOpen((v) => !v);
            setMobileSearchOpen(false);
          }}
        >
          <Menu className="w-5 h-5" />
        </button>

        {/* Logo */}
        <Link to="/dashboard" className="flex items-center gap-1.5 cursor-pointer">
          <div className="w-5 h-5 rounded flex items-center justify-center">
            <img src={bullrunLogo} alt="BullRun Logo" className="w-5 h-5" />
          </div>
          <span className="font-bold text-gray-900 text-base">BullRun</span>
        </Link>

        {/* Navigation Links - hidden on mobile */}
        <div className="hidden md:flex items-center gap-0.5">
          <Link
            to="/dashboard"
            className={`px-2.5 py-1.5 text-xs font-medium rounded-md transition-colors flex items-center gap-1.5 cursor-pointer ${location.pathname === '/dashboard'
              ? 'text-green-600 bg-green-50'
              : 'text-gray-700 hover:text-gray-900 hover:bg-gray-50'
              }`}
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
            </svg>
            Market
          </Link>
          <Link
            to="/portfolio"
            className={`px-2.5 py-1.5 text-xs font-medium rounded-md transition-colors flex items-center gap-1.5 cursor-pointer ${location.pathname === '/portfolio'
              ? 'text-green-600 bg-green-50'
              : 'text-gray-700 hover:text-gray-900 hover:bg-gray-50'
              }`}
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 13.255A23.931 23.931 0 0112 15c-3.183 0-6.22-.62-9-1.745M16 6V4a2 2 0 00-2-2h-4a2 2 0 00-2 2v2m4 6h.01M5 20h14a2 2 0 002-2V8a2 2 0 00-2 2H5a2 2 0 00-2 2z" />
            </svg>
            Portfolio
          </Link>
        </div>
      </div>

      {/* Center - Search (desktop/tablet) */}
      <div className="hidden md:block flex-1 max-w-md mx-4">
        <div className="relative border border-gray-200 rounded-md cursor-pointer" ref={searchRef}>
          <Search className="absolute left-2.5 top-1/2 transform -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
          <input
            type="text"
            placeholder="Search stocks..."
            value={query}
            onChange={onInputChange}
            onKeyDown={onKeyDown}
            onFocus={onFocus}
            onBlur={onBlur}
            aria-autocomplete="list"
            aria-expanded={suggestions.length > 0}
            aria-activedescendant={activeIndex >= 0 ? `srch-opt-${activeIndex}` : undefined}
            className="w-full pl-9 pr-8 py-1.5 text-xs border border-gray-200 rounded-md cursor-pointer focus:outline-none focus:ring-1 focus:ring-green-500 focus:border-transparent"
          />
          {query ? (
            <button
              type="button"
              onClick={() => {
                setQuery('');
                setShowSuggestions(false);
                setTimeout(() => {
                  setSuggestions([]);
                  setActiveIndex(-1);
                }, 200);
              }}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-gray-400 hover:text-gray-600 rounded cursor-pointer"
              aria-label="Clear search"
              title="Clear"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          ) : null}

          {suggestions.length > 0 && (
            <ul
              className={`absolute z-50 mt-2 w-full bg-white border border-gray-200 rounded-md shadow-lg overflow-hidden transition-all duration-200 origin-top ${showSuggestions
                ? 'opacity-100 scale-y-100 translate-y-0'
                : 'opacity-0 scale-y-95 -translate-y-2 pointer-events-none'
                }`}
              style={{ transformOrigin: 'top center' }}
            >
              {suggestions.map((s, idx) => (
                <li
                  key={s.ticker}
                  id={`srch-opt-${idx}`}
                  className={`transition-all duration-150 ${showSuggestions ? 'opacity-100 translate-x-0' : 'opacity-0 -translate-x-2'}`}
                  style={{ transitionDelay: showSuggestions ? `${idx * 30}ms` : '0ms' }}
                >
                  <button
                    type="button"
                    onMouseEnter={() => setActiveIndex(idx)}
                    onClick={() => selectSuggestion(s)}
                    className={`w-full px-3 py-2 text-left flex items-center gap-2 transition-colors ${idx === activeIndex ? 'bg-gray-50' : 'bg-white'} hover:bg-gray-50 cursor-pointer`}
                  >
                    {/* Logo with black background */}
                    <div className="w-8 h-8 bg-black rounded flex items-center justify-center flex-shrink-0">
                      {s.logo ? (
                        <img
                          src={s.logo}
                          alt={s.ticker}
                          className="w-6 h-6 object-contain"
                          onError={(e) => {
                            e.target.style.display = 'none';
                            e.target.parentElement.innerHTML = `<span class="text-white text-xs font-semibold">${s.ticker[0]}</span>`;
                          }}
                        />
                      ) : (
                        <span className="text-white text-xs font-semibold">{s.ticker[0]}</span>
                      )}
                    </div>
                    <div className="flex flex-col min-w-0 flex-1">
                      <span className="font-semibold text-gray-900 text-sm">{s.ticker}</span>
                      <span className="text-xs text-gray-500 truncate">{s.name}</span>
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {/* Right side - Actions */}
      <div className="flex items-center gap-2">
        {/* Mobile: search toggle */}
        <button
          type="button"
          className="md:hidden p-1.5 text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-md transition-all duration-200 cursor-pointer"
          aria-label="Toggle search"
          aria-expanded={mobileSearchOpen}
          onClick={() => {
            setMobileSearchOpen((v) => !v);
            setMobileNavOpen(false);
          }}
        >
          <Search className="w-5 h-5" />
        </button>

        {/* Theme toggle with animation */}
        <button
          type="button"
          onClick={() => {
            const newTheme = theme === 'light' ? 'dark' : 'light';
            onThemeChange(newTheme);
          }}
          className="relative p-1.5 text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-md transition-all duration-300 cursor-pointer overflow-hidden group"
          title={theme === 'light' ? 'Switch to Dark Mode' : 'Switch to Light Mode'}
          ref={themeRef}
        >
          <div className="relative w-4 h-4">
            {/* Sun icon */}
            <Sun
              className={`w-4 h-4 absolute inset-0 transition-all duration-500 ${theme === 'light'
                ? 'opacity-100 rotate-0 scale-100'
                : 'opacity-0 rotate-180 scale-50'
                }`}
            />
            {/* Moon icon */}
            <svg
              className={`w-4 h-4 absolute inset-0 transition-all duration-500 ${theme === 'dark'
                ? 'opacity-100 rotate-0 scale-100'
                : 'opacity-0 -rotate-180 scale-50'
                }`}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z"
              />
            </svg>
          </div>
          {/* Ripple effect on click */}
          <span className="absolute inset-0 bg-green-400 opacity-0 group-active:opacity-20 transition-opacity duration-200 rounded-md" />
        </button>

        {/* Pro button hidden on very small screens */}
        <button
          onClick={() => setShowProModal(true)}
          className="hidden sm:inline-flex relative px-3 py-1.5 bg-gradient-to-r from-green-600 to-green-700 text-white text-xs font-semibold rounded-md transition-all duration-300 cursor-pointer overflow-hidden group"
        >
          <span className="relative z-10">Pro</span>
          <span
            className="absolute inset-0 w-full h-full bg-gradient-to-r from-transparent via-white to-transparent opacity-0 group-hover:opacity-30 transform -skew-x-12 group-hover:translate-x-full transition-all duration-700 ease-in-out"
            style={{ left: '-100%' }}
          />
        </button>

        {/* Pro Plan Modal */}
        {showProModal && (
          <div className="fixed inset-0 bg-opacity-50 flex items-center justify-center z-[100]" onClick={() => setShowProModal(false)}>
            <div className="bg-white rounded-lg shadow-2xl border border-gray-200 p-8 max-w-md w-full mx-4 relative animate-[modalSlideIn_0.3s_ease-out]" onClick={(e) => e.stopPropagation()}>
              <button
                onClick={() => setShowProModal(false)}
                className="absolute top-4 right-4 text-gray-400 hover:text-gray-600 transition-colors cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>

              <div className="text-center">
                {/* Success Icon */}
                <div className="mx-auto w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mb-4">
                  <svg className="w-8 h-8 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                  </svg>
                </div>

                <h2 className="text-2xl font-bold text-gray-900 mb-2">🎉 Congratulations!</h2>
                <p className="text-gray-600 mb-4">
                  You have exclusive access to <span className="font-semibold text-green-600">Pro</span> for 2 months!
                </p>

                <div className="bg-green-50 border border-green-200 rounded-lg p-4 mb-4">
                  <p className="text-sm text-gray-700">
                    Enjoy premium features including advanced analytics, real-time market insights, and priority support.
                  </p>
                </div>

                <p className="text-xs text-gray-500 mb-6">
                  More details coming soon! We're working on exciting new features just for you.
                </p>

                <button
                  onClick={() => setShowProModal(false)}
                  className="w-full px-4 py-2 bg-green-600 text-white font-semibold rounded-md hover:bg-green-700 transition-colors cursor-pointer"
                >
                  Got it, thanks!
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Profile */}
        <div className="relative" ref={menuRef}>
          <button
            type="button"
            onClick={() => setMenuOpen((v) => !v)}
            className="w-7 h-7 rounded-full overflow-hidden flex items-center justify-center cursor-pointer bg-gray-300"
            aria-haspopup="menu"
            aria-expanded={menuOpen}
          >
            {user?.picture ? (
              <img
                src={user.picture}
                alt="User"
                className="w-7 h-7 rounded-full object-cover"
                referrerPolicy="no-referrer"
                onError={(e) => {
                  e.currentTarget.style.display = 'none';
                  e.currentTarget.parentElement.innerHTML = `
            <span class="text-[10px] font-semibold text-gray-700">${user?.name?.[0]?.toUpperCase() || 'U'}</span>`;
                }}
              />
            ) : (
              <span className="text-[10px] font-semibold text-gray-700">
                {user?.name?.[0]?.toUpperCase() || 'U'}
              </span>
            )}
          </button>
          {menuOpen && (
            <div className="absolute right-0 mt-2 w-48 bg-white rounded-md shadow-lg z-50">
              <button
                onClick={() => { setMenuOpen(false); onLogout(); }}
                className="block w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-100 cursor-pointer"
              >
                Sign Out
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Mobile search panel */}
      {mobileSearchOpen && (
        <div className="absolute left-0 right-0 top-full md:hidden bg-white border-b border-gray-200 px-4 py-2 z-50">
          <div className="max-w-md mx-auto">
            <div className="relative border border-gray-200 rounded-md cursor-pointer" ref={searchRef}>
              <Search className="absolute left-2.5 top-1/2 transform -translate-y-1/2 w-4 h-4 text-gray-400" />
              <input
                type="text"
                placeholder="Search stocks..."
                value={query}
                onChange={onInputChange}
                onKeyDown={onKeyDown}
                onFocus={onFocus}
                onBlur={onBlur}
                aria-autocomplete="list"
                aria-expanded={suggestions.length > 0}
                aria-activedescendant={activeIndex >= 0 ? `srch-opt-${activeIndex}` : undefined}
                className="w-full pl-9 pr-8 py-2 text-sm border border-gray-200 rounded-md cursor-pointer focus:outline-none focus:ring-1 focus:ring-green-500 focus:border-transparent"
              />
              {query ? (
                <button
                  type="button"
                  onClick={() => {
                    setQuery('');
                    setShowSuggestions(false);
                    setTimeout(() => {
                      setSuggestions([]);
                      setActiveIndex(-1);
                    }, 200);
                  }}
                  className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-gray-400 hover:text-gray-600 rounded cursor-pointer"
                  aria-label="Clear search"
                  title="Clear"
                >
                  <X className="w-4 h-4" />
                </button>
              ) : null}

              {suggestions.length > 0 && (
                <ul
                  className={`absolute z-50 mt-2 w-full bg-white border border-gray-200 rounded-md shadow-lg overflow-hidden transition-all duration-200 origin-top ${showSuggestions
                    ? 'opacity-100 scale-y-100 translate-y-0'
                    : 'opacity-0 scale-y-95 -translate-y-2 pointer-events-none'
                    }`}
                  style={{ transformOrigin: 'top center' }}
                >
                  {suggestions.map((s, idx) => (
                    <li
                      key={s.ticker}
                      id={`srch-opt-${idx}`}
                      className={`transition-all duration-150 ${showSuggestions ? 'opacity-100 translate-x-0' : 'opacity-0 -translate-x-2'}`}
                      style={{ transitionDelay: showSuggestions ? `${idx * 30}ms` : '0ms' }}
                    >
                      <button
                        type="button"
                        onMouseEnter={() => setActiveIndex(idx)}
                        onClick={() => selectSuggestion(s)}
                        className={`w-full px-3 py-2 text-left flex items-center gap-2 transition-colors ${idx === activeIndex ? 'bg-gray-50' : 'bg-white'} hover:bg-gray-50 cursor-pointer`}
                      >
                        <div className="w-8 h-8 bg-black rounded flex items-center justify-center flex-shrink-0">
                          {s.logo ? (
                            <img
                              src={s.logo}
                              alt={s.ticker}
                              className="w-6 h-6 object-contain"
                              onError={(e) => {
                                e.target.style.display = 'none';
                                e.target.parentElement.innerHTML = `<span class="text-white text-xs font-semibold">${s.ticker[0]}</span>`;
                              }}
                            />
                          ) : (
                            <span className="text-white text-xs font-semibold">{s.ticker[0]}</span>
                          )}
                        </div>
                        <div className="flex flex-col min-w-0 flex-1">
                          <span className="font-semibold text-gray-900 text-sm">{s.ticker}</span>
                          <span className="text-xs text-gray-500 truncate">{s.name}</span>
                        </div>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Mobile nav panel */}
      {mobileNavOpen && (
        <div className="absolute left-0 right-0 top-full md:hidden bg-white border-b border-gray-200 shadow z-40">
          <div className="px-4 py-2 space-y-1">
            <Link
              to="/dashboard"
              onClick={() => setMobileNavOpen(false)}
              className={`block px-3 py-2 text-sm font-medium rounded-md ${location.pathname === '/dashboard'
                ? 'text-green-700 bg-green-50'
                : 'text-gray-700 hover:text-gray-900 hover:bg-gray-50'
                }`}
            >
              Market
            </Link>
            <Link
              to="/portfolio"
              onClick={() => setMobileNavOpen(false)}
              className={`block px-3 py-2 text-sm font-medium rounded-md ${location.pathname === '/portfolio'
                ? 'text-green-700 bg-green-50'
                : 'text-gray-700 hover:text-gray-900 hover:bg-gray-50'
                }`}
            >
              Portfolio
            </Link>
            {/* Add Pro button to mobile menu */}
            <button
              onClick={() => {
                setShowProModal(true);
                setMobileNavOpen(false);
              }}
              className="w-full text-left px-3 py-2 text-sm font-medium rounded-md bg-gradient-to-r from-green-600 to-green-700 text-white cursor-pointer"
            >
              Pro
            </button>
          </div>
        </div>
      )}
    </nav>
  );
}

export default Navbar;