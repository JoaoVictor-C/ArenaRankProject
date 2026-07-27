import { NAV_GROUPS, type View } from "../lib/nav";

interface Props {
  view: View;
  onView: (v: View) => void;
  pillCounts?: Partial<Record<View, number>>;
}

export function Sidebar({ view, onView, pillCounts }: Props) {
  return (
    <aside className="sidebar">
      {NAV_GROUPS.map((grp) => (
        <div className="nav-group" key={grp.label}>
          <div className="nav-group-label">{grp.label}</div>
          {grp.items.map((it) => {
            const pill = pillCounts?.[it.id];
            return (
              <button
                key={it.id}
                type="button"
                className={view === it.id ? "nav-item nav-item-active" : "nav-item"}
                aria-current={view === it.id ? "page" : undefined}
                onClick={() => onView(it.id)}
              >
                <span className="ms ms-18" aria-hidden="true">
                  {it.icon}
                </span>
                <span className="nav-item-label">{it.label}</span>
                {!!pill && <span className="nav-pill">{pill}</span>}
              </button>
            );
          })}
        </div>
      ))}
    </aside>
  );
}
