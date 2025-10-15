import React from 'react';
import { TrendingUp, BarChart3 } from 'lucide-react';
import { MarketOverview, TickerTape } from "react-ts-tradingview-widgets";
import Loading from '../components/Loading';
import { useNavigate } from 'react-router-dom';
import ComparisonChart from '../components/ComparisonChart';
import { useQuery, useQueryClient } from '@tanstack/react-query';

function Dashboard({ isChatbotOpen, setIsChatbotOpen, user }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const VITE_APP_API_URL = import.meta.env.VITE_APP_API_URL;
  // Load tickers for logo/name lookups
  const [tickers, setTickers] = React.useState([]);

  // Define which benchmarks to compare - you can change these dynamically
  const [benchmarks, setBenchmarks] = React.useState([
    { symbol: 'QQQ', key: 'nasdaq', label: 'NASDAQ 100' },
    { symbol: 'DIA', key: 'dow', label: 'Dow Jones' }
  ]);

  // Edit Watchlist modal state - MOVED TO TOP
  const [editOpen, setEditOpen] = React.useState(false);
  const [q, setQ] = React.useState('');
  const [suggestions, setSuggestions] = React.useState([]);
  const [activeIdx, setActiveIdx] = React.useState(-1);
  const [focused, setFocused] = React.useState(false);
  const [pending, setPending] = React.useState([]);
  const [saving, setSaving] = React.useState(false); // Add this line

  React.useEffect(() => {
    let cancelled = false;
    fetch('/tickers.json')
      .then(r => r.json())
      .then(d => { if (!cancelled) setTickers(Array.isArray(d) ? d : []); })
      .catch(() => { });
    return () => { cancelled = true; };
  }, []);
  const getTickerDetails = (symbol) => {
    const t = tickers.find(x => x.ticker === symbol);
    return t || { ticker: symbol, name: symbol, logo: null };
  };

  // Build benchmarks query param from array
  const benchmarksParam = benchmarks
    .map(b => `${b.symbol}:${b.key}:${b.label}`)
    .join(',');

  const { data: marketData, isLoading: loading } = useQuery({
    queryKey: ['market-summary', user?.token, benchmarksParam],
    enabled: !!user?.token,
    staleTime: Infinity,
    queryFn: async () => {
      const url = new URL(`${VITE_APP_API_URL}/api/market-summary`);
      if (benchmarksParam) {
        url.searchParams.set('benchmarks', benchmarksParam);
      }
      const res = await fetch(url, {
        headers: {
          'Authorization': `Bearer ${user.token}`
        }
      });
      if (!res.ok) throw new Error('Failed to load market data');
      return res.json();
    },
  });

  // NOW the conditional returns are safe - all hooks are declared above
  const newsItems = (marketData?.news?.slice(0, 6)) || [
    { title: 'Tech leads market rebound; AI stocks surge', date: marketData?.mainArticle?.date || '', summary: 'Growth shares advance as yields stabilize; investors rotate back into risk.', url: 'https://news.example.com/ai-rebound' },
    { title: 'Oil retreats as supply outlook improves', date: marketData?.mainArticle?.date || '', summary: 'Crude falls after reports of increased output; inflation expectations ease.', url: 'https://news.example.com/oil-retreats' },
    { title: 'Fed minutes signal data-dependent stance', date: marketData?.mainArticle?.date || '', summary: 'Officials emphasize flexibility; markets price in steady rates near-term.', url: 'https://news.example.com/fed-minutes' },
    { title: 'Dollar eases, boosting EM assets', date: marketData?.mainArticle?.date || '', summary: 'Greenback slips; emerging market equities and FX find support.', url: 'https://news.example.com/dollar-eases' },
    { title: 'Earnings season kicks off with beats', date: marketData?.mainArticle?.date || '', summary: 'Several bellwethers top expectations; guidance mixed but improving.', url: 'https://news.example.com/earnings-beats' },
    { title: 'Yields dip; risk appetite improves', date: marketData?.mainArticle?.date || '', summary: 'Treasury yields edge lower as markets price softer inflation path.', url: 'https://news.example.com/yields-dip' }
  ];

  // New datasets from API
  const watchlistStocks = marketData?.watchlistStocks || [];
  const topMarketMovers = marketData?.topStocks || [];

  if (loading) {
    return <Loading message="Loading market data..." fullScreen={false} />;
  }

  if (!marketData) {
    return (
      <div className="w-full h-full flex items-center justify-center bg-gray-50">
        <p className="text-xl text-red-400">Failed to load market data</p>
      </div>
    );
  }

  // Highlight numbers in text
  const highlightNumbers = (text) => {
    const regex = /([+-]?\d+[,\d]*\.?\d*%?)/g;
    const parts = text.split(regex);

    return parts.map((part, index) => {
      if (regex.test(part)) {
        const isPositive = part.startsWith('+');
        const isNegative = part.startsWith('-');
        const bgColorClass = isPositive ? 'bg-green-50' : isNegative ? 'bg-red-50' : 'bg-blue-50';
        const textColorClass = isPositive ? 'text-green-700' : isNegative ? 'text-red-700' : 'text-blue-700';
        return (
          <span key={index} className={`${textColorClass} ${bgColorClass} font-normal px-1 rounded`}>
            {part}
          </span>
        );
      }
      return part;
    });
  };

  // Edit Watchlist modal state + helpers
  const topStocksDefault = [
    { ticker: 'AAPL', name: 'Apple Inc.' },
    { ticker: 'MSFT', name: 'Microsoft Corporation' },
    { ticker: 'NVDA', name: 'NVIDIA Corporation' },
    { ticker: 'GOOGL', name: 'Alphabet Inc.' },
    { ticker: 'AMZN', name: 'Amazon.com Inc.' }
  ];

  const runModalSearch = (value) => {
    const query = (value || '').trim();
    if (!query) {
      if (focused) {
        setSuggestions(topStocksDefault);
        setActiveIdx(topStocksDefault.length ? 0 : -1);
      } else {
        setSuggestions([]);
        setActiveIdx(-1);
      }
      return;
    }
    const qUpper = query.toUpperCase();
    const qLower = query.toLowerCase();
    const ranked = (tickers || [])
      .filter(t =>
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
      .slice(0, 8);
    setSuggestions(ranked);
    setActiveIdx(ranked.length ? 0 : -1);
  };

  const addPending = (sym) => {
    const t = (sym || '').trim().toUpperCase();
    if (!t) return;
    setPending(p => (p.includes(t) ? p : [...p, t]));
    setQ('');
    setSuggestions([]);
    setActiveIdx(-1);
  };
  const removePending = (sym) => setPending(p => p.filter(x => x !== sym));

  const onModalKeyDown = (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      if (suggestions.length) {
        const s = suggestions[activeIdx] || suggestions[0];
        if (s) addPending(s.ticker);
        else if (q.trim()) addPending(q);
      } else if (q.trim()) {
        addPending(q);
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

  const saveWatchlist = async () => {
    if (!pending.length) {
      setEditOpen(false);
      return;
    }
    setSaving(true);
    try {
      await fetch(`${VITE_APP_API_URL}/api/user/watchlist`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${user.token}`
        },
        body: JSON.stringify({ symbols: pending })
      });

      // Force refetch by invalidating and refetching
      await queryClient.invalidateQueries({
        queryKey: ['market-summary', user?.token, benchmarksParam],
        refetchType: 'active'
      });

      // Wait a bit for the refetch to complete
      await queryClient.refetchQueries({
        queryKey: ['market-summary', user?.token, benchmarksParam]
      });

      setEditOpen(false);
      setPending([]);
    } catch (_) {
      // no-op
    } finally {
      setSaving(false);
    }
  };

  const exportToPDF = async () => {
    try {
      // Get the dashboard container
      const dashboardElement = document.getElementById('dashboard-content');

      if (!dashboardElement) {
        console.error('Dashboard element not found');
        return;
      }

      // Show loading state (optional)
      const originalCursor = document.body.style.cursor;
      document.body.style.cursor = 'wait';

      // Create a clone to avoid modifying the actual DOM
      const clone = dashboardElement.cloneNode(true);

      // Replace OKLCH colors with RGB equivalents
      const replaceOklchColors = (element) => {
        const computedStyle = window.getComputedStyle(element);
        const backgroundColor = computedStyle.backgroundColor;
        const color = computedStyle.color;

        // If colors contain oklch, override with RGB
        if (backgroundColor.includes('oklch')) {
          element.style.backgroundColor = 'rgb(249, 250, 251)'; // gray-50
        }
        if (color.includes('oklch')) {
          element.style.color = 'rgb(17, 24, 39)'; // gray-900
        }

        // Recursively process children
        Array.from(element.children).forEach(replaceOklchColors);
      };

      // Apply to clone
      replaceOklchColors(clone);

      // Temporarily add clone to body (hidden)
      clone.style.position = 'absolute';
      clone.style.left = '-9999px';
      document.body.appendChild(clone);

      // Capture the clone as canvas
      const canvas = await html2canvas(clone, {
        scale: 2, // Higher quality
        useCORS: true, // Allow cross-origin images
        logging: false,
        backgroundColor: '#f9fafb' // Explicit RGB background
      });

      // Remove the clone
      document.body.removeChild(clone);

      // Calculate PDF dimensions
      const imgWidth = 210; // A4 width in mm
      const pageHeight = 297; // A4 height in mm
      const imgHeight = (canvas.height * imgWidth) / canvas.width;
      let heightLeft = imgHeight;

      const imgData = canvas.toDataURL('image/png');
      const pdf = new jsPDF('p', 'mm', 'a4');
      let position = 0;

      // Add first page
      pdf.addImage(imgData, 'PNG', 0, position, imgWidth, imgHeight);
      heightLeft -= pageHeight;

      // Add additional pages if content is longer than one page
      while (heightLeft >= 0) {
        position = heightLeft - imgHeight;
        pdf.addPage();
        pdf.addImage(imgData, 'PNG', 0, position, imgWidth, imgHeight);
        heightLeft -= pageHeight;
      }

      // Generate filename with current date
      const date = new Date().toISOString().split('T')[0];
      pdf.save(`BullRun-Dashboard-${date}.pdf`);

      // Reset cursor
      document.body.style.cursor = originalCursor;
    } catch (error) {
      console.error('Error generating PDF:', error);
      document.body.style.cursor = 'auto';
    }
  };

  // Format date by subtracting 4 hours
  const adjustNewsDate = (dateString, hours) => {
    if (!dateString) return '';
    try {
      const date = new Date(dateString);
      // Subtract 4 hours (4 * 60 * 60 * 1000 milliseconds)
      date.setTime(date.getTime() - (hours * 60 * 60 * 1000));

      // Format the date nicely
      return date.toLocaleString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
        hour12: true
      });
    } catch (e) {
      return dateString; // Return original if parsing fails
    }
  };

  return (
    <div className="w-full h-full overflow-auto bg-gray-50">
      <div className="px-6 py-6 max-w-[1400px] mx-auto">
        {/* Main Article - Keep as is */}
        <div className="bg-white rounded-md p-4 mb-3 shadow-sm border border-gray-200">
          <div className="flex items-start gap-2.5 mb-2">
            <div className="p-1.5 bg-green-50 rounded flex-shrink-0">
              <TrendingUp className="w-3.5 h-3.5 text-green-600" />
            </div>
            <div className="flex-1 min-w-0">
              <h2 className="text-md font-bold text-gray-900 mb-0.5 leading-tight">
                {marketData.mainArticle.title}
              </h2>
              <p className="text-sm text-gray-500">{marketData.mainArticle.date}</p>
            </div>
          </div>
          <p className="text-sm text-gray-700 leading-relaxed">
            {highlightNumbers(marketData.mainArticle.content)}
          </p>
        </div>

        {/* Index Comparison Chart (toggles inside chart now) - chart fetches its own timeframes */}
        <div className="bg-white rounded-md mb-3">
          <ComparisonChart
            ticker="S&P 500"
            symbol="SPY"
            token={user.token}
            benchmarks={benchmarks}
            logo="https://raw.githubusercontent.com/davidepalazzo/ticker-logos/refs/heads/main/ticker_icons/SPY.png"
            price={marketData?.marketChart?.price}
            prevClose={marketData?.marketChart?.prevClose}
            change={marketData?.marketChart?.change}
            changePct={marketData?.marketChart?.changePct}
          />
        </div>

        {/* NEW LAYOUT: 3-Column Grid with 3 Rows */}
        <div className="grid grid-cols-1 lg:grid-cols-3 lg:grid-rows-3 gap-4 mb-4">

          {/* Key Movements - 2 cols, 1 row (top left) */}
          <div className="bg-white rounded-md shadow-sm border border-gray-200 lg:col-span-2 lg:row-span-1 max-h-[350px] md:max-h-[250px] overflow-y-auto">
            <div className="px-3.5 pt-3 pb-2 border-b border-gray-100">
              <div className="flex items-center gap-1.5">
                <BarChart3 className="w-4 h-4 text-green-600" />
                <h3 className="font-bold text-gray-900 text-sm">Key Movements</h3>
              </div>
            </div>
            <div className="px-3.5 py-3">
              <ul className="space-y-2">
                {marketData.keyMovements.map((movement, index) => (
                  <li key={index} className="flex gap-1.5 text-sm text-gray-700">
                    <span className="text-green-600 mt-0.5 flex-shrink-0 text-xs">•</span>
                    <span>{movement}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>

          {/* Watchlist - 1 col, 1 rows (top right) */}
          <div className="bg-white rounded-md shadow-sm border border-gray-200 flex flex-col lg:row-span-1 lg:col-span-1 max-h-[500px] md:max-h-[250px] overflow-y-auto">
            <div className="px-3.5 pt-3 pb-2 border-b border-gray-100 flex items-center justify-between flex-shrink-0">
              <div className="flex items-center gap-1.5">
                <TrendingUp className="w-4 h-4 text-green-600" />
                <h3 className="font-bold text-gray-900 text-sm">Your Watchlist</h3>
              </div>
              <button
                type="button"
                onClick={() => {
                  setEditOpen(true);
                  setPending(watchlistStocks.map(s => s.symbol)); // Pre-populate with existing watchlist
                  setQ('');
                  setSuggestions([]);
                  setActiveIdx(-1);
                }}
                className="text-xs px-2 py-1 rounded-md border border-gray-300 text-gray-700 hover:bg-gray-50 cursor-pointer"
              >
                Edit
              </button>
            </div>
            <div className="px-3.5 py-3 flex-1 overflow-y-auto">
              {watchlistStocks.length === 0 ? (
                <div className="text-xs text-gray-500">No symbols in your watchlist.</div>
              ) : (
                <div className="space-y-2.5">
                  {watchlistStocks.map((stock, index) => {
                    const t = getTickerDetails(stock.symbol);
                    return (
                      <div
                        key={index}
                        onClick={() => navigate(`/dashboard/${stock.symbol}`)}
                        className="flex items-center justify-between py-1.5 border-b border-gray-50 last:border-0 cursor-pointer hover:bg-gray-50 transition-colors rounded px-2 -mx-2"
                      >
                        <div className="flex items-center gap-2 flex-1 min-w-0">
                          <div className="w-7 h-7 bg-black rounded flex items-center justify-center flex-shrink-0">
                            {t.logo ? (
                              <img
                                src={t.logo}
                                alt={stock.symbol}
                                className="w-5 h-5 object-contain"
                                onError={(e) => {
                                  e.currentTarget.style.display = 'none';
                                  e.currentTarget.parentElement.innerHTML = `<span class="text-white text-xs font-semibold">${stock.symbol[0]}</span>`;
                                }}
                              />
                            ) : (
                              <span className="text-white text-xs font-semibold">{stock.symbol[0]}</span>
                            )}
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="font-semibold text-xs text-gray-900">{stock.symbol}</div>
                            <div className="text-[10px] text-gray-500 truncate">{t.name}</div>
                          </div>
                        </div>
                        <div className="text-right ml-2">
                          <div className="text-xs font-medium text-gray-900">${stock.price}</div>
                          <div className={`text-[10px] font-medium ${String(stock.change || '').startsWith('+') ? 'text-green-600' : 'text-red-600'}`}>
                            {stock.change} ({stock.changePercent})
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>

          {/* Watch Points - Full row (second row) */}
          <div className="bg-white rounded-md shadow-sm border border-gray-200 lg:col-span-3 lg:row-span-1 max-h-[500px] md:max-h-[250px] overflow-y-auto">
            <div className="px-3.5 pt-3 pb-2 border-b border-gray-100">
              <div className="flex items-center gap-1.5">
                <BarChart3 className="w-4 h-4 text-green-600" />
                <h3 className="font-bold text-gray-900 text-sm">Watch Points</h3>
              </div>
            </div>
            <div className="px-3.5 py-3">
              <ul className="space-y-2">
                {marketData.watchPoints.map((point, index) => (
                  <li key={index} className="flex gap-1.5 text-sm text-gray-700">
                    <span className="text-green-600 mt-0.5 flex-shrink-0 text-xs">•</span>
                    <span>{point}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>

          {/* Implications - 1 col, 1 row (third row left) */}
          <div className="bg-white rounded-md shadow-sm border border-gray-200 lg:col-span-2 lg:row-span-1 max-h-[500px] md:max-h-[250px] overflow-y-auto">
            <div className="px-3.5 pt-3 pb-2 border-gray-100 border-b">
              <div className="flex items-center gap-1.5">
                <BarChart3 className="w-4 h-4 text-green-600" />
                <h3 className="font-bold text-gray-900 text-sm">Implications</h3>
              </div>
            </div>
            <div className="px-3.5 py-3">
              <ul className="space-y-2">
                {marketData.implications.map((implication, index) => (
                  <li key={index} className="flex gap-1.5 text-sm text-gray-700">
                    <span className="text-green-600 mt-0.5 flex-shrink-0 text-sm">•</span>
                    <span>{implication}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>

          {/* Top Movers by Volume - 1 col, 1 row (third row middle) */}
          <div className="bg-white rounded-md shadow-sm border border-gray-200 flex flex-col lg:row-span-1 lg:col-span-1 max-h-[500px] md:max-h-[250px] overflow-y-auto">
            <div className="px-3.5 pt-3 pb-2 border-b border-gray-100 flex-shrink-0">
              <div className="flex items-center gap-1.5">
                <TrendingUp className="w-4 h-4 text-green-600" />
                <h3 className="font-bold text-gray-900 text-sm">Top Market Movers</h3>
              </div>
            </div>
            <div className="px-3.5 py-3 flex-1 overflow-y-auto">
              <div className="space-y-2.5">
                {topMarketMovers.map((stock, index) => {
                  const t = getTickerDetails(stock.symbol);
                  return (
                    <div
                      key={index}
                      onClick={() => navigate(`/dashboard/${stock.symbol}`)}
                      className="flex items-center justify-between py-1.5 border-b border-gray-50 last:border-0 cursor-pointer hover:bg-gray-50 transition-colors rounded px-2 -mx-2"
                    >
                      <div className="flex items-center gap-2 flex-1 min-w-0">
                        <div className="w-7 h-7 bg-black rounded flex items-center justify-center flex-shrink-0">
                          {t.logo ? (
                            <img
                              src={t.logo}
                              alt={stock.symbol}
                              className="w-5 h-5 object-contain"
                              onError={(e) => {
                                e.currentTarget.style.display = 'none';
                                e.currentTarget.parentElement.innerHTML = `<span class="text-white text-xs font-semibold">${stock.symbol[0]}</span>`;
                              }}
                            />
                          ) : (
                            <span className="text-white text-xs font-semibold">{stock.symbol[0]}</span>
                          )}
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="font-semibold text-xs text-gray-900">{stock.symbol}</div>
                          <div className="text-[10px] text-gray-500 truncate">{t.name}</div>
                        </div>
                      </div>
                      <div className="text-right ml-2">
                        <div className="text-xs font-medium text-gray-900">${stock.price}</div>
                        <div className={`text-[10px] font-medium ${String(stock.change || '').startsWith('+') ? 'text-green-600' : 'text-red-600'}`}>
                          {stock.change} ({stock.changePercent})
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

        </div>

        {/* News Row - Full width rows with images */}
        <div className="bg-white rounded-md p-6 shadow-sm border border-gray-200">
          <div className="flex items-start gap-2.5 mb-4">
            <div className="p-1.5 bg-green-50 rounded flex-shrink-0">
              <TrendingUp className="w-3.5 h-3.5 text-green-600" />
            </div>
            <div className="flex-1 min-w-0">
              <h2 className="text-md font-bold text-gray-900 mb-0.5 leading-tight">In The News</h2>
              <p className="text-sm text-gray-500">{marketData?.mainArticle?.date || ''}</p>
            </div>
          </div>
          <div className="flex flex-col gap-4">
            {(marketData?.news || [])
              .sort((a, b) => {
                const dateA = new Date(a.date || a.published || 0);
                const dateB = new Date(b.date || b.published || 0);
                return dateB - dateA; // Most recent first (descending)
              })
              .slice(0, 6)
              .map((item, idx) => {
                const href = item.url || item.link || '#';
                const imageUrl = item.image_url || item.thumbnail_url || item.image || null;

                return (
                  <a
                    key={idx}
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="group flex flex-col border border-gray-200 rounded-lg p-4 hover:shadow-md transition-shadow focus:outline-none focus-visible:ring-2 focus-visible:ring-green-600 focus-visible:ring-offset-2"
                  >
                    {/* Publisher Info at top */}
                    {item.publisher && (
                      <div className="flex items-center gap-2 mb-3">
                        {item.publisher.logo_url && (
                          <img
                            src={item.publisher.logo_url}
                            alt={item.publisher.name || 'publisher'}
                            className="w-5 h-5 object-contain rounded"
                            loading="lazy"
                          />
                        )}
                        <span className="text-xs text-gray-500 font-medium">
                          {item.publisher.name || 'Unknown Publisher'}
                        </span>
                      </div>
                    )}

                    {/* Image and Content side by side */}
                    <div className="flex flex-col md:flex-row gap-4">
                      {/* News Image */}
                      {imageUrl && (
                        <div className="flex-shrink-0 w-32 h-24 md:w-48 md:h-32 rounded-lg overflow-hidden bg-gray-100">
                          <img
                            src={imageUrl != "" ? imageUrl : item.publisher?.logo_url}
                            alt={item.title}
                            className="w-full h-full object-contain"
                            loading="lazy"
                            onError={(e) => {
                              // Fallback to publisher logo if main image fails
                              if (item.publisher?.logo_url && e.currentTarget.src !== item.publisher.logo_url) {
                                e.currentTarget.src = item.publisher.logo_url;
                              } else {
                                // If publisher logo also fails or doesn't exist, hide the image container
                                e.currentTarget.style.display = 'none';
                                e.currentTarget.parentElement.classList.add('hidden');
                              }
                            }}
                          />
                        </div>
                      )}

                      {/* Content */}
                      <div className="flex-1 min-w-0 flex flex-col">
                        <h3 className="text-sm font-bold text-gray-900 leading-snug mb-2 group-hover:text-green-700">
                          {item.title}
                        </h3>
                        <p className="text-xs text-gray-500 mb-2">{adjustNewsDate(item.date || item.published, 0)}</p>
                        <p className="text-sm text-gray-700 line-clamp-3 mb-2">{item.summary || item.description}</p>
                        <span className="text-xs font-semibold text-green-700 group-hover:underline">Read more →</span>
                      </div>
                    </div>
                  </a>
                );
              })}
          </div>
        </div>

        {editOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center">
            <div className="absolute inset-0 bg-black/40" onClick={() => setEditOpen(false)} />
            <div className="relative bg-white w-full max-w-md rounded-md shadow-lg border border-gray-200 p-4">
              <h3 className="text-sm font-bold text-gray-900 mb-2">Edit Watchlist</h3>
              <div className="text-xs text-gray-500 mb-3">Search and add tickers to your watchlist.</div>

              <div className="relative mb-3">
                <input
                  type="text"
                  value={q}
                  onChange={(e) => { setQ(e.target.value); runModalSearch(e.target.value); }}
                  onKeyDown={onModalKeyDown}
                  onFocus={() => { setFocused(true); if (!q.trim()) { setSuggestions(topStocksDefault); setActiveIdx(topStocksDefault.length ? 0 : -1); } }}
                  onBlur={() => { setTimeout(() => { setFocused(false); setSuggestions([]); setActiveIdx(-1); }, 150); }}
                  placeholder="Type a ticker or name..."
                  className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-green-500 cursor-pointer"
                />
                {!!suggestions.length && (
                  <ul className="absolute z-50 mt-2 w-full bg-white border border-gray-200 rounded-md shadow-lg overflow-hidden">
                    {suggestions.map((s, idx) => {
                      const details = getTickerDetails(s.ticker);
                      return (
                        <li key={s.ticker}>
                          <button
                            type="button"
                            onMouseEnter={() => setActiveIdx(idx)}
                            onClick={() => addPending(s.ticker)}
                            className={`w-full px-3 py-2 text-left text-sm transition-colors cursor-pointer flex items-center gap-2 ${idx === activeIdx ? 'bg-gray-50' : 'bg-white'}`}
                          >
                            <div className="w-6 h-6 bg-black rounded flex items-center justify-center flex-shrink-0">
                              {details.logo ? (
                                <img
                                  src={details.logo}
                                  alt={s.ticker}
                                  className="w-4 h-4 object-contain"
                                  onError={(e) => {
                                    e.currentTarget.style.display = 'none';
                                    e.currentTarget.parentElement.innerHTML = `<span class="text-white text-[10px] font-semibold">${s.ticker[0]}</span>`;
                                  }}
                                />
                              ) : (
                                <span className="text-white text-[10px] font-semibold">{s.ticker[0]}</span>
                              )}
                            </div>
                            <div className="flex-1">
                              <span className="font-semibold text-gray-900">{s.ticker}</span>
                              <span className="text-gray-500 ml-2 text-xs">{s.name}</span>
                            </div>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>

              {!!pending.length && (
                <div className="flex flex-wrap gap-2 mb-3">
                  {pending.map(t => {
                    const details = getTickerDetails(t);
                    return (
                      <span key={t} className="inline-flex items-center gap-1.5 px-2 py-1.5 rounded-full bg-gray-100 text-gray-700 text-xs border border-gray-200">
                        <div className="w-5 h-5 bg-black rounded-full flex items-center justify-center flex-shrink-0">
                          {details.logo ? (
                            <img
                              src={details.logo}
                              alt={t}
                              className="w-3.5 h-3.5 object-contain"
                              onError={(e) => {
                                e.currentTarget.style.display = 'none';
                                e.currentTarget.parentElement.innerHTML = `<span class="text-white text-[9px] font-semibold">${t[0]}</span>`;
                              }}
                            />
                          ) : (
                            <span className="text-white text-[9px] font-semibold">{t[0]}</span>
                          )}
                        </div>
                        <span className="font-medium">{t}</span>
                        <button type="button" onClick={() => removePending(t)} className="text-gray-500 hover:text-gray-700 cursor-pointer ml-0.5">×</button>
                      </span>
                    );
                  })}
                </div>
              )}

              <div className="flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setEditOpen(false)}
                  disabled={saving}
                  className="px-3 py-1.5 text-xs rounded-md border border-gray-300 text-gray-700 hover:bg-gray-50 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={saveWatchlist}
                  disabled={saving}
                  className="px-3 py-1.5 bg-green-600 text-white text-xs font-semibold rounded-md hover:bg-green-700 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {saving ? 'Saving...' : 'Save'}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Disclaimer - Keep as is */}
        <div className="mt-6 px-3 py-3 text-[10px] text-gray-500 leading-relaxed">
          <p>
            BullRun, Inc. ("BullRun") is in the process of applying for registration as an investment adviser with the U.S. Securities and Exchange Commission.
            Until registration is effective BullRun does not provide investment advisory services to the public and is not soliciting clients in any jurisdiction
            where such solicitation or provision of services would be unlawful prior to registration or notice filing. All information on this site is for
            informational purposes only and should not be construed as investment advice, an offer, or a solicitation to buy or sell any security.
          </p>
        </div>
      </div>
    </div>
  );
}

export default Dashboard;