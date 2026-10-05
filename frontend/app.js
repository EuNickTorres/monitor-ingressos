const PROD_API_URL = 'https://monitor-ingressos.onrender.com';
const API_URL = (location.hostname === 'localhost' || location.hostname === '127.0.0.1')
  ? 'http://localhost:3000'
  : PROD_API_URL;

const CACHE_TTL_MS = 60 * 1000;
const REQUEST_TIMEOUT_MS = 15 * 1000;
const PARTNER_URLS = {
  'camarote-fielzone': 'https://camarotefielzone.com.br/',
  'lounge-brahma': 'https://loungebrahma.com.br/',
  'bar-do-zeca': 'https://bardozeca.soudaliga.com.br/',
  'arena-kids': 'https://arenakidscorinthians.com.br/',
  'galeria-sccp-ticket360': 'https://www.ticket360.com.br/sub-categoria/1708/camarote-galeria-sccp',
  'camarote-fiel-torcedor-ticket360': 'https://www.ticket360.com.br/eventos/pesquisar?s=Fiel+torcedor',
};

let jogos = [];
let jogoSelecionado = null;
let filtroAtual = 'upcoming';
let requestOfertasId = 0;
const ofertasCache = new Map();

const elements = {
  apiDot: document.getElementById('apiDot'),
  headerTime: document.getElementById('headerTime'),
  gamesList: document.getElementById('gamesList'),
  offersContent: document.getElementById('offersContent'),
  offersTitle: document.getElementById('offersTitle'),
  selectedSummary: document.getElementById('selectedSummary'),
  activePartners: document.getElementById('activePartners'),
  ticketOptions: document.getElementById('ticketOptions'),
  upcomingCount: document.getElementById('upcomingCount'),
  partnerCount: document.getElementById('partnerCount'),
  lowestPrice: document.getElementById('lowestPrice'),
};

document.querySelectorAll('[data-filter]').forEach(button => {
  button.addEventListener('click', () => alterarFiltro(button.dataset.filter));
});
document.getElementById('scrollPrevious').addEventListener('click', () => rolarJogos(-1));
document.getElementById('scrollNext').addEventListener('click', () => rolarJogos(1));
elements.gamesList.addEventListener('click', event => {
  const card = event.target.closest('[data-game-id]');
  if (card) selecionarJogo(card.dataset.gameId);
});
elements.offersContent.addEventListener('click', event => {
  if (event.target.closest('[data-retry]')) carregar({ force: true });
});

carregar();
setInterval(() => carregar({ silent: true, force: true }), CACHE_TTL_MS);

