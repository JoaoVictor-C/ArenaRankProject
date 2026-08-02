import { Link } from "react-router-dom";

import "./ProfileSurfaceNav.css";

export function ProfileSurfaceNav({
  riotId,
  active,
}: {
  riotId: string;
  active: "profile" | "lens";
}) {
  const profilePath = `/perfil/${encodeURIComponent(riotId)}`;

  return (
    <nav className="profile-surface-nav" aria-label="Seções do perfil">
      <Link className={active === "profile" ? "is-active" : ""} to={profilePath}>
        Perfil
      </Link>
      <Link to={`${profilePath}#partidas`}>Partidas</Link>
      <Link to={`${profilePath}#campeoes`}>Campeões</Link>
      {import.meta.env.DEV && (
        <Link className={active === "lens" ? "is-active" : ""} to={`${profilePath}/lens`}>
          <span>Lens</span>
          <small>PREVIEW</small>
        </Link>
      )}
    </nav>
  );
}
