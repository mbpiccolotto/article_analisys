/* app.js — toda a interface da triagem: modelos de tela (antiga pasta HTML), tema, envio, filtros e resultados.
   O servidor só entrega este arquivo, o style.css e a API JSON (/api/...). */
(() => {
  'use strict';

  const MAX_UPLOAD_BYTES = 32 * 1024 * 1024;  // mesmo limite do servidor
  const $ = id => document.getElementById(id);
  /** Escapa texto para HTML (todo dado vindo de arquivos passa por aqui). */
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]));
  /** Aceita vírgula ou ponto como separador decimal. */
  const parseDecimal = value => Number(String(value).trim().replace(',', '.'));

  // ==========================================================================
  // Tema claro/escuro (aplicado já no <head>, antes da renderização)
  // ==========================================================================

  const THEME_KEY = 'triage-theme';
  const readTheme = () => { try { return localStorage.getItem(THEME_KEY); } catch (_) { return null; } };
  const saveTheme = theme => { try { localStorage.setItem(THEME_KEY, theme); } catch (_) { /* armazenamento indisponível */ } };

  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    const label = theme === 'dark' ? '☀ Modo claro' : '☾ Modo escuro';
    document.querySelectorAll('[data-theme-toggle]').forEach(button => {
      button.textContent = label;
      button.setAttribute('aria-label', label);
    });
  }
  applyTheme(readTheme() || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'));

  // ==========================================================================
  // Modelos de tela
  // ==========================================================================

  const themeToggle = () => '<button type="button" class="secondary theme-toggle" data-theme-toggle>☾ Modo escuro</button>';

  /** Grupo de seleção de arquivos: "Escolher arquivos" + "Escolher pasta" para um formato. */
  const sourceGroup = (kind, title, description, filesId, folderId, filesLabel) => `
    <section class="source-group ${kind}-source" aria-labelledby="${kind}-source-title">
      <div><h2 id="${kind}-source-title">${title}</h2><p>${description}</p></div>
      <div class="source-options">
        <label for="${filesId}" class="drop-zone"><span>${filesLabel}</span><small>Um ou mais arquivos</small></label>
        <label for="${folderId}" class="drop-zone folder-zone"><span>Escolher pasta</span><small>Todos os arquivos da pasta</small></label>
      </div>
    </section>`;

  const uploadView = () => `
<main class="shell">
  <p class="eyebrow">REVISÃO SISTEMÁTICA</p>
  <h1>Triagem de Artigos</h1>
  <p class="lead">Envie uma exportação da sua base bibliográfica (RIS, BibTeX, CSV, PubMed ou EndNote), defina os critérios do projeto e receba uma pré-triagem rápida. Formatos diferentes de RIS são convertidos automaticamente.</p>
  <p id="alert" class="alert" role="alert" hidden></p>

  <form id="upload-form" class="upload-card">
    <div class="analysis-action">
      <div class="analysis-controls"><button type="submit">Analisar artigos</button><button type="button" id="convert-ris" class="secondary" title="Gera um único arquivo .ris com os registros dos arquivos escolhidos, sem analisar">Converter para RIS</button></div>
      <div class="interface-controls">${themeToggle()}</div>
    </div>

    <div class="source-actions">
      ${sourceGroup('ref', 'Referências bibliográficas', 'RIS, BibTeX (.bib), CSV (Scopus, Web of Science, IEEE Xplore), PubMed (.nbib) ou EndNote (.enw).', 'ref-files', 'ref-folder', 'Escolher arquivos')}
    </div>
    <input id="ref-files" type="file" accept=".ris,.bib,.bibtex,.nbib,.medline,.enw,.csv,.txt" multiple>
    <input id="ref-folder" type="file" accept=".ris,.bib,.bibtex,.nbib,.medline,.enw,.csv,.txt" webkitdirectory directory multiple>
    <p id="chosen" class="chosen">Nenhum arquivo selecionado.</p>
    <p class="hint">Limite total: 32 MB. Os registros são analisados pelos metadados (título, resumo, palavras-chave e periódico). Use "Converter para RIS" para só gerar o arquivo .ris, sem analisar.</p>

    <section class="criteria" aria-labelledby="filters-title">
      <div class="editor-heading">
        <div><h2 id="filters-title">Filtros da análise</h2><p>Configure os critérios para este projeto. Os filtros da última análise ficam guardados neste computador e podem ser restaurados.</p></div>
        <div class="editor-actions">
          <button type="button" id="restore-filters" class="secondary" disabled>Restaurar critérios anteriores</button>
          <button type="button" id="reset-filters" class="secondary">Limpar filtros</button>
          <button type="button" id="add-filter" class="secondary">+ Adicionar filtro</button>
        </div>
      </div>
      <p id="filter-status" class="filter-status" aria-live="polite"></p>
      <label class="threshold-label"><span>Limiar de inclusão</span> <input id="threshold" type="number" min="0" step="0.5" placeholder="Ex.: 8" aria-describedby="decimal-hint"> <span>pontos</span></label>
      <p id="decimal-hint" class="decimal-hint">Use as setas para avançar ou recuar em intervalos de 0,5 ponto.</p>
      <div id="filter-list" class="filter-list"></div>

      <aside class="filter-example" aria-labelledby="example-title">
        <h3 id="example-title">Exemplo de configuração (somente leitura)</h3>
        <p>Adicione filtros com os mesmos campos abaixo e ajuste-os ao seu projeto. Um filtro obrigatório precisa ser encontrado para que o estudo seja incluído.</p>
        <div class="example-grid">
          <div><strong>População</strong><span>Termos: adultos; participantes</span><span>Peso: 2 · Obrigatório</span></div>
          <div><strong>Intervenção</strong><span>Termos: intervenção; tratamento</span><span>Peso: 2 · Obrigatório</span></div>
          <div><strong>Desfecho</strong><span>Termos: resultado primário; eficácia</span><span>Peso: 2 · Opcional</span></div>
        </div>
        <p><strong>Limiar de inclusão do exemplo: 4 pontos.</strong> Neste caso, o estudo precisa atingir 4 de 6 pontos e atender a todos os filtros obrigatórios.</p>
      </aside>
    </section>
  </form>
</main>`;

  const loadingView = () => `
<div id="loading" class="loading" aria-live="polite" aria-hidden="true">
  <div class="loading-card"><div class="spinner"></div><h2>Analisando os arquivos…</h2><p>Lendo metadados e aplicando os filtros configurados. Isto pode levar alguns instantes.</p></div>
</div>`;

  const filterRowView = () => `
<div class="filter-row">
  <label>Nome<input class="filter-label" placeholder="Ex.: População-alvo"></label>
  <label>Termos (separe por ; ou quebra de linha)<textarea class="filter-terms" placeholder="termo 1; termo 2"></textarea></label>
  <label>Peso<input class="filter-weight" type="number" min="0.5" step="0.5" value="1" aria-label="Peso"></label>
  <label class="required"><input class="filter-required" type="checkbox"> <span>Obrigatório</span></label>
  <button type="button" class="remove-filter" aria-label="Remover filtro">×</button>
</div>`;

  const articleCard = article => `
      <article class="article-card ${article.decision === 'Incluído' ? 'included' : 'excluded'}" data-year="${esc(article.year)}" data-title="${esc(article.title)}" data-author="${esc(article.authors)}">
        <div class="decision-line"><strong>${esc(article.decision)}</strong><span>${esc(article.score_label)} <span>pontos</span></span></div>
        <h3>${esc(article.title)}</h3>
        <p class="file-name">${esc(article.source_type)} · ${esc(article.filename)}</p>
        <dl class="article-metadata">
          <div><dt>Ano</dt><dd>${esc(article.year)}</dd></div>
          <div><dt>Autores</dt><dd>${esc(article.authors)}</dd></div>
          <div><dt>Periódico</dt><dd>${esc(article.journal)}</dd></div>
          <div><dt>DOI</dt><dd>${esc(article.doi)}</dd></div>
          <div><dt>Repositório</dt><dd>${esc(article.repository)}</dd></div>
        </dl>
        <details class="card-details">
          <summary><span class="expand-label">Expandir detalhes</span><span class="collapse-label">Ocultar detalhes</span></summary>
          <div class="card-details-content">
            <div class="abstract-block"><strong>Resumo</strong><p>${esc(article.abstract)}</p></div>
            <p class="rationale"><strong>Triagem:</strong> ${esc(article.rationale)}</p>
            <ul class="filter-checks">
              ${article.filter_results.map(check => `<li class="${check.matched ? 'pass' : 'fail'}"><span>${check.matched ? '✓' : '–'}</span>${esc(check.label)} <small>(${esc(check.points_label)}/${esc(check.weight_label)} pt${check.required ? ', obrigatório' : ''})</small></li>`).join('\n              ')}
            </ul>
            ${article.extraction_note ? `<p class="extraction-note">${esc(article.extraction_note)}</p>` : ''}
          </div>
        </details>
      </article>`;

  const resultsView = data => `
<main class="shell results-shell">
  <a class="back" href="/" id="new-analysis">← Nova análise</a>
  <p class="eyebrow">RESULTADOS</p>
  <div class="results-title-row">
    <h1>${data.articles.length} ${data.articles.length > 1 ? 'artigos analisados' : 'artigo analisado'}</h1>
    <div class="export-buttons">
      <button type="button" data-export="excel">Baixar lista Excel detalhada</button>
      <button type="button" data-export="ris"${data.ris_included ? '' : ' disabled title="Nenhum registro incluído veio de arquivo RIS."'}>Baixar RIS dos incluídos (${data.ris_included})</button>
      <button type="button" data-export="prisma-svg" class="secondary prisma-download">Baixar fluxograma PRISMA</button>
      <button type="button" data-export="prisma" class="secondary prisma-download">Baixar planilha PRISMA</button>
    </div>
  </div>
  <p id="export-alert" class="alert" role="alert" hidden></p>
  <p class="summary">Classificação atual: ${data.included} incluído(s) e ${data.excluded} excluído(s). Limiar usado: ${esc(data.threshold_label)}/${esc(data.maximum_label)}.</p>
  <p class="dedup-summary">${data.prisma.duplicates_removed} duplicata(s) removida(s) automaticamente de ${data.prisma.identified_total} registro(s) identificado(s). O modelo PRISMA detalha as fontes e a auditoria.</p>
  <aside class="human-review-notice">Observação importante: o PRISMA é preenchido automaticamente a partir da pré-triagem. A análise criteriosa humana do texto completo é indispensável para confirmar elegibilidade e inclusão final.</aside>

  <section class="quick-results" aria-labelledby="quick-title">
    <div class="quick-heading">
      <div><p class="eyebrow">RESULTADO RÁPIDO</p><h2 id="quick-title">Resumo por artigo</h2></div>
      <div class="quick-actions">
        <div class="interface-controls">${themeToggle()}</div>
        <div class="analysis-controls">
          <div class="card-sort">
            <label for="sort-cards"><span>Organizar cards por</span> <select id="sort-cards"><option value="year">Ano</option><option value="title">Título</option><option value="author">Autor</option></select></label>
            <button id="sort-direction" type="button" class="secondary" aria-label="Alternar ordem crescente ou decrescente">Crescente ↑</button>
          </div>
          <div class="card-filter">
            <label for="filter-cards"><span>Visualizar</span> <select id="filter-cards"><option value="all">Todos</option><option value="included">Apenas incluídos</option><option value="excluded">Apenas excluídos</option></select></label>
          </div>
        </div>
      </div>
    </div>

    <div class="article-cards">${data.articles.map(articleCard).join('')}
    </div>
  </section>

  <p class="footer-note">A decisão é uma pré-triagem. Confirme os dados e a inclusão final no texto completo; use o Excel para a matriz detalhada.</p>
</main>`;

  // ==========================================================================
  // Telas: alternância entre envio e resultados (o formulário é preservado)
  // ==========================================================================

  let results = null;  // última resposta da análise (usada nas exportações)

  function showView(name) {
    $('view-upload').hidden = name !== 'upload';
    $('view-results').hidden = name !== 'results';
    document.title = name === 'results' ? 'Resultados da triagem' : 'Revisão Sistemática de Artigos';
    scrollTo(0, 0);
  }

  function showResults(data) {
    results = data;
    $('view-results').innerHTML = resultsView(data);
    applyTheme(document.documentElement.dataset.theme);  // rótulo do botão de tema recém-criado
    bindResults();
    history.pushState({view: 'results'}, '', '#resultados');
    showView('results');
  }

  window.addEventListener('popstate', () => showView(history.state?.view === 'results' && results ? 'results' : 'upload'));

  /** Mostra (ou esconde, com texto vazio) a mensagem de erro de um painel. */
  function setAlert(id, message) {
    const element = $(id);
    element.textContent = message || '';
    element.hidden = !message;
  }

  // ==========================================================================
  // Envio: arquivos, filtros e análise
  // ==========================================================================

  function bindUpload() {
    const form = $('upload-form');
    const fileInputs = [...form.querySelectorAll('input[type="file"]')];
    const chosen = $('chosen');
    const filterList = $('filter-list');
    const thresholdInput = $('threshold');
    const restoreButton = $('restore-filters');
    const filterStatus = $('filter-status');

    // ---- Arquivos: só um seletor fica ativo por vez (arquivos ou pasta).
    function showChosenFiles(source) {
      if (source.files.length) fileInputs.filter(input => input !== source).forEach(input => { input.value = ''; });
      const files = [...source.files];
      chosen.textContent = files.length
        ? `${files.length} arquivo(s) selecionado(s): ${files.slice(0, 5).map(file => file.name).join(', ')}${files.length > 5 ? '…' : ''}`
        : 'Nenhum arquivo selecionado.';
    }
    fileInputs.forEach(input => input.addEventListener('change', () => showChosenFiles(input)));

    // ---- Filtros
    function addFilter({label = '', terms = '', weight = 1, required = false} = {}) {
      const holder = document.createElement('div');
      holder.innerHTML = filterRowView().trim();
      const row = holder.firstElementChild;
      row.querySelector('.filter-label').value = label;
      row.querySelector('.filter-terms').value = Array.isArray(terms) ? terms.join('; ') : terms;
      row.querySelector('.filter-weight').value = weight;
      row.querySelector('.filter-required').checked = required;
      row.querySelector('.remove-filter').addEventListener('click', () => row.remove());
      filterList.append(row);
    }

    function setFilters(configuration) {
      filterList.replaceChildren();
      thresholdInput.value = configuration?.threshold ?? '';
      (configuration?.filters ?? []).forEach(addFilter);
    }

    /** Lê as linhas da tela já convertidas (termos em lista, peso numérico). */
    const readFilterRows = () => [...filterList.querySelectorAll('.filter-row')].map(row => ({
      label: row.querySelector('.filter-label').value.trim(),
      terms: row.querySelector('.filter-terms').value.split(/[;\n,]/).map(term => term.trim()).filter(Boolean),
      weight: parseDecimal(row.querySelector('.filter-weight').value),
      required: row.querySelector('.filter-required').checked,
    }));
    const isComplete = filter => filter.label && filter.terms.length && filter.weight > 0;

    // ---- Última sessão: guardada pelo servidor (cache/last_session.json) a cada análise.
    async function fetchLastSession() {
      const response = await fetch('/api/last-session', {cache: 'no-store'});
      return response.status === 200 ? response.json() : null;
    }

    async function restoreLastSession() {
      try {
        const saved = await fetchLastSession();
        if (saved) {
          setFilters(saved);
          filterStatus.textContent = 'Filtros e limiar da última sessão restaurados.';
        } else {
          filterStatus.textContent = 'Não há filtros salvos para restaurar.';
          restoreButton.disabled = true;
        }
      } catch (_) {
        filterStatus.textContent = 'Não foi possível ler os filtros salvos. O servidor local está em execução?';
      }
    }

    $('add-filter').addEventListener('click', () => addFilter());
    $('reset-filters').addEventListener('click', () => { setFilters(); chosen.textContent = 'Filtros removidos.'; });
    restoreButton.addEventListener('click', restoreLastSession);
    fetchLastSession().then(saved => { restoreButton.disabled = !saved; }).catch(() => {});

    // ---- Envio
    form.addEventListener('submit', async event => {
      event.preventDefault();
      const reject = message => { chosen.textContent = message; };

      const files = fileInputs.flatMap(input => [...input.files]);
      if (!files.length) return reject('Selecione pelo menos um arquivo de referências antes de analisar.');

      const rows = readFilterRows();
      const filters = rows.filter(isComplete);
      if (!filters.length) return reject('Adicione pelo menos um filtro com termos e peso antes de analisar.');

      const threshold = parseDecimal(thresholdInput.value);
      if (!Number.isFinite(threshold) || threshold < 0) return reject('Informe um limiar válido, usando vírgula ou ponto para decimais.');
      if (filters.length !== rows.length) return reject('Preencha nome, termos e um peso maior que zero em todos os filtros, ou remova os incompletos.');

      setAlert('alert', '');
      $('loading').classList.add('visible');
      $('loading').setAttribute('aria-hidden', 'false');
      try {
        showResults(await analyse(files, {filters, threshold}));
        restoreButton.disabled = false;  // o servidor acabou de guardar esta sessão
      } catch (error) {
        setAlert('alert', error.message);
        scrollTo(0, 0);
      } finally {
        $('loading').classList.remove('visible');
        $('loading').setAttribute('aria-hidden', 'true');
      }
    });

    // ---- Conversão para RIS (sem análise nem filtros)
    $('convert-ris').addEventListener('click', async event => {
      const files = fileInputs.flatMap(input => [...input.files]);
      if (!files.length) return setAlert('alert', 'Selecione pelo menos um arquivo de referências para converter.');
      setAlert('alert', '');
      const button = event.currentTarget;
      button.disabled = true;
      try {
        const {blob, filename, records, warnings} = await convertToRis(files);
        saveBlob(blob, filename);
        chosen.textContent = `${records} registro(s) convertido(s) para RIS em ${filename}.${warnings ? ` Avisos: ${warnings}` : ''}`;
      } catch (error) {
        setAlert('alert', error.message);
      } finally {
        button.disabled = false;
      }
    });

    setFilters();
  }

  /** Corpo: 4 bytes (tamanho N) + N bytes de JSON {filters, threshold, files} + conteúdo dos arquivos em sequência. */
  async function sendFiles(url, files, configuration) {
    // O nome inclui a pasta quando o envio é por pasta (o repositório pode ser inferido dela).
    const names = files.map(file => file.webkitRelativePath || file.name);
    const meta = new TextEncoder().encode(JSON.stringify({...configuration, files: files.map((file, index) => ({name: names[index], size: file.size}))}));
    const header = new Uint8Array(4);
    new DataView(header.buffer).setUint32(0, meta.length);
    const body = new Blob([header, meta, ...files]);
    if (body.size > MAX_UPLOAD_BYTES) throw new Error('O envio excede o limite total de 32 MB.');
    try {
      return await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/octet-stream'}, body});
    } catch (_) {
      throw new Error('Não foi possível falar com o servidor local. Ele está em execução?');
    }
  }

  async function analyse(files, configuration) {
    const response = await sendFiles('/api/analyse', files, configuration);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || 'Não foi possível analisar os arquivos.');
    return data;
  }

  async function convertToRis(files) {
    const response = await sendFiles('/api/convert', files, {});
    if (!response.ok) throw new Error((await response.json().catch(() => ({}))).error || 'Não foi possível converter os arquivos.');
    return {
      blob: await response.blob(),
      filename: /filename="([^"]+)"/.exec(response.headers.get('Content-Disposition') || '')?.[1] || 'referencias_convertidas.ris',
      records: response.headers.get('X-Registros') || '0',
      warnings: decodeURIComponent(response.headers.get('X-Avisos') || ''),
    };
  }

  // ==========================================================================
  // Resultados: ordenação, filtro dos cartões e exportações
  // ==========================================================================

  function bindResults() {
    const container = document.querySelector('.article-cards');
    const cards = () => [...container.querySelectorAll('.article-card')];
    const sortSelect = $('sort-cards');
    const filterSelect = $('filter-cards');
    const directionButton = $('sort-direction');
    let direction = 1;  // 1 = crescente / A–Z, -1 = decrescente / Z–A

    const yearOf = card => {
      const year = Number((card.dataset.year || '').match(/\d{4}/)?.[0]);
      return Number.isFinite(year) ? year : null;
    };

    function compare(criterion, a, b) {
      if (criterion === 'year') {
        const [yearA, yearB] = [yearOf(a), yearOf(b)];
        if (yearA === null || yearB === null) return yearA === yearB ? 0 : (yearA === null ? 1 : -1);  // sem ano: sempre no fim
        return direction * (yearA - yearB);
      }
      return direction * a.dataset[criterion].localeCompare(b.dataset[criterion], 'pt-BR', {numeric: true, sensitivity: 'base'});
    }

    function sortCards() {
      const isYear = sortSelect.value === 'year';
      directionButton.textContent = direction === 1 ? (isYear ? 'Crescente ↑' : 'A–Z ↑') : (isYear ? 'Decrescente ↓' : 'Z–A ↓');
      cards().sort((a, b) => compare(sortSelect.value, a, b)).forEach(card => container.append(card));
    }

    sortSelect.addEventListener('change', sortCards);
    directionButton.addEventListener('click', () => { direction *= -1; sortCards(); });
    filterSelect.addEventListener('change', () => {
      const filter = filterSelect.value;  // all | included | excluded (classes dos cartões)
      cards().forEach(card => { card.hidden = filter !== 'all' && !card.classList.contains(filter); });
    });

    $('new-analysis').addEventListener('click', event => {
      event.preventDefault();
      if (history.state?.view === 'results') history.back(); else showView('upload');
    });
    document.querySelectorAll('[data-export]').forEach(button => button.addEventListener('click', () => download(button.dataset.export, button)));
  }

  function saveBlob(blob, filename) {
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = filename;
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 10000);
  }

  async function download(kind, button) {
    setAlert('export-alert', '');
    button.disabled = true;
    try {
      const response = await fetch(`/api/export/${kind}`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({records: results.articles, duplicates: results.duplicates, prisma: results.prisma}),
      });
      if (!response.ok) throw new Error((await response.json().catch(() => ({}))).error || 'Não foi possível exportar o arquivo.');
      saveBlob(await response.blob(), /filename="([^"]+)"/.exec(response.headers.get('Content-Disposition') || '')?.[1] || 'triagem');
    } catch (error) {
      setAlert('export-alert', error.message);
    } finally {
      button.disabled = false;
    }
  }

  // ==========================================================================
  // Inicialização
  // ==========================================================================

  document.addEventListener('DOMContentLoaded', () => {
    document.body.insertAdjacentHTML('afterbegin', `<div id="view-upload">${uploadView()}</div><div id="view-results" hidden></div>${loadingView()}`);
    applyTheme(document.documentElement.dataset.theme);  // rótulo dos botões, que ainda não existiam no <head>
    document.addEventListener('click', event => {
      if (!event.target.closest('[data-theme-toggle]')) return;
      const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
      saveTheme(next);
      applyTheme(next);
    });
    bindUpload();
  });
})();
