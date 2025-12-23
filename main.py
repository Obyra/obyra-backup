from app import app

from flask import render_template

@app.route('/terminos')
def terminos():
    """Página de términos y condiciones"""
    return render_template('legal/terminos.html')

@app.route('/privacidad')
def privacidad():
    """Página de política de privacidad"""
    return render_template('legal/privacidad.html')

@app.route('/offline')
def offline():
    """Página offline para PWA"""
    return render_template('offline.html')

if __name__ == '__main__':
    import os
    # DEBUG solo se activa si FLASK_DEBUG=1 (nunca en producción)
    debug_mode = os.environ.get('FLASK_DEBUG', '0').lower() in ('1', 'true', 'yes')
    app.run(host='0.0.0.0', port=5000, debug=debug_mode)
