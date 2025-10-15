import React from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import Loading from '../components/Loading';
import { Building, ChartLine } from 'lucide-react';
import ComparisonChart from '../components/ComparisonChart';

function Ticker({ user }) {
  const { ticker } = useParams();
  const VITE_APP_API_URL = import.meta.env.VITE_APP_API_URL;
  const sym = (ticker || '').toUpperCase();

  // Define which benchmarks to compare - you can change these dynamically or based on stock characteristics
  const [benchmarks, setBenchmarks] = React.useState([
    { symbol: 'SPY', key: 'sp500', label: 'S&P 500' },
    { symbol: 'QQQ', key: 'nasdaq', label: 'NASDAQ 100' }
  ]);

  // Build benchmarks query param from array
  const benchmarksParam = benchmarks
    .map(b => `${b.symbol}:${b.key}:${b.label}`)
    .join(',');

  const { data, isLoading, isError } = useQuery({
    queryKey: ['ticker-details', sym, user?.token, benchmarksParam],
    enabled: !!user?.token && !!sym,
    staleTime: 60_000,
    queryFn: async () => {
      const url = new URL(`${VITE_APP_API_URL}/api/ticker/${encodeURIComponent(sym)}`);
      if (benchmarksParam) {
        url.searchParams.set('benchmarks', benchmarksParam);
      }
      const res = await fetch(url, {
        headers: { Authorization: `Bearer ${user.token}` },
      });
      if (!res.ok) throw new Error('Failed to load ticker');
      return res.json();
    },
  });

  // Unconditional: hooks must be before any early returns
  const [aboutExpanded, setAboutExpanded] = React.useState(false);

  const fmt = (n, d = 2) => {
    const v = Number(n);
    if (!isFinite(v)) return '-';
    return v.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
  };
  const fmtCurrency = (n) => {
    const v = Number(n);
    if (!isFinite(v)) return '-';
    return v.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 });
  };
  const fmtCompact = (n) => {
    const v = Number(n);
    if (!isFinite(v)) return '-';
    return v.toLocaleString('en-US', { notation: 'compact', maximumFractionDigits: 2 });
  };

  const RangeBar = ({ low, high, value }) => {
    const l = Number(low);
    const h = Number(high);
    const v = Number(value);
    const pct = isFinite(l) && isFinite(h) && h > l && isFinite(v) ? Math.max(0, Math.min(100, ((v - l) * 100) / (h - l))) : 0;
    return (
      <div className="w-full">
        <div className="relative h-2 rounded-full bg-orange-200 overflow-hidden">
          <div className="absolute inset-0 bg-gradient-to-r from-orange-400 to-orange-500" />
          <div className="absolute top-1/2 -mt-1 w-2 h-2 rounded-full bg-white border border-orange-500 shadow" style={{ left: `calc(${pct}% - 4px)` }} />
        </div>
      </div>
    );
  };

  if (isLoading) {
    return <Loading message={`Loading ${sym}...`} fullScreen={false} />;
  }

  if (isError || !data) {
    return (
      <div className="w-full h-full flex items-center justify-center bg-gray-50">
        <p className="text-xl text-red-400">Failed to load {sym}</p>
      </div>
    );
  }

  const chg = Number(data.change ?? 0);
  const chgPct = Number(data.changePercent ?? 0);
  const negative = chg < 0;

  const aboutText = data.company?.description || '—';
  const ABOUT_LIMIT = 220;
  const isLong = aboutText.length > ABOUT_LIMIT;
  const visibleAbout = aboutExpanded || !isLong ? aboutText : aboutText.slice(0, ABOUT_LIMIT).trimEnd() + '…';

  return (
    <div className="w-full h-full overflow-auto bg-[#fafafa]">
      <div className="px-6 py-6 max-w-5xl mx-auto">
        {/* Back + breadcrumb */}
        <nav className="mb-4 text-xs text-gray-500" aria-label="Breadcrumb">
          <ol className="flex items-center gap-1">
            <li>
              <Link to="/dashboard" className="hover:text-gray-700">Market</Link>
            </li>
            <li className="text-gray-400">/</li>
            <li className="text-gray-700 font-medium">{sym}</li>
          </ol>
        </nav>

        {/* Chart comparison (now includes header with logo/name/price); chart fetches its own timeframes */}
        <ComparisonChart
          ticker={sym}
          symbol={sym}
          token={user.token}
          benchmarks={benchmarks}
          logo={data.company?.logo}
          price={data.lastPrice}
          prevClose={data.prevClose}
          change={chg}
          changePct={chgPct}
        />

        {/* Two cards */}
        <div className="mt-6 grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Company Info */}
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm">
            <div className="px-5 py-4 border-b border-gray-100 flex items-center gap-2">
              <Building className="w-4 h-4 text-gray-500" />
              <h2 className="text-[15px] font-semibold text-gray-900">Company Info</h2>
            </div>

            <div className="px-5 py-4 grid grid-cols-1 sm:grid-cols-2 gap-x-10 gap-y-4 text-sm">
              <div>
                <div className="text-gray-500 text-xs mb-1">Market Cap</div>
                <div className="font-semibold text-gray-900">${data.company.marketCap ? fmtCompact(data.company.marketCap) : '-'}</div>
              </div>
              <div>
                <div className="text-gray-500 text-xs mb-1">Primary Exchange</div>
                <div className="font-semibold text-gray-900">{data.company.exchange || '-'}</div>
              </div>
              <div>
                <div className="text-gray-500 text-xs mb-1">Country</div>
                <div className="font-semibold text-gray-900">{data.company?.country?.toUpperCase() || '-'}</div>
              </div>
              <div>
                <div className="text-gray-500 text-xs mb-1">Website</div>
                <div className="font-semibold text-orange-700">
                  {data.company?.website ? (
                    <a className="hover:underline" href={data.company.website} target="_blank" rel="noreferrer">
                      {data.company.website}
                    </a>
                  ) : '-'}
                </div>
              </div>
              <div>
                <div className="text-gray-500 text-xs mb-1">IPO Date</div>
                <div className="font-semibold text-gray-900">{data.company?.ipoDate || '-'}</div>
              </div>
            </div>

            <div className="px-5">
              <div className="h-px bg-gray-100" />
            </div>

            <div className="px-5 py-4">
              <div className="text-gray-900 text-sm font-semibold mb-1">About</div>
              <p className="text-sm text-gray-700 leading-relaxed">
                {visibleAbout}
              </p>
              {isLong && (
                <button
                  type="button"
                  className="mt-2 text-xs font-medium text-orange-700 hover:underline cursor-pointer"
                  onClick={() => setAboutExpanded((v) => !v)}
                  aria-expanded={aboutExpanded}
                >
                  {aboutExpanded ? 'Show less' : 'Show more'}
                </button>
              )}
            </div>
          </div>

          {/* Price */}
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm">
            <div className="px-5 py-4 border-b border-gray-100 flex items-center gap-2">
              <ChartLine className="w-4 h-4 text-gray-500" />
              <h2 className="text-[15px] font-semibold text-gray-900">Price</h2>
            </div>

            <div className="px-5 py-4 grid grid-cols-2 gap-6 text-sm">
              <div>
                <div className="text-gray-500 text-xs mb-1">Price</div>
                <div className="font-semibold text-gray-900">{fmt(data.lastPrice)}</div>
              </div>
              <div>
                <div className="text-gray-500 text-xs mb-1">Change</div>
                <div className={`font-semibold ${negative ? 'text-red-600' : 'text-green-600'}`}>{`${negative ? '' : '+'}${fmt(chg)}`}</div>
              </div>
              <div>
                <div className="text-gray-500 text-xs mb-1">Change %</div>
                <div className={`font-semibold ${negative ? 'text-red-600' : 'text-green-600'}`}>{`${negative ? '' : '+'}${fmt(chgPct)}%`}</div>
              </div>
              <div>
                <div className="text-gray-500 text-xs mb-1">Volume</div>
                <div className="font-semibold text-gray-900">{fmtCompact(data.day?.volume)}</div>
              </div>
            </div>

            <div className="px-5 pb-4 space-y-5 text-sm">
              {/* Day Range */}
              <div>
                <div className="text-gray-700 text-sm mb-2">Day Range</div>
                <RangeBar low={data.day?.low} high={data.day?.high} value={data.lastPrice} />
                <div className="mt-1 flex justify-between text-[11px] text-gray-600">
                  <span>{fmt(data.day?.low)}</span>
                  <span>{fmt(data.day?.high)}</span>
                </div>
              </div>

              {/* 52-Week Range */}
              <div>
                <div className="text-gray-700 text-sm mb-2">52-Week Range</div>
                <RangeBar low={data.ranges?.fiftyTwoWeek?.low} high={data.ranges?.fiftyTwoWeek?.high} value={data.lastPrice} />
                <div className="mt-1 flex justify-between text-[11px] text-gray-600">
                  <span>{fmt(data.ranges?.fiftyTwoWeek?.low)}</span>
                  <span>{fmt(data.ranges?.fiftyTwoWeek?.high)}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default Ticker;