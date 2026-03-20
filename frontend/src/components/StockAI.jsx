import { useState, useEffect } from 'react';
import axios from 'axios';
import { Activity, AlertTriangle, CheckCircle, TrendingUp, Clock, CalendarDays } from 'lucide-react';

const TradeCard = ({ trade, isSwing }) => {
  const signal = trade.signal || trade.side || 'BUY';
  const entry = trade.entry || trade.entry_price || '-';
  const t1 = trade.t1 || trade.target_price || '-';
  const t2 = trade.t2 || '-';
  const t3 = trade.t3 || '-';
  const sl = trade.sl || trade.stop_loss || '-';
  const reasoning = trade.reasoning || trade.ai_reasoning || 'AI selected this trade based on technical indicators and pre-market data.';
  const multiplier = trade.position_multiplier || 1.0;

  return (
    <div className="bg-gray-800/50 hover:bg-gray-800 border border-gray-700 rounded-lg p-4 transition shadow-sm mb-3">
      <div className="flex justify-between items-start mb-2">
        <div>
          <h3 className="text-lg font-bold text-white flex items-center gap-2">
            {trade.symbol} 
            <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${signal === 'BUY' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}`}>
              {signal}
            </span>
            {multiplier < 1.0 && (
              <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-500/20 text-amber-400 border border-amber-500/30">
                {Math.round(multiplier * 100)}% SIZE
              </span>
            )}
          </h3>
          <p className="text-xs text-gray-400 mt-1 line-clamp-2" title={reasoning}>{reasoning}</p>
        </div>
        <div className="text-right">
          <p className="text-sm text-gray-400">Entry</p>
          <p className="font-mono text-white font-medium">₹{entry}</p>
        </div>
      </div>
      <div className="grid grid-cols-4 gap-2 mt-3 pt-3 border-t border-gray-700/50">
        <div>
          <p className="text-[10px] text-gray-500 uppercase font-semibold tracking-wider">Stop Loss</p>
          <p className="font-mono text-red-400 text-sm font-medium pt-1">₹{sl}</p>
        </div>
        <div>
          <p className="text-[10px] text-gray-500 uppercase font-semibold tracking-wider">Target 1</p>
          <p className="font-mono text-green-400 text-sm font-medium pt-1">₹{t1}</p>
        </div>
        <div>
          <p className="text-[10px] text-gray-500 uppercase font-semibold tracking-wider">Target 2</p>
          <p className="font-mono text-green-400 text-sm font-medium pt-1">₹{t2}</p>
        </div>
        <div>
          <p className="text-[10px] text-gray-500 uppercase font-semibold tracking-wider">Target 3</p>
          <p className="font-mono text-green-400 text-sm font-medium pt-1">₹{t3}</p>
        </div>
      </div>
      <div className="mt-3 pt-3 flex justify-between items-center border-t border-gray-700/50 text-xs text-gray-400">
        <div className="flex items-center gap-1.5">
          {isSwing ? (
            <>
              <CalendarDays size={14} className="text-purple-400"/>
              <span><strong className="text-gray-300">Period:</strong> {trade.holding_period || '3-7 days'}</span>
            </>
          ) : (
            <>
              <Activity size={14} className="text-blue-400"/>
              <span><strong className="text-gray-300">R:R:</strong> {trade.rr_ratio || trade.risk_reward_ratio || '1:2'}</span>
            </>
          )}
        </div>
      </div>
    </div>
  );
};

export default function StockAI() {
  const [trades, setTrades] = useState([]);
  const [agentStatus, setAgentStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [tradesResp, statusResp] = await Promise.all([
          axios.get(`${import.meta.env.VITE_API_URL}/trades/today`),
          axios.get(`${import.meta.env.VITE_API_URL}/agent/status`)
        ]);
        setTrades(tradesResp.data.trades || []);
        setAgentStatus(statusResp.data);
      } catch (err) {
        setError("Failed to fetch data");
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, []);

  if (loading) {
    return (
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 shadow-2xl animate-pulse">
        <div className="h-6 w-1/3 bg-gray-800 rounded mb-4"></div>
        <div className="space-y-3">
          <div className="h-32 bg-gray-800 rounded"></div>
          <div className="h-32 bg-gray-800 rounded"></div>
        </div>
      </div>
    );
  }

  const intradayTrades = trades.filter(t => !t.trade_type || t.trade_type === 'INTRADAY');
  const swingTrades = trades.filter(t => t.trade_type === 'SWING');

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
        <div className="flex flex-col items-center justify-center p-10 text-center bg-gray-800/30 rounded-lg border border-gray-800 border-dashed transition-all">
          <TrendingUp className="text-blue-500/50 mb-4 animate-pulse" size={48} />
          <h3 className="text-white font-bold text-lg mb-2">
            {agentStatus?.vix_message || "No Trades Today"}
          </h3>
          <p className="text-gray-400 text-sm max-w-sm">
            {agentStatus?.vix_message 
              ? "The AI agent has completed its scan. However, due to current market conditions, no high-conviction trades were approved." 
              : "Market may be closed or the pre-market scan hasn't run yet. Please check back later."}
          </p>
        </div>
      ) : (
        <div className="space-y-6">
          {intradayTrades.length > 0 && (
            <div>
              <h3 className="text-md font-semibold text-gray-300 flex items-center gap-2 mb-3 border-b border-gray-800 pb-2">
                <Clock size={16} className="text-blue-400"/>
                Intraday Trades
                <span className="text-xs font-normal text-gray-500 bg-gray-800 px-2 py-0.5 rounded-full">{intradayTrades.length}</span>
              </h3>
              <div>
                {intradayTrades.map((trade) => (
                  <TradeCard key={trade.id || Math.random()} trade={trade} isSwing={false} />
                ))}
              </div>
            </div>
          )}

          {swingTrades.length > 0 && (
            <div>
              <h3 className="text-md font-semibold text-gray-300 flex items-center gap-2 mb-3 border-b border-gray-800 pb-2">
                <CalendarDays size={16} className="text-purple-400"/>
                Swing Trades
                <span className="text-xs font-normal text-gray-500 bg-gray-800 px-2 py-0.5 rounded-full">{swingTrades.length}</span>
              </h3>
              <div>
                {swingTrades.map((trade) => (
                  <TradeCard key={trade.id || Math.random()} trade={trade} isSwing={true} />
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
