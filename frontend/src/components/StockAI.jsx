import { useState, useEffect } from 'react';
import axios from 'axios';
import { Activity, AlertTriangle, CheckCircle, TrendingUp } from 'lucide-react';

export default function StockAI() {
  const [trades, setTrades] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchTodayTrades = async () => {
      try {
        const response = await axios.get(`${import.meta.env.VITE_API_URL}/trades/today`);
        setTrades(response.data.trades || []);
      } catch (err) {
        setError("Failed to fetch today's trades");
      } finally {
        setLoading(false);
      }
    };
    fetchTodayTrades();
  }, []);

  if (loading) {
    return (
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 shadow-2xl animate-pulse">
        <div className="h-6 w-1/3 bg-gray-800 rounded mb-4"></div>
        <div className="space-y-3">
          <div className="h-20 bg-gray-800 rounded"></div>
          <div className="h-20 bg-gray-800 rounded"></div>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 shadow-2xl transition hover:border-blue-500/30">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-bold font-inter text-white flex items-center gap-2">
          <Activity className="text-blue-400" size={24} />
          Today's Staged Trades
        </h2>
        <span className="px-3 py-1 bg-blue-500/10 text-blue-400 text-xs font-semibold rounded-full border border-blue-500/20">
          Live AI Scan
        </span>
      </div>

      {error ? (
        <div className="flex bg-red-500/10 border border-red-500/20 rounded-lg p-4 text-red-400 items-center gap-3">
          <AlertTriangle size={20} />
          <p>{error}</p>
        </div>
      ) : trades.length === 0 ? (
        <div className="flex flex-col items-center justify-center p-8 text-center bg-gray-800/30 rounded-lg border border-gray-800 border-dashed">
          <TrendingUp className="text-gray-500 mb-2" size={32} />
          <p className="text-gray-400 font-medium">No Trades Today</p>
          <p className="text-gray-500 text-sm mt-1">Market may be closed or AI kill rules were triggered.</p>
        </div>
      ) : (
        <div className="space-y-4">
          {trades.map((trade) => (
            <div key={trade.id} className="bg-gray-800/50 hover:bg-gray-800 border border-gray-700 rounded-lg p-4 transition">
              <div className="flex justify-between items-start mb-2">
                <div>
                  <h3 className="text-lg font-bold text-white flex items-center gap-2">
                    {trade.symbol} 
                    <span className={`px-2 py-0.5 rounded text-xs font-bold ${trade.side === 'BUY' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}`}>
                      {trade.side}
                    </span>
                  </h3>
                </div>
                <div className="text-right">
                  <p className="text-sm text-gray-400">Entry</p>
                  <p className="font-mono text-white">₹{trade.entry_price}</p>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4 mt-3 pt-3 border-t border-gray-700/50">
                <div>
                  <p className="text-xs text-gray-500 uppercase tracking-widest">Target</p>
                  <p className="font-mono text-green-400">₹{trade.target_price}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-500 uppercase tracking-widest">Stop Loss</p>
                  <p className="font-mono text-red-400">₹{trade.stop_loss}</p>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
