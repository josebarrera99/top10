# Reporte MKT-pepe

Aplicación de Streamlit para análisis de datos de marketing.

## Configuración para Streamlit Cloud

1. Haz fork de este repositorio
2. Ve a [share.streamlit.io](https://share.streamlit.io)
3. Conecta tu cuenta de GitHub
4. Selecciona este repositorio
5. Configura las variables de entorno en los secretos de Streamlit Cloud:
   - `DB_SERVER`
   - `DB_DATABASE` 
   - `DB_USERNAME`
   - `DB_PASSWORD`

## Instalación local

```bash
pip install -r requirements.txt
streamlit run reporte.py
```

## Variables de entorno requeridas

Crea un archivo `.env` con: