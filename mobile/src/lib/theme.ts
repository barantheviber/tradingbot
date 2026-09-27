export const colors = {
  bg: '#0d1117',
  card: '#161b22',
  border: '#30363d',
  text: '#e6edf3',
  muted: '#8b949e',
  accent: '#58a6ff',
  up: '#3fb950',
  down: '#f85149',
  warn: '#d29922',
};

export function pnlColor(value: number | null | undefined): string {
  if (!value) return colors.text;
  return value > 0 ? colors.up : colors.down;
}
