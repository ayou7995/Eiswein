import { useParams } from 'react-router-dom';

export function TickerDetailPage(): JSX.Element {
  const { symbol } = useParams<{ symbol: string }>();
  return (
    <section aria-labelledby="ticker-heading" className="flex flex-col gap-4">
      <h1 id="ticker-heading" className="text-2xl font-semibold">
        標的分析：{symbol ?? '—'}
      </h1>
      <p className="text-sm text-slate-400">
        Phase 4 建置中：K 線圖、12 指標、Pros/Cons、進場/停損建議。
      </p>
    </section>
  );
}
