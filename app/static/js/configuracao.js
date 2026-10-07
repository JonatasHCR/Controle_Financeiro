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
