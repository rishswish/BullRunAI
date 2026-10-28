import React, { useState, useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
// Update the import statement at the top (line 3)
import { Wallet, TrendingUp, BarChart2, PieChart as PieIcon, RefreshCw, Trophy, Building2, Plus, Eye, EyeOff, X, Landmark } from 'lucide-react';
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, PieChart, Pie, Cell } from 'recharts';
import Loading from '../components/Loading';
import ManualHoldingsModal from '../components/ManualHoldingsModal';
import { useNavigate } from 'react-router-dom';

// Demo dataset (brokers, balances, holdings, transactions)
const KNOWN_BROKER_MAP = {
  ROBINHOOD: ['Robinhood'],
  SCHWAB: ['Charles Schwab', 'Schwab'],
  TD: ['TD Ameritrade', 'TD'],
  'INTERACTIVE-BROKERS-FLEX': ['Interactive Brokers', 'IBKR', 'IBKR FLEX'],
  VANGUARD: ['Vanguard'],
  COINBASE: ['Coinbase'],
};

const DEMO_ACCOUNTS = [
  { id: 'demo-1', institution: 'Robinhood', name: 'Taxable' },
  { id: 'demo-2', institution: 'Charles Schwab', name: 'Roth IRA' },
  { id: 'demo-3', institution: 'Vanguard', name: '401(k)' },
  { id: 'demo-4', institution: 'Fidelity', name: 'HSA' },
  { id: 'demo-5', institution: 'TD Ameritrade', name: 'Joint' },
];

const DEMO_BALANCES = [
  { accountId: 'demo-1', amount: 24500 },
  { accountId: 'demo-2', amount: 58500 },
  { accountId: 'demo-3', amount: 112000 },
  { accountId: 'demo-4', amount: 8700 },
  { accountId: 'demo-5', amount: 33400 },
];

const DEMO_HOLDINGS = [
  { accountId: 'demo-1', symbol: 'AAPL', name: 'Apple Inc.', weight: 18.2, marketValue: 52340 },
  { accountId: 'demo-2', symbol: 'MSFT', name: 'Microsoft', weight: 15.0, marketValue: 43100 },
  { accountId: 'demo-3', symbol: 'NVDA', name: 'NVIDIA', weight: 14.0, marketValue: 40200 },
  { accountId: 'demo-5', symbol: 'AMZN', name: 'Amazon.com', weight: 9.5, marketValue: 27300 },
  { accountId: 'demo-2', symbol: 'GOOGL', name: 'Alphabet Class A', weight: 8.3, marketValue: 23800 },
  { accountId: 'demo-4', symbol: 'BRK.B', name: 'Berkshire Hathaway B', weight: 7.6, marketValue: 21800 },
  { accountId: 'demo-3', symbol: 'VTI', name: 'Vanguard Total Stock Market ETF', weight: 14.8, marketValue: 42600 },
  { accountId: 'demo-1', symbol: 'VXUS', name: 'Vanguard Total International Stock ETF', weight: 12.6, marketValue: 36200 },
];

const DEMO_TRANSACTIONS = [
  { id: 't1', date: '2025-09-25', accountId: 'demo-1', symbol: 'AAPL', action: 'BUY', quantity: 10, price: 210.25 },
  { id: 't2', date: '2025-09-23', accountId: 'demo-2', symbol: 'MSFT', action: 'BUY', quantity: 6, price: 415.60 },
  { id: 't3', date: '2025-09-20', accountId: 'demo-3', symbol: 'VTI', action: 'BUY', quantity: 15, price: 265.40 },
  { id: 't4', date: '2025-09-18', accountId: 'demo-5', symbol: 'NVDA', action: 'SELL', quantity: 3, price: 121.30 },
  { id: 't5', date: '2025-09-16', accountId: 'demo-4', symbol: 'AMZN', action: 'BUY', quantity: 2, price: 181.55 },
  { id: 't6', date: '2025-09-15', accountId: 'demo-3', symbol: 'VXUS', action: 'BUY', quantity: 20, price: 62.85 },
];

