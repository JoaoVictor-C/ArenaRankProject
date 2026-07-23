# Product

## Register

product

## Platform

web

## Users

Jogadores competitivos de League of Legends **Arena** no Brasil. Chegam querendo saber onde estão: a posição no ranking, o Casual Rating (CR) atual, se subiram ou caíram, como se comparam com amigos e quais campeões/duplas dominam o meta. A Riot não oferece ranqueada oficial para o Arena, então este é o lugar onde o modo ganha uma nota competitiva de verdade. O público é amplo dentro desse nicho — do jogador focado em ladder ao curioso que só quer conferir winrate de campeão — e alguns também organizam e disputam campeonatos.

## Product Purpose

Dar ao modo Arena a camada competitiva que falta: um ladder com CR/tier, perfis de jogador, estatísticas de campeões e duplas, detalhe de partidas e campeonatos — tudo alimentado por dados reais da API da Riot. O produto costura três coisas numa só rede: o placar de referência (o jogador confia no CR como sua nota e volta para acompanhar rank, streak e evolução), a descoberta de meta (tierlist e winrate guiam o que jogar) e a comunidade (campeonatos rodando, perfis conectados). Sucesso é o jogador voltando com recorrência porque este virou o ponto de encontro competitivo do Arena.

## Positioning

O hub social do Arena: o único lugar onde ranking, campeonatos e perfis se conectam como a rede da comunidade competitiva do modo — não só uma tabela de stats, mas onde a cena se organiza e se reconhece. O CR legítimo é a espinha dorsal que dá autoridade a tudo que se pendura nele.

## Brand Personality

Competitivo, premium, legítimo. A interface carrega peso de esports sério: ouro para rating e tiers, medalhões, molduras que evocam o próprio universo do jogo. Nada aqui deve soar provisório ou de brincadeira — o rank precisa parecer uma conquista com valor. Voz direta e confiante, em PT-BR, falando com quem já conhece o Arena. A referência de mira é FACEIT / esports (peso competitivo dark com identidade forte, comunidade que se leva a sério) somada ao acabamento de data-viz de Mobalytics / Blitz (gráficos limpos, insights bem desenhados, moderno).

## Anti-references

Não pode parecer:
- **SaaS genérico / dashboard corporativo** — cinza-azulado, cards idênticos repetidos, o template hero-metric, Inter sem alma. Nada de cara de painel B2B.
- **Site de stats poluído e ad-heavy** — densidade caótica, anúncios, mil widgets brigando por atenção (o op.gg antigo). Densidade sim, mas curada.
- **Cartoon / infantil** — cores primárias saturadas, bordas fofas, mascotes. Longe do peso competitivo.
- **Cripto / neon futurista** — roxo-neon com glow, glassmorphism decorativo, gradientes gritantes, estética web3.

## Design Principles

Legitimidade primeiro. Cada tela precisa fazer o CR e o rank lerem como um placar competitivo real, com valor conquistado — nunca como um brinquedo. Hierarquia, precisão dos números e acabamento servem a essa confiança.

Hub, não só ladder. Ranking, campeonatos e perfis são partes de uma mesma rede; o design conecta essas superfícies em vez de tratá-las como páginas soltas. O jogador deve sentir que entrou numa cena, não numa consulta avulsa.

Densidade com autoridade. Densidade de dados nível esports (op.gg/Mobalytics como régua) mas curada e legível — a ferramenta desaparece na tarefa. O oposto do caos ad-heavy: cada dado ganhou seu lugar.

Premium do universo do jogo, merecido. A identidade de ouro/tier/medalhão pertence ao mundo do Arena e aparece nos momentos que importam (rating, topo do ranking, conquistas), não pulverizada por toda a tela. Isso evita ao mesmo tempo o cinza-SaaS e o neon-cripto.

Rápido e confiável. Um hub de stats vive de velocidade e de tabelas corretas; skeletons no lugar de spinners, estados vazios que ensinam, vocabulário de componente consistente de tela em tela.

## Accessibility & Inclusion

Sem meta formal de WCAG definida pelo produto. Ainda assim, o próprio código levanta dois riscos concretos que valem atenção ao evoluir a UI: há vídeo de fundo e animações de reveal (garantir alternativa sob `prefers-reduced-motion`), e a sinalização de subiu/caiu depende de verde/vermelho (não confiar só na cor — reforçar com seta/sinal para daltônicos). Contraste de corpo legível sobre as superfícies escuras é o piso pragmático a manter.
