/* Interacciones de presentación; no envían formularios ni consultan al backend. */
(() => {
  'use strict';

  const buscarSede = document.getElementById('buscar-sede');
  const distrito = document.getElementById('sede-distrito');
  const resultado = document.getElementById('resultado-sede');
  const nombreSede = document.getElementById('sede-nombre');

  if (buscarSede && distrito && resultado && nombreSede) {
    buscarSede.addEventListener('click', () => {
      // El texto del resultado se inserta sin interpretar HTML ni pedir una ubicación real.
      nombreSede.textContent = `Fitness Planet · ${distrito.value}`;
      resultado.hidden = false;
    });
    distrito.addEventListener('change', () => {
      resultado.hidden = true;
    });
  }

  const inscripcion = document.getElementById('inscripcion-info');
  const planSeleccionado = document.getElementById('plan-seleccionado');
  if (inscripcion && planSeleccionado) {
    inscripcion.addEventListener('show.bs.modal', (evento) => {
      // Los valores proceden de las tarjetas Jinja y solo personalizan este diálogo.
      const tarjeta = evento.relatedTarget;
      planSeleccionado.textContent = tarjeta?.dataset.plan
        ? `Plan ${tarjeta.dataset.plan} · ${tarjeta.dataset.precio}`
        : 'Encuentra el plan ideal para ti en recepción.';
    });
  }

  // Cerrar el menú móvil al navegar hacia una sección de esta misma página.
  const navegacion = document.getElementById('public-navigation');
  if (navegacion) {
    navegacion.querySelectorAll('a').forEach((enlace) => {
      enlace.addEventListener('click', () => {
        const destino = new URL(enlace.href, window.location.href);
        if (destino.pathname === window.location.pathname && destino.hash) {
          const menu = window.bootstrap?.Collapse.getOrCreateInstance(navegacion, { toggle: false });
          // Si se pulsa durante la apertura, esperar al evento para no perder el cierre.
          if (navegacion.classList.contains('collapsing')) {
            navegacion.addEventListener('shown.bs.collapse', () => menu?.hide(), { once: true });
          } else if (navegacion.classList.contains('show')) {
            menu?.hide();
          }
        }
      });
    });
  }
})();