function Portfolio({ isChatbotOpen, setIsChatbotOpen, user }) {
  const VITE_APP_API_URL = import.meta.env.VITE_APP_API_URL;
  const { data: portfolio, isLoading: loading, refetch } = useQuery({
    queryKey: ['portfolio-summary', user?.token],
    enabled: !!user?.token,
    staleTime: Infinity,
    queryFn: async () => {
      const res = await fetch(`${VITE_APP_API_URL}/api/portfolio/summary`, {
        headers: { Authorization: `Bearer ${user.token}` },
      });
      if (!res.ok) throw new Error('Failed to load portfolio');
      return res.json();
    },
  });
  const [hasConnectedAccounts, setHasConnectedAccounts] = useState(false);
  const [connectOpen, setConnectOpen] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [selectedBroker, setSelectedBroker] = useState('');
  const [loginUrl, setLoginUrl] = useState('');

  const [awaitingCompletion, setAwaitingCompletion] = useState(false);
  const [connectNotice, setConnectNotice] = useState('');
  const [manualOpen, setManualOpen] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);

  // Demo mode (eye)
  const [demoMode, setDemoMode] = useState(false);
  const [demoPortfolio, setDemoPortfolio] = useState(null);

  // Router
  const navigate = useNavigate();
  const handleTickerClick = (sym) => {
    if (!sym) return;
    navigate(`/dashboard/${encodeURIComponent(String(sym).toUpperCase())}`);
  };

  // Account filter (multi-select)
  const [selectedAccountIds, setSelectedAccountIds] = useState([]);
  const [accountsOpen, setAccountsOpen] = useState(false);
  const accountsRef = useRef(null);

  // Orders (real, fetched from backend)
  const [orders, setOrders] = useState([]);
  const [ordersLoading, setOrdersLoading] = useState(false);

  const COLORS = ['#4f46e5', '#22c55e', '#f59e0b', '#ef4444', '#14b8a6', '#8b5cf6', '#3b82f6', '#06b6d4'];

  const formatCurrency = (n) => {
    const val = Number(n || 0);
    return val.toLocaleString('en-US', { style: 'currency', currency: 'USD' });
  };

  const openConnectModal = () => {
    setSelectedBroker('');
    setLoginUrl('');
    setAwaitingCompletion(false);
    setConnectNotice('');
    setConnectOpen(true);
  };

  const requestConnectUrl = async (brokerSlug) => {
    if (demoMode) {
      return;
    }
    try {
      // Frontend guard: prevent duplicate connects if already connected
      const connectedBrokerSlugs = new Set(
        (allAccounts || []).map(a => {
          const inst = (a.institution || '').toUpperCase();
          for (const [slug, names] of Object.entries(KNOWN_BROKER_MAP)) {
            if (names.some(n => inst.includes(n.toUpperCase()))) return slug;
          }
          return null;
        }).filter(Boolean)
      );
      if (brokerSlug && connectedBrokerSlugs.has(brokerSlug.toUpperCase())) {
        setSelectedBroker(brokerSlug);
        setLoginUrl('');
        setAwaitingCompletion(false);
        // Soft-block: simply do not call backend, show inline message via disabled button label
        return;
      }

      setIsGenerating(true);
      setSelectedBroker(brokerSlug);
      const qs = brokerSlug ? `?broker=${encodeURIComponent(brokerSlug)}` : '';
      const res = await fetch(`${VITE_APP_API_URL}/api/snaptrade/connect_url${qs}`, {
        headers: { Authorization: `Bearer ${user.token}` },
      });
      const data = await res.json();
      if (!res.ok && data?.error === 'not_configured') {
        setConnectNotice(data.message || 'Brokerage linking is not configured on this deployment.');
        return;
      }
      const url = typeof data?.url === 'string' ? data.url : (data?.url?.redirectURI || data?.url?.redirectUri || '');
      setLoginUrl(url || '');
      if (url && url.startsWith('http')) {
        // Do not auto-open; show user an explicit Open Link button to avoid premature blank tabs
        setAwaitingCompletion(true);
      }
    } catch (e) {
      console.error('Failed to generate connect URL', e);
      setLoginUrl('');
    } finally {
      setIsGenerating(false);
    }
  };

  // Build demo portfolio from predefined data
  const generateDemoPortfolio = () => {
    const total = DEMO_BALANCES.reduce((s, b) => s + Number(b.amount || 0), 0);
    const invest = DEMO_HOLDINGS.reduce((s, h) => s + Number(h.marketValue || 0), 0);

    return {
      hasConnectedAccounts: true,
      totals: { totalBalance: total, totalInvestments: invest },
      accounts: DEMO_ACCOUNTS,
      balances: DEMO_BALANCES,
      topHoldings: DEMO_HOLDINGS,
      transactions: DEMO_TRANSACTIONS,
      positions: DEMO_HOLDINGS.length,
    };
  };

  const refreshPortfolio = async () => {
    try {
      setIsRefreshing(true);
      const { data } = await refetch();
      const refreshed = data;
      setHasConnectedAccounts(!!refreshed?.hasConnectedAccounts);
      if (Array.isArray(refreshed?.accounts) && refreshed.accounts.length > 0) {
        setSelectedAccountIds(refreshed.accounts.map(a => a.id));
      }
      if (Array.isArray(refreshed?.orders)) {
        setOrders(refreshed.orders);
      }
      setDemoMode(false);
      setDemoPortfolio(null);
    } catch (e) {
      console.error('Failed to refresh portfolio', e);
    } finally {
      setIsRefreshing(false);
      setConnectOpen(false);
      setAwaitingCompletion(false);
      setSelectedBroker('');
      setLoginUrl('');
    }
  };

  // Add this state variable after line 73
  const [showConnectModal, setShowConnectModal] = useState(false);

  // Add this useEffect after the existing useEffect (around line 210)
  useEffect(() => {
    // Check if we've already shown the connect modal to this user
    const hasSeenConnectModal = localStorage.getItem('hasSeenConnectModal');
    const connectModalData = hasSeenConnectModal ? JSON.parse(hasSeenConnectModal) : null;
    const isConnectModalExpired = connectModalData ?
      (Date.now() - connectModalData.timestamp) > (24 * 60 * 60 * 1000) : true; // 1 day in milliseconds

    // Show connect modal if:
    // 1. User has no connected accounts
    // 2. Not in demo mode
    // 3. Haven't shown the modal before
    // 4. Modal isn't already open
    if (portfolio &&
      !portfolio.hasConnectedAccounts &&
      !demoMode &&
      !hasSeenConnectModal &&
      !showConnectModal) {
      setShowConnectModal(true);
    }
  }, [portfolio, demoMode, showConnectModal]);

  // Add this function to handle connecting from the modal
  const handleConnectFromModal = () => {
    setShowConnectModal(false);
    // Mark that user has seen the modal
    localStorage.setItem('hasSeenConnectModal', JSON.stringify({
      seen: true,
      timestamp: Date.now()
    }));
    // Open the connect modal
    openConnectModal();
  };


  const handleConnectModalClose = () => {
    setShowConnectModal(false);
    // Mark that user has seen the modal
    localStorage.setItem('hasSeenConnectModal', 'true');
  };


  useEffect(() => {
    if (portfolio) {
      setHasConnectedAccounts(!!portfolio?.hasConnectedAccounts);
      if (Array.isArray(portfolio?.accounts) && portfolio.accounts.length > 0) {
        setSelectedAccountIds(portfolio.accounts.map(a => a.id));
      }
      if ((orders || []).length === 0 && Array.isArray(portfolio?.orders)) {
        setOrders(portfolio.orders);
      }
    }
  }, [portfolio]);

  // Close Accounts dropdown on outside click
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (!accountsOpen) return;
      if (accountsRef.current && !accountsRef.current.contains(e.target)) {
        setAccountsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [accountsOpen]);

  if (loading) {
    return <Loading message="Loading portfolio..." fullScreen={false} />;
  }

  // Use demo or real data
  const p = (demoMode && demoPortfolio) ? demoPortfolio : portfolio;

  const allAccounts = p?.accounts || [];
  const activeAccountIds = selectedAccountIds.length > 0 ? new Set(selectedAccountIds) : new Set(); // empty Set = show nothing
  const selectionEmpty = selectedAccountIds.length === 0;
  const accounts = selectionEmpty ? [] : allAccounts.filter(a => activeAccountIds.has(a.id));

  // Filtered views
  const balancesFiltered = selectionEmpty ? [] : (p?.balances || []).filter(b => activeAccountIds.has(b.accountId));
  const holdingsFiltered = selectionEmpty ? [] : (p?.topHoldings || []).filter(h => h?.accountId && activeAccountIds.has(h.accountId));
  const transactionsFiltered = selectionEmpty ? [] : (p?.transactions || []).filter(t => activeAccountIds.has(t.accountId));
  const ordersFiltered = selectionEmpty ? [] : (orders || []).filter(o => activeAccountIds.has(o.accountId));

  // Recompute totals for the filtered selection
  const totalBalance = balancesFiltered.reduce((s, b) => s + Number(b.amount || 0), 0);
  const totalInvestments = holdingsFiltered.reduce((s, h) => s + Number(h.marketValue || 0), 0);
  const topHoldings = holdingsFiltered;
  const netWorth = totalBalance + totalInvestments;

  // Build balances dataset grouped by institution (fallback to account name)
  const accountsById = Object.fromEntries((accounts || []).map(a => [a.id, a]));
  const balancesAgg = {};
  (balancesFiltered || []).forEach(b => {
    const acct = accountsById[b.accountId] || {};
    const label = acct.institution || acct.name || 'Account';
    const amt = Number(b.amount || 0);
    balancesAgg[label] = (balancesAgg[label] || 0) + amt;
  });
  const balancesData = Object.entries(balancesAgg).map(([name, value]) => ({ name, value }));

  const positionsCount = (topHoldings || []).length;

  return (
    <div className="w-full h-full overflow-auto bg-gray-50">
      <div className=" px-6 py-6 max-w-5xl mx-auto">
        {/* Top Action Buttons */}
        <div className="flex w-full items-center justify-start md:justify-end flex-row md:flex-row gap-3 mb-4">
          {/* <button className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors">
            <Plus className="w-3.5 h-3.5" />
            Manual Entry
          </button> */}
          <button
            onClick={openConnectModal}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-white bg-green-600 rounded-lg hover:bg-green-700 transition-colors cursor-pointer"
          >
            <Plus className="w-3.5 h-3.5" />
            Connect Account
          </button>
          {/* Accounts Filter */}
          <div className="relative" ref={accountsRef}>
            <button
              onClick={() => setAccountsOpen((v) => !v)}
              className="list-none flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors cursor-pointer"
            >
              Accounts
              <svg className={`w-3 h-3 text-gray-500 transition-transform ${accountsOpen ? 'rotate-180' : ''}`} viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.24 4.5a.75.75 0 01-1.08 0l-4.24-4.5a.75.75 0 01.02-1.06z" clipRule="evenodd" />
              </svg>
            </button>
            {accountsOpen && (
              <div className="absolute right-0 mt-2 w-60 bg-white rounded-md border border-gray-200 shadow-lg z-50 p-2 space-y-1">
                <div className="flex items-center justify-between px-1 py-1">
                  <span className="text-[11px] text-gray-500">Filter by accounts</span>
                  <button
                    onClick={() => setSelectedAccountIds([])}
                    className="text-[11px] text-green-600 hover:underline cursor-pointer"
                  >
                    Clear
                  </button>
                </div>
                <div className="max-h-60 overflow-auto pr-1">
                  {(allAccounts || []).map((a) => {
                    const checked = selectedAccountIds.includes(a.id);
                    return (
                      <label key={`filter-${a.id}`} className="flex items-center gap-2 px-2 py-1 rounded hover:bg-gray-50 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={(e) => {
                            setSelectedAccountIds((prev) => {
                              if (e.target.checked) return [...prev, a.id];
                              return prev.filter(id => id !== a.id);
                            });
                          }}
                          className="h-3.5 w-3.5"
                        />
                        <div className="flex-1">
                          <div className="text-[12px] text-gray-900 font-medium">{a.institution || 'Brokerage'}</div>
                          <div className="text-[10px] text-gray-500">{a.name || ''}</div>
                        </div>
                      </label>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
          <button
            onClick={() => setManualOpen(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-green-700 bg-white border border-green-600 rounded-lg hover:bg-green-50 transition-colors cursor-pointer"
          >
            Manage holdings
          </button>
        </div>

        <ManualHoldingsModal open={manualOpen} onClose={() => setManualOpen(false)} onSaved={refreshPortfolio} user={user} />
        {p?.source === 'manual' && (
          <p className="text-[11px] text-gray-500 mb-3 md:text-right">
            Self-reported holdings{p?.asOf ? ` · priced at ${p.asOf} close` : ''}
          </p>
        )}

        {connectOpen && (
          <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-[1000]">
            <div className="bg-white rounded-md shadow-xl border border-gray-200 w-full max-w-md mx-4">
              <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between">
                <h3 className="text-sm font-semibold text-gray-900">Connect a brokerage</h3>
                <button onClick={() => setConnectOpen(false)} className="text-gray-400 hover:text-gray-600 cursor-pointer">✕</button>
              </div>
              <div className="p-4">
                {demoMode ? (
                  <>
                    <p className="text-xs text-gray-700 mb-3">Connecting is disabled in demo mode. Exit demo to connect your accounts.</p>
                    <div className="space-y-2">
                      <button
                        onClick={() => { setDemoMode(false); setDemoPortfolio(null); setConnectOpen(false); if (Array.isArray(portfolio?.accounts)) { setSelectedAccountIds(portfolio.accounts.map(a => a.id)); } }}
                        className="w-full px-3 py-2 text-xs font-semibold text-white bg-green-600 rounded-md hover:bg-green-700 cursor-pointer"
                      >
                        Exit demo mode
                      </button>
                      <button
                        onClick={() => setConnectOpen(false)}
                        className="w-full px-3 py-2 text-xs border border-gray-200 rounded-md hover:bg-gray-50 cursor-pointer"
                      >
                        Close
                      </button>
                    </div>
                  </>
                ) : !awaitingCompletion ? (
                  <>
                    {connectNotice && (
                      <div className="mb-3 rounded-md border border-amber-200 bg-amber-50 p-3 text-[11px] text-amber-900">
                        <p className="font-semibold mb-1">SnapTrade linking is available, not enabled here</p>
                        <p className="mb-2">{connectNotice} You can enter your positions manually instead; prices and analysis work the same.</p>
                        <button onClick={() => { setConnectOpen(false); setManualOpen(true); }}
                          className="px-2 py-1 rounded bg-green-600 text-white font-semibold hover:bg-green-700 cursor-pointer">
                          Enter holdings manually
                        </button>
                      </div>
                    )}
                    <p className="text-xs text-gray-600 mb-3">Select your brokerage to open SnapTrade in a new tab.</p>
                    <div className="grid grid-cols-2 gap-2 mb-3">
                      {[
                        { name: 'Robinhood', slug: 'ROBINHOOD' },
                        { name: 'Schwab', slug: 'SCHWAB' },
                        { name: 'TD Ameritrade', slug: 'TD' },
                        { name: 'Interactive Brokers', slug: 'INTERACTIVE-BROKERS-FLEX' },
                        { name: 'Vanguard', slug: 'VANGUARD' },
                        { name: 'Coinbase', slug: 'COINBASE' },
                      ].map((b) => (
                        <button
                          key={b.slug}
                          disabled={isGenerating || (new Set((allAccounts || []).map(a => {
                            const inst = (a.institution || '').toUpperCase();
                            for (const [slug, names] of Object.entries(KNOWN_BROKER_MAP)) {
                              if (names.some(n => inst.includes(n.toUpperCase()))) return slug;
                            }
                            return null;
                          }).filter(Boolean))).has(b.slug)}
                          onClick={() => requestConnectUrl(b.slug)}
                          className="px-3 py-2 text-xs border border-gray-200 rounded-md hover:bg-gray-50 disabled:opacity-50 cursor-pointer"
                        >
                          {(new Set((allAccounts || []).map(a => {
                            const inst = (a.institution || '').toUpperCase();
                            for (const [slug, names] of Object.entries(KNOWN_BROKER_MAP)) {
                              if (names.some(n => inst.includes(n.toUpperCase()))) return slug;
                            }
                            return null;
                          }).filter(Boolean))).has(b.slug)
                            ? 'Connected'
                            : (isGenerating && selectedBroker === b.slug ? 'Opening…' : b.name)}
                        </button>
                      ))}
                    </div>
                    <button
                      disabled={isGenerating}
                      onClick={() => requestConnectUrl('')}
                      className="w-full px-3 py-2 text-xs border border-gray-200 rounded-md hover:bg-gray-50 disabled:opacity-50 cursor-pointer"
                    >
                      Other / No preference
                    </button>
                    {loginUrl && !loginUrl.startsWith('http') && (
                      <p className="text-[11px] text-red-500 mt-3">Failed to generate a connection link. Please try another brokerage.</p>
                    )}
                  </>
                ) : (
                  <>
                    <div className="flex items-center gap-2 mb-3">
                      <div className="w-6 h-6 rounded-full bg-green-50 flex items-center justify-center">
                        <span className="text-green-600 text-xs">✓</span>
                      </div>
                      <p className="text-xs text-gray-700">Open the link to complete your connection in a new tab.</p>
                    </div>
                    <div className="space-y-2">
                      <button
                        disabled={!loginUrl || !loginUrl.startsWith('http')}
                        onClick={() => {
                          window.location.href = loginUrl;
                        }}
                        className="w-full px-3 py-2 text-xs border border-gray-200 rounded-md hover:bg-gray-50 disabled:opacity-50 cursor-pointer"
                      >
                        Open Link
                      </button>
                      <button
                        disabled={isRefreshing}
                        onClick={refreshPortfolio}
                        className="w-full px-3 py-2 text-xs font-semibold text-white bg-green-600 rounded-md hover:bg-green-700 disabled:opacity-50 cursor-pointer"
                      >
                        {isRefreshing ? 'Refreshing…' : "I've completed the connection"}
                      </button>
                      <button
                        onClick={() => { setAwaitingCompletion(false); setLoginUrl(''); }}
                        className="w-full px-3 py-2 text-xs border border-gray-200 rounded-md hover:bg-gray-50 cursor-pointer"
                      >
                        Back
                      </button>
                    </div>
                  </>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Top Stats Cards with mini charts */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-3">
          {/* Net Worth */}
          <div className="bg-white rounded-md p-4 shadow-sm border border-gray-200">
            <div className="flex items-start justify-between">
              <div className="flex-1">
                <div className="flex items-center gap-1.5 mb-1">
                  <div className="p-1.5 bg-green-50 rounded">
                    <Wallet className="w-3.5 h-3.5 text-green-600" />
                  </div>
                  <h3 className="text-md font-semibold text-gray-900">Net Worth</h3>
                </div>
                <p className="text-xs text-gray-500 mb-2">Cash + Investments</p>

                <p className="text-2xl font-bold text-green-600">{formatCurrency(netWorth)}</p>
              </div>
            </div>
          </div>

          {/* Cash and Investments mini cards */}
          <div className="grid grid-cols-2 gap-3">
            {/* Cash */}
            <div className="bg-white rounded-md p-4 shadow-sm border border-gray-200">
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <div className="flex items-center gap-1.5 mb-1">
                    <div className="p-1.5 bg-green-50 rounded">
                      <BarChart2 className="w-3.5 h-3.5 text-green-600" />
                    </div>
                    <h3 className="text-md font-semibold text-gray-900">Cash</h3>
                  </div>
                  <p className="text-[9px] text-gray-500 mb-2">Across selected accounts</p>
                  <p className="text-xl font-bold text-green-600">{formatCurrency(totalBalance)}</p>
                </div>
              </div>
            </div>

            {/* Investments */}
            <div className="bg-white rounded-md p-4 shadow-sm border border-gray-200">
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <div className="flex items-center gap-1.5 mb-1">
                    <div className="p-1.5 bg-green-50 rounded">
                      <TrendingUp className="w-3.5 h-3.5 text-green-600" />
                    </div>
                    <h3 className="text-md font-semibold text-gray-900">Investments</h3>
                  </div>
                  <p className="text-[9px] text-gray-500 mb-2">Excluding cash positions</p>
                  <p className="text-xl font-bold text-green-600">{formatCurrency(totalInvestments)}</p>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Middle Cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-3">
          {/* Balances */}
          <div className="bg-white rounded-md p-4 shadow-sm border border-gray-200">
            <div className="flex items-center gap-1.5 mb-3">
              <div className="p-1.5 bg-green-50 rounded">
                <BarChart2 className="w-3.5 h-3.5 text-green-600" />
              </div>
              <div>
                <h3 className="text-md font-semibold text-gray-900">Cash Balances</h3>
                <p className="text-xs text-gray-500">Total positive cash balance: {formatCurrency(totalBalance)}</p>
              </div>
            </div>

            {accounts.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-8">
                <div className="w-12 h-12 bg-green-50 rounded-full flex items-center justify-center mb-3">
                  <BarChart2 className="w-6 h-6 text-green-600" />
                </div>
                <h4 className="text-sm font-semibold text-gray-900 mb-1">No accounts selected</h4>
                <p className="text-xs text-gray-500 text-center">Select one or more accounts to see your balance distribution.</p>
              </div>
            ) : (
              <>
                <div className="h-56">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={balancesData} margin={{ top: 5, right: 10, left: 0, bottom: 20 }}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="name" interval={0} angle={-35} textAnchor="end" height={50} tick={{ fontSize: 10 }} />
                      <YAxis tick={{ fontSize: 10 }} />
                      <Tooltip formatter={(v) => formatCurrency(v)} />
                      <Bar dataKey="value" fill="#3b82f6" radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
                {/* Balances breakdown legend */}
                <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-2">
                  {balancesData.slice(0, 10).map((row, idx) => (
                    <div key={`bal-legend-${idx}`} className="flex items-center justify-between text-xs">
                      <div className="flex items-center gap-2">
                        <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ backgroundColor: COLORS[idx % COLORS.length] }} />
                        <span className="text-gray-900 font-medium truncate max-w-[180px]">{row.name}</span>
                      </div>
                      <div className="text-right text-gray-600">
                        {formatCurrency(row.value)}
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>

          {/* Investment Portfolio */}
          <div className="bg-white rounded-md p-4 shadow-sm border border-gray-200">
            <div className="flex items-center gap-1.5 mb-3">
              <div className="p-1.5 bg-green-50 rounded">
                <PieIcon className="w-3.5 h-3.5 text-green-600" />
              </div>
              <div>
                <h3 className="text-md font-semibold text-gray-900">Investment Portfolio</h3>
                <p className="text-xs text-gray-500">{positionsCount} positions • Total value: {formatCurrency(totalInvestments)}</p>
              </div>
            </div>

            {accounts.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-8">
                <div className="w-12 h-12 bg-green-50 rounded-full flex items-center justify-center mb-3">
                  <PieIcon className="w-6 h-6 text-green-600" />
                </div>
                <h4 className="text-sm font-semibold text-gray-900 mb-1">No accounts selected</h4>
                <p className="text-xs text-gray-500 text-center">Select one or more accounts to see your portfolio distribution.</p>
              </div>
            ) : (
              <>
                <div className="h-56">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={(topHoldings || []).map((h, idx) => ({ name: h.symbol || h.name || `H${idx + 1}`, value: Number(h.marketValue || 0) }))}
                        dataKey="value"
                        nameKey="name"
                        innerRadius={55}
                        outerRadius={85}
                        paddingAngle={2}
                      >
                        {(topHoldings || []).map((_, idx) => (
                          <Cell key={`cell-${idx}`} fill={COLORS[idx % COLORS.length]} />
                        ))}
                      </Pie>
                      <Tooltip formatter={(v, n) => [formatCurrency(v), n]} />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                {/* Detailed Breakdown legend */}
                <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-2">
                  {(topHoldings || []).slice(0, 10).map((h, idx) => (
                    <div key={`legend-${idx}`} className="flex items-center justify-between text-xs">
                      <div className="flex items-center gap-2">
                        <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ backgroundColor: COLORS[idx % COLORS.length] }} />
                        <button
                          onClick={() => h.symbol && handleTickerClick(h.symbol)}
                          className="text-gray-900 font-medium truncate max-w-[180px] hover:underline text-left cursor-pointer"
                        >
                          {h.symbol || h.name}
                        </button>
                      </div>
                      <div className="text-right text-gray-600 flex items-center gap-3">
                        <span>{formatCurrency(h.marketValue || 0)}</span>
                        <span className="text-[10px] text-gray-500">{(h.weight ?? 0).toFixed ? (h.weight).toFixed(1) : h.weight}%</span>                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        </div>

        {/* Recent Transactions / Orders */}
        <div className="bg-white rounded-md p-4 shadow-sm border border-gray-200 mb-3">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-1.5">
              <div className="p-1.5 bg-green-50 rounded">
                <RefreshCw className="w-3.5 h-3.5 text-green-600" />
              </div>
              <h3 className="text-md font-semibold text-gray-900">Recent Orders</h3>
            </div>
            <button className="p-1.5 hover:bg-gray-100 rounded-lg transition-colors">
              <svg className="w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 5v.01M12 12v.01M12 19v.01M12 6a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2z" />
              </svg>
            </button>
          </div>

          {demoMode ?
            (
              (transactionsFiltered.length === 0) ? (
                <div className="flex flex-col items-center justify-center py-12">
                  <div className="w-12 h-12 bg-green-50 rounded-full flex items-center justify-center mb-3">
                    <RefreshCw className="w-6 h-6 text-green-600" />
                  </div>
                  <h4 className="text-sm font-semibold text-gray-900 mb-1">No recent demo transactions</h4>
                  <p className="text-xs text-gray-500">They will appear here when available</p>
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="min-w-full text-xs">
                    <thead>
                      <tr className="text-left text-gray-500 border-b border-gray-100">
                        <th className="py-2 pr-4">Date</th>
                        <th className="py-2 pr-4">Account</th>
                        <th className="py-2 pr-4">Symbol</th>
                        <th className="py-2 pr-4">Action</th>
                        <th className="py-2 pr-4 text-right">Quantity</th>
                        <th className="py-2 pr-0 text-right">Price</th>
                      </tr>
                    </thead>
                    <tbody>
                      {transactionsFiltered.slice(0, 10).map((t) => {
                        const acct = (p.accounts || []).find(a => a.id === t.accountId);
                        return (
                          <tr key={t.id} className="border-b border-gray-50">
                            <td className="py-2 pr-4 text-gray-700">{t.date}</td>
                            <td className="py-2 pr-4 text-gray-700">{t.date}</td>
                            <td className="py-2 pr-4 text-gray-700">{acct?.institution || 'Account'}</td>
                            <td className="py-2 pr-4">
                              <button
                                onClick={() => handleTickerClick(t.symbol)}
                                className="text-gray-900 font-medium hover:underline text-left cursor-pointer"
                              >
                                {t.symbol}
                              </button>
                            </td>
                            <td className={`py-2 pr-4 font-semibold ${t.action === 'BUY' ? 'text-green-600' : 'text-red-600'}`}>{t.action}</td>
                            <td className="py-2 pr-4 text-right text-gray-700">{Number(t.quantity ?? 0).toLocaleString('en-US', { maximumFractionDigits: 9 })}</td>
                            <td className="py-2 pr-0 text-right text-gray-700">{formatCurrency(t.price)}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )
            ) : (ordersFiltered.length === 0) ?
              (
                <div className="flex flex-col items-center justify-center py-12">
                  <div className="w-12 h-12 bg-green-50 rounded-full flex items-center justify-center mb-3">
                    <RefreshCw className="w-6 h-6 text-green-600" />
                  </div>
                  <h4 className="text-sm font-semibold text-gray-900 mb-1">No recent orders</h4>
                  <p className="text-xs text-gray-500">Orders will appear here as you trade</p>
                </div>
              ) :
              (
                <div className="overflow-x-auto">
                  <table className="min-w-full text-xs">
                    <thead>
                      <tr className="text-left text-gray-500 border-b border-gray-100">
                        <th className="py-2 pr-4">Placed/Updated</th>
                        <th className="py-2 pr-4">Account</th>
                        <th className="py-2 pr-4">Symbol</th>
                        <th className="py-2 pr-4">Action</th>
                        <th className="py-2 pr-4 text-right">Qty</th>
                        <th className="py-2 pr-0 text-right">Type</th>
                      </tr>
                    </thead>
                    <tbody>
                      {ordersFiltered.slice(0, 10).map((o) => {
                        const acct = (p.accounts || []).find(a => a.id === o.accountId);
                        return (
                          <tr key={o.brokerageOrderId} className="border-b border-gray-50">
                            <td className="py-2 pr-4 text-gray-700">{acct?.institution || 'Account'}</td>
                            <td className="py-2 pr-4">
                              <button
                                onClick={() => handleTickerClick(o.symbol)}
                                className="text-gray-900 font-medium hover:underline text-left cursor-pointer"
                              >
                                {o.symbol}
                              </button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
        </div>

        {/* Top Holdings */}
        <div className="bg-white rounded-md p-4 shadow-sm border border-gray-200 mb-3">
          <div className="flex items-center gap-1.5 mb-4">
            <div className="p-1.5 bg-green-50 rounded">
              <Trophy className="w-3.5 h-3.5 text-green-600" />
            </div>
            <h3 className="text-md font-semibold text-gray-900">Top Holdings</h3>
          </div>

          {topHoldings.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12">
              <div className="w-12 h-12 bg-green-50 rounded-full flex items-center justify-center mb-3">
                <Trophy className="w-6 h-6 text-green-600" />
              </div>
              <h4 className="text-sm font-semibold text-gray-900 mb-1">No holdings</h4>
              <p className="text-xs text-gray-500">Select accounts with holdings to see them here</p>
            </div>
          ) : (
            <div className="text-xs text-gray-700">
              <ul className="space-y-2">
                {(topHoldings || []).slice(0, 10).map((h, idx) => (
                  <div
                    key={`legend-${idx}`}
                    className="flex items-center justify-between text-xs cursor-pointer"
                    onClick={() => handleTickerClick(h.symbol || h.name)}
                  >
                    <div className="flex items-center gap-2">
                      <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ backgroundColor: COLORS[idx % COLORS.length] }} />
                      <span className="text-gray-900 font-medium truncate max-w-[180px] hover:underline">
                        {h.symbol || h.name}
                      </span>
                    </div>
                    <div className="text-right text-gray-600 flex items-center gap-3">
                      <span>{formatCurrency(h.marketValue || 0)}</span>
                      <span className="text-[10px] text-gray-500">{(h.weight ?? 0).toFixed ? (h.weight).toFixed(1) : h.weight}%</span>
                    </div>
                  </div>
                ))}
              </ul>
            </div>
          )}
        </div>

        {/* Connected Accounts */}
        <div className="bg-white rounded-md p-4 shadow-sm border border-gray-200">
          <div className="flex items-center gap-1.5 mb-4">
            <div className="p-1.5 bg-green-50 rounded">
              <Building2 className="w-3.5 h-3.5 text-green-600" />
            </div>
            <div>
              <h3 className="text-md font-semibold text-gray-900">Connected Accounts</h3>
              <p className="text-xs text-gray-500">
                {`${accounts.length} institution(s)`}
              </p>
            </div>
          </div>

          {accounts.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12">
              <div className="w-12 h-12 bg-green-50 rounded-full flex items-center justify-center mb-3">
                <Building2 className="w-6 h-6 text-green-600" />
              </div>
              <h4 className="text-sm font-semibold text-gray-900 mb-1">No accounts selected</h4>
              <p className="text-xs text-gray-500 mb-4">Use the Accounts filter to select accounts.</p>
              <button
                onClick={openConnectModal}
                className="px-4 py-1.5 text-xs font-semibold text-white bg-green-600 rounded-lg hover:bg-green-700 transition-colors cursor-pointer"
              >
                Connect Account
              </button>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {accounts.map((a) => (
                <div key={a.id} className="border border-gray-200 rounded-md p-3 bg-white">
                  <p className="text-[12px] font-semibold text-gray-900">{a.institution || 'Brokerage'}</p>
                  <p className="text-[11px] text-gray-600">{a.name || 'Account'}{a.number ? ` • ${a.number}` : ''}</p>
                </div>
              ))}
            </div>
          )}
        </div>

        {showConnectModal && (
          <div className="fixed inset-0 bg-transparent flex items-center justify-center z-[1000]" onClick={handleConnectModalClose}>
            <div className="bg-white rounded-lg shadow-2xl border border-gray-200 p-8 max-w-md w-full mx-4 relative animate-[modalSlideIn_0.3s_ease-out]" onClick={(e) => e.stopPropagation()}>
              <button
                onClick={handleConnectModalClose}
                className="absolute top-4 right-4 text-gray-400 hover:text-gray-600 transition-colors cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>

              <div className="text-center">
                {/* Portfolio Icon */}
                <div className="mx-auto w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mb-4">
                  <Landmark className="w-8 h-8 text-green-600" />
                </div>

                <h2 className="text-xl font-bold text-gray-900 mb-2">Connect Your Portfolio</h2>
                <p className="text-gray-600 mb-4">
                  Get started with <span className="font-semibold text-green-600">Pro</span> features for free!
                </p>

                <div className="bg-green-50 border border-green-200 rounded-lg p-4 mb-4">
                  <h3 className="text-sm font-semibold text-gray-900 mb-2 text-left">What you'll get:</h3>
                  <ul className="text-xs text-gray-700 space-y-1 text-left">
                    <li className="flex items-center gap-2">
                      <div className="w-1.5 h-1.5 bg-green-600 rounded-full"></div>
                      <span>Real-time net worth tracking</span>
                    </li>
                    <li className="flex items-center gap-2">
                      <div className="w-1.5 h-1.5 bg-green-600 rounded-full"></div>
                      <span>Bank-level security & encryption</span>
                    </li>
                    <li className="flex items-center gap-2">
                      <div className="w-1.5 h-1.5 bg-green-600 rounded-full"></div>
                      <span>AI-powered daily portfolio reports</span>
                    </li>
                    <li className="flex items-center gap-2">
                      <div className="w-1.5 h-1.5 bg-green-600 rounded-full"></div>
                      <span>Smart notifications on portfolio changes</span>
                    </li>
                  </ul>
                </div>

                <p className="text-xs text-gray-500 mb-6">
                  All Pro features are <span className="font-semibold text-green-600">completely free</span> for your first 2 months!
                </p>

                <div className="space-y-2">
                  <button
                    onClick={handleConnectFromModal}
                    className="w-full px-4 py-2 bg-green-600 text-white font-semibold rounded-md hover:bg-green-700 transition-colors cursor-pointer"
                  >
                    Connect Portfolio
                  </button>
                  <button
                    onClick={handleConnectModalClose}
                    className="w-full px-4 py-2 text-gray-600 border border-gray-200 rounded-md hover:bg-gray-50 transition-colors cursor-pointer"
                  >
                    Maybe later
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Disclaimer */}
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

export default Portfolio;