export const v = (val: unknown): string | number =>
  val != null ? (val as string | number) : '-';

export const formatPace = (paceMinPerKm: number | undefined): string => {
  if (paceMinPerKm == null) return '-';
  const min = Math.floor(paceMinPerKm);
  const sec = Math.round((paceMinPerKm - min) * 60);
  return `${min}'${sec.toString().padStart(2, '0')}"`;
};

/**
 * 将 activity_summary.yearly 对象转为 ECharts LineChart 可用的 {name, value}[] 格式。
 * 用于仪表盘/大屏的年度跑量图表。
 */
export const yearlyToChart = (
  yearly: Record<string, { distance: number; count: number }> | undefined,
): { name: string; value: number }[] =>
  yearly
    ? Object.entries(yearly)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([year, val]) => ({
          name: year,
          value: Math.round((val.distance ?? 0) / 1000),
        }))
    : [];
