/* Configuração: busca na lista de contratos e arrastar a planilha. */
(function () {
  'use strict';
  var semAcento = function (t) { return t.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase(); };

  var atual = document.querySelector('.cfg-item[aria-current=true]');
  var listaCr = document.getElementById('cfg-lista');
  if (atual && listaCr) listaCr.scrollTop = atual.offsetTop - listaCr.offsetTop - 80;

  var busca = document.getElementById('cfg-busca');
  if (busca) {
    busca.addEventListener('input', function () {
      var q = semAcento(busca.value.trim()), n = 0, lista = document.getElementById('cfg-lista');
      lista.querySelectorAll('.cfg-item').forEach(function (b) { var ok = semAcento(b.textContent).indexOf(q) >= 0; b.hidden = !ok; if (ok) n++; });
      var v = lista.querySelector('.nada');
      if (!n) { if (!v) { v = document.createElement('p'); v.className = 'nada note'; lista.append(v); } v.textContent = 'Nenhum contrato encontrado.'; v.hidden = false; }
      else if (v) v.hidden = true;
    });
  }

  // parâmetros em lote: mostra a lista do alvo escolhido e quantos contratos serão afetados
  var lote = document.getElementById('f-lote');
  if (lote) {
    var C = JSON.parse(document.getElementById('lote-contratos').textContent);
    var norm = function (t) { return semAcento(t).trim(); };
    var alvoAtual = function () { return lote.querySelector('input[name=alvo]:checked').value; };
    var afetados = function () {
      var a = alvoAtual();
      if (a === 'todos') {
        var sob = lote.querySelector('input[name=sobrescrever]');
        return C.filter(function (c) { return !c.proprio || (sob && sob.checked); });
      }
      var sel = Array.prototype.map.call(lote.querySelectorAll('[data-alvo="' + a + '"] input[name=sel]:checked'), function (i) { return i.value; });
      if (a === 'cr') return C.filter(function (c) { return sel.indexOf(c.cr) >= 0; });
      if (a === 'cli') return C.filter(function (c) { return sel.indexOf(c.cliente) >= 0; });
      var alvo = sel.map(norm);
      return C.filter(function (c) { return c.coordenadores.some(function (n) { return alvo.indexOf(norm(n)) >= 0; }); });
    };
    var atualizar = function () {
      var a = alvoAtual();
      lote.querySelectorAll('[data-alvo]').forEach(function (g) {
        var on = g.dataset.alvo === a; g.hidden = !on;
        g.querySelectorAll('input[name=sel]').forEach(function (i) { i.disabled = !on; });
      });
      var cs = afetados(), caixa = document.getElementById('lote-afeta');
      caixa.textContent = !cs.length ? (a === 'todos' ? 'Todos os contratos têm valores próprios: só o padrão global muda.' : 'Marque pelo menos um item para ver os contratos afetados.')
        : 'Afeta ' + cs.length + (cs.length === 1 ? ' contrato: ' : ' contratos: ') + cs.map(function (c) { return c.cr; }).join(', ') + '.';
    };
    lote.addEventListener('change', atualizar);
    lote.querySelectorAll('.lote-sel input[type=search]').forEach(function (b) {
      b.addEventListener('input', function () {
        var q = semAcento(b.value.trim());
        b.nextElementSibling.querySelectorAll('label').forEach(function (l) { l.hidden = semAcento(l.textContent).indexOf(q) < 0; });
      });
    });
    atualizar();
  }

  var drop = document.getElementById('drop'), arq = document.getElementById('f-arq'), nome = document.getElementById('f-nome');
  if (drop && arq) {
    var mostrar = function () { nome.textContent = arq.files.length ? arq.files[0].name : 'Nenhum arquivo escolhido'; };
    arq.addEventListener('change', mostrar);
    drop.addEventListener('dragover', function (e) { e.preventDefault(); drop.classList.add('on'); });
    drop.addEventListener('dragleave', function () { drop.classList.remove('on'); });
    drop.addEventListener('drop', function (e) {
      e.preventDefault(); drop.classList.remove('on');
      if (e.dataTransfer.files.length) { arq.files = e.dataTransfer.files; mostrar(); }
    });
  }
})();
