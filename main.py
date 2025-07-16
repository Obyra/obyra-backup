from app import app
import main_app  # Importar configuración de Google OAuth

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
