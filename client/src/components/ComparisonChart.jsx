import { useEffect, useMemo, useState, useCallback, useRef } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';

const TF_ORDER = ['1D', '5D', '1M', '6M', 'YTD', '1Y', 'ALL'];
const HEAVY_TFS = new Set(['6M', 'YTD', '1Y', 'ALL']);
const BENCH_LABELS = { sp500: 'S&P 500', nasdaq: 'NASDAQ 100', dow: 'Dow Jones' };
const BENCH_COLORS = { sp500: '#3b82f6', nasdaq: '#8b5cf6', dow: '#f59e0b' }; // blue, purple, amber

function currencyUSD(n, max = 0) {
  const v = Number(n);
  if (!isFinite(v)) return '-';
  return v.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: max });
}
function percentStr(n, max = 2) {
  const v = Number(n);
  if (!isFinite(v)) return '-';
  return `${v.toLocaleString('en-US', { maximumFractionDigits: max })}%`;
}

function buildSmoothPathXY(points) {
  const pts = points.filter(p => Number.isFinite(p.x) && Number.isFinite(p.y));
  if (pts.length === 0) return '';
  if (pts.length === 1) return `M ${pts[0].x} ${pts[0].y}`;
  if (pts.length === 2) return `M ${pts[0].x} ${pts[0].y} L ${pts[1].x} ${pts[1].y}`;

  let d = `M ${pts[0].x} ${pts[0].y}`;
  for (let i = 1; i < pts.length - 1; i++) {
    const curr = pts[i];
    const next = pts[i + 1];
    const mx = (curr.x + next.x) / 2;
    const my = (curr.y + next.y) / 2;
    d += ` Q ${curr.x} ${curr.y} ${mx} ${my}`;
  }
  const last = pts[pts.length - 1];
  d += ` L ${last.x} ${last.y}`;
  return d;
}

