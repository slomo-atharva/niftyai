import { useState, useEffect } from 'react';
import axios from 'axios';
import { ListChecks, Info, ShieldAlert, Target } from 'lucide-react';

const WatchlistCard = ({ stock }) => {
  return (
    <div className="bg-gray-800/40 hover:bg-gray-800/60 border border-gray-700/50 rounded-xl p-5 transition-all duration-300 shadow-lg group">
      <div className="flex justify-between items-start mb-4">
        <div className="flex flex-col gap-1">
          <h3 className="text-xl font-bold text-white group-hover:text-blue-400 transition-colors">
            {stock.symbol}
            <span className={`ml-3 px-2.5 py-0.5 rounded-full text-[10px] uppercase tracking-wider font-black ${
              stock.opportunity_type === 'SWING' 
                ? 'bg-purple-500/20 text-purple-400 border border-purple-500/30' 
                : 'bg-blue-500/20 text-blue-400 border border-blue-500/30'
            }`}>
              {stock.opportunity_type}
            </span>
          </h3>
        </div>
      </div>
      
      <div className="space-y-4">
        <div>
          <p className="text-xs font-bold text-gray-500 uppercase tracking-widest flex items-center gap-1.5 mb-1.5">
            <Info size={12} className="text-blue-400" /> Why to Watch
          </p>
          <p className="text-sm text-gray-300 leading-relaxed font-medium">{stock.reason}</p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2">
          <div className="bg-gray-900/40 p-3 rounded-lg border border-gray-700/30">
            <p className="text-[10px] font-bold text-gray-500 uppercase tracking-widest flex items-center gap-1.5 mb-1.5">
              <Target size={12} className="text-green-400" /> Key Levels
            </p>
            <p className="text-sm text-green-300/90 font-mono font-medium">{stock.key_levels}</p>
          </div>

          <div className="bg-gray-900/40 p-3 rounded-lg border border-gray-700/30">
            <p className="text-[10px] font-bold text-gray-500 uppercase tracking-widest flex items-center gap-1.5 mb-1.5">
              <ShieldAlert size={12} className="text-red-400" /> Risk Factors
            </p>
            <p className="text-sm text-red-300/90 font-medium">{stock.risk_factors}</p>
          </div>
        </div>
      </div>
    </div>
  );
};

export default function NextSessionWatchlist() {
  const [watchlist, setWatchlist] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchWatchlist = async () => {
      try {
        const response = await axios.get(`${import.meta.env.VITE_API_URL}/watchlist`);
        setWatchlist(response.data.watchlist || []);
      } catch (err) {
        console.error("Watchlist fetch error:", err);
        setError("Failed to load watchlist");
      } finally {
        setLoading(false);
      }
    };
    fetchWatchlist();
  }, []);

  if (loading) {
    return (
      <div className="bg-gray-900/50 border border-gray-800 rounded-2xl p-8 animate-pulse mb-6">
        <div className="h-8 w-64 bg-gray-800 rounded-lg mb-8"></div>
        <div className="space-y-4">
          <div className="h-40 bg-gray-800 rounded-xl"></div>
          <div className="h-40 bg-gray-800 rounded-xl"></div>
        </div>
      </div>
    );
  }

  if (watchlist.length === 0) return null;

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-2xl p-8 shadow-2xl relative overflow-hidden group/main mb-6">
      <div className="absolute top-0 right-0 p-8 opacity-10 group-hover/main:opacity-20 transition-opacity">
        <ListChecks size={120} className="text-blue-500" />
      </div>

      <div className="relative z-10">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h2 className="text-2xl font-black text-white flex items-center gap-3 tracking-tight">
              <div className="p-2 bg-blue-500/10 rounded-lg">
                <ListChecks className="text-blue-400" size={28} />
              </div>
              Next Session Watchlist
            </h2>
            <p className="text-gray-400 text-sm mt-1 font-medium italic">Hand-picked by AI for the upcoming market session</p>
          </div>
          <span className="px-4 py-1.5 bg-yellow-500/10 text-yellow-400 text-[10px] font-black rounded-full border border-yellow-500/30 uppercase tracking-[0.2em]">
            Market Closed
          </span>
        </div>

        <div className="grid grid-cols-1 gap-4">
          {watchlist.map((stock) => (
            <WatchlistCard key={stock.id} stock={stock} />
          ))}
        </div>
      </div>
    </div>
  );
}
