# Agentes del Grupo EG en la nube

Este repositorio es PRIVADO y no contiene claves. Las claves viven como variables de entorno del entorno de la nube en claude.ai.

## Qué hay aquí
- `lib/odoo_cli.py`: lectura/notas/escritura en Odoo por XML-RPC (variables `ODOO_*`).
- `lib/siigo_cli.py`: cartera, ingresos y clientes de SIIGO (variables `SIIGO_<EMPRESA>_USER|KEY`).
- `herramientas_locales/exportar_secretos.py`: corre solo en tu PC y arma el archivo con las variables a pegar (no se sube a GitHub).
- `protocolos/` y `rutinas/`: reglas y prompts de los agentes (se agregan al migrar cada rutina).

## Cómo trabajan en la nube
- Odoo y SIIGO: por estos scripts (el entorno debe permitir esos dominios).
- Correo de Klar, gerencia, Tecnolavex y Omicron: por el conector Composio/Gmail (cuentas conectadas por OAuth), solo borradores.
- Drive, Notion, Calendario: conectores de claude.ai.
- Memoria y Buzón: páginas y base de Notion (la nube no conserva archivos entre ejecuciones).
- Avisos: PushNotification (probado: llega al celular desde la nube).