async function fetchJson(url) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(url, {
      headers: { Accept: 'application/json' },
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(`A API respondeu com HTTP ${response.status}`);
    return await response.json();
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('A API demorou mais de 15 segundos para responder');
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

async function carregar({ silent = false, force = false } = {}) {
  try {
    const dados = await fetchJson(`${API_URL}/jogos`);
    jogos = agruparJogos(Array.isArray(dados) ? dados : []);
    setApiStatus(true);
    atualizarResumoGeral();

    const visiveis = jogosVisiveis();
    if (!jogoSelecionado || !visiveis.some(jogo => jogo.id === jogoSelecionado)) {
      jogoSelecionado = visiveis[0]?.id || null;
    }

    renderizarJogos();
    if (jogoSelecionado) {
      await carregarOfertas(jogoSelecionado, { force, silent });
    } else {
      renderizarSemJogos();
    }
  } catch (error) {
    setApiStatus(false);
    if (!silent || jogos.length === 0) renderizarErro(error);
  }
}

function agruparJogos(lista) {
  const grupos = new Map();
  [...lista]
    .filter(jogo => jogo && jogo.slug && jogo.data)
    .sort((a, b) => new Date(a.data) - new Date(b.data))
    .forEach(jogo => {
      const nomeLimpo = limparNomeJogo(jogo.nome || 'Corinthians x adversário');
      // O monitor e exclusivo para jogos do Corinthians como mandante. Evita
      // cards criados a partir de banners promocionais e transmissoes de jogos.
      if (!/^corinthians\s+x\s+/i.test(nomeLimpo)) return;
      const dia = String(jogo.data).slice(0, 10);
      const chave = `${dia}|${chaveAdversario(nomeLimpo)}`;
      const existente = grupos.get(chave);

      if (!existente) {
        grupos.set(chave, { id: chave, nome: nomeLimpo, data: jogo.data, slugs: [jogo.slug] });
        return;
      }

      if (!existente.slugs.includes(jogo.slug)) existente.slugs.push(jogo.slug);
      const dataAtual = new Date(existente.data);
      const dataNova = new Date(jogo.data);
      if (dataAtual.getUTCHours() === 0 && dataNova.getUTCHours() !== 0) existente.data = jogo.data;
      if (nomeLimpo.length < existente.nome.length) existente.nome = nomeLimpo;
    });
  return [...grupos.values()];
}

function limparNomeJogo(nome) {
  let base = String(nome)
    .replace(/\s+(campeonato|brasileir[a-zá]*|conmebol|conmenbol|libertadores|copa|sul-americana|paulista|rodada)\b.*$/i, '')
    .replace(/\s+/g, ' ')
    .trim();
  if (/corinthians\s+x\s+.*estudiantes/i.test(base)) base = 'Corinthians x Estudiantes';
  return base || 'Corinthians x adversário';
}

function chaveAdversario(nome) {
  let chave = normalizarTexto(extrairAdversario(nome));
  if (chave.includes('estudiantes')) return 'estudiantes';
  if (chave.includes('rosario central')) return 'rosario central';
  if (chave.includes('atletico mineiro') || chave.includes('atletico mg')) return 'atletico mg';
  return chave;
}

function jogosVisiveis() {
  const hoje = dataLocalKey(new Date());
  const proximos = jogos.filter(jogo => String(jogo.data).slice(0, 10) >= hoje);
  const historico = jogos
    .filter(jogo => String(jogo.data).slice(0, 10) < hoje)
    .sort((a, b) => new Date(b.data) - new Date(a.data));
  return filtroAtual === 'history' ? historico : proximos;
}

function alterarFiltro(filtro) {
  if (filtro === filtroAtual) return;
  filtroAtual = filtro;
  document.querySelectorAll('[data-filter]').forEach(button => {
    button.setAttribute('aria-pressed', String(button.dataset.filter === filtro));
  });
  const visiveis = jogosVisiveis();
  jogoSelecionado = visiveis[0]?.id || null;
  renderizarJogos();
  if (jogoSelecionado) carregarOfertas(jogoSelecionado);
  else renderizarSemJogos();
}

function renderizarJogos() {
  const visiveis = jogosVisiveis();
  if (visiveis.length === 0) {
    elements.gamesList.innerHTML = '<div class="state-copy">Nenhum jogo nesta visualização.</div>';
    return;
  }

  elements.gamesList.innerHTML = visiveis.map(jogo => {
    const ativo = jogo.id === jogoSelecionado;
    const cache = ofertasCache.get(jogo.id);
    const total = cache?.data?.length;
    const data = new Date(jogo.data);
    const adversario = extrairAdversario(jogo.nome);
    return `
      <button class="game-card" type="button" data-game-id="${escapeAttr(jogo.id)}" aria-pressed="${ativo}" aria-label="${escapeAttr(jogo.nome)}, ${escapeAttr(formatarDataCompleta(data))}">
        <span class="game-card-top">
          <span class="game-date">
            <span class="game-day">${escapeHtml(String(data.getUTCDate()).padStart(2, '0'))}</span>
            <span class="game-month">${escapeHtml(formatarMes(data))}<br>${escapeHtml(formatarHorario(data))}</span>
          </span>
          <span class="game-timing">${escapeHtml(rotuloDistancia(jogo.data))}</span>
        </span>
        <span class="game-card-copy">
          <span class="game-kicker">Corinthians ×</span>
          <span class="game-opponent">${escapeHtml(adversario)}</span>
          <span class="game-meta">${total == null ? 'Consultar ofertas' : `${total} parceiro${total === 1 ? '' : 's'}`}</span>
        </span>
      </button>`;
  }).join('');
}

function selecionarJogo(id) {
  if (jogoSelecionado === id) return;
  jogoSelecionado = id;
  renderizarJogos();
  const card = [...elements.gamesList.querySelectorAll('[data-game-id]')]
    .find(item => item.dataset.gameId === id);
  card?.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
  carregarOfertas(id);
}

async function carregarOfertas(id, { force = false, silent = false } = {}) {
  const jogo = jogos.find(item => item.id === id);
  if (!jogo) return;
  const cached = ofertasCache.get(id);
  if (!force && cached && Date.now() - cached.timestamp < CACHE_TTL_MS) {
    renderizarOfertas(jogo, cached.data);
    return;
  }

  const requestId = ++requestOfertasId;
  if (!silent || !cached) renderizarCarregandoOfertas(jogo);

  try {
    const respostas = await Promise.allSettled(
      jogo.slugs.map(slug => fetchJson(`${API_URL}/ofertas?jogo_slug=${encodeURIComponent(slug)}`))
    );
    const sucessos = respostas
      .filter(resultado => resultado.status === 'fulfilled')
      .flatMap(resultado => Array.isArray(resultado.value) ? resultado.value : []);
    if (respostas.every(resultado => resultado.status === 'rejected')) throw respostas[0].reason;

    const ofertas = mesclarOfertas(sucessos);
    ofertasCache.set(id, { data: ofertas, timestamp: Date.now() });
    if (requestId !== requestOfertasId || jogoSelecionado !== id) return;
    renderizarJogos();
    renderizarOfertas(jogo, ofertas);
  } catch (error) {
    if (requestId !== requestOfertasId || jogoSelecionado !== id) return;
    if (cached) renderizarOfertas(jogo, cached.data);
    else renderizarErroOfertas(jogo, error);
  }
}

function mesclarOfertas(lista) {
  const porParceiro = new Map();
  lista.forEach(oferta => {
    const parceiro = oferta.parceiro_id || {};
    const chave = parceiro.slug || normalizarTexto(parceiro.nome || 'parceiro');
    const atual = porParceiro.get(chave) || { ...oferta, parceiro_id: parceiro, itens: [], _itens: new Map() };
    (oferta.itens || []).forEach(item => atual._itens.set(normalizarTexto(item.nome || ''), item));
    atual.status = atual.status === 'ativo' || oferta.status === 'ativo' ? 'ativo' : 'fechado';
    atual.desatualizado = Boolean(atual.desatualizado && oferta.desatualizado);
    if (oferta.atualizado_em && (!atual.atualizado_em || new Date(oferta.atualizado_em) > new Date(atual.atualizado_em))) {
      atual.atualizado_em = oferta.atualizado_em;
    }
    porParceiro.set(chave, atual);
  });

  return [...porParceiro.values()]
    .map(oferta => {
      oferta.itens = [...oferta._itens.values()].sort((a, b) => Number(a.preco) - Number(b.preco));
      delete oferta._itens;
      return oferta;
    })
    .sort((a, b) => {
      if (a.status !== b.status) return a.status === 'ativo' ? -1 : 1;
      return menorPreco(a) - menorPreco(b);
    });
}

function renderizarCarregandoOfertas(jogo) {
  elements.offersTitle.textContent = limparNomeJogo(jogo.nome);
  elements.selectedSummary.hidden = true;
  elements.offersContent.setAttribute('aria-busy', 'true');
  elements.offersContent.innerHTML = `
    <div class="partners-grid" aria-label="Carregando ofertas">
      <div class="skeleton-card" aria-hidden="true"></div>
      <div class="skeleton-card" aria-hidden="true"></div>
    </div>`;
}

function renderizarOfertas(jogo, ofertas) {
  elements.offersTitle.textContent = limparNomeJogo(jogo.nome);
  elements.offersContent.setAttribute('aria-busy', 'false');
  elements.selectedSummary.hidden = false;
  const ativos = ofertas.filter(oferta => oferta.status === 'ativo' && (oferta.itens || []).length > 0);
  const totalItens = ofertas.reduce((total, oferta) => total + (oferta.itens || []).length, 0);
  elements.activePartners.textContent = String(ativos.length).padStart(2, '0');
  elements.ticketOptions.textContent = String(totalItens).padStart(2, '0');
  elements.partnerCount.textContent = String(ofertas.length).padStart(2, '0');
  const precos = ofertas.flatMap(oferta => (oferta.itens || []).map(item => Number(item.preco))).filter(Number.isFinite);
  elements.lowestPrice.textContent = precos.length ? formatarPreco(Math.min(...precos), false) : '—';

  if (ofertas.length === 0) {
    elements.offersContent.innerHTML = estadoVazio('00', 'Ainda sem ofertas', 'Os parceiros ainda não publicaram opções para esta partida.');
    return;
  }
  elements.offersContent.innerHTML = `<div class="partners-grid">${ofertas.map(renderizarParceiro).join('')}</div>`;
}

function renderizarParceiro(oferta) {
  const parceiro = oferta.parceiro_id || {};
  const nome = parceiro.nome || 'Parceiro';
  const itens = Array.isArray(oferta.itens) ? oferta.itens : [];
  const fechado = oferta.status === 'fechado' || itens.length === 0;
  const desatualizado = Boolean(oferta.desatualizado);
  const iniciais = nome.split(/\s+/).filter(Boolean).map(parte => parte[0]).join('').slice(0, 2).toUpperCase();
  const status = desatualizado ? 'A revisar' : fechado ? 'Fechado' : 'Atualizado';
  const statusClass = desatualizado ? 'stale' : fechado ? 'closed' : 'active';
  const visiveis = itens.slice(0, 5);
  const adicionais = itens.slice(5);
  const slug = parceiro.slug || '';
  const url = urlSegura(parceiro.url || PARTNER_URLS[slug]);
  const atualizado = oferta.atualizado_em ? formatarAtualizacao(oferta.atualizado_em) : 'Última coleta sem horário';

  return `
    <article class="partner-card${fechado ? ' is-closed' : ''}${desatualizado ? ' is-stale' : ''}">
      <header class="partner-card-header">
        <div class="partner-identity">
          <span class="partner-monogram" aria-hidden="true">${escapeHtml(iniciais || '•')}</span>
          <div>
            <h3 class="partner-name">${escapeHtml(nome)}</h3>
            <p class="partner-count">${itens.length} opç${itens.length === 1 ? 'ão' : 'ões'} encontrada${itens.length === 1 ? '' : 's'}</p>
          </div>
        </div>
        <span class="status-badge ${statusClass}">${escapeHtml(status)}</span>
      </header>
      <div class="partner-price-block">
        <span class="price-label">A partir de</span>
        <strong class="starting-price">${itens.length ? escapeHtml(formatarPreco(menorPreco(oferta))) : 'Indisponível'}</strong>
      </div>
      <div class="ticket-list">
        ${visiveis.length ? visiveis.map(renderizarItem).join('') : '<p class="state-copy">Nenhum ingresso disponível nesta coleta.</p>'}
        ${adicionais.length ? `
          <details class="more-tickets">
            <summary>Ver mais ${adicionais.length} opç${adicionais.length === 1 ? 'ão' : 'ões'}</summary>
            ${adicionais.map(renderizarItem).join('')}
          </details>` : ''}
      </div>
      <footer class="partner-footer">
        <span>${escapeHtml(atualizado)}</span>
        ${url ? `<a class="partner-link" href="${escapeAttr(url)}" target="_blank" rel="noopener noreferrer">Abrir parceiro ↗</a>` : ''}
      </footer>
    </article>`;
}

function renderizarItem(item) {
  const preco = Number(item.preco);
  const detalhe = item.tipo === 'combo'
    ? `${item.adultos || 0} adulto(s)${item.criancas ? ` + ${item.criancas} criança(s)` : ''}`
    : item.publico || 'individual';
  return `
    <div class="ticket-row">
      <div>
        <div class="ticket-name">${escapeHtml(item.nome || 'Ingresso')}</div>
        <div class="ticket-subtitle">${escapeHtml(detalhe)}</div>
      </div>
      <span class="ticket-price">${Number.isFinite(preco) ? escapeHtml(formatarPreco(preco)) : '—'}</span>
    </div>`;
}

function renderizarSemJogos() {
  elements.offersTitle.textContent = filtroAtual === 'history' ? 'Histórico vazio' : 'Agenda em atualização';
  elements.selectedSummary.hidden = true;
  elements.offersContent.innerHTML = estadoVazio('00', 'Nenhum jogo por aqui', filtroAtual === 'history'
    ? 'Ainda não há partidas anteriores cadastradas.'
    : 'O monitor não encontrou novas partidas publicadas pelos parceiros.');
}

function renderizarErro(error) {
  elements.gamesList.innerHTML = '<div class="state-copy">Não foi possível carregar a agenda.</div>';
  elements.offersTitle.textContent = 'Conexão interrompida';
  elements.selectedSummary.hidden = true;
  elements.offersContent.setAttribute('aria-busy', 'false');
  elements.offersContent.innerHTML = `
    <div class="error-state"><div class="state-inner">
      <span class="state-index">!</span>
      <h3 class="state-title">A API não respondeu</h3>
      <p class="state-copy">${escapeHtml(error.message || 'Falha desconhecida')}. Tente novamente em alguns instantes.</p>
      <button class="retry-button" type="button" data-retry>Tentar novamente</button>
    </div></div>`;
}

function renderizarErroOfertas(jogo, error) {
  elements.offersTitle.textContent = limparNomeJogo(jogo.nome);
  elements.selectedSummary.hidden = true;
  elements.offersContent.setAttribute('aria-busy', 'false');
  elements.offersContent.innerHTML = `
    <div class="error-state"><div class="state-inner">
      <span class="state-index">!</span>
      <h3 class="state-title">Ofertas indisponíveis</h3>
      <p class="state-copy">${escapeHtml(error.message || 'Não conseguimos consultar os parceiros agora')}.</p>
      <button class="retry-button" type="button" data-retry>Tentar novamente</button>
    </div></div>`;
}

function estadoVazio(indice, titulo, texto) {
  return `
    <div class="empty-state"><div class="state-inner">
      <span class="state-index">${escapeHtml(indice)}</span>
      <h3 class="state-title">${escapeHtml(titulo)}</h3>
      <p class="state-copy">${escapeHtml(texto)}</p>
    </div></div>`;
}

function setApiStatus(online) {
  elements.apiDot.className = `api-status-dot ${online ? 'online' : 'offline'}`;
  elements.headerTime.textContent = online
    ? `Atualizado ${new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}`
    : 'API offline';
}

function atualizarResumoGeral() {
  const hoje = dataLocalKey(new Date());
  const proximos = jogos.filter(jogo => String(jogo.data).slice(0, 10) >= hoje);
  elements.upcomingCount.textContent = String(proximos.length).padStart(2, '0');
}

function rolarJogos(direcao) {
  const card = elements.gamesList.querySelector('.game-card');
  const distancia = (card?.getBoundingClientRect().width || 320) + 14;
  elements.gamesList.scrollBy({ left: distancia * direcao, behavior: 'smooth' });
}

function menorPreco(oferta) {
  const precos = (oferta.itens || []).map(item => Number(item.preco)).filter(Number.isFinite);
  return precos.length ? Math.min(...precos) : Number.POSITIVE_INFINITY;
}

function extrairAdversario(nome) {
  const partes = limparNomeJogo(nome).split(/\s+x\s+/i);
  return partes.length > 1 ? partes.slice(1).join(' x ') : limparNomeJogo(nome);
}

function rotuloDistancia(iso) {
  const hoje = new Date(`${dataLocalKey(new Date())}T00:00:00`);
  const diaJogo = new Date(`${String(iso).slice(0, 10)}T00:00:00`);
  const dias = Math.round((diaJogo - hoje) / 86400000);
  if (dias === 0) return 'Hoje';
  if (dias === 1) return 'Amanhã';
  if (dias > 1) return `Em ${dias} dias`;
  return 'Encerrado';
}

function formatarMes(data) {
  return data.toLocaleDateString('pt-BR', { month: 'short', timeZone: 'UTC' }).replace('.', '');
}

function formatarHorario(data) {
  const hora = data.getUTCHours();
  const minuto = data.getUTCMinutes();
  return hora === 0 && minuto === 0 ? 'a definir' : `${String(hora).padStart(2, '0')}h${String(minuto).padStart(2, '0')}`;
}

function formatarDataCompleta(data) {
  return data.toLocaleDateString('pt-BR', {
    weekday: 'long', day: '2-digit', month: 'long', year: 'numeric', timeZone: 'UTC',
  });
}

function formatarPreco(valor, centavos = true) {
  return new Intl.NumberFormat('pt-BR', {
    style: 'currency', currency: 'BRL',
    minimumFractionDigits: centavos ? 2 : 0,
    maximumFractionDigits: centavos ? 2 : 0,
  }).format(valor);
}

function formatarAtualizacao(iso) {
  const data = new Date(iso);
  if (Number.isNaN(data.getTime())) return 'Atualização recente';
  return `Coletado ${data.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })} às ${data.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}`;
}

function dataLocalKey(data) {
  const ano = data.getFullYear();
  const mes = String(data.getMonth() + 1).padStart(2, '0');
  const dia = String(data.getDate()).padStart(2, '0');
  return `${ano}-${mes}-${dia}`;
}

function normalizarTexto(valor) {
  return String(valor).normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
}

function urlSegura(valor) {
  if (!valor) return '';
  try {
    const url = new URL(valor);
    return url.protocol === 'https:' ? url.href : '';
  } catch {
    return '';
  }
}

function escapeHtml(valor) {
  return String(valor).replace(/[&<>'"]/g, caractere => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
  })[caractere]);
}

function escapeAttr(valor) {
  return escapeHtml(valor).replace(/`/g, '&#96;');
}
