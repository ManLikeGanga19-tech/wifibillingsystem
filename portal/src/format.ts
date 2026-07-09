/** DRF DurationField renders "HH:MM:SS" or "D HH:MM:SS" (or ISO "P7DT00H00M00S"). */
export function formatDuration(duration: string): string {
  let days = 0;
  let hours = 0;
  let minutes = 0;
  const iso = duration.match(/^P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?/);
  const plain = duration.match(/^(?:(\d+) )?(\d{2}):(\d{2}):\d{2}$/);
  if (iso) {
    days = Number(iso[1] ?? 0);
    hours = Number(iso[2] ?? 0);
    minutes = Number(iso[3] ?? 0);
  } else if (plain) {
    days = Number(plain[1] ?? 0);
    hours = Number(plain[2]);
    minutes = Number(plain[3]);
  } else {
    return duration;
  }
  if (days >= 30) return `${Math.round(days / 30)} Month${days >= 60 ? 's' : ''}`;
  if (days >= 7) return `${Math.round(days / 7)} Week${days >= 14 ? 's' : ''}`;
  if (days > 0) return `${days} Day${days > 1 ? 's' : ''}`;
  if (hours > 0) return `${hours} Hour${hours > 1 ? 's' : ''}`;
  return `${minutes} Min`;
}

export function formatSpeed(kbps: number): string {
  return kbps >= 1024 ? `${Math.round(kbps / 1024)} Mbps` : `${kbps} Kbps`;
}

export function formatKsh(amount: string | number): string {
  return `KSh ${Number(amount).toLocaleString('en-KE', { maximumFractionDigits: 0 })}`;
}

export function formatExpiry(iso: string): string {
  return new Date(iso).toLocaleString('en-KE', {
    weekday: 'short',
    hour: '2-digit',
    minute: '2-digit',
    day: 'numeric',
    month: 'short',
  });
}

/** Client-side Kenyan phone sanity check (server re-validates authoritatively). */
export function isValidKenyanPhone(raw: string): boolean {
  const digits = raw.replace(/\D/g, '');
  return (
    (digits.length === 10 && digits.startsWith('0') && '17'.includes(digits[1])) ||
    (digits.length === 12 && digits.startsWith('254') && '17'.includes(digits[3])) ||
    (digits.length === 9 && '17'.includes(digits[0]))
  );
}
