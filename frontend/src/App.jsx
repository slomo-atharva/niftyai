import StockAI from './components/StockAI'
import TradeTracker from './components/TradeTracker'
import PreMarketAgent from './components/PreMarketAgent'
import NextSessionWatchlist from './components/NextSessionWatchlist'
import { Activity } from 'lucide-react'

function App() {
  return (
    <div className="min-h-screen bg-gray-950 text-white font-inter selection:bg-blue-500/30">
      {/* Header */}
      <header className="border-b border-gray-800 bg-gray-900/50 backdrop-blur-xl sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-gradient-to-br from-blue-500 to-teal-400 rounded-lg shadow-[0_0_15px_rgba(59,130,246,0.3)]">
              <Activity className="text-white" size={24} />
            </div>
            <h1 className="text-2xl font-black tracking-tight bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-teal-300">
              NiftyAI
            </h1>
          </div>
          <div className="flex items-center gap-4 text-sm font-medium">
            <span className="flex items-center gap-2 text-gray-400 bg-gray-800/50 px-3 py-1.5 rounded-full border border-gray-700/50">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500"></span>
              </span>
              System Active
            </span>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-6 py-8">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          
          {/* Left Column: Pre-Market Agent (Span 1) */}
          <div className="lg:col-span-1">
            <PreMarketAgent />
          </div>

          {/* Right Column: Live Trades (Span 2) */}
          <div className="lg:col-span-2 space-y-6">
            <NextSessionWatchlist />
            <StockAI />
          </div>
        </div>

        {/* Full Width Row: Trade History */}
        <div className="mt-6">
          <TradeTracker />
        </div>
      </main>
    </div>
  )
}

export default App
