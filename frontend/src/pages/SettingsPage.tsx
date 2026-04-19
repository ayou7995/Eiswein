import { WatchlistSection } from '../components/WatchlistSection';

export function SettingsPage(): JSX.Element {
  return (
    <section aria-labelledby="settings-heading" className="flex flex-col gap-6">
      <header>
        <h1 id="settings-heading" className="text-2xl font-semibold text-slate-100">
          設定
        </h1>
        <p className="mt-1 text-sm text-slate-400">
          Phase 5 建置中：資料來源、通知、密碼變更、稽核日誌將逐步加入。
          以下觀察清單區塊已可使用。
        </p>
      </header>

      <WatchlistSection />
    </section>
  );
}
