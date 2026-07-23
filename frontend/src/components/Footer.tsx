/* Rodapé do site (do design). Disclaimer ToS Riot incluído. */
import { Link } from "react-router-dom";

export function Footer() {
  return (
    <footer className="site-footer">
      <div className="inner">
        <div className="brand">
          <img src="/assets/logo.png" alt="ArenaRank" />
          <p>
            O ranking competitivo dos modos casuais de League of Legends. Rating justo, transparente e auditável.
          </p>
        </div>
        <div>
          <h4>Produto</h4>
          <ul>
            <li><Link to="/leaderboard">Leaderboard</Link></li>
            <li><Link to="/duo">Ache seu Duo</Link></li>
            <li><Link to="/perfil/Frederic Boulos#BR1">Perfis</Link></li>
            <li><Link to="/sistema">Como funciona</Link></li>
          </ul>
        </div>
        <div>
          <h4>Plataforma</h4>
          <ul>
            <li><Link to="/admin">Painel Admin</Link></li>
            <li><Link to="/sistema">Integridade</Link></li>
            <li><Link to="/sistema">ArenaRank Pro</Link></li>
            <li><Link to="/campeonatos">Torneios</Link></li>
          </ul>
        </div>
        <div>
          <h4>Recursos</h4>
          <ul>
            <li><Link to="/sistema">Como o CR funciona</Link></li>
            <li><Link to="/sistema">Integridade</Link></li>
            <li><Link to="/winrate">Champ Winrate</Link></li>
            <li><Link to="/leaderboard">Status</Link></li>
          </ul>
        </div>
      </div>
      <div className="legal">
        <span>© 2026 ArenaRank. Dados da Riot Games usados conforme os Termos de Serviço da API de Desenvolvedor.</span>
        <span>Não endossado ou afiliado à Riot Games.</span>
      </div>
    </footer>
  );
}
