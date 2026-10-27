# Valorix360 · Proyecto para Visual Studio Code

## Estructura
- `app_valorix.py`        App web (Streamlit): sube el PDF, revisa datos, diagnóstico, proyección y agentes
- `valorix_extractor.py`  Lee el PDF (con OCR opcional), mapea cuentas, valida y llena la plantilla Excel
- `valorix_motor.py`      Cálculo determinista: indicadores, valor y riesgo, estrés, hallazgos, plan, proyección
- `valorix_credito.py`    Adaptador del vaciado interno y recomendación crediticia por escenarios
- `valorix_agentes.py`    Agentes (contable, financiero, cumplimiento y riesgos) con verificación de cifras
- `valorix_tabular.py`    Carga de datos desde Excel o CSV (alternativa al PDF) y plantilla de datos
- `valorix_informe.py`    Informe de diagnóstico en PDF
- `tests/`                 Pruebas automáticas (`pip install -r requirements-dev-lock.txt` y luego `pytest tests`)
- `requirements-lock.txt` Versiones exactas probadas para producción
- `requirements-dev-lock.txt` Versiones exactas probadas para desarrollo y pruebas
- `.github/workflows/ci.yml` Verificación automática en cada push a `main` y pull request
- `web/`                  Landing page estática (index.html + styles.css + app.js; valorix360.html es la versión de un solo archivo)
- `probar.py`             Prueba de punta a punta sin interfaz
- `valorix360_plantilla_diagnostico.xlsx`  Plantilla con fórmulas
- `.streamlit/config.toml` Tema violeta de la app
- `.vscode/`              Configuración y botones de ejecución (F5)
- `ejemplos/`, `marca/`, `salidas/`  PDF y resultado de ejemplo, logos en violeta, y resultados generados

## Puesta en marcha en VS Code (Windows)
1. Instala Python 3.11+ (marca "Add to PATH") y VS Code con la extensión Python.
2. Archivo > Abrir carpeta > esta carpeta `valorix360`.
3. Terminal > Nuevo terminal, y ejecuta:
       py -m venv .venv
       .venv\Scripts\activate
       pip install -r requirements-lock.txt
4. Ctrl+Shift+P > "Python: Select Interpreter" > elige `.venv`.
5. Pulsa F5 y elige "Valorix360: app web (Streamlit)". Se abre en http://localhost:8501.
   (Atajo: `iniciar.bat` en Windows o `./iniciar.sh` en Mac/Linux hace los pasos 3 y 5.)

Mac/Linux: usa `python3 -m venv .venv` y `source .venv/bin/activate`. Ajusta en `.vscode/settings.json`
el intérprete a `${workspaceFolder}/.venv/bin/python`.

## Para comprobar que todo funciona
    python probar.py
Debe mostrar 8 validaciones OK y crear `salidas/prueba.xlsx`.

Para instalar el entorno de desarrollo con las pruebas:

    pip install -r requirements-dev-lock.txt
    pytest tests

Los archivos `requirements.txt` y `requirements-dev.txt` conservan las dependencias
directas con rangos flexibles. Los archivos `*-lock.txt` fijan las versiones exactas
que pasaron la suite y deben actualizarse juntos después de validar cambios de dependencias.

El workflow de GitHub Actions instala `requirements-dev-lock.txt`, ejecuta `pip check`,
compila los módulos Python y corre toda la suite en Python 3.11.

## Variables opcionales (copia `.env.example` a `.env`)
- `VALORIX_PASSWORD`   acceso con contraseña única (solo cuando VALORIX_CUENTAS=0)
- `VALORIX_CUENTAS`    1 (por defecto) = cuentas de usuario, empresas y diagnósticos guardados; 0 = modo local sin cuentas
- `VALORIX_ENTORNO`    `local` (por defecto) o `produccion`; producción activa comprobaciones de seguridad obligatorias
- `VALORIX_CODIGO_INVITACION`  si se define, el registro exige ese código
- `VALORIX_DB`         ruta del archivo SQLite (por defecto `data/valorix.db`)
- `DATABASE_URL`       URL de PostgreSQL (por ejemplo `postgresql://usuario:clave@host:5432/base?sslmode=require`); si existe, reemplaza a SQLite y las cuentas sobreviven a reinicios y despliegues. Guárdala como secreto del hosting, nunca en el código.
- `ANTHROPIC_API_KEY`  habilita los agentes con IA (sin clave, responden con reglas)
- `VALORIX_MODELO`     modelo de los agentes
- `VALORIX_URL_APP`    URL pública de la app (se usa en el enlace del correo de recuperación)
- `SMTP_HOST`, `SMTP_PORT` (587), `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`  correo saliente para recuperar contraseñas. Con Outlook/Hotmail usa `smtp-mail.outlook.com` y una contraseña de aplicación. Sin SMTP, la app avisa que el envío no está configurado.
- `VALORIX_CORREO_CONSOLA`  1 = solo para desarrollo: imprime el enlace de recuperación en el registro del servidor

