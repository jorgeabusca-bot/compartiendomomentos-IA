# CompartiendoMomentos.ar

Red social para conocer gente y compartir momentos especiales.

## Características

- Registro de usuarios (gratuitos y abonados)
- Perfiles personalizados con fotos
- Sistema de eventos
- Galería de fotos por evento
- Sistema de puntaje y roles
- Diseño responsive
- Colores de Argentina 🇦🇷

## Tecnologías

- Flask (Backend)
- HTML/CSS/JS (Frontend)
- JSON (Base de datos)

## Instalación local

```bash
pip install Flask Flask-CORS
python app.py
```

## Despliegue en Render.com

1. Subir este repositorio a GitHub
2. Ir a [render.com](https://render.com)
3. Crear Web Service
4. Conectar con GitHub
5. Seleccionar el repositorio
6. Configurar:
   - Build Command: (vacío)
   - Start Command: `gunicorn app:app`

## Credenciales de prueba

- admin / admin123 (Coordinador General)
- maria / maria123 (Coordinador Principal)
- juan / juan123 (Usuario gratuito)
