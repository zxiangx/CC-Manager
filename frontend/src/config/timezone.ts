export const BEIJING_TIMEZONE = 'Asia/Shanghai';

export function getTimezone(): string {
  return BEIJING_TIMEZONE;
}

export function setTimezone(tz: string) {
  // Kept as a compatibility no-op for older callers. CCM intentionally uses
  // one display timezone on every device so timestamps never drift by client.
  void tz;
}

/** Resolve the effective IANA timezone string */
export function resolveTimezone(): string {
  return BEIJING_TIMEZONE;
}

function getDateParts(date: Date, tz: string): { year: number; month: number; day: number } {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: tz,
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
  }).formatToParts(date);
  return {
    year: Number(parts.find(p => p.type === 'year')!.value),
    month: Number(parts.find(p => p.type === 'month')!.value),
    day: Number(parts.find(p => p.type === 'day')!.value),
  };
}

/** Normalize an ISO timestamp to ensure UTC interpretation.
 *  Backend sends naive datetimes (no Z suffix) that are actually UTC. */
function ensureUtc(iso: string): string {
  if (/Z$/i.test(iso) || /[+-]\d{2}:?\d{2}$/.test(iso)) return iso;
  return iso + 'Z';
}

/** Format an ISO timestamp string for display in chat.
 *  Today → HH:MM, same year → MM/DD HH:MM, different year → YYYY/MM/DD HH:MM */
export function formatMessageTime(isoString: string, now?: Date): string {
  const tz = resolveTimezone();
  const date = new Date(ensureUtc(isoString));
  const msgParts = getDateParts(date, tz);
  const nowParts = getDateParts(now ?? new Date(), tz);

  const time = date.toLocaleTimeString(undefined, {
    timeZone: tz,
    hour: '2-digit',
    minute: '2-digit',
  });

  const isToday = msgParts.year === nowParts.year
    && msgParts.month === nowParts.month
    && msgParts.day === nowParts.day;

  if (isToday) return time;

  const mm = String(msgParts.month).padStart(2, '0');
  const dd = String(msgParts.day).padStart(2, '0');

  if (msgParts.year !== nowParts.year) {
    return `${msgParts.year}/${mm}/${dd} ${time}`;
  }
  return `${mm}/${dd} ${time}`;
}

/** Format an ISO timestamp for general display (tasks, headers).
 *  Always shows date + time: YYYY/MM/DD HH:MM or MM/DD HH:MM (same year). */
export function formatDateTime(isoString: string, now?: Date): string {
  const tz = resolveTimezone();
  const date = new Date(ensureUtc(isoString));
  const msgParts = getDateParts(date, tz);
  const nowParts = getDateParts(now ?? new Date(), tz);

  const time = date.toLocaleTimeString(undefined, {
    timeZone: tz,
    hour: '2-digit',
    minute: '2-digit',
  });

  const mm = String(msgParts.month).padStart(2, '0');
  const dd = String(msgParts.day).padStart(2, '0');

  if (msgParts.year !== nowParts.year) {
    return `${msgParts.year}/${mm}/${dd} ${time}`;
  }
  return `${mm}/${dd} ${time}`;
}
