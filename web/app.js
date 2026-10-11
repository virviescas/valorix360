const ENDPOINT = 'https://formsubmit.co/ajax/virviescas_2318@hotmail.com';

// URL pública de la app de Streamlit. Vacía: en producción los botones llevan al formulario de contacto.
const URL_APP_PUBLICA = '';
const PUERTO_APP_LOCAL = 8501;

function urlApp() {
  const h = location.hostname;
  if (location.protocol === 'file:') return `http://localhost:${PUERTO_APP_LOCAL}`;
  const red_local = h === 'localhost' || h.endsWith('.local') || /^(127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(h);
  return red_local ? `${location.protocol}//${h}:${PUERTO_APP_LOCAL}` : URL_APP_PUBLICA;
}

document.querySelectorAll('a[data-app]').forEach((a) => {
  const u = urlApp();
  if (u) { a.href = u; a.target = '_blank'; a.rel = 'noopener'; }
});

const form = document.getElementById('f');
const msg = document.getElementById('msg');
const boton = form.querySelector('button[type=submit]');

function aviso(texto, error) {
  msg.textContent = texto;
  msg.classList.toggle('error', Boolean(error));
}

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  if (form._honey.value) return;
  boton.disabled = true;
  aviso('Enviando...');
  try {
    const r = await fetch(ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({
        nombre: form.nombre.value,
        correo: form.correo.value,
        empresa: form.empresa.value,
        _subject: 'Nueva solicitud de diagnóstico Valorix360',
        _replyto: form.correo.value,
        _template: 'table',
        _captcha: 'false',
      }),
    });
    const data = await r.json();
    if (!r.ok || String(data.success) !== 'true') throw new Error(data.message || 'Error de envío');
    aviso('Gracias, ' + form.nombre.value + '. Recibimos tu solicitud y te escribiremos pronto.');
    form.reset();
  } catch (err) {
    aviso('No pudimos enviar tu solicitud. Inténtalo de nuevo en unos minutos.', true);
  } finally {
    boton.disabled = false;
  }
});
