# Valorix360 · Proyecto para Visual Studio Code

## Estructura
- `app_valorix.py`        App web (Streamlit): sube el PDF, revisa datos, diagnóstico, proyección y agentes
- `valorix_extractor.py`  Lee el PDF (con OCR opcional), mapea cuentas, valida y llena la plantilla Excel
- `valorix_motor.py`      Cálculo determinista: indicadores, valor y riesgo, estrés, hallazgos, plan, proyección
- `valorix_agentes.py`    Agentes (contable, financiero, cumplimiento y riesgos) con verificación de cifras
- `valorix_tabular.py`    Carga de datos desde Excel o CSV (alternativa al PDF) y plantilla de datos
- `valorix_informe.py`    Informe de diagnóstico en PDF
- `tests/`                Pruebas automáticas (`pip install -r requirements-dev.txt` y luego `pytest tests`)
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
       pip install -r requirements.txt
4. Ctrl+Shift+P > "Python: Select Interpreter" > elige `.venv`.
5. Pulsa F5 y elige "Valorix360: app web (Streamlit)". Se abre en http://localhost:8501.
   (Atajo: `iniciar.bat` en Windows o `./iniciar.sh` en Mac/Linux hace los pasos 3 y 5.)

Mac/Linux: usa `python3 -m venv .venv` y `source .venv/bin/activate`. Ajusta en `.vscode/settings.json`
el intérprete a `${workspaceFolder}/.venv/bin/python`.

## Para comprobar que todo funciona
    python probar.py
Debe mostrar 8 validaciones OK y crear `salidas/prueba.xlsx`.

## Variables opcionales (copia `.env.example` a `.env`)
- `VALORIX_PASSWORD`   acceso con contraseña única (solo cuando VALORIX_CUENTAS=0)
- `VALORIX_CUENTAS`    1 (por defecto) = cuentas de usuario, empresas y diagnósticos guardados; 0 = modo local sin cuentas
- `VALORIX_CODIGO_INVITACION`  si se define, el registro exige ese código
- `VALORIX_DB`         ruta del archivo SQLite (por defecto `data/valorix.db`)
- `DATABASE_URL`       URL de PostgreSQL (por ejemplo `postgresql://usuario:clave@host:5432/base?sslmode=require`); si existe, reemplaza a SQLite y las cuentas sobreviven a reinicios y despliegues. Guárdala como secreto del hosting, nunca en el código.
- `ANTHROPIC_API_KEY`  habilita los agentes con IA (sin clave, responden con reglas)
- `VALORIX_MODELO`     modelo de los agentes

## OCR (solo PDF escaneados)
Instala Tesseract con idioma español: en Windows, el instalador de UB-Mannheim y el paquete "spa".

## Principios de diseño
- Las cifras las calcula siempre el código; los agentes solo interpretan y deben citar fuentes.
- Cada cifra citada por la IA se verifica contra el diagnóstico (tolerancia 0,5%).
- Las notas del cliente se tratan como datos, no como instrucciones.
- Es una herramienta de apoyo: no es auditoría, revisoría fiscal ni dictamen.
- Con "Agentes con IA" activo se envían cifras y notas a la API de Anthropic: solo con autorización del cliente.