export default function ComparisonChart({ ticker, symbol, token, benchmarks = [], price, prevClose, change, changePct, logo, isMobile }) {
  console.log('isMobile', isMobile);
  const [tf, setTf] = useState('5D');
  const [visibleBenches, setVisibleBenches] = useState({ sp500: true, nasdaq: true, dow: true });
  const queryClient = useQueryClient();
  const VITE_APP_API_URL = import.meta.env.VITE_APP_API_URL;
  // Responsive sizing based on container
  const containerRef = useRef(null);
  const [chartSize, setChartSize] = useState({ w: 0, h: 0 });

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
  
    const compute = () => {
      const rect = el.getBoundingClientRect();
      // Remove the hardcoded 320px minimum for mobile
      const width = isMobile 
        ? Math.max(280, Math.floor(rect.width || 0))  // Lower minimum for mobile
        : Math.max(320, Math.floor(rect.width || 0)); // Keep 320px for desktop
      
      setChartSize(prev => {
        if (Math.abs(prev.w - width) < 5) return prev;
        
        const isTablet = !isMobile && width < 1024;
  
        let height;
        if (isMobile) {
          height = Math.round(Math.max(240, Math.min(420, width * 0.6)));
        } else if (isTablet) {
          height = Math.round(Math.max(260, Math.min(440, width * 0.36)));
        } else {
          height = Math.round(Math.max(260, Math.min(380, width * 0.30)));
        }
        return { w: width, h: height };
      });
    };
    
    // Initial computation with delays
    compute();
    const timeout1 = setTimeout(compute, 50);
    const timeout2 = setTimeout(compute, 200);
    
    const ro = new ResizeObserver(compute);
    ro.observe(el);
    
    window.addEventListener('resize', compute);
    window.addEventListener('orientationchange', compute);
    
    // Force recomputation when tab becomes visible (fixes tab switching issue)
    const handleVisibilityChange = () => {
      if (!document.hidden) {
        setTimeout(compute, 100);
      }
    };
    document.addEventListener('visibilitychange', handleVisibilityChange);
    
    return () => {
      clearTimeout(timeout1);
      clearTimeout(timeout2);
      ro.disconnect();
      window.removeEventListener('resize', compute);
      window.removeEventListener('orientationchange', compute);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [isMobile]);
  
  const buildBenchmarksParam = useCallback(() => {
    if (!benchmarks || !benchmarks.length) return '';
    return benchmarks.map(b => `${b.symbol}:${b.key}:${b.label}`).join(',');
  }, [benchmarks]);

  // Fetch function for timeframe data
  const fetchTimeframe = async (tfKey) => {
    if (!symbol || !token) throw new Error('Missing symbol or token');
    
    const url = new URL(`${VITE_APP_API_URL}/api/chart/timeframe`);
    url.searchParams.set('ticker', symbol);
    url.searchParams.set('tf', tfKey);
    const bp = buildBenchmarksParam();
    if (bp) url.searchParams.set('benchmarks', bp);
    
    const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
    if (!res.ok) throw new Error('Failed to load timeframe');
    const json = await res.json();
    return { series: json.series || [], benchmarks: json.benchmarks || [] };
  };

  // Prefetch light timeframes on mount
  useEffect(() => {
    if (!symbol || !token) return;
    
    // Prefetch light timeframes
    queryClient.prefetchQuery({
      queryKey: ['chart-timeframe', symbol, '1D', buildBenchmarksParam()],
      queryFn: () => fetchTimeframe('1D'),
      staleTime: 5 * 60 * 1000, // 5 minutes
    });
    queryClient.prefetchQuery({
      queryKey: ['chart-timeframe', symbol, '5D', buildBenchmarksParam()],
      queryFn: () => fetchTimeframe('5D'),
      staleTime: 5 * 60 * 1000,
    });
    queryClient.prefetchQuery({
      queryKey: ['chart-timeframe', symbol, '1M', buildBenchmarksParam()],
      queryFn: () => fetchTimeframe('1M'),
      staleTime: 5 * 60 * 1000,
    });
  }, [symbol, token, buildBenchmarksParam, queryClient]);

  // Use TanStack Query for current timeframe
  const { data: tfData, isLoading, error } = useQuery({
    queryKey: ['chart-timeframe', symbol, tf, buildBenchmarksParam()],
    queryFn: () => fetchTimeframe(tf),
    enabled: !!symbol && !!token,
    staleTime: 5 * 60 * 1000, // 5 minutes
    gcTime: 30 * 60 * 1000, // 30 minutes (previously cacheTime)
  });

  const baseSeries = tfData?.series || []; // main ticker [{ t, c }]
  const allBenchmarks = tfData?.benchmarks || []; // [{ key, label, symbol, series }]

  // Build % change series for each benchmark
  const benchPctByKey = useMemo(() => {
    const map = {};
    for (const bench of allBenchmarks) {
      const raw = bench.series || [];
      const firstClose = raw.length && typeof raw[0].c === 'number' ? raw[0].c : null;
      const pct = firstClose
        ? raw.map(p => ({ t: p.t, r: typeof p.c === 'number' ? (p.c / firstClose - 1) * 100 : null }))
        : [];
      // index by date
      const byDate = new Map();
      for (const p of pct) if (p?.t) byDate.set(p.t, p.r);
      map[bench.key] = byDate;
    }
    return map;
  }, [allBenchmarks]);

  // Align main series with all benchmark % changes
  const aligned = useMemo(() => {
    const out = [];
    let startClose = null;
    for (let i = 0; i < baseSeries.length; i++) {
      const b = baseSeries[i];
      if (!b?.t) continue;
      const c = typeof b.c === 'number' ? b.c : null;
      if (startClose == null && typeof c === 'number') startClose = c;
      const prev = i > 0 && typeof baseSeries[i - 1]?.c === 'number' ? baseSeries[i - 1].c : null;
      const dayChg = prev != null && c != null ? c - prev : null;
      const cumChg = startClose != null && c != null ? c - startClose : null;
      const cumPct = startClose != null && c != null && startClose !== 0 ? (c / startClose - 1) * 100 : null;

      const row = { i, t: b.t, mainClose: c, mainPrev: prev, mainDayChg: dayChg, mainCumChg: cumChg, mainCumPct: cumPct };
      // attach each benchmark's %
      for (const bench of allBenchmarks) {
        row[`${bench.key}Pct`] = benchPctByKey[bench.key]?.get(b.t) ?? null;
      }
      out.push(row);
    }
    return out;
  }, [baseSeries, allBenchmarks, benchPctByKey]);

  // Responsive canvas
  const w = chartSize.w || (isMobile ? 320 : 800);
  const h = chartSize.h || (isMobile ? 240 : 360);
  
  // Dynamic paddings based on width
  const narrow = isMobile;
  const leftPad = narrow ? 42 : 56;
  const rightPad = narrow ? 34 : 56;
  const topPad = narrow ? 16 : 26;
  const bottomPad = narrow ? 30 : 36;

  const innerW = w - leftPad - rightPad;
  const innerH = h - topPad - bottomPad;

  // Font scale
  const fs = Math.max(0.7, Math.min(1, w / 1000));
  const fAxis = Math.round(13 * fs);
  const fX = Math.round(11 * fs);
  const fPct = fAxis;

  const xScale = (i) => {
    const n = Math.max(1, aligned.length - 1);
    return leftPad + (i / n) * innerW;
  };
  const yScalePrice = (v) => topPad + innerH - ((v - y0) / (y1 - y0)) * innerH;

  // Price axis from main ticker only
  const mainPrices = aligned.map(p => p.mainClose).filter(v => typeof v === 'number');
  const minMain = mainPrices.length ? Math.min(...mainPrices) : 0;
  const maxMain = mainPrices.length ? Math.max(...mainPrices) : 1;
  const padMain = (maxMain - minMain) * 0.1 || 1;
  const y0 = Math.max(0, minMain - padMain);
  const y1 = maxMain + padMain;

  // Percent domain: collect all visible benchmark % values
  const allPctVals = [];
  for (const bench of allBenchmarks) {
    if (visibleBenches[bench.key]) {
      allPctVals.push(...aligned.map(p => p[`${bench.key}Pct`]).filter(v => typeof v === 'number'));
    }
  }
  const maxPos = allPctVals.length ? Math.max(0, ...allPctVals) : 1;
  const maxNegAbs = allPctVals.length ? Math.max(0, ...allPctVals.map(v => Math.abs(Math.min(0, v)))) : 1;

  // Align benchmark % baseline to main first-day price pixel
  const mainFirst = aligned[0]?.mainClose;
  const yBase = typeof mainFirst === 'number' ? yScalePrice(mainFirst) : (topPad + innerH / 2);
  const spaceUp = yBase - topPad;
  const spaceDown = (topPad + innerH) - yBase;
  const kUp = maxPos > 0 ? spaceUp / maxPos : Infinity;
  const kDown = maxNegAbs > 0 ? spaceDown / maxNegAbs : Infinity;
  // Use full available space (no fixed px/percent clamp)
  const k = Math.max(0, Math.min(kUp, kDown));

  const yBench = (pct) => yBase - (Number(pct) || 0) * k;

  // Left Y ticks (price)
  const priceTicks = 4;
  const priceStep = (y1 - y0) / priceTicks;
  const yTicksPrice = Array.from({ length: priceTicks + 1 }).map((_, i) => y0 + priceStep * i);

  // Right Y ticks (percent)
  const spanPct = Math.max(maxPos, maxNegAbs) || 1;
  const pctMax = Math.ceil(spanPct / 5) * 5;
  const pctTicks = [-pctMax, -pctMax / 2, 0, pctMax / 2, pctMax];
  const yTicksPct = pctTicks.map(v => ({ v, y: yBench(v) }));

  // Paths
  const mainPoints = aligned.map(p => ({ x: xScale(p.i), y: yScalePrice(p.mainClose) }));
  const mainPath = buildSmoothPathXY(mainPoints);
  const mainArea = mainPath
    ? `${mainPath} L ${xScale(aligned.length - 1)} ${h - bottomPad} L ${xScale(0)} ${h - bottomPad} Z`
    : '';

  // Build path for each visible benchmark
  const benchPaths = allBenchmarks.map(bench => {
    if (!visibleBenches[bench.key]) return null;
    const pts = aligned
      .filter(p => typeof p[`${bench.key}Pct`] === 'number')
      .map(p => ({ x: xScale(p.i), y: yBench(p[`${bench.key}Pct`]) }));
    return { key: bench.key, label: bench.label, color: BENCH_COLORS[bench.key] || '#3b82f6', path: buildSmoothPathXY(pts) };
  }).filter(Boolean);

  // X-axis labels - responsive count
  const xTickCount = innerW < 420 ? 3 : innerW < 900 ? 5 : 7;
  const xTickIdxs = Array.from({ length: xTickCount }).map((_, i) => {
    const step = Math.max(0, aligned.length - 1) / (xTickCount + 1);
    return Math.round(step * (i + 1));
  });
  const xTicks = xTickIdxs.map(i => ({ i, t: aligned[i]?.t, x: xScale(i) }));

  const formatWordDate = useCallback((isoLike) => {
    if (!isoLike) return '';
    const d = new Date(isoLike);
    if (isNaN(d.getTime())) return String(isoLike);
    // Subtract 4 hours (convert UTC to local time)
    d.setTime(d.getTime() - (4 * 60 * 60 * 1000));
    const day = d.getDate();
    const suffix = (n) => {
      const v = n % 100;
      if (v >= 11 && v <= 13) return 'th';
      switch (n % 10) {
        case 1: return 'st';
        case 2: return 'nd';
        case 3: return 'rd';
        default: return 'th';
      }
    };
    const month = d.toLocaleString('en-US', { month: 'short' });
    const year = d.getFullYear();
    return `${month} ${day}${suffix(day)}, ${year}`;
  }, []);

  const formatAxisDate = useCallback((isoLike) => {
    if (!isoLike) return '';
    const d = new Date(isoLike);
    if (isNaN(d.getTime())) return String(isoLike);
    // Subtract 4 hours (convert UTC to local time)
    d.setTime(d.getTime() - (4 * 60 * 60 * 1000));
    const month = d.toLocaleString('en-US', { month: 'short' });
    const day = d.getDate();
    const year = d.getFullYear();
    return `${month} ${day}, ${year}`;
  }, []);

  const formatTooltipLabel = useCallback((isoLike, timeframe) => {
    if (!isoLike) return '';
    const d = new Date(isoLike);
    if (isNaN(d.getTime())) return String(isoLike);
    // Subtract 4 hours (convert UTC to local time)
    d.setTime(d.getTime() - (4 * 60 * 60 * 1000));

    // For 1D timeframe, show time only
    if (timeframe === '1D') {
      const hours = d.getHours();
      const minutes = d.getMinutes();
      const ampm = hours >= 12 ? 'PM' : 'AM';
      const displayHours = hours % 12 || 12;
      const displayMinutes = minutes.toString().padStart(2, '0');
      return `${displayHours}:${displayMinutes} ${ampm}`;
    }

    // For 5D timeframe, show date AND time
    if (timeframe === '5D') {
      const day = d.getDate();
      const suffix = (n) => {
        const v = n % 100;
        if (v >= 11 && v <= 13) return 'th';
        switch (n % 10) {
          case 1: return 'st';
          case 2: return 'nd';
          case 3: return 'rd';
          default: return 'th';
        }
      };
      const month = d.toLocaleString('en-US', { month: 'short' });
      const year = d.getFullYear();
      const hours = d.getHours();
      const minutes = d.getMinutes();
      const ampm = hours >= 12 ? 'PM' : 'AM';
      const displayHours = hours % 12 || 12;
      const displayMinutes = minutes.toString().padStart(2, '0');
      return `${month} ${day}${suffix(day)}, ${year} ${displayHours}:${displayMinutes} ${ampm}`;
    }

    // For other timeframes, show full date
    const day = d.getDate();
    const suffix = (n) => {
      const v = n % 100;
      if (v >= 11 && v <= 13) return 'th';
      switch (n % 10) {
        case 1: return 'st';
        case 2: return 'nd';
        case 3: return 'rd';
        default: return 'th';
      }
    };
    const month = d.toLocaleString('en-US', { month: 'short' });
    const year = d.getFullYear();
    return `${month} ${day}${suffix(day)}, ${year}`;
  }, []);

  // Hover
  const [hover, setHover] = useState(null);

  const onMove = (e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const xPx = e.clientX - rect.left;
    const xSvg = (xPx / rect.width) * w;
    const rel = Math.max(0, Math.min(1, (xSvg - leftPad) / innerW));
    const n = Math.max(1, aligned.length - 1);
    const idx = Math.round(rel * n);
    const pt = aligned[idx];
    setHover(pt || null);
  };
  const onLeave = () => setHover(null);

  const lastIdx = aligned.length - 1;
  const lastX = lastIdx >= 0 ? xScale(aligned[lastIdx]?.i) : 0;
  const lastY = lastIdx >= 0 ? yScalePrice(aligned[lastIdx]?.mainClose) : 0;

  const firstClose = baseSeries.find(p => typeof p?.c === 'number')?.c ?? null;
  const lastClose = [...baseSeries].reverse().find(p => typeof p?.c === 'number')?.c ?? null;

  const tfPriceNum = lastClose ?? Number(price);

  // For 1D timeframe, calculate change from prevClose; for others, from first data point in series
  let tfChangeNum, tfChangePctNum;
  if (tf === '1D' && typeof prevClose === 'number' && typeof lastClose === 'number' && prevClose !== 0) {
    // 1D: use yesterday's close as baseline
    tfChangeNum = lastClose - prevClose;
    tfChangePctNum = ((lastClose / prevClose) - 1) * 100;
  } else if (firstClose != null && lastClose != null && firstClose !== 0) {
    // Other timeframes: use first point in series as baseline
    tfChangeNum = lastClose - firstClose;
    tfChangePctNum = ((lastClose / firstClose) - 1) * 100;
  } else {
    // Fallback to props
    tfChangeNum = Number(change);
    tfChangePctNum = Number(changePct);
  }

  const topSummaryPrice = Number.isFinite(tfPriceNum)
    ? tfPriceNum.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : '-';
  const topSummaryChg = Number.isFinite(tfChangeNum)
    ? tfChangeNum.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : '-';
  const topSummaryPct = Number.isFinite(tfChangePctNum)
    ? tfChangePctNum.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : '-';
  const neg = Number(tfChangeNum) < 0;

  const toggleBench = (key) => {
    setVisibleBenches(prev => ({ ...prev, [key]: !prev[key] }));
  };

  const handleSelectTf = (key) => {
    setTf(key);
  };

  // Show loading state
  if (isLoading) {
    return (
      <div className="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">
        <div className="px-6 pt-6 flex items-center justify-center h-96">
          <div className="text-center">
            <div className="inline-block w-8 h-8 border-4 border-gray-200 border-t-green-600 rounded-full animate-spin mb-3" />
            <p className="text-sm text-gray-600">Loading chart data...</p>
          </div>
        </div>
      </div>
    );
  }

  // Show error state
  if (error) {
    return (
      <div className="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">
        <div className="px-6 pt-6 flex items-center justify-center h-96">
          <div className="text-center">
            <p className="text-sm text-red-600">Failed to load chart: {error.message}</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 shadow-sm overflow-hidden">
      {/* NEW LAYOUT: Logo/Name on left, Price/Change on right */}
      <div className="px-6 pt-6 flex items-start justify-between">
        {/* Left: Logo + Ticker Name */}
        <div className="flex items-center gap-3">
          {logo ? (
            <div className="w-10 h-10 md:w-12 md:h-12 rounded bg-black flex items-center justify-center flex-shrink-0">
              <img
                src={logo}
                alt={`${ticker} logo`}
                className="w-8 h-8 md:w-10 md:h-10 rounded"
                onError={(e) => { e.currentTarget.style.display = 'none'; }}
              />
            </div>
          ) : (
            <div className="w-10 h-10 md:w-12 md:h-12 rounded bg-gray-200 flex items-center justify-center text-gray-600 font-bold text-base md:text-lg flex-shrink-0">
              {ticker?.slice(0, 1) || 'S'}
            </div>
          )}
          <div>
            <div className="text-lg md:text-2xl font-bold text-gray-900">{ticker}</div>
            <div className="text-[10px] md:text-xs text-gray-500 mt-0.5">Market Index</div>
          </div>
        </div>

        {/* Right: Price + Change */}
        <div className="text-right">
          <div className="text-2xl md:text-4xl font-bold text-gray-900">${topSummaryPrice}</div>
          <div className={`mt-1 text-[11px] md:text-sm font-semibold ${neg ? 'text-red-600' : 'text-green-600'}`}>
            {(neg ? '' : '+') + topSummaryChg} ({(neg ? '' : '+') + topSummaryPct}%)
          </div>
        </div>
      </div>

      {/* Timeframe buttons below name */}
      <div className="px-6 pt-4 pb-2">
        <div className="flex items-center gap-2 overflow-x-auto scrollbar:hidden">
          {TF_ORDER.map(k => {
            const isActive = tf === k;
            const isHeavy = HEAVY_TFS.has(k);
            
            return (
              <button
                key={k}
                type="button"
                onClick={() => handleSelectTf(k)}
                disabled={isLoading}
                className={`px-2 md:px-3 py-1.5 text-[10px] md:text-xs rounded-md border ${
                  isActive
                    ? 'bg-gray-900 text-white border-gray-900 cursor-pointer'
                    : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50 cursor-pointer disabled:opacity-50'
                }`}
                aria-pressed={isActive}
              >
                {k}
              </button>
            );
          })}
        </div>
      </div>

      <div className="px-2 py-3" ref={containerRef}>
        <svg
          viewBox={`0 0 ${w} ${h}`}
          className="w-full"
          style={{ height: h }}
          onMouseMove={onMove}
          onMouseLeave={onLeave}
        >
          {/* Left (price) grid + labels */}
          {yTicksPrice.map((t, i) => {
            const y = yScalePrice(t);
            return (
              <g key={`p-${i}`}>
                <line x1={leftPad} y1={y} x2={w - rightPad} y2={y} stroke="#e5e7eb" strokeDasharray="4 4" />
                <text x={16} y={y + 4} fontSize={fAxis} fill="#6b7280">{currencyUSD(t, 0)}</text>
              </g>
            );
          })}

          {/* Right (percent) labels */}
          {benchPaths.length > 0 ? yTicksPct.map(({ v, y }, i) => (
            <text key={`pct-${i}`} x={w - rightPad + 8} y={y + 4} fontSize={fPct} fill="#6b7280">{percentStr(v)}</text>
          )) : null}

          {/* X-axis labels */}
          {xTicks.map((xt, i) => (
            <g key={`x-${i}`}>
              <line x1={xt.x} y1={h - bottomPad} x2={xt.x} y2={h - bottomPad + 6} stroke="#9ca3af" />
              <text x={xt.x} y={h - bottomPad + 18} fontSize={fX} fill="#6b7280" textAnchor="middle">
                {formatAxisDate(xt.t)}
              </text>
            </g>
          ))}

          {/* Main area + line */}
          <defs>
            <linearGradient id="gradBase" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor="#10b981" stopOpacity="0.15" />
              <stop offset="100%" stopColor="#10b981" stopOpacity="0.02" />
            </linearGradient>
          </defs>
          <path d={mainArea} fill="url(#gradBase)" />
          <path d={mainPath} fill="none" stroke="#10b981" strokeWidth="3" strokeLinejoin="round" strokeLinecap="round" />

          {/* Benchmark lines */}
          {benchPaths.map(bp => (
            <path key={bp.key} d={bp.path} fill="none" stroke={bp.color} strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" />
          ))}

          {/* Last main point marker */}
          {lastIdx >= 0 ? (
            <circle cx={lastX} cy={lastY} r="6" fill="#fff" stroke="#10b981" strokeWidth="3" />
          ) : null}

          {/* Hover tooltip */}
          {hover ? (
            <>
              <line x1={xScale(hover.i)} y1={topPad} x2={xScale(hover.i)} y2={h - bottomPad} stroke="#d1d5db" strokeWidth="2" strokeDasharray="6 4" />

              {/* Tooltip box - smart positioning to avoid covering cursor */}
              {(() => {
                const tooltipWidth = isMobile 
                  ? Math.min(280, Math.max(200, Math.floor(innerW * 0.55)))
                  : Math.min(240, Math.max(180, Math.floor(innerW * 0.25)));
                const cursorX = xScale(hover.i);
                const chartMidpoint = leftPad + innerW / 2;

                // If cursor is on right half, show tooltip on left side of cursor
                const tooltipX = cursorX > chartMidpoint
                  ? Math.max(leftPad + 8, cursorX - tooltipWidth - 16)
                  : Math.min(w - rightPad - tooltipWidth, cursorX + 16);

                const baseHeight = isMobile ? 140 : 120;
                const rowHeight = isMobile ? 28 : 22;
                const extra = Math.min(isMobile ? 100 : 70, benchPaths.length * rowHeight);
                const tooltipHeight = baseHeight + extra;

                return (
                  <g transform={`translate(${tooltipX}, ${topPad + 14})`}>
                    {/* Use foreignObject to embed HTML for flexbox support */}
                    <foreignObject width={tooltipWidth} height={tooltipHeight} x="0" y="0">
                      <div
                        xmlns="http://www.w3.org/1999/xhtml"
                        className="w-full h-full flex flex-col items-center justify-start bg-white rounded-xl md:rounded-lg border-[1.5px] border-gray-200 p-3 md:p-2.5 shadow-lg gap-1.5 md:gap-1"
                      >
                        {/* Main ticker price */}
                        <div className="text-[22px] md:text-[20px] pt-1 md:pt-0.5 font-bold text-gray-900 leading-none">
                          {currencyUSD(hover.mainClose, 2)}
                        </div>

                        {/* Main ticker percentage */}
                        {hover.mainCumPct != null && (
                          <div
                            className={`text-[18px] md:text-[16px] font-bold leading-none ${hover.mainCumPct >= 0 ? 'text-green-500' : 'text-red-500'
                              }`}
                          >
                            {hover.mainCumPct >= 0 ? '+' : ''}{percentStr(hover.mainCumPct, 2)}
                          </div>
                        )}

                        {/* Date/Time label */}
                        <div className="text-[13px] md:text-[11px] font-semibold text-gray-500 mb-1 md:mb-0">
                          {formatTooltipLabel(hover.t, tf)}
                        </div>

                        {/* Benchmark percentages - scroll if too many */}
                        <div className="w-full max-h-32 overflow-y-auto md:max-h-28">
                          {benchPaths.map((bp) => {
                            const pct = hover[`${bp.key}Pct`];
                            const isPositive = pct != null && pct >= 0;
                            return (
                              <div
                                key={bp.key}
                                className="w-full flex justify-between items-center py-0.5"
                              >
                                <span
                                  className="text-[13px] md:text-[11px] font-semibold"
                                  style={{ color: bp.color }}
                                >
                                  {bp.label}
                                </span>
                                <span
                                  className={`text-[13px] md:text-[11px] font-bold ${pct != null
                                    ? (isPositive ? 'text-green-500' : 'text-red-500')
                                    : 'text-gray-400'
                                    }`}
                                >
                                  {pct != null ? `${isPositive ? '+' : ''}${percentStr(pct, 2)}` : '-'}
                                </span>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    </foreignObject>
                  </g>
                );
              })()}
                          </>
          ) : null}
          {/* Add drop shadow filter definition */}
          <defs>
            <filter id="tooltipShadow" x="-20%" y="-20%" width="140%" height="140%">
              <feGaussianBlur in="SourceAlpha" stdDeviation="4" />
              <feOffset dx="0" dy="3" result="offsetblur" />
              <feComponentTransfer>
                <feFuncA type="linear" slope="0.12" />
              </feComponentTransfer>
              <feMerge>
                <feMergeNode />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>
        </svg>
      </div>

      {/* Benchmark toggles at bottom - wrap chips but don't break text */}
      <div className="px-6 pb-6">
        <div className="flex flex-wrap items-center gap-3">
          <span className="inline-flex items-center gap-2 text-xs font-medium text-gray-900 rounded-full px-2 py-1 border border-green-500 bg-green-50 shadow-sm whitespace-nowrap">
            <span className="w-2.5 h-2.5 rounded-full bg-emerald-500" />
            {ticker}
          </span>
          {allBenchmarks.map(bench => (
            <button
              key={bench.key}
              type="button"
              onClick={() => toggleBench(bench.key)}
              className={`inline-flex items-center gap-2 text-xs rounded-full px-2 py-1 border transition-colors cursor-pointer whitespace-nowrap ${visibleBenches[bench.key]
                ? 'bg-green-50 text-black border-green-500 font-semibold shadow-sm'
                : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50'
                }`}
              aria-pressed={visibleBenches[bench.key]}
            >
              <span
                className={`w-3 h-3 rounded-full ${visibleBenches[bench.key] ? 'opacity-100' : 'opacity-40'}`}
                style={{ backgroundColor: BENCH_COLORS[bench.key] || '#3b82f6' }}
              />
              {BENCH_LABELS[bench.key] || bench.label}
            </button>
          ))}
        </div>
      </div>
          </div>
  );
}