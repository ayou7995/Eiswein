// Shared relative-time formatter used by settings-adjacent UI. Lifted out of
// SettingsPage so SchwabConnectCard (and any future sibling card) can render
// identical "X 分鐘前" strings without a second, drifting implementation.
//
// Accepts ISO timestamps and falls back gracefully on null / unparseable input.
export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return '尚未執行';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const diffMs = Date.now() - date.getTime();
  const diffMin = Math.floor(diffMs / 60_000);
  if (diffMin < 1) return '剛剛';
  if (diffMin < 60) return `${diffMin} 分鐘前`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr} 小時前`;
  const diffDay = Math.floor(diffHr / 24);
  if (diffDay < 30) return `${diffDay} 天前`;
  return date.toLocaleString('zh-TW', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  });
}
