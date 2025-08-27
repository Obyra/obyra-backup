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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
