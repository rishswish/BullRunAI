import React, { useEffect, useState } from 'react';
import { Plus, Trash2, Loader2 } from 'lucide-react';

const TICKER_RE = /^[A-Z]{1,5}(\.[A-Z])?$/;
const emptyRow = () => ({ symbol: '', quantity: '', avgCost: '' });

/**
 * Editor for self-reported positions (for users without a linked brokerage).
 * Saved to Firestore via PUT /api/portfolio/manual; prices come from Polygon end-of-day data.
 */
export default function ManualHoldingsModal({ open, onClose, onSaved, user }) {
  const API = import.meta.env.VITE_APP_API_URL;
  const [rows, setRows] = useState([emptyRow()]);
  const [cash, setCash] = useState('');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!open || !user?.token) return;
    setLoading(true);
    setError('');
    fetch(`${API}/api/portfolio/manual`, { headers: { Authorization: `Bearer ${user.token}` } })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d) => {
        const h = (d.holdings || []).map((x) => ({
          symbol: x.symbol, quantity: String(x.quantity), avgCost: x.avgCost == null ? '' : String(x.avgCost),
        }));
        setRows(h.length ? h : [emptyRow()]);
        setCash(d.cash ? String(d.cash) : '');
      })
      .catch(() => setError('Could not load your holdings.'))
      .finally(() => setLoading(false));
  }, [open, user?.token, API]);

  if (!open) return null;

  const update = (i, key, val) =>
    setRows((prev) => prev.map((r, j) => (j === i ? { ...r, [key]: key === 'symbol' ? val.toUpperCase() : val } : r)));

  const filled = rows.filter((r) => r.symbol || r.quantity || r.avgCost);
  const invalid = filled.some((r) => !TICKER_RE.test(r.symbol) || !(Number(r.quantity) > 0)
    || (r.avgCost !== '' && !(Number(r.avgCost) >= 0)));

  const save = async () => {
    setSaving(true);
    setError('');
    try {
      const res = await fetch(`${API}/api/portfolio/manual`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${user.token}` },
        body: JSON.stringify({
          holdings: filled.map((r) => ({
            symbol: r.symbol, quantity: Number(r.quantity), avgCost: r.avgCost === '' ? null : Number(r.avgCost),
          })),
          cash: Number(cash || 0),
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      onSaved?.();
      onClose();
    } catch {
      setError('Saving failed. Please try again.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-[1000]">
      <div className="bg-white rounded-md shadow-xl border border-gray-200 w-full max-w-lg mx-4">
        <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between">
          <div>
            <h3 className="text-sm font-semibold text-gray-900">Manage holdings</h3>
            <p className="text-[11px] text-gray-500">Enter your positions; prices update from market data at each close.</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 cursor-pointer" aria-label="Close">✕</button>
        </div>

        <div className="p-4">
          {loading ? (
            <div className="flex items-center gap-2 text-xs text-gray-500 py-6 justify-center">
              <Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading…
            </div>
          ) : (
            <>
              <div className="grid grid-cols-[1fr_1fr_1fr_28px] gap-2 text-[11px] font-medium text-gray-500 mb-1 px-0.5">
                <span>Ticker</span><span>Shares</span><span>Avg cost ($, optional)</span><span />
              </div>
              <div className="space-y-1.5 max-h-72 overflow-auto pr-1">
                {rows.map((r, i) => {
                  const bad = (r.symbol || r.quantity) && (!TICKER_RE.test(r.symbol) || !(Number(r.quantity) > 0));
                  return (
                    <div key={i} className="grid grid-cols-[1fr_1fr_1fr_28px] gap-2 items-center">
                      <input value={r.symbol} onChange={(e) => update(i, 'symbol', e.target.value)} placeholder="NVDA"
                        className={`px-2 py-1.5 text-xs border rounded-md focus:outline-none focus:ring-1 focus:ring-green-600 ${bad ? 'border-red-300' : 'border-gray-200'}`} />
                      <input value={r.quantity} onChange={(e) => update(i, 'quantity', e.target.value)} placeholder="10"
                        inputMode="decimal" className="px-2 py-1.5 text-xs border border-gray-200 rounded-md focus:outline-none focus:ring-1 focus:ring-green-600" />
                      <input value={r.avgCost} onChange={(e) => update(i, 'avgCost', e.target.value)} placeholder="120.50"
                        inputMode="decimal" className="px-2 py-1.5 text-xs border border-gray-200 rounded-md focus:outline-none focus:ring-1 focus:ring-green-600" />
                      <button onClick={() => setRows((p) => (p.length > 1 ? p.filter((_, j) => j !== i) : [emptyRow()]))}
                        className="p-1 text-gray-400 hover:text-red-500 cursor-pointer" aria-label="Remove row">
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  );
                })}
              </div>
              <button onClick={() => setRows((p) => [...p, emptyRow()])}
                className="mt-2 inline-flex items-center gap-1 text-xs text-green-700 hover:underline cursor-pointer">
                <Plus className="w-3.5 h-3.5" /> Add position
              </button>

              <div className="mt-4 flex items-center gap-2">
                <label className="text-xs text-gray-600 w-28">Cash ($)</label>
                <input value={cash} onChange={(e) => setCash(e.target.value)} placeholder="0" inputMode="decimal"
                  className="flex-1 px-2 py-1.5 text-xs border border-gray-200 rounded-md focus:outline-none focus:ring-1 focus:ring-green-600" />
              </div>

              {error && <p className="text-[11px] text-red-600 mt-3">{error}</p>}
              {invalid && <p className="text-[11px] text-red-600 mt-3">Check the highlighted rows: ticker like NVDA, shares above 0.</p>}

              <div className="mt-4 flex gap-2 justify-end">
                <button onClick={onClose} className="px-3 py-1.5 text-xs border border-gray-200 rounded-md hover:bg-gray-50 cursor-pointer">Cancel</button>
                <button onClick={save} disabled={saving || invalid}
                  className="px-3 py-1.5 text-xs font-semibold text-white bg-green-600 rounded-md hover:bg-green-700 disabled:opacity-50 cursor-pointer">
                  {saving ? 'Saving…' : 'Save holdings'}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
