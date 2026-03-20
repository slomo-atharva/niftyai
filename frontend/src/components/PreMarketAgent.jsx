import { useState, useEffect } from 'react';
import axios from 'axios';
import { Cpu, Play, Loader2, Gauge } from 'lucide-react';

export default function PreMarketAgent() {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);

  useEffect(() => {
    fetchStatus();
  }, []);

  const fetchStatus = async () => {
    try {
      const response = await axios.get(`${import.meta.env.VITE_API_URL}/agent/status`);
      setStatus(response.data);
    } catch (err) {
      console.error('Failed to fetch agent status', err);
    } finally {
      setLoading(false);
    }
  };

  const handleManualScan = async () => {
    setScanning(true);
    try {
      await axios.post(`${import.meta.env.VITE_API_URL}/agent/run`);
      // Simulating a delay for the UI to show the scanning state appropriately
      setTimeout(() => {
        fetchStatus();
        setScanning(false);
      }, 3000);
    } catch (err) {
      console.error('Failed to trigger scan', err);
      setScanning(false);
    }
  };

  if (loading) {
    return (
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 shadow-2xl h-full animate-pulse">
         <div className="h-6 w-1/2 bg-gray-800 rounded mb-4"></div>
         <div className="h-20 bg-gray-800 rounded"></div>
      </div>
    );
  }

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 shadow-2xl h-full flex flex-col transition hover:border-teal-500/30">
      <div className="flex justify-between items-start mb-6">
        <h2 className="text-xl font-bold font-inter text-white flex items-center gap-2">
          <Cpu className="text-teal-400" size={24} />
          Pre-Market Agent
        </h2>
        
        <div className="flex items-center gap-2">
          <span className="relative flex h-3 w-3">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-teal-400 opacity-75"></span>
            <span className="relative inline-flex rounded-full h-3 w-3 bg-teal-500"></span>
          </span>
          <span className="text-xs text-teal-400 font-semibold uppercase tracking-wider">Online</span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 mb-8 flex-grow">
        <div className="bg-gray-800/40 border border-gray-700/50 rounded-lg p-4">
          <p className="text-xs text-gray-500 uppercase tracking-widest mb-1 flex items-center gap-1"><Gauge size={12}/> VIX</p>
          <div className="flex items-baseline gap-2">
            <p className={`text-2xl font-light ${status?.vix > 20 ? 'text-red-400' : 'text-white'}`}>
              {status?.vix ? status.vix.toFixed(2) : '--'}
            </p>
            {status?.vix_regime && (
              <span className={`text-[10px] font-bold uppercase px-1.5 py-0.5 rounded ${
                status.vix < 15 ? 'bg-teal-500/20 text-teal-400' :
                status.vix < 20 ? 'bg-blue-500/20 text-blue-400' :
                status.vix < 25 ? 'bg-amber-500/20 text-amber-400' :
                status.vix < 30 ? 'bg-orange-500/20 text-orange-400' :
                'bg-red-500/20 text-red-400'
              }`}>
                {status.vix_regime.split(' ')[0]}
              </span>
            )}
          </div>
        </div>
        <div className="bg-gray-800/40 border border-gray-700/50 rounded-lg p-4">
          <p className="text-xs text-gray-500 uppercase tracking-widest mb-1">SGX Nifty</p>
          <p className={`text-2xl font-light ${status?.sgx_nifty < -1 ? 'text-red-400' : 'text-white'}`}>
            {status?.sgx_nifty ? status.sgx_nifty.toFixed(2) : '--'}
          </p>
        </div>
        <div className="bg-gray-800/40 border border-gray-700/50 rounded-lg p-4 col-span-2">
          <p className="text-xs text-gray-500 uppercase tracking-widest mb-2 flex justify-between items-center">
            <span>Last Run Details</span>
            {status?.scan_type && (
              <span className={`px-2 py-0.5 rounded text-[10px] ${status.scan_type === 'LIVE' ? 'bg-teal-500/20 text-teal-400' : 'bg-amber-500/20 text-amber-400'}`}>
                {status.scan_type} SCAN
              </span>
            )}
          </p>
          <div className="space-y-2">
            <p className="text-white text-sm font-medium">
              {status?.last_run_time ? new Date(status.last_run_time).toLocaleString() : 'Never'}
            </p>
            {status?.last_run_time && (
              <div className="grid grid-cols-3 gap-2 mt-2 pt-2 border-t border-gray-700/30">
                <div>
                  <p className="text-[10px] text-gray-500 uppercase">Scanned</p>
                  <p className="text-sm text-teal-400 font-semibold">{status.stocks_scanned || 0}</p>
                </div>
                <div>
                  <p className="text-[10px] text-gray-500 uppercase">Staged</p>
                  <p className="text-sm text-green-400 font-semibold">{status.trades_staged || 0}</p>
                </div>
                <div>
                  <p className="text-[10px] text-gray-500 uppercase">Killed</p>
                  <p className="text-sm text-red-400 font-semibold">{status.trades_killed || 0}</p>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      <button 
        onClick={handleManualScan}
        disabled={scanning}
        className={`w-full py-3 px-4 rounded-lg font-bold flexitems-center justify-center gap-2 transition-all duration-300 ${
          scanning 
            ? 'bg-teal-500/20 text-teal-300 cursor-not-allowed border border-teal-500/30' 
            : 'bg-teal-500 hover:bg-teal-400 text-gray-900 shadow-[0_0_15px_rgba(20,184,166,0.5)] hover:shadow-[0_0_25px_rgba(20,184,166,0.6)]'
        }`}
      >
        {scanning ? (
          <>
            <Loader2 className="animate-spin" size={20} />
            Running Scan...
          </>
        ) : (
          <>
            <Play size={20} fill="currentColor" />
            Manual Pre-Market Scan
          </>
        )}
      </button>
    </div>
  );
}
