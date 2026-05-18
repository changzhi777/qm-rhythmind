export const v = (val: unknown): string | number =>
  val != null ? (val as string | number) : '-';

export const formatPace = (paceMinPerKm: number | undefined): string => {
  if (paceMinPerKm == null) return '-';
  const min = Math.floor(paceMinPerKm);
  const sec = Math.round((paceMinPerKm - min) * 60);
  return `${min}'${sec.toString().padStart(2, '0')}"`;
};
