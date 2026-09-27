import { useEffect, useRef } from "react";
import {
  createChart, CrosshairMode, LineStyle, type IChartApi, type IPriceLine, type ISeriesApi, type UTCTimestamp,
} from "lightweight-charts";
import type { Candle, Position } from "../../shared/types";

interface Props {
  candles: Candle[];
  positions: Position[];
}

/** Candlestick + volume chart with entry / stop / take-profit lines for open positions. */
export default function CandleChart({ candles, positions }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volume = useRef<ISeriesApi<"Histogram"> | null>(null);
  const lines = useRef<IPriceLine[]>([]);
  const fitted = useRef(false);

  useEffect(() => {
    if (!box.current) return;
    const c = createChart(box.current, {
      autoSize: true,
      layout: { background: { color: "#151821" }, textColor: "#aab2c0" },
      grid: { vertLines: { color: "#1f2330" }, horzLines: { color: "#1f2330" } },
      crosshair: { mode: CrosshairMode.Normal },
      timeScale: { timeVisible: true, secondsVisible: false, borderColor: "#2a2f3d" },
      rightPriceScale: { borderColor: "#2a2f3d" },
    });
    series.current = c.addCandlestickSeries({
      upColor: "#26a69a", downColor: "#ef5350", borderVisible: false, wickUpColor: "#26a69a", wickDownColor: "#ef5350",
    });
    volume.current = c.addHistogramSeries({ priceFormat: { type: "volume" }, priceScaleId: "vol" });
    c.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    chart.current = c;
    return () => {
      c.remove();
      chart.current = null;
      series.current = null;
      volume.current = null;
      lines.current = [];
      fitted.current = false;
    };
  }, []);

  useEffect(() => {
    if (!series.current || !volume.current) return;
    series.current.setData(
      candles.map(([t, o, h, l, cl]) => ({ time: (t / 1000) as UTCTimestamp, open: o, high: h, low: l, close: cl })),
    );
    volume.current.setData(
      candles.map(([t, o, , , cl, v]) => ({
        time: (t / 1000) as UTCTimestamp,
        value: v,
        color: cl >= o ? "rgba(38,166,154,0.4)" : "rgba(239,83,80,0.4)",
      })),
    );
    if (!fitted.current && candles.length) {
      chart.current?.timeScale().fitContent();
      fitted.current = true;
    }
  }, [candles]);

  useEffect(() => {
    const s = series.current;
    if (!s) return;
    lines.current.forEach((l) => s.removePriceLine(l));
    lines.current = [];
    for (const p of positions) {
      const add = (price: number | null | undefined, color: string, title: string, style = LineStyle.Dashed) => {
        if (price === null || price === undefined) return;
        lines.current.push(s.createPriceLine({ price, color, lineWidth: 1, lineStyle: style, axisLabelVisible: true, title }));
      };
      add(p.entry_price, "#8ab4f8", `#${p.id} giriş`, LineStyle.Solid);
      add(p.stop_loss, "#ef5350", `#${p.id} stop`);
      add(p.take_profit, "#26a69a", `#${p.id} TP`);
      if (p.trailing_stop !== undefined && p.trailing_stop !== null && p.trailing_stop !== p.stop_loss)
        add(p.trailing_stop, "#f6c344", `#${p.id} trailing`);
    }
  }, [positions]);

  return <div className="chart" ref={box} />;
}
