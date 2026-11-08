/* Interacciones de presentación; no envían formularios ni consultan al backend. */
(() => {
  'use strict';

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
  // El chat vive únicamente en el DOM: no utiliza fetch, formularios ni almacenamiento.
  const abrirChat = document.getElementById('fp-chat-toggle');
  const panelChat = document.getElementById('fp-support-chat');
  const cerrarChat = document.getElementById('fp-chat-close');
  const mensajesChat = document.getElementById('fp-chat-messages');
  const respuestaChat = document.getElementById('fp-chat-reply');
  const enviarChat = document.getElementById('fp-chat-send');

  if (abrirChat && panelChat && cerrarChat && mensajesChat && respuestaChat && enviarChat) {
    const cambiarVisibilidad = (abierto) => {
      panelChat.hidden = !abierto;
      abrirChat.setAttribute('aria-expanded', String(abierto));
      if (abierto) {
        respuestaChat.focus({ preventScroll: true });
      } else {
        abrirChat.focus({ preventScroll: true });
      }
    };

    const agregarMensaje = (texto, remitente) => {
      const burbuja = document.createElement('div');
      burbuja.className = `fp-chat-message fp-chat-message--${remitente}`;
      const contenido = document.createElement('p');
      // textContent evita interpretar etiquetas o scripts escritos por el visitante.
      contenido.textContent = texto;
      const etiqueta = document.createElement('span');
      etiqueta.textContent = remitente === 'visitor' ? 'Tú · mensaje de prueba' : 'Asistente virtual · respuesta simulada';
      burbuja.append(contenido, etiqueta);
      mensajesChat.append(burbuja);
      mensajesChat.scrollTop = mensajesChat.scrollHeight;
    };

    const obtenerRespuesta = (texto) => {
      const consulta = texto.toLocaleLowerCase('es').normalize('NFD').replace(/[\u0300-\u036f]/g, '');
      if (/\b(sedes?|ubicacion|direccion|mapa|ate|llegar)\b/.test(consulta)) {
        return 'Nuestra sede principal está en Ate, Lima. En la sección de ubicación puedes explorar el mapa y abrir Google Maps para planificar tu visita.';
      }
      if (/membresia|precio|plan|pago|inscri/.test(consulta)) {
        return 'En Membresías encontrarás los planes y precios vigentes en soles. Puedes elegir uno y completar tu inscripción y pago con nuestro equipo en recepción.';
      }
      if (/clase|horario|reserva|spinning|yoga|zumba/.test(consulta)) {
        return 'Consulta el Calendario para ver horarios, profesores y cupos por fecha. Las reservas se gestionan en recepción con una inscripción activa y vigente.';
      }
      if (/rutina|entrenador|ejercicio|profesor|team/.test(consulta)) {
        return 'Conoce a los profesores de nuestras clases en Nuestro Team. Para tu rutina personalizada, solicita al equipo de recepción la asignación de ejercicios según tus objetivos.';
      }
      return 'Gracias por escribirnos. Esta es una respuesta simulada. Para atención real, visita nuestra recepción; también puedes consultar los planes, el calendario y la ubicación desde esta web.';
    };

    const enviarMensaje = () => {
      const texto = respuestaChat.value.trim().slice(0, 500);
      if (!texto) return;
      agregarMensaje(texto, 'visitor');
      respuestaChat.value = '';
      enviarChat.disabled = true;
      agregarMensaje(obtenerRespuesta(texto), 'assistant');
      respuestaChat.focus({ preventScroll: true });
    };

    abrirChat.addEventListener('click', () => cambiarVisibilidad(panelChat.hidden));
    cerrarChat.addEventListener('click', () => cambiarVisibilidad(false));
    respuestaChat.addEventListener('input', () => {
      enviarChat.disabled = !respuestaChat.value.trim();
    });
    enviarChat.addEventListener('click', enviarMensaje);
    respuestaChat.addEventListener('keydown', (evento) => {
      if (evento.key === 'Enter' && !evento.isComposing) {
        evento.preventDefault();
        enviarMensaje();
      }
    });
    panelChat.addEventListener('keydown', (evento) => {
      if (evento.key === 'Escape') {
        evento.preventDefault();
        cambiarVisibilidad(false);
      }
    });
  }
})();
