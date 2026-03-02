// Vol Surface Heatmap — @nivo/heatmap visualization of implied volatility surface
// Shares ticker selector with Heston panel in SimulationLab

import { useQuery } from '@tanstack/react-query'
import { ResponsiveHeatMap } from '@nivo/heatmap'
import { simulation } from '@/lib/api'

export default function VolSurfaceHeatmap({ ticker }: { ticker: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ['vol-surface', ticker],
    queryFn: () => simulation.volSurface(ticker),
    enabled: !!ticker,
  })

  if (isLoading) {
    return <div style={{ color: 'var(--color-text-dim)', fontSize: 11 }}>Loading vol surface…</div>
  }

  if (!data || !data.surface_data) {
    return (
      <div style={{ color: 'var(--color-text-dim)', fontSize: 11, fontFamily: 'var(--font-sans)' }}>
        No vol surface data — options data needed.
      </div>
    )
  }

  const { moneyness, expiries, ivs, atm_iv, skew_25d } = data.surface_data

  // Check if we have any real IV data (non-null, non-zero)
  const hasRealData = ivs.some(row => row?.some(v => v != null && v > 0))

  if (!hasRealData) {
    return (
      <div style={{ color: 'var(--color-text-dim)', fontSize: 11, fontFamily: 'var(--font-sans)', padding: '20px 0', textAlign: 'center' }}>
        <div style={{ marginBottom: 4 }}>No implied volatility data available for {ticker}.</div>
        <div style={{ fontSize: 10 }}>Options chain data is needed to build the surface.</div>
      </div>
    )
  }

  // Transform into Nivo HeatMap format — use null for missing cells
  // Abbreviate expiry labels: "30d" instead of full
  const heatmapData = expiries.map((exp, i) => ({
    id: `${exp}d`,
    data: moneyness.map((m, j) => ({
      x: `${(m * 100).toFixed(0)}%`,
      y: ivs[i]?.[j] ?? null,
    })),
  }))

  // Reduce tick density to ~8 labels max
  const moneynessTicks = moneyness.length > 8
    ? moneyness.filter((_, i) => i % Math.ceil(moneyness.length / 8) === 0).map(m => `${(m * 100).toFixed(0)}%`)
    : undefined

  return (
    <div>
      <div style={{ height: 220 }} className="vol-heatmap">
        <ResponsiveHeatMap
          data={heatmapData}
          margin={{ top: 20, right: 20, bottom: 50, left: 50 }}
          axisTop={null}
          axisRight={null}
          axisBottom={{
            tickSize: 0,
            tickPadding: 8,
            tickRotation: -45,
            tickValues: moneynessTicks,
            legend: 'Moneyness',
            legendPosition: 'middle' as const,
            legendOffset: 40,
          }}
          axisLeft={{
            tickSize: 0,
            tickPadding: 8,
            legend: 'Expiry',
            legendPosition: 'middle' as const,
            legendOffset: -42,
          }}
          colors={{
            type: 'sequential',
            scheme: 'oranges',
          }}
          emptyColor="hsl(228 15% 14%)"
          borderWidth={1}
          borderColor="hsl(228 15% 16%)"
          labelTextColor="hsl(220 15% 92%)"
          theme={{
            text: { fontFamily: 'var(--font-mono)', fontSize: 9 },
            axis: {
              ticks: { text: { fill: 'hsl(220 10% 45%)', fontFamily: 'var(--font-mono)', fontSize: 9 } },
              legend: { text: { fill: 'hsl(220 10% 45%)', fontFamily: 'var(--font-sans)', fontSize: 10 } },
            },
          }}
        />
      </div>

      {/* Summary stats */}
      <div className="flex gap-4" style={{ marginTop: 8 }}>
        {atm_iv != null && (
          <div style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--color-text-dim)' }}>
            ATM IV: <span style={{ color: 'var(--color-cyan)' }}>{(atm_iv * 100).toFixed(1)}%</span>
          </div>
        )}
        {skew_25d != null && (
          <div style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--color-text-dim)' }}>
            25Δ Skew: <span style={{ color: 'var(--color-cyan)' }}>{(skew_25d * 100).toFixed(1)}%</span>
          </div>
        )}
        <div style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--color-text-dim)' }}>
          As of: {data.as_of}
        </div>
      </div>
    </div>
  )
}
