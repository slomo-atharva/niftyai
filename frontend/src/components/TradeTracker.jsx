import { useState, useEffect } from 'react';
import axios from 'axios';
import { History, Target, XCircle } from 'lucide-react';

export default function TradeTracker() {
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchHistory = async () => {
      try {
        const response = await axios.get(`${import.meta.env.VITE_API_URL}/trades/history`);
        setHistory(response.data.trades || []);
      } catch (err) {
        console.error('Failed to fetch trade history', err);
      } finally {
        setLoading(false);
      }
    };
    fetchHistory();
  }, []);

  if (loading) {
    return (
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 shadow-2xl animate-pulse mt-6">
        <div className="h-6 w-1/4 bg-gray-800 rounded mb-4"></div>
        <div className="h-32 bg-gray-800 rounded"></div>
      </div>
    );
  }

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 shadow-2xl mt-6 transition hover:border-purple-500/30">
      <div className="flex items-center gap-2 mb-6">
        <History className="text-purple-400" size={24} />
        <h2 className="text-xl font-bold font-inter text-white">Trade History & Outcomes</h2>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="border-b border-gray-800">
              <th className="pb-3 text-xs font-semibold text-gray-400 uppercase tracking-wider">Symbol</th>
              <th className="pb-3 text-xs font-semibold text-gray-400 uppercase tracking-wider">Type</th>
              <th className="pb-3 text-xs font-semibold text-gray-400 uppercase tracking-wider">Entry</th>
              <th className="pb-3 text-xs font-semibold text-gray-400 uppercase tracking-wider text-right">Outcome</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800/50">
            {history.slice().sort((a,b) => new Date(b.created_at) - new Date(a.created_at)).map((trade) => (
              <tr key={trade.id} className="hover:bg-gray-800/30 transition-colors">
                <td className="py-4 font-medium text-white">{trade.symbol}</td>
                <td className="py-4">
                  <span className={`text-xs px-2 py-1 rounded ${trade.side === 'BUY' ? 'text-green-400 bg-green-400/10' : 'text-red-400 bg-red-400/10'}`}>
                    {trade.side}
                  </span>
                </td>
                <td className="py-4 font-mono text-sm text-gray-300">₹{trade.entry_price}</td>
                <td className="py-4 text-right">
                  {!trade.outcome ? (
                    <span className="text-gray-500 text-sm">Pending</span>
                  ) : trade.outcome.success ? (
                    <div className="flex items-center justify-end gap-1 text-green-400 text-sm font-medium">
                      <Target size={14} /> Hit Target
                    </div>
                  ) : (
                    <div className="flex items-center justify-end gap-1 text-red-400 text-sm font-medium">
                      <XCircle size={14} /> Hit SL
                    </div>
                  )}
                </td>
              </tr>
            ))}
            {history.length === 0 && (
              <tr>
                <td colSpan="4" className="py-8 text-center text-gray-500">No historical trades yet.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
