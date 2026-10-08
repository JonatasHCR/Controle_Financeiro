/*
 * Painel: filtros, gráficos (Chart.js) e tabelas. Os números vêm prontos de
 * /api/painel — aqui só se desenha. O mesmo arquivo serve a impressão do PDF.
 */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };
  var CFG = JSON.parse($('config-painel').textContent);
  var D = JSON.parse($('dados-iniciais').textContent);

  // ---------- formatação ----------
  var nf0 = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 0 });
  var nf1 = new Intl.NumberFormat('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  var nf2 = new Intl.NumberFormat('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  function brl(v) { return v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' }); }
  function brlC(v) {
    var s = v < 0 ? '−' : '', a = Math.abs(v);
    return a >= 1e6 ? s + 'R$ ' + nf2.format(a / 1e6) + ' mi' : a >= 1e3 ? s + 'R$ ' + nf0.format(a / 1e3) + ' mil' : s + 'R$ ' + nf0.format(a);
  }
  function axC(v) { var a = Math.abs(v); return v === 0 ? '0' : a >= 1e6 ? nf1.format(v / 1e6).replace(',0', '') + ' mi' : a >= 1e3 ? nf0.format(v / 1e3) + ' mil' : nf0.format(v); }
  function pct(v) { return nf1.format(v * 100) + '%'; }
  var MES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
  var MESL = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro'];
  function mLab(m) { var p = m.split('-'); return MES[+p[1] - 1] + '/' + p[0].slice(2); }
  function dBR(s) { return s ? s.split('-').reverse().join('/') : '—'; }
  function css(n) { return getComputedStyle(document.documentElement).getPropertyValue(n).trim(); }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function plural(n, s, p) { return n + ' ' + (n === 1 ? s : p); }
  function sum(a, f) { return a.reduce(function (s, x) { return s + f(x); }, 0); }
  function cor(i) { return 'var(--c' + ((i % 8) + 1) + ')'; }
  function corHex(i) { return css('--c' + ((i % 8) + 1)); }
  var semAcento = function (t) { return t.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase(); };
  function origemTag(c) { return !c.receita ? ['warn', 'sem receita'] : !c.despesa ? ['info', 'sem despesa'] : null; }
  function tagHtml(c) {
    var t = origemTag(c);
    return (t ? ' <span class="pill ' + t[0] + '">' + t[1] + '</span>' : '') +
      (c.ativo === false ? ' <span class="pill">desativado</span>' : '');
  }

  // ---------- estado e URL ----------
  var st = { cli: [], coord: [], cr: [], modo: 'todas', mes: '', de: '', ate: '', nf: 'all', agrupar: 'cli' };
  var ABERTOS = {};
  var BUSCA = {};
  (function lerUrl() {
    var q = new URLSearchParams(location.search);
    st.cli = q.getAll('cliente'); st.coord = q.getAll('coordenador'); st.cr = q.getAll('cr');
    st.modo = q.get('modo') || 'todas'; st.mes = q.get('mes') || ''; st.de = q.get('de') || ''; st.ate = q.get('ate') || '';
    st.nf = q.get('nf') === 'open' ? 'open' : 'all'; st.agrupar = q.get('agrupar') || 'cli';
  })();
  function query() {
    var q = new URLSearchParams();
    st.cli.forEach(function (v) { q.append('cliente', v); });
    st.coord.forEach(function (v) { q.append('coordenador', v); });
    st.cr.forEach(function (v) { q.append('cr', v); });
    if (st.modo !== 'todas') q.set('modo', st.modo);
    if (st.modo === 'acum' || st.modo === 'mes') { if (st.mes) q.set('mes', st.mes); }
    if (st.modo === 'intervalo') { if (st.de) q.set('de', st.de); if (st.ate) q.set('ate', st.ate); }
    if (st.nf === 'open') q.set('nf', 'open');
    if (st.agrupar !== 'cli') q.set('agrupar', st.agrupar);
    return q.toString();
  }
  var pedido = 0;
  function atualizar() {
    var qs = query();
    if (!CFG.impressao) history.replaceState(null, '', location.pathname + (qs ? '?' + qs : ''));
    var meu = ++pedido;
    document.body.classList.add('carregando');
    fetch(CFG.api + (qs ? '?' + qs : ''), { headers: { Accept: 'application/json' }, credentials: 'same-origin' })
      .then(function (r) { if (r.status === 401 || r.redirected) { location.reload(); throw new Error('sessão'); } return r.json(); })
      .then(function (dados) { if (meu === pedido) { D = dados; render(); } })
      .catch(function () { if (meu === pedido) toast('Não foi possível atualizar o painel. Tente de novo.'); })
      .finally(function () { if (meu === pedido) document.body.classList.remove('carregando'); });
  }
  function sincronizarPeriodoComServidor() {
    // o servidor resolve "sem mês" para o mês mais recente da base; na impressão
    // a URL só tem o token, então NFs e agrupamento também vêm de lá
    var m = D.meta;
    st.modo = m.modo; if (m.mes) st.mes = m.mes; if (m.de) st.de = m.de; if (m.ate) st.ate = m.ate;
    if (m.estado) { st.nf = m.estado.nf; st.agrupar = m.estado.agrupar; }
  }

  // ---------- seleção múltipla com busca ----------
  function filtrarBusca(b) {
    var q = semAcento(b.value.trim()), n = 0, pop = b.closest('.pop');
    pop.querySelectorAll('.lista label').forEach(function (l) { var ok = semAcento(l.textContent).indexOf(q) >= 0; l.hidden = !ok; if (ok) n++; });
    var v = pop.querySelector('.nada');
    if (!n) { if (!v) { v = document.createElement('p'); v.className = 'nada note'; v.style.padding = '8px'; pop.querySelector('.lista').after(v); } v.textContent = 'Nada encontrado para “' + b.value + '”.'; v.hidden = false; }
    else if (v) v.hidden = true;
  }
  function multi(el, itens, todos, nome) {
    var k = el.dataset.k, s = st[k], det = el.querySelector('details'), aberto = det && det.open;
    var foco = document.activeElement && document.activeElement.closest && document.activeElement.closest('.ms') === el ? document.activeElement : null;
    var fv = foco && foco.type === 'checkbox' ? foco.value : null, fb = foco && foco.classList.contains('busca');
    var resumo = !s.length ? todos : s.length === 1 ? nome(s[0]) : s.length + ' selecionados';
    el.innerHTML = '<details' + (aberto ? ' open' : '') + '><summary>' + esc(resumo) + (s.length > 1 ? '<span class="n">' + s.length + '</span>' : '') + '</summary><div class="pop">' +
      '<input class="busca" type="search" placeholder="Digite para buscar…" aria-label="Buscar"><div class="lista">' +
      itens.map(function (it) {
        return '<label><input type="checkbox" value="' + esc(it[0]) + '"' + (s.indexOf(it[0]) >= 0 ? ' checked' : '') + '>' + (it[3] ? '<span class="dot" style="background:' + it[3] + ';margin-top:5px"></span>' : '') + '<span>' + esc(it[1]) + (it[2] ? '<small>' + esc(it[2]) + '</small>' : '') + '</span></label>';
      }).join('') + '</div><div class="rod"><button type="button" data-acao="todos">Marcar todos</button><button type="button" data-acao="limpar">Limpar</button></div></div></details>';
    var bq = el.querySelector('.busca');
    if (BUSCA[k]) { bq.value = BUSCA[k]; filtrarBusca(bq); }
    if (fb) bq.focus();
    else if (fv != null) { var cb = Array.prototype.find.call(el.querySelectorAll('input[type=checkbox]'), function (i) { return i.value === fv; }); if (cb) cb.focus(); }
  }
  document.querySelectorAll('.ms').forEach(function (el) {
    var k = el.dataset.k;
    el.addEventListener('change', function (e) {
      if (e.target.type !== 'checkbox') return;
      var v = e.target.value;
      st[k] = e.target.checked ? st[k].concat([v]) : st[k].filter(function (x) { return x !== v; });
      atualizar();
    });
    el.addEventListener('input', function (e) { if (e.target.classList.contains('busca')) { BUSCA[k] = e.target.value; filtrarBusca(e.target); } });
    el.addEventListener('click', function (e) {
      var a = e.target.dataset && e.target.dataset.acao; if (!a) return;
      st[k] = a === 'limpar' ? [] : Array.prototype.map.call(el.querySelectorAll('.lista label:not([hidden]) input'), function (i) { return i.value; });
      atualizar();
    });
    el.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && e.target.classList.contains('busca')) {
        e.preventDefault();
        var vis = el.querySelectorAll('.lista label:not([hidden]) input');
        if (vis.length === 1) vis[0].click();
      }
    });
    el.addEventListener('toggle', function (e) {
      if (!e.target.open) return;
      document.querySelectorAll('.ms details[open]').forEach(function (d) { if (d !== e.target) d.open = false; });
      var b = e.target.querySelector('.busca'); if (b && document.activeElement !== b) b.focus();
    }, true);
  });
  document.addEventListener('click', function (e) { if (!e.target.closest('.ms')) document.querySelectorAll('.ms details[open]').forEach(function (d) { d.open = false; }); });
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    document.querySelectorAll('.ms details[open]').forEach(function (d) { d.open = false; d.querySelector('summary').focus(); });
    if (!$('modal').hidden) $('modal').hidden = true;
  });

  function syncFiltros() {
    var o = D.opcoes;
    st.cr = st.cr.filter(function (cr) { return o.contratos.some(function (c) { return c.cr === cr; }); });
    multi($('f-cli'), o.clientes.map(function (x) { return [x, x]; }), 'Todos os clientes', function (x) { return x; });
    multi($('f-coord'), o.coordenadores.map(function (x) { return [x, x]; }), 'Todos os coordenadores', function (x) { return x; });
    multi($('f-cr'), o.contratos.map(function (c) {
      var t = origemTag(c);
      return [c.cr, c.cr + ' · ' + c.nome, (t ? t[1] + ' · ' : '') + c.cliente + (c.coordenadores.length ? ' · ' + c.coordenadores.join(' / ') : ''), cor(c.cor)];
    }), 'Todos (' + o.contratos.length + ')', function (cr) { var c = o.contratos.find(function (x) { return x.cr === cr; }); return c ? cr + ' · ' + c.nome : cr; });
    var m = D.meta;
    $('f-mes').innerHTML = m.meses_base.map(function (x) { return '<option value="' + x + '"' + (x === st.mes ? ' selected' : '') + '>' + mLab(x) + '</option>'; }).join('');
    var fd = $('f-de'), fa = $('f-ate');
    fd.value = st.de; fa.value = st.ate;
    fd.min = m.data_min || ''; fd.max = st.ate || ''; fa.min = st.de || m.data_min || ''; fa.removeAttribute('max');
    $('w-mes').hidden = !(st.modo === 'mes' || st.modo === 'acum');
    $('w-int').hidden = st.modo !== 'intervalo';
    $('l-mes').textContent = st.modo === 'mes' ? 'Mês' : 'Acumulado até o mês';
    document.querySelectorAll('[data-modo]').forEach(function (b) { b.setAttribute('aria-pressed', b.dataset.modo === st.modo); });
    document.querySelectorAll('[data-nf]').forEach(function (b) { b.setAttribute('aria-pressed', b.dataset.nf === st.nf); });
    var sel = D.contratos.map(function (c) { return c.cr; });
    $('legenda-c').innerHTML = o.contratos.map(function (c) {
      var busca = semAcento([c.cr, c.nome, c.cliente].concat(c.coordenadores).join(' '));
      return '<button type="button" data-cr="' + esc(c.cr) + '" data-busca="' + esc(busca) + '" aria-pressed="' + (st.cr.length === 1 && st.cr[0] === c.cr) + '"' + (sel.indexOf(c.cr) >= 0 ? '' : ' data-off') + '><span class="dot" style="background:' + cor(c.cor) + '"></span><span><b>' + esc(c.cr) + '</b> · ' + esc(c.nome) + tagHtml(c) + '</span></button>';
    }).join('');
    filtrarLista();
  }

  // A lista guarda o texto da busca entre um redesenho e outro.
  function filtrarLista() {
    var termo = semAcento($('busca-c').value.trim());
    var botoes = $('legenda-c').querySelectorAll('button[data-cr]');
    var vistos = 0;
    botoes.forEach(function (b) {
      b.hidden = !!termo && b.dataset.busca.indexOf(termo) < 0;
      if (!b.hidden) vistos++;
    });
    $('lista-c-n').textContent = termo ? vistos + ' de ' + botoes.length : '(' + botoes.length + ')';
    $('lista-c-vazia').hidden = vistos > 0;
  }
  $('busca-c').addEventListener('input', filtrarLista);
  $('busca-c').addEventListener('keydown', function (e) {
    if (e.key !== 'Enter') return;
    var unicos = $('legenda-c').querySelectorAll('button[data-cr]:not([hidden])');
    if (unicos.length === 1) { e.preventDefault(); soContrato(unicos[0].dataset.cr); }
  });
  $('legenda-c').addEventListener('click', function (e) { var b = e.target.closest('button[data-cr]'); if (b) soContrato(b.dataset.cr); });
  $('f-mes').addEventListener('change', function (e) { st.mes = e.target.value; atualizar(); });
  $('f-de').addEventListener('change', function (e) {
    var v = e.target.value;
    if (!v || (st.ate && v > st.ate) || (D.meta.data_min && v < D.meta.data_min)) {
      e.target.value = st.de;
      toast(st.ate && v > st.ate ? 'A data inicial não pode ser depois da data final.' : 'Não há dados antes de ' + dBR(D.meta.data_min) + '.');
      return;
    }
    st.de = v; atualizar();
  });
  $('f-ate').addEventListener('change', function (e) {
    var v = e.target.value;
    if (!v || (st.de && v < st.de)) { e.target.value = st.ate; toast('A data final não pode ser antes da data inicial.'); return; }
    st.ate = v; atualizar();
  });
  document.querySelectorAll('[data-modo]').forEach(function (b) {
    b.addEventListener('click', function () {
      st.modo = b.dataset.modo;
      if ((st.modo === 'mes' || st.modo === 'acum') && !st.mes) st.mes = D.meta.base_max;
      atualizar();
    });
  });
  document.querySelectorAll('[data-nf]').forEach(function (b) { b.addEventListener('click', function () { st.nf = b.dataset.nf; atualizar(); }); });
  document.querySelectorAll('[data-agrupar]').forEach(function (b) { b.addEventListener('click', function () { st.agrupar = b.dataset.agrupar; ABERTOS = {}; atualizar(); }); });
  $('bt-limpar').addEventListener('click', function () {
    Object.keys(BUSCA).forEach(function (k) { delete BUSCA[k]; });
    st = { cli: [], coord: [], cr: [], modo: 'todas', mes: '', de: '', ate: '', nf: 'all', agrupar: 'cli' };
    ABERTOS = {};
    atualizar();
  });
  function soContrato(cr) { st.cr = st.cr.length === 1 && st.cr[0] === cr ? [] : [cr]; atualizar(); }

  // ---------- aviso e janela ----------
  var toastT;
  function toast(msg) { var t = $('toast'); t.textContent = msg; t.hidden = false; clearTimeout(toastT); toastT = setTimeout(function () { t.hidden = true; }, 3800); }
  function abrirModal(titulo, html) { $('modal-t').textContent = titulo; $('modal-c').innerHTML = html; $('modal').hidden = false; $('modal-x').focus(); }
  function fecharModal() { $('modal').hidden = true; }
  $('modal-x').addEventListener('click', fecharModal);
  $('modal').addEventListener('click', function (e) { if (e.target.id === 'modal') fecharModal(); });

  // ---------- Chart.js ----------
  var charts = {};
  function chart(id, cfg) { if (charts[id]) charts[id].destroy(); charts[id] = new Chart($(id), cfg); }
  function limparChart(id) { if (charts[id]) { charts[id].destroy(); delete charts[id]; } }
  // gráfico sem dado: some o eixo vazio e entra uma frase dizendo por quê
  function semDados(id, vazio, msg) {
    var caixa = $(id).parentNode, aviso = caixa.nextElementSibling;
    if (!aviso || !aviso.classList.contains('sem-dados')) { aviso = document.createElement('p'); aviso.className = 'empty sem-dados'; caixa.after(aviso); }
    aviso.textContent = msg; aviso.hidden = !vazio; caixa.hidden = vazio;
    if (vazio) limparChart(id);
    return vazio;
  }
  function tip() { return { backgroundColor: css('--tip-bg'), titleColor: css('--tip-ink'), bodyColor: css('--tip-ink'), footerColor: css('--tip-ink'), padding: 10, cornerRadius: 6, titleFont: { weight: '600' }, boxPadding: 4 }; }
  function eixos() {
    Chart.defaults.font.family = css('--f-body'); Chart.defaults.font.size = 11; Chart.defaults.color = css('--ink-2');
    if (CFG.impressao) Chart.defaults.animation = false;
    return { grid: css('--grid'), axis: css('--ink-3') };
  }

  // ---------- ficha ----------
  function anel(f, corA, s, l) {
    var r = 42, C = 2 * Math.PI * r, o = C * (1 - Math.max(0, Math.min(1, f)));
    return '<div class="anel"><svg viewBox="0 0 104 104" role="img" aria-label="' + l + ' ' + pct(f) + '"><circle cx="52" cy="52" r="' + r + '" fill="none" stroke="var(--surface-2)" stroke-width="10"/><circle cx="52" cy="52" r="' + r + '" fill="none" stroke="' + corA + '" stroke-width="10" stroke-dasharray="' + C.toFixed(1) + '" stroke-dashoffset="' + o.toFixed(1) + '" transform="rotate(-90 52 52)" stroke-linecap="round"/><text x="52" y="58" text-anchor="middle" style="font:700 19px var(--f-disp);fill:var(--ink)">' + nf0.format(f * 100) + '%</text></svg><b style="font-size:13px;font-family:var(--f-body)">' + l + '</b><span>' + s + '</span></div>';
  }
  function ficha() {
    var cs = D.contratos, one = cs.length === 1, c0 = cs[0], F = D.ficha, R = D.meta.rotulos;
    var k = D.meta.corte, bdTxt = MESL[+k.slice(5) - 1] + ' de ' + k.slice(0, 4), corpo;
    if (one && !c0.receita) {
      corpo = '<div class="aviso">Este centro de custo existe no Controle de Despesa, mas não tem contrato no Gerenciamento de Receita. O Controle Financeiro mostra os custos com <b>receita zero</b>, por isso o resultado fica negativo. Valor, cliente e prazos aparecem quando o contrato for cadastrado na Receita.</div>';
    } else if (one) {
      var f = function (l, v, cl) { return '<div><dt>' + l + '</dt><dd' + (cl ? ' class="' + cl + '"' : '') + '>' + v + '</dd></div>'; };
      corpo = '<dl class="campos">' + f('Data-base', bdTxt) + f('Início', dBR(c0.inicio)) + f('Fim da execução', dBR(c0.fim_execucao)) +
        f('Fim da vigência', dBR(c0.fim_vigencia), c0.fim_vigencia && c0.fim_execucao && c0.fim_vigencia < c0.fim_execucao ? 'risco' : '') +
        f('Valor inicial', brlC(c0.valor_inicial)) + f('Aditivos', (c0.aditivos > 0 ? '+' : '') + brlC(c0.aditivos)) + f('Valor atual', brlC(c0.valor)) + f('Horizonte da projeção', dBR(c0.horizonte)) + '</dl>';
    } else {
      corpo = '<div class="tbl-wrap"><table class="mini"><thead><tr><th>Contrato</th><th>Início</th><th>Fim execução</th><th>Fim vigência</th><th class="r">Valor inicial</th><th class="r">Aditivos</th><th class="r">Valor atual</th></tr></thead><tbody>' +
        cs.map(function (c) {
          return '<tr><td><span class="cid"><span class="dot" style="background:' + cor(c.cor) + '"></span><b>' + esc(c.cr) + '</b> ' + esc(c.nome) + tagHtml(c) + '</span></td><td>' + dBR(c.inicio) + '</td><td>' + dBR(c.fim_execucao) + '</td><td' +
            (c.fim_vigencia && c.fim_execucao && c.fim_vigencia < c.fim_execucao ? ' style="color:var(--neg);font-weight:600"' : '') + '>' + dBR(c.fim_vigencia) + '</td><td class="r">' + brlC(c.valor_inicial) + '</td><td class="r">' + (c.aditivos ? '+' + brlC(c.aditivos) : '—') + '</td><td class="r">' + brlC(c.valor) + '</td></tr>';
        }).join('') + '</tbody><tfoot><tr><td colspan="4">Total · data-base ' + bdTxt + '</td><td class="r">' + brlC(sum(cs, function (c) { return c.valor_inicial; })) + '</td><td class="r">+' + brlC(sum(cs, function (c) { return c.aditivos; })) + '</td><td class="r">' + brlC(F.valor) + '</td></tr></tfoot></table></div>';
    }
    var sub = one ? esc(c0.cliente) + (c0.coordenadores.length ? ' · ' + esc(c0.coordenadores.join(' / ')) : '') + (c0.receita ? ' · <span class="pill ' + (c0.status === 'CONCLUÍDO' ? 'neu' : 'ok') + '">' + c0.status.toLowerCase() + '</span>' : '') + tagHtml(c0)
      : 'Cliente: ' + esc(R.cliente) + ' · Coordenador: ' + esc(R.coordenador);
    $('ficha').classList.toggle('multi', !one);
    $('ficha').innerHTML = '<div><div class="ficha-t"><span class="eb">' + (one ? 'Contrato ' + esc(c0.numero || '—') : 'Carteira selecionada') + '</span><h2>' + esc(one ? c0.cr + ' · ' + c0.descricao : (R.titulo || plural(cs.length, 'contrato', 'contratos'))) + '</h2><p>' + sub + '</p></div>' + corpo + '</div>' +
      '<div class="aneis">' + anel(F.exec, 'var(--accent)', brlC(F.fat) + ' de ' + brlC(F.valor), 'Execução financeira') + anel(F.tempo, 'var(--ink-3)', F.tempo_txt, 'Tempo transcorrido') + '</div>';
  }

  // ---------- cascata ----------
  function cascata() {
    var g = eixos(), K = D.cascata;
    $('sub-cascata').textContent = D.meta.periodo + ' · contrato atual ' + brlC(K.valor) + ' · faturado ' + pct(K.valor ? K.fat / K.valor : 0) + ' do contrato';
    var srt = function (a, b) { return a - b; };
    var passos = [
      ['Receita bruta', [0, K.fat], css('--ink-3')], ['Tributos ' + K.tributos_txt, [K.liq, K.fat], css('--neg') + 'bb'],
      ['Receita líquida', [0, K.liq], css('--rev')], ['Custo realizado', [K.liq - K.cus, K.liq].sort(srt), css('--cost')],
      ['Resultado atual', [0, K.res].sort(srt), K.res >= 0 ? css('--pos') : css('--neg')]];
    var vals = [K.fat, -K.trib, K.liq, -K.cus, K.res];
    var topo = [K.fat, K.liq, K.liq, K.res];
    var conector = { id: 'con', afterDatasetsDraw: function (ch) {
      var c = ch.ctx, m = ch.getDatasetMeta(0), y = ch.scales.y; c.save(); c.strokeStyle = css('--ink-3'); c.setLineDash([3, 3]); c.lineWidth = 1;
      for (var i = 0; i < m.data.length - 1; i++) { var a = m.data[i], b = m.data[i + 1], yy = y.getPixelForValue(topo[i]); c.beginPath(); c.moveTo(a.x + a.width / 2, yy); c.lineTo(b.x - b.width / 2, yy); c.stroke(); }
      c.setLineDash([]); c.fillStyle = css('--ink'); c.font = '700 11.5px ' + css('--f-disp'); c.textAlign = 'center';
      m.data.forEach(function (b, i) { var v = vals[i]; c.fillText((v < 0 ? '−' : '') + brlC(Math.abs(v)).replace('R$ ', ''), b.x, Math.min(b.y, b.base) - 6); }); c.restore();
    } };
    chart('c-cascata', { type: 'bar', data: { labels: passos.map(function (s) { return s[0]; }), datasets: [{ data: passos.map(function (s) { return s[1]; }), backgroundColor: passos.map(function (s) { return s[2]; }), borderRadius: 3, borderSkipped: false, barPercentage: 0.62 }] }, plugins: [conector],
      options: { maintainAspectRatio: false, animation: false, layout: { padding: { top: 18 } }, plugins: { legend: { display: false }, tooltip: Object.assign(tip(), { callbacks: { label: function (c) { return ' ' + brl(vals[c.dataIndex]); } } }) },
        scales: { x: { grid: { display: false }, border: { color: g.axis }, ticks: { maxRotation: 0, autoSkip: false, font: { size: 10.5 }, callback: function (v) { var l = this.getLabelForValue(v), p = l.split(' '); return p.length > 2 ? [p.slice(0, 2).join(' '), p.slice(2).join(' ')] : l; } } },
          y: { grid: { color: function (c) { return c.tick.value === 0 ? g.axis : g.grid; } }, border: { display: false }, ticks: { callback: axC, maxTicksLimit: 5 } } } } });
    var L = [['', 'Receita bruta', K.mes ? 'NFs do BM' : pct(K.valor ? K.fat / K.valor : 0) + ' do contrato', K.fat], ['−', 'Tributos · ' + K.tributos_txt, 'retidos na NF', -K.trib], ['=', 'Receita líquida', 'bruta − tributos', K.liq],
      ['−', 'Custo realizado', K.liq ? pct(K.cus / K.liq) + ' da receita líquida' : '—', -K.cus], ['=', 'Resultado atual', K.liq ? pct(K.res / K.liq) + ' da receita líquida' : '—', K.res]];
    $('razao').innerHTML = L.map(function (x, i) {
      var corV = i === 2 ? 'var(--rev)' : i === 3 ? 'var(--cost)' : i === 4 ? (x[3] >= 0 ? 'var(--pos)' : 'var(--neg)') : 'var(--ink)';
      return '<div class="' + (i === 4 ? 'tot' : '') + '"><span class="op">' + x[0] + '</span><span class="l">' + x[1] + '<small>' + x[2] + '</small></span><span class="v" style="color:' + corV + '">' + (i === 4 && x[3] > 0 ? '+' : '') + brlC(x[3]) + '</span></div>';
    }).join('');
  }

  // ---------- resumo agrupado ----------
  function grupo() {
    var G = D.por_grupo, pre = document.body.classList.contains('pre'), porCr = G.agrupar === 'cr';
    $('h-grupo').textContent = 'Resumo por ' + G.singular;
    $('sub-grupo').textContent = D.meta.periodo + ' · ' + plural(G.linhas.length, G.singular, G.plural) + ' · ' + plural(D.contratos.length, 'contrato', 'contratos');
    document.querySelectorAll('[data-agrupar]').forEach(function (b) { b.setAttribute('aria-pressed', String(b.dataset.agrupar === G.agrupar)); });
    var taxaTxt = function (t) { return nf0.format(t * 100) + '%'; };
    var faixa = function (ts) { return ts.length === 1 ? taxaTxt(ts[0]) : nf0.format(ts[0] * 100) + '–' + taxaTxt(ts[ts.length - 1]); };
    var v = function (x) { return '<span class="' + (x < 0 ? 'neg-t' : '') + '">' + brl(x) + '</span>'; };
    var lucro = function (o) {
      if (!o.bruta) return '<span class="note">—</span>';
      var p = o.res / o.bruta, w = Math.min(1, Math.abs(p) / 0.5) * 100;
      return '<span class="lucro"><span class="' + (p < 0 ? 'neg-t' : '') + '">' + pct(p) + '</span><span class="barra"><i style="width:' + w + '%;background:' + (p < 0 ? 'var(--neg)' : 'var(--pos)') + '"></i></span></span>';
    };
    var cels = function (o, taxa) {
      return '<td class="r">' + brl(o.bruta) + '</td><td class="r">' + brl(o.liq) + '</td><td class="r">' + v(0 - o.desp) + '</td><td class="r">' + v(0 - o.pis) + '</td><td class="r">' + v(0 - o.adm) + (taxa ? '<span class="taxa">' + taxa + '</span>' : '') + '</td><td class="r" style="font-weight:700">' + v(o.res) + '</td><td class="r">' + lucro(o) + '</td>';
    };
    var det = function (c) { return '<b>' + esc(c.cr) + '</b> ' + esc(c.nome) + ' · ' + esc(G.agrupar === 'cli' ? c.coordenadores.join(' / ') || 'sem coordenador' : c.cliente); };
    $('tb-grupo').innerHTML = G.linhas.length ? '<table><thead><tr><th>' + esc(G.titulo) + '</th><th class="r">Receita bruta</th><th class="r">Receita líquida</th><th class="r">Despesas</th><th class="r">PIS e COFINS</th><th class="r">ADM</th><th class="r">Resultado</th><th class="r">% Lucro</th></tr></thead><tbody>' +
      G.linhas.map(function (g) {
        // grupo com um contrato só não abre: a linha do contrato repetiria a do grupo
        var abre = g.contratos.length > 1, ab = abre && (pre || ABERTOS[g.nome]);
        return '<tr class="' + (abre ? 'grp' : 'um') + '"' + (abre ? ' tabindex="0" role="button" data-g="' + esc(g.nome) + '" aria-expanded="' + !!ab + '"' : '') + '><td><span class="seta">' + (abre ? '▸' : '') + '</span>' + esc(g.nome) +
          (porCr ? '' : ' <span class="note" style="font-weight:400">· ' + plural(g.contratos.length, 'contrato', 'contratos') + '</span>') + '</td>' + cels(g, faixa(g.taxas)) + '</tr>' +
          (ab ? g.contratos.map(function (c) { return '<tr class="filho"><td><span class="cid"><span class="dot" style="background:' + cor(c.cor) + '"></span><span>' + det(c) + '</span></span></td>' + cels(c, taxaTxt(c.taxa)) + '</tr>'; }).join('') : '');
      }).join('') + '</tbody><tfoot><tr><td>Total</td>' + cels(G.total, '') + '</tr></tfoot></table>' : '<p class="empty">Nenhum contrato no filtro.</p>';
    $('nota-grupo').textContent = 'Receita líquida = bruta − tributos retidos na NF. PIS e COFINS = ' + nf2.format(G.pis_cofins * 100) + '% da bruta − crédito sobre as despesas de naturezas marcadas na Configuração. ADM = taxa adm. de cada contrato × bruta. Resultado = líquida − despesas − PIS/COFINS − ADM.' +
      (G.agrupar === 'coord' ? ' Contrato com mais de um coordenador entra em cada grupo; o total conta o contrato uma vez.' : '') + (pre ? '' : ' Clique num grupo para ver os contratos.');
  }
  function alternarGrupo(tr) { ABERTOS[tr.dataset.g] = !ABERTOS[tr.dataset.g]; grupo(); var n = $('tb-grupo').querySelector('tr.grp[data-g="' + CSS.escape(tr.dataset.g) + '"]'); if (n) n.focus(); }
  $('tb-grupo').addEventListener('click', function (e) { var r = e.target.closest('tr.grp'); if (r && !document.body.classList.contains('pre')) alternarGrupo(r); });
  $('tb-grupo').addEventListener('keydown', function (e) { var r = e.target.closest('tr.grp'); if (r && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); alternarGrupo(r); } });

  // ---------- recebimento ----------
  function receb() {
    var g = eixos(), R = D.recebimento;
    $('sub-receb').textContent = 'Valor bruto das NFs emitidas · ' + D.meta.periodo + ' · status de pagamento atual';
    $('rec-tot').innerHTML = '<b class="num">' + brlC(R.total) + '</b><span>' + plural(R.n, 'NF emitida', 'NFs emitidas') + '</span><span><b style="font-size:16px;color:var(--paid)">' + pct(R.total ? R.pago / R.total : 0) + '</b> pago · <b style="font-size:16px;color:var(--warn-ink)">' + pct(R.total ? R.aberto / R.total : 0) + '</b> a receber (' + brlC(R.aberto) + ')</span>';
    var linhas = R.por_contrato;
    $('rec-box').style.height = Math.max(90, linhas.length * 38 + 40) + 'px';
    chart('c-receb', { type: 'bar', data: { labels: linhas.map(function (x) { return x.cr + ' · ' + x.nome; }), datasets: [
      { label: 'Pago', data: linhas.map(function (x) { return x.pago; }), backgroundColor: css('--paid'), borderRadius: { topLeft: 3, bottomLeft: 3 }, borderSkipped: false, barPercentage: 0.62, stack: 's' },
      { label: 'Não pago', data: linhas.map(function (x) { return x.aberto; }), backgroundColor: css('--open'), borderRadius: { topRight: 3, bottomRight: 3 }, borderSkipped: false, barPercentage: 0.62, stack: 's' }] },
      options: { indexAxis: 'y', maintainAspectRatio: false, animation: false, onClick: function (e, els) { if (els.length) soContrato(linhas[els[0].index].cr); },
        plugins: { legend: { display: false }, tooltip: Object.assign(tip(), { callbacks: { label: function (c) { var x = linhas[c.dataIndex], t = x.pago + x.aberto; return ' ' + c.dataset.label + ': ' + brl(c.parsed.x) + ' (' + pct(t ? c.parsed.x / t : 0) + ')'; } } }) },
        scales: { x: { stacked: true, grid: { color: g.grid }, border: { display: false }, ticks: { callback: axC, maxTicksLimit: 6 } }, y: { stacked: true, grid: { display: false }, border: { color: g.axis } } } } });
    $('rc-open').innerHTML = R.abertas.length ? R.abertas.map(function (gr) {
      return '<div class="ab-g" data-cr="' + esc(gr.cr) + '" tabindex="0" role="button" aria-label="Filtrar ' + esc(gr.cr) + '"><div class="ab-h"><b><span class="dot" style="background:' + cor(gr.cor) + '"></span>' + esc(gr.cr) + ' · ' + esc(gr.nome) + '</b><span class="num" style="font-weight:600">' + brl(gr.total) + '</span></div><div class="chips">' +
        gr.nfs.map(function (n) { return '<span class="chip ' + (n.dias > 60 ? 'old' : '') + '">BM ' + (n.bm || '—') + ' · NF ' + esc(n.nf) + ' · <b>' + brlC(n.valor) + '</b> · ' + n.dias + ' d</span>'; }).join('') + '</div></div>';
    }).join('') : '<p class="note">Todas as NFs do período estão pagas.</p>';
  }
  $('rc-open').addEventListener('click', function (e) { var g = e.target.closest('.ab-g'); if (g) soContrato(g.dataset.cr); });
  $('rc-open').addEventListener('keydown', function (e) { var g = e.target.closest('.ab-g'); if (g && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); soContrato(g.dataset.cr); } });

  // ---------- mensal ----------
  function mensal() {
    var g = eixos(), M = D.mensal, alfa = function (h, on) { return on ? h : h + '55'; };
    chart('c-mensal', { type: 'bar', data: { labels: M.rotulos, datasets: [
      { label: 'Receita líquida', data: M.rl, backgroundColor: M.destaque.map(function (o) { return alfa(css('--rev'), o); }), borderRadius: { topLeft: 3, topRight: 3 }, barPercentage: 0.9, categoryPercentage: 0.72, order: 2 },
      { label: 'Custo realizado', data: M.cu, backgroundColor: M.destaque.map(function (o) { return alfa(css('--cost'), o); }), borderRadius: { topLeft: 3, topRight: 3 }, barPercentage: 0.9, categoryPercentage: 0.72, order: 2 },
      { label: 'Ganho', type: 'line', data: M.g, borderColor: css('--ink'), backgroundColor: css('--ink'), borderWidth: 2, pointRadius: 2.5, pointHoverRadius: 5, pointBorderColor: css('--surface'), tension: 0, order: 1 }] },
      options: { maintainAspectRatio: false, animation: false, interaction: { mode: 'index', intersect: false },
        onClick: function (e, els) { if (els.length && !CFG.impressao) { st.mes = M.meses[els[0].index]; st.modo = 'mes'; atualizar(); } },
        onHover: function (e, els) { e.native.target.style.cursor = els.length ? 'pointer' : 'default'; },
        plugins: { legend: { display: false }, tooltip: Object.assign(tip(), { callbacks: { label: function (c) { return ' ' + c.dataset.label + ': ' + brl(c.parsed.y); }, footer: function () { return 'Clique para filtrar este mês'; } } }) },
        scales: { x: { grid: { display: false }, border: { color: g.axis }, ticks: { autoSkip: true, maxRotation: 0 } }, y: { grid: { color: function (c) { return c.tick.value === 0 ? g.axis : g.grid; } }, border: { display: false }, ticks: { callback: axC, maxTicksLimit: 6 } } } } });
  }

  // ---------- execução ----------
  function execucao() {
    $('exec').innerHTML = D.execucao.map(function (e) {
      return '<div class="prog-row" data-cr="' + esc(e.cr) + '" tabindex="0" role="button" aria-label="' + esc(e.cr + ' ' + e.nome) + ': faturado ' + pct(e.fc) + ', tempo ' + pct(e.tp) + '">' +
        '<div class="prog-top"><b><span class="dot" style="background:' + cor(e.cor) + '"></span>' + esc(e.cr) + ' · ' + esc(e.nome) + '</b><span class="pill ' + e.classe + '">' + e.texto + '</span></div>' +
        '<div class="track"><div class="fill" style="width:' + Math.min(100, e.fc * 100) + '%;background:' + cor(e.cor) + '"></div><div class="tick" style="left:' + e.tp * 100 + '%"></div></div>' +
        '<div class="prog-foot"><span class="num">Faturado <b style="color:var(--ink)">' + pct(e.fc) + '</b> · tempo <b style="color:var(--ink)">' + pct(e.tp) + '</b> · ' + (e.gap < 0 ? 'faltam ' + brlC(-e.gap * e.valor) : brlC(e.gap * e.valor) + ' à frente') + '</span><span class="num">' + brlC(e.fat) + ' de ' + brlC(e.valor) + '</span></div>' +
        (!e.despesa ? '<div class="prog-foot"><span>Sem despesa no Controle de Despesa: custo considerado zero</span><span class="pill info">sem despesa</span></div>' : '') + '</div>';
    }).join('') + (D.sem_receita.length ? '<p class="note">' + D.sem_receita.map(function (c) { return '<b>' + esc(c) + '</b>'; }).join(', ') + ': sem contrato na Receita, sem valor nem prazo. Não entra nesta comparação.</p>' : '') +
      (!D.execucao.length && !D.sem_receita.length ? '<p class="empty">Nenhum contrato no filtro.</p>' : '');
  }
  $('exec').addEventListener('click', function (e) { var r = e.target.closest('.prog-row'); if (r) soContrato(r.dataset.cr); });
  $('exec').addEventListener('keydown', function (e) { var r = e.target.closest('.prog-row'); if (r && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); soContrato(r.dataset.cr); } });

  // ---------- itens ----------
  function itens() {
    var g = eixos(), varios = D.contratos.length > 1;
    var lbl = function (x) { return (varios ? x.cr + ' · ' : '') + (x.d.length > 34 ? x.d.slice(0, 33) + '…' : x.d); };
    var top = D.itens;
    var semItens = semDados('c-itens', !top.length, 'Nenhuma despesa no período para os contratos filtrados.');
    if (!semItens) chart('c-itens', { type: 'bar', data: { labels: top.map(lbl), datasets: [{ data: top.map(function (x) { return x.v; }), backgroundColor: top.map(function (x) { return varios ? corHex(x.cor) : css('--cost'); }), borderRadius: { topRight: 3, bottomRight: 3 }, barPercentage: 0.7 }] },
      options: { indexAxis: 'y', maintainAspectRatio: false, animation: false, plugins: { legend: { display: false }, tooltip: Object.assign(tip(), { callbacks: { title: function (i) { var x = top[i[0].dataIndex]; return x.cr + ' · ' + x.d; }, label: function (c) { return ' Custo realizado: ' + brl(c.parsed.x); } } }) },
        scales: { x: { grid: { color: g.grid }, border: { display: false }, ticks: { callback: axC, maxTicksLimit: 6 } }, y: { grid: { display: false }, border: { color: g.axis } } } } });
  }

  // ---------- tabelas ----------
  function tabelas() {
    var P = D.pendencias;
    $('tb-conc').innerHTML = P.length ? '<table><thead><tr><th>Prazo</th><th>Contrato</th><th>Assunto</th><th>Prioridade</th></tr></thead><tbody>' + P.map(function (r) {
      var cls = r.dias == null ? 'neu' : r.dias < 0 ? 'crit' : r.dias <= 15 ? 'warn' : 'neu';
      return '<tr><td class="num"><span class="pill ' + cls + '">' + dBR(r.prazo) + (r.dias == null ? '' : ' · ' + (r.dias < 0 ? 'vencido' : r.dias + ' d')) + '</span></td><td><span class="cid"><span class="dot" style="background:' + cor(r.cor) + '"></span>' + esc(r.cr) + '</span></td><td>' + esc(r.assunto) + '</td><td><span class="pill ' + (r.prioridade === 'ALTA' ? 'crit' : r.prioridade === 'MÉDIA' ? 'warn' : 'neu') + '">' + esc(r.prioridade) + '</span></td></tr>';
    }).join('') + '</tbody></table>' : '<p class="empty">Nenhuma pendência em aberto.</p>';

    var PL = D.pleitos, adt = PL.lista;
    var tt = function (l, v, s, c) { return '<div class="bloco ' + (c || '') + '"><span class="l">' + l + '</span><span class="v">' + v + '</span><span class="s">' + s + '</span></div>'; };
    $('dtiles').innerHTML = tt('Valor potencial', brlC(PL.potencial), plural(adt.length, 'evento', 'eventos')) + tt('Valor aprovado', brlC(PL.aprovado), 'validado ou feito', PL.aprovado > 0 ? 'pos' : '') + tt('% aprovado', PL.potencial ? pct(PL.aprovado / PL.potencial) : '—', PL.potencial ? brlC(PL.potencial - PL.aprovado) + ' pendentes' : 'sem valores');
    var cls = function (s) { return /VALID|FEITO/.test(s) ? 'ok' : /ANÁLISE/.test(s) ? 'warn' : 'neu'; };
    $('tb-adt').innerHTML = adt.length ? '<table><thead><tr><th>Contrato</th><th>Evento</th><th>Data-base</th><th>Status</th><th class="r">Valor bruto</th></tr></thead><tbody>' + adt.map(function (a) {
      return '<tr><td><span class="cid"><span class="dot" style="background:' + cor(a.cor) + '"></span>' + esc(a.cr) + '</span></td><td>' + esc(a.descricao) + '<div class="note">' + esc(a.tipo.toLowerCase()) + '</div></td><td>' + esc(a.data_base) + '</td><td><span class="pill ' + cls(a.status) + '">' + esc(a.status.toLowerCase()) + '</span></td><td class="r num">' + (a.valor ? nf2.format(a.valor) : '—') + '</td></tr>';
    }).join('') + '</tbody></table>' : '<p class="empty">Nenhum evento registrado para o filtro.</p>';

    var N = D.nfs, rows = st.nf === 'open' ? N.lista.filter(function (n) { return !n.paga; }) : N.lista;
    var lim = document.body.classList.contains('pre') ? rows : rows.slice(0, 60);
    var per = D.meta.periodo.replace(/^./, function (c) { return c.toUpperCase(); });
    $('sub-nf').textContent = per + ' · ' + plural(rows.length, 'NF', 'NFs') + (st.nf === 'open' ? ' não pagas' : '') + (lim.length < rows.length ? ' · exibindo as ' + lim.length + ' mais recentes' : '');
    $('nf-sum').innerHTML = '<span>A receber: <b class="num">' + brl(N.a_receber) + '</b> · ' + plural(N.n_a_receber, 'NF', 'NFs') + '</span>' + (st.nf === 'open' ? '' : '<span>Pago: <b class="num">' + brl(N.pago) + '</b> · ' + plural(N.n_pago, 'NF', 'NFs') + '</span>');
    document.querySelectorAll('[data-nf]').forEach(function (b) { b.setAttribute('aria-pressed', String(b.dataset.nf === st.nf)); });
    $('tb-nf').innerHTML = rows.length ? '<table><thead><tr><th>Contrato</th><th class="r">BM</th><th>Data-base</th><th class="r">NF</th><th>Emissão</th><th>Tipo</th><th>Status</th><th class="r">Valor bruto</th></tr></thead><tbody>' + lim.map(function (n) {
      return '<tr><td><span class="cid"><span class="dot" style="background:' + cor(n.cor) + '"></span>' + esc(n.cr) + '</span></td><td class="r">' + (n.bm || '—') + '</td><td>' + esc(n.data_base) + '</td><td class="r">' + esc(n.numero) + '</td><td>' + esc(n.emitida_em) + '</td><td>' + (n.tipo === 'reajuste' ? 'Reajuste' : 'Medição') + '</td><td>' + (n.paga ? '<span class="pill ok">paga</span>' : '<span class="pill warn">não paga</span>') + '</td><td class="r">' + nf2.format(n.valor) + '</td></tr>';
    }).join('') + '</tbody><tfoot><tr><td colspan="7">Total</td><td class="r">' + nf2.format(sum(rows, function (n) { return n.valor; })) + '</td></tr></tfoot></table>' : '<p class="empty">Nenhuma NF para esse filtro.</p>';
  }

  // ---------- relatório ----------
  if ($('bt-pre')) $('bt-pre').addEventListener('click', function () {
    var on = document.body.classList.toggle('pre');
    $('bt-pre').textContent = on ? 'Voltar ao painel' : 'Pré-visualizar relatório';
    render();
  });
  if ($('bt-pdf')) $('bt-pdf').addEventListener('click', function () {
    if (D.vazio) { toast('Nenhum contrato no filtro.'); return; }
    var R = D.meta.rotulos, url = CFG.pdf + (query() ? '?' + query() : '');
    abrirModal('Gerar relatório em PDF', '<p class="note" style="font-size:13px;color:var(--ink-2)">O sistema monta o PDF no servidor com os filtros atuais e baixa o arquivo. Não é preciso usar a impressão do navegador.</p>' +
      '<dl class="campos" style="grid-template-columns:repeat(2,minmax(0,1fr))"><div><dt>Cliente</dt><dd style="font-size:13.5px">' + esc(R.cliente) + '</dd></div><div><dt>Coordenador</dt><dd style="font-size:13.5px">' + esc(R.coordenador) + '</dd></div><div><dt>Contratos</dt><dd style="font-size:13.5px">' + esc(R.contratos) + '</dd></div><div><dt>Período</dt><dd style="font-size:13.5px">' + esc(D.meta.periodo) + '</dd></div><div><dt>NFs</dt><dd style=\"font-size:13.5px\">' + esc(R.nf) + '</dd></div><div><dt>Resumo agrupado por</dt><dd style=\"font-size:13.5px\">' + esc(R.agrupar) + '</dd></div></dl>' +
      '<div id="pdf-passos"></div><div class="cfg-bar"><span></span><div class="acoes"><button type="button" class="btn" id="pdf-cancel">Cancelar</button><button type="button" class="btn prim" id="pdf-go">Gerar PDF</button></div></div>');
    $('pdf-cancel').addEventListener('click', fecharModal);
    var pronto = false;
    $('pdf-go').addEventListener('click', function () {
      if (pronto) { fecharModal(); return; }
      var bt = $('pdf-go'); bt.disabled = true;
      $('pdf-passos').innerHTML = '<ul class="passos"><li class="run"><i></i>Gerando o PDF no servidor (A4 paisagem)…</li></ul>';
      fetch(url, { credentials: 'same-origin' }).then(function (r) {
        if (!r.ok) throw new Error(r.status === 429 ? 'Muitos pedidos seguidos. Espere um minuto.' : 'O servidor não conseguiu gerar o PDF.');
        var nome = (r.headers.get('Content-Disposition') || '').match(/filename="?([^";]+)/);
        return r.blob().then(function (b) { return { blob: b, nome: nome ? nome[1] : 'relatorio-financeiro.pdf' }; });
      }).then(function (x) {
        var a = document.createElement('a'); a.href = URL.createObjectURL(x.blob); a.download = x.nome; document.body.appendChild(a); a.click(); a.remove();
        setTimeout(function () { URL.revokeObjectURL(a.href); }, 5000);
        $('pdf-passos').innerHTML = '<ul class="passos"><li class="ok"><i>✓</i>Arquivo pronto</li></ul><div class="arq" style="margin-top:12px"><span class="ic">PDF</span><div><b>' + esc(x.nome) + '</b><div class="note">A4 paisagem · o download começou</div></div></div>';
        $('pdf-cancel').hidden = true;
        pronto = true;
        bt.textContent = 'Fechar'; bt.disabled = false;
      }).catch(function (e) {
        $('pdf-passos').innerHTML = '<div class="aviso">' + esc(e.message) + '</div>'; bt.disabled = false;
      });
    });
  });

  // ---------- render ----------
  function render() {
    sincronizarPeriodoComServidor();
    syncFiltros();
    var vazio = D.vazio, R = D.meta.rotulos;
    $('vazio').hidden = !vazio;
    document.querySelectorAll('main > section').forEach(function (s) { s.hidden = vazio; });
    var gestor = $('gestor'); if (gestor) gestor.textContent = R.gestor;
    $('context').innerHTML = vazio ? '' : (R.titulo ? 'Mostrando <b>' + esc(R.titulo) + '</b> · ' : '') + 'Período <b>' + esc(D.meta.periodo) + '</b>';
    $('rel-titulo').textContent = R.titulo || 'Relatório financeiro de contratos';
    $('rel-filtros').innerHTML = [['Cliente', R.cliente], ['Coordenador', R.coordenador], ['Contratos', R.contratos], ['Período', D.meta.periodo], ['NFs', R.nf], ['Resumo agrupado por', R.agrupar], ['Gerado em', new Date().toLocaleString('pt-BR')]]
      .map(function (x) { return '<dt>' + x[0] + '</dt><dd>' + esc(x[1]) + '</dd>'; }).join('');
    if (vazio) { window.__graficosProntos = true; return; }
    ficha(); cascata(); grupo(); receb(); mensal(); execucao(); itens(); tabelas();
    // Quadro mais alto que a folha (A4 paisagem ≈ 700px úteis) quebra entre páginas,
    // em vez de pular inteiro e deixar a página anterior em branco.
    if (CFG.impressao) document.querySelectorAll('main > section.card').forEach(function (s) { s.classList.toggle('longo', s.offsetHeight > 700); });
    window.__graficosProntos = true;
  }
  render();
  var mq = matchMedia('(prefers-color-scheme: dark)'); if (mq.addEventListener) mq.addEventListener('change', render);
  new MutationObserver(render).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
  window.addEventListener('beforeprint', function () { Object.keys(charts).forEach(function (k) { charts[k].resize(); }); });
})();
