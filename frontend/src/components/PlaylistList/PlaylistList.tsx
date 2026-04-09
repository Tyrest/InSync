type Item = { name: string; enabled: boolean; onToggle: (enabled: boolean) => void };

export function PlaylistList({ items }: { items: Item[] }): JSX.Element {
  return (
    <div className="space-y-2">
      {items.map((item) => (
        <label key={item.name} className="flex items-center gap-2 rounded bg-zinc-900 p-3">
          <input
            type="checkbox"
            checked={item.enabled}
            onChange={(event) => item.onToggle(event.target.checked)}
          />
          <span>{item.name}</span>
        </label>
      ))}
    </div>
  );
}
