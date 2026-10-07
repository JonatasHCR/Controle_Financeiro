/*
 * Comportamentos por atributo: a CSP (`script-src 'self'`) bloqueia handler inline.
 */
(function () {
  'use strict';

  // <form data-confirmar="Restaurar o banco?">
  document.addEventListener('submit', function (evento) {
    var formulario = evento.target.closest('[data-confirmar]');
    if (formulario && !window.confirm(formulario.getAttribute('data-confirmar'))) {
      evento.preventDefault();
    }
  });

  // <select data-enviar-ao-mudar> dentro de um form GET
  document.addEventListener('change', function (evento) {
    var campo = evento.target.closest('[data-enviar-ao-mudar]');
    if (campo && campo.form) campo.form.submit();
  });

  // menu do usuário fecha ao clicar fora
  document.addEventListener('click', function (evento) {
    var menu = document.getElementById('user');
    if (menu && menu.open && !evento.target.closest('#user')) menu.open = false;
  });
})();
