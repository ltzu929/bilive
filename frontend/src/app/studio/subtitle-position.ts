/** ASS alignment: 1–3 bottom, 4–6 middle, 7–9 top. */
export function subtitlePosition(value: number): {horizontal: string; vertical: string} {
  const alignment = Math.min(9, Math.max(1, Number(value) || 2));
  return {
    horizontal: alignment % 3 === 1 ? 'flex-start' : alignment % 3 === 0 ? 'flex-end' : 'center',
    vertical: alignment >= 7 ? 'flex-start' : alignment >= 4 ? 'center' : 'flex-end',
  };
}
