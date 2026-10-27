const ENDPOINT = 'https://formsubmit.co/ajax/virviescas_2318@hotmail.com';

document.querySelectorAll('a[data-app]').forEach((a) => { a.href = '#contacto'; });

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