## Perfil crediticio interno

El libro interno `Vaciado de CIFRAS` se puede cargar como Excel desde el mismo selector
de archivos. El sistema reconoce sus hojas, conserva los periodos incompletos como datos
faltantes y calcula un perfil crediticio interno con plazos de 12, 24 y 36 meses.

La recomendación usa dos niveles:

- **Recomendado:** DSCR mínimo de 1,25x.
- **Máximo indicativo:** DSCR mínimo de 1,10x, marcado como escenario de mayor riesgo.

Calcula escenarios con y sin deuda vigente, usa la tasa financiera observada más el estrés
configurado y preserva una advertencia cuando falta el flujo de caja libre. El perfil se
mantiene como campo interno del diagnóstico guardado y no aparece en las pestañas, CSV ni
informe normal del cliente. Tampoco se incluye en el contexto de los agentes.
No constituye aprobación bancaria y requiere validación humana antes de presentar una solicitud.

## Ver la app desde el celular o la tablet (misma red Wi-Fi)
- App: `http://<IP-del-equipo>:8501` (Streamlit la muestra como "Network URL").
- Landing: dentro de `web/`, `python -m http.server 8080 --bind 0.0.0.0` y abre `http://<IP-del-equipo>:8080`.
- Si Windows pregunta por el firewall, permite el acceso en redes privadas. Ambas páginas se adaptan a celular, tablet y laptop.

## Flujo rápido sin Streamlit

La landing estática funciona de forma independiente: sus botones llevan al formulario
de contacto y no abren Streamlit ni `share.streamlit.io`. El workflow
`.github/workflows/pages.yml` la publica automáticamente en GitHub Pages después de
cada cambio en `web/`, normalmente en:

    https://virviescas.github.io/valorix360/

Para probarla localmente:

    cd web
    python -m http.server 8080

Después abre `http://localhost:8080`. Para publicarla rápidamente, sube solo la carpeta
`web/` a Netlify Drop o Cloudflare Pages. Este flujo recibe solicitudes de diagnóstico;
el procesamiento financiero permanece en la app interna hasta publicar un backend seguro.

## Publicación
1. **App (Streamlit Community Cloud)**: sube el repositorio a GitHub, crea la app en share.streamlit.io con `app_valorix.py` y publícala como accesible para los clientes. `packages.txt` instala Tesseract. En *Secrets* define `DATABASE_URL` (PostgreSQL), `VALORIX_URL_APP`, `SMTP_*` y, si aplica, `ANTHROPIC_API_KEY` y `VALORIX_CODIGO_INVITACION`.
   Define también `VALORIX_ENTORNO=produccion`. En ese modo se exige `DATABASE_URL`, una `VALORIX_URL_APP` HTTPS, SMTP para recuperación y se bloquea el correo por consola.
2. **Landing (Netlify o Cloudflare Pages)**: publica la carpeta `web/` (`_headers` añade cabeceras de seguridad). Después de comprobar que la app no redirige a la autenticación de Streamlit Cloud, escribe su URL pública en `URL_APP_PUBLICA` de `web/app.js`; mientras esté vacía, los botones llevan al formulario y no exponen el login de Streamlit.
3. Activa el formulario de contacto: el primer envío pide confirmar el correo de destino (FormSubmit).

## OCR (solo PDF escaneados)
Instala Tesseract con idioma español: en Windows, el instalador de UB-Mannheim y el paquete "spa".

## Principios de diseño
- Las cifras las calcula siempre el código; los agentes solo interpretan y deben citar fuentes.
- Cada cifra citada por la IA se verifica contra el diagnóstico (tolerancia 0,5%).
- Las notas del cliente se tratan como datos, no como instrucciones.
- Es una herramienta de apoyo: no es auditoría, revisoría fiscal ni dictamen.
- Con "Agentes con IA" activo se envían cifras y notas a la API de Anthropic: solo con autorización del cliente.
