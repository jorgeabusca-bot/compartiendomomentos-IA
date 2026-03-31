from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_from_directory
from flask_cors import CORS
import json
import os
from datetime import datetime
from werkzeug.utils import secure_filename

app = Flask(__name__)

# Configuración desde variables de entorno
app.secret_key = os.environ.get('SECRET_KEY', 'compartiendomomentos2024')
CORS(app)

# Configuración de uploads
UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Crear directorio de uploads si no existe
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# Archivo de base de datos
DB_FILE = os.environ.get('DB_FILE', 'database.json')

UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

DB_FILE = 'database.json'

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def cargar_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {
        'usuarios': [],
        'eventos': [],
        'comentarios': [],
        'puntajes': []
    }

def guardar_db(data):
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/uploads/<path:filename>')
def serve_upload(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# ============================================
# RUTAS DE PÁGINAS
# ============================================

@app.route('/')
def index():
    db = cargar_db()
    hoy = datetime.now().strftime('%Y-%m-%d')
    
    eventos_futuros = [e for e in db['eventos'] if e.get('fecha', '') >= hoy]
    eventos_ordenados = sorted(eventos_futuros, key=lambda x: x.get('fecha', ''))
    
    for evento in eventos_ordenados:
        if evento.get('gratis', False):
            evento['tipo'] = 'GRATIS'
        else:
            evento['tipo'] = 'CON ABONO'
    
    return render_template('index.html', 
                         eventos=eventos_ordenados,
                         usuario=session.get('usuario'))

@app.route('/eventos')
def eventos():
    db = cargar_db()
    hoy = datetime.now().strftime('%Y-%m-%d')
    eventos_futuros = [e for e in db['eventos'] if e.get('fecha', '') >= hoy]
    eventos = sorted(eventos_futuros, key=lambda x: x.get('fecha', ''))
    return render_template('eventos.html', eventos=eventos)

@app.route('/asociados')
def asociados():
    db = cargar_db()
    usuarios = [u for u in db['usuarios'] if u.get('activo', True)]
    roles_orden = {'Coordinador General': 1, 'Coordinador Principal': 2, 'Coordinador': 3, 'Socio': 4}
    usuarios_ordenados = sorted(usuarios, key=lambda x: roles_orden.get(x.get('rol', 'Socio'), 5))
    return render_template('asociados.html', usuarios=usuarios_ordenados)

@app.route('/perfil')
def perfil():
    if 'usuario' not in session:
        return redirect(url_for('login'))
    
    db = cargar_db()
    usuario = None
    for u in db['usuarios']:
        if u['username'] == session['usuario']:
            usuario = u
            break
    
    if not usuario:
        flash('Usuario no encontrado', 'error')
        return redirect(url_for('login'))
    
    return render_template('perfil.html', usuario=usuario, es_propio=True, puede_ver_detalles=True)

@app.route('/ver-perfil/<username>')
def ver_perfil(username):
    if 'usuario' not in session:
        return redirect(url_for('login'))
    
    db = cargar_db()
    usuario = None
    for u in db['usuarios']:
        if u['username'] == username:
            usuario = u
            break
    
    if not usuario:
        flash('Usuario no encontrado', 'error')
        return redirect(url_for('asociados'))
    
    es_propio = session['usuario'] == username
    usuario_actual = None
    for u in db['usuarios']:
        if u['username'] == session['usuario']:
            usuario_actual = u
            break
    
    puede_ver_detalles = usuario_actual and usuario_actual.get('tipo') == 'abonado'
    
    return render_template('perfil.html', 
                         usuario=usuario, 
                         es_propio=es_propio,
                         puede_ver_detalles=puede_ver_detalles)

# ============================================
# SOCIAL - Conocer gente
# ============================================

@app.route('/social')
def social():
    if 'usuario' not in session:
        return redirect(url_for('login'))
    
    db = cargar_db()
    usuarios = [u for u in db['usuarios'] if u.get('activo', True) and u['username'] != session['usuario']]
    
    db_usuario_actual = None
    for u in db['usuarios']:
        if u['username'] == session['usuario']:
            db_usuario_actual = u
            break
    
    puede_ver_detalles = db_usuario_actual and db_usuario_actual.get('tipo') == 'abonado'
    
    roles_orden = {'Coordinador General': 1, 'Coordinador Principal': 2, 'Coordinador': 3, 'Socio': 4}
    usuarios_ordenados = sorted(usuarios, key=lambda x: roles_orden.get(x.get('rol', 'Socio'), 5))
    
    return render_template('social.html', 
                         usuarios=usuarios_ordenados,
                         puede_ver_detalles=puede_ver_detalles)

# ============================================
# AUTENTICACIÓN
# ============================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        db = cargar_db()
        for usuario in db['usuarios']:
            if usuario['username'] == username and usuario['password'] == password:
                session['usuario'] = username
                session['tipo'] = usuario.get('tipo', 'gratuito')
                session['rol'] = usuario.get('rol', 'Socio')
                flash('¡Bienvenido!', 'success')
                return redirect(url_for('index'))
        
        flash('Usuario o contraseña incorrectos', 'error')
    
    return render_template('login.html')

@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        nombre = request.form['nombre']
        tipo = request.form.get('tipo', 'gratuito')
        
        db = cargar_db()
        
        for u in db['usuarios']:
            if u['username'] == username:
                flash('El usuario ya existe', 'error')
                return render_template('registro.html')
        
        nuevo_usuario = {
            'id': len(db['usuarios']) + 1,
            'username': username,
            'email': email,
            'password': password,
            'nombre': nombre,
            'tipo': tipo,
            'rol': 'Socio',
            'puntaje': 0,
            'activo': True,
            'fecha_registro': datetime.now().strftime('%Y-%m-%d'),
            'foto_perfil': '',
            'fotos': [],
            'descripcion': ''
        }
        
        db['usuarios'].append(nuevo_usuario)
        guardar_db(db)
        
        flash('¡Registro exitoso! Ahora puedes iniciar sesión', 'success')
        return redirect(url_for('login'))
    
    return render_template('registro.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Sesión cerrada', 'info')
    return redirect(url_for('index'))

# ============================================
# EDITAR PERFIL
# ============================================

@app.route('/editar-perfil', methods=['GET', 'POST'])
def editar_perfil():
    if 'usuario' not in session:
        return redirect(url_for('login'))
    
    db = cargar_db()
    usuario = None
    usuario_idx = None
    for idx, u in enumerate(db['usuarios']):
        if u['username'] == session['usuario']:
            usuario = u
            usuario_idx = idx
            break
    
    if request.method == 'POST':
        nombre = request.form['nombre']
        email = request.form['email']
        descripcion = request.form.get('descripcion', '')
        
        db['usuarios'][usuario_idx]['nombre'] = nombre
        db['usuarios'][usuario_idx]['email'] = email
        db['usuarios'][usuario_idx]['descripcion'] = descripcion
        
        if 'foto_perfil' in request.files:
            file = request.files['foto_perfil']
            if file and file.filename and allowed_file(file.filename):
                if db['usuarios'][usuario_idx].get('foto_perfil'):
                    old_file = os.path.join(app.config['UPLOAD_FOLDER'], db['usuarios'][usuario_idx]['foto_perfil'])
                    if os.path.exists(old_file):
                        os.remove(old_file)
                filename = secure_filename(f"perfil_{session['usuario']}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{file.filename.rsplit('.', 1)[1].lower()}")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                db['usuarios'][usuario_idx]['foto_perfil'] = filename
        
        if 'fotos' in request.files:
            files = request.files.getlist('fotos')
            foto_descripciones = request.form.getlist('foto_descripcion')
            for i, file in enumerate(files):
                if file and file.filename and allowed_file(file.filename):
                    foto_id = len(db['usuarios'][usuario_idx].get('fotos', [])) + 1
                    filename = secure_filename(f"foto_{session['usuario']}_{foto_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{file.filename.rsplit('.', 1)[1].lower()}")
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    if 'fotos' not in db['usuarios'][usuario_idx]:
                        db['usuarios'][usuario_idx]['fotos'] = []
                    desc = foto_descripciones[i] if i < len(foto_descripciones) else ''
                    db['usuarios'][usuario_idx]['fotos'].append({
                        'nombre': filename,
                        'descripcion': desc,
                        'fecha': datetime.now().strftime('%Y-%m-%d')
                    })
        
        guardar_db(db)
        flash('Perfil actualizado correctamente', 'success')
        return redirect(url_for('perfil'))
    
    return render_template('editar_perfil.html', usuario=usuario)

@app.route('/eliminar-foto/<int:foto_idx>')
def eliminar_foto(foto_idx):
    if 'usuario' not in session:
        return redirect(url_for('login'))
    
    db = cargar_db()
    for u in db['usuarios']:
        if u['username'] == session['usuario']:
            if 'fotos' in u and foto_idx < len(u['fotos']):
                foto = u['fotos'][foto_idx]
                filename = foto['nombre'] if isinstance(foto, dict) else foto
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                if os.path.exists(filepath):
                    os.remove(filepath)
                del u['fotos'][foto_idx]
                guardar_db(db)
                flash('Foto eliminada', 'success')
            break
    
    return redirect(url_for('editar_perfil'))

@app.route('/modificar-foto/<int:foto_idx>', methods=['POST'])
def modificar_foto(foto_idx):
    if 'usuario' not in session:
        return redirect(url_for('login'))
    
    db = cargar_db()
    nueva_descripcion = request.form.get('descripcion', '')
    
    for u in db['usuarios']:
        if u['username'] == session['usuario']:
            if 'fotos' in u and foto_idx < len(u['fotos']):
                if isinstance(u['fotos'][foto_idx], dict):
                    u['fotos'][foto_idx]['descripcion'] = nueva_descripcion
                else:
                    u['fotos'][foto_idx] = {
                        'nombre': u['fotos'][foto_idx],
                        'descripcion': nueva_descripcion,
                        'fecha': datetime.now().strftime('%Y-%m-%d')
                    }
                guardar_db(db)
                flash('Descripción actualizada', 'success')
            break
    
    return redirect(url_for('editar_perfil'))

# ============================================
# SUSCRIPCIÓN / UPGRADE
# ============================================

@app.route('/suscribirse', methods=['GET', 'POST'])
def suscribirse():
    if 'usuario' not in session:
        return redirect(url_for('login'))
    
    db = cargar_db()
    usuario = None
    usuario_idx = None
    for idx, u in enumerate(db['usuarios']):
        if u['username'] == session['usuario']:
            usuario = u
            usuario_idx = idx
            break
    
    if request.method == 'POST':
        if usuario:
            db['usuarios'][usuario_idx]['tipo'] = 'abonado'
            session['tipo'] = 'abonado'
            guardar_db(db)
            flash('¡Felicidades! Ahora eres usuario Abonado', 'success')
            return redirect(url_for('perfil'))
    
    return render_template('suscribirse.html', usuario=usuario)

@app.route('/cancelar-suscripcion', methods=['POST'])
def cancelar_suscripcion():
    if 'usuario' not in session:
        return redirect(url_for('login'))
    
    db = cargar_db()
    for idx, u in enumerate(db['usuarios']):
        if u['username'] == session['usuario']:
            db['usuarios'][idx]['tipo'] = 'gratuito'
            session['tipo'] = 'gratuito'
            guardar_db(db)
            flash('Suscripción cancelada', 'info')
            break
    
    return redirect(url_for('perfil'))

# ============================================
# EVENTOS
# ============================================

@app.route('/admin/eventos', methods=['GET', 'POST'])
def admin_eventos():
    if 'usuario' not in session:
        return redirect(url_for('login'))
    
    db = cargar_db()
    hoy = datetime.now().strftime('%Y-%m-%d')
    
    if request.method == 'POST':
        accion = request.form.get('accion')
        
        if accion == 'crear':
            portada_filename = ''
            if 'portada' in request.files:
                file = request.files['portada']
                if file and file.filename and allowed_file(file.filename):
                    portada_filename = secure_filename(f"evento_portada_{len(db['eventos']) + 1}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{file.filename.rsplit('.', 1)[1].lower()}")
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], portada_filename))
            
            nuevo_evento = {
                'id': len(db['eventos']) + 1,
                'titulo': request.form['titulo'],
                'descripcion': request.form['descripcion'],
                'fecha': request.form['fecha'],
                'hora': request.form['hora'],
                'lugar': request.form['lugar'],
                'gratis': request.form.get('gratis') == 'on',
                'descuento_abonado': float(request.form.get('descuento', 0)),
                'creado_por': session['usuario'],
                'participantes': [],
                'portada': portada_filename,
                'fotos': []
            }
            db['eventos'].append(nuevo_evento)
            guardar_db(db)
            flash('Evento creado', 'success')
        
        elif accion == 'eliminar':
            evento_id = int(request.form['evento_id'])
            db['eventos'] = [e for e in db['eventos'] if e['id'] != evento_id]
            guardar_db(db)
            flash('Evento eliminado', 'info')
        
        elif accion == 'borrar_pasados':
            eventos_pasados = [e for e in db['eventos'] if e.get('fecha', '') < hoy]
            if eventos_pasados:
                for ep in eventos_pasados:
                    if ep.get('portada'):
                        filepath = os.path.join(app.config['UPLOAD_FOLDER'], ep['portada'])
                        if os.path.exists(filepath):
                            os.remove(filepath)
                    if ep.get('fotos'):
                        for foto in ep['fotos']:
                            fotofile = foto['nombre'] if isinstance(foto, dict) else foto
                            filepath = os.path.join(app.config['UPLOAD_FOLDER'], fotofile)
                            if os.path.exists(filepath):
                                os.remove(filepath)
                db['eventos'] = [e for e in db['eventos'] if e.get('fecha', '') >= hoy]
                guardar_db(db)
                flash(f'{len(eventos_pasados)} evento(s) pasado(s) eliminado(s)', 'info')
            else:
                flash('No hay eventos pasados para eliminar', 'info')
    
    eventos_futuros = [e for e in db['eventos'] if e.get('fecha', '') >= hoy]
    eventos_pasados = [e for e in db['eventos'] if e.get('fecha', '') < hoy]
    
    return render_template('admin.html', eventos=eventos_futuros, eventos_pasados=eventos_pasados)

@app.route('/admin/evento/<int:evento_id>/agregar-fotos', methods=['POST'])
def agregar_fotos_evento(evento_id):
    if 'usuario' not in session:
        return redirect(url_for('login'))
    
    db = cargar_db()
    
    for evento in db['eventos']:
        if evento['id'] == evento_id:
            if 'fotos' in request.files:
                files = request.files.getlist('fotos')
                for file in files:
                    if file and file.filename and allowed_file(file.filename):
                        foto_id = len(evento.get('fotos', [])) + 1
                        filename = secure_filename(f"evento_{evento_id}_foto_{foto_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{file.filename.rsplit('.', 1)[1].lower()}")
                        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                        if 'fotos' not in evento:
                            evento['fotos'] = []
                        evento['fotos'].append(filename)
                guardar_db(db)
                flash('Fotos agregadas al evento', 'success')
            break
    
    return redirect(url_for('admin_eventos'))

@app.route('/admin/evento/<int:evento_id>/eliminar-foto/<filename>')
def eliminar_foto_evento(evento_id, filename):
    if 'usuario' not in session:
        return redirect(url_for('login'))
    
    db = cargar_db()
    
    for evento in db['eventos']:
        if evento['id'] == evento_id:
            if 'fotos' in evento and filename in evento['fotos']:
                evento['fotos'].remove(filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                if os.path.exists(filepath):
                    os.remove(filepath)
                guardar_db(db)
                flash('Foto eliminada', 'success')
            break
    
    return redirect(url_for('admin_eventos'))

@app.route('/evento/<int:evento_id>/participar', methods=['POST'])
def participar_evento(evento_id):
    if 'usuario' not in session:
        return redirect(url_for('login'))
    
    db = cargar_db()
    
    for evento in db['eventos']:
        if evento['id'] == evento_id:
            if session['usuario'] not in evento['participantes']:
                evento['participantes'].append(session['usuario'])
                guardar_db(db)
                flash('¡Te inscribiste al evento!', 'success')
            else:
                flash('Ya estás inscripto', 'warning')
            break
    
    return redirect(url_for('index'))

# ============================================
# PUNTAJES Y ROLES
# ============================================

@app.route('/dar-puntaje/<int:usuario_id>', methods=['POST'])
def dar_puntaje(usuario_id):
    if 'usuario' not in session:
        return redirect(url_for('login'))
    
    if session.get('tipo') != 'abonado':
        flash('Solo los socios abonados pueden dar puntaje', 'error')
        return redirect(url_for('asociados'))
    
    puntaje = int(request.form['puntaje'])
    
    db = cargar_db()
    
    for usuario in db['usuarios']:
        if usuario['id'] == usuario_id:
            usuario['puntaje'] = usuario.get('puntaje', 0) + puntaje
            guardar_db(db)
            
            if usuario['puntaje'] >= 100:
                usuario['rol'] = 'Coordinador General'
            elif usuario['puntaje'] >= 50:
                usuario['rol'] = 'Coordinador Principal'
            elif usuario['puntaje'] >= 20:
                usuario['rol'] = 'Coordinador'
            
            guardar_db(db)
            flash(f'Puntaje {puntaje} asignado a {usuario["nombre"]}', 'success')
            break
    
    return redirect(url_for('asociados'))

# ============================================
# INICIO
# ============================================

if __name__ == '__main__':
    if not os.path.exists(DB_FILE):
        db_inicial = {
            'usuarios': [
                {
                    'id': 1,
                    'username': 'admin',
                    'email': 'admin@compartiendomomentos.com',
                    'password': 'admin123',
                    'nombre': 'Administrador',
                    'tipo': 'abonado',
                    'rol': 'Coordinador General',
                    'puntaje': 100,
                    'activo': True,
                    'fecha_registro': '2024-01-01',
                    'foto_perfil': '',
                    'fotos': [],
                    'descripcion': 'Coordinador general de la comunidad. ¡Siempre disponible para ayudar!'
                },
                {
                    'id': 2,
                    'username': 'maria',
                    'email': 'maria@email.com',
                    'password': 'maria123',
                    'nombre': 'María García',
                    'tipo': 'abonado',
                    'rol': 'Coordinador Principal',
                    'puntaje': 55,
                    'activo': True,
                    'fecha_registro': '2024-02-15',
                    'foto_perfil': '',
                    'fotos': [],
                    'descripcion': 'Me encanta conocer gente nueva y compartir momentos inolvidables.'
                },
                {
                    'id': 3,
                    'username': 'juan',
                    'email': 'juan@email.com',
                    'password': 'juan123',
                    'nombre': 'Juan Pérez',
                    'tipo': 'gratuito',
                    'rol': 'Socio',
                    'puntaje': 5,
                    'activo': True,
                    'fecha_registro': '2024-03-10',
                    'foto_perfil': '',
                    'fotos': [],
                    'descripcion': ''
                }
            ],
            'eventos': [
                {
                    'id': 1,
                    'titulo': 'Cena de Integración',
                    'descripcion': 'Una cena especial para conocer nuevas personas y compartir momentos únicos.',
                    'fecha': '2026-04-15',
                    'hora': '20:00',
                    'lugar': 'Restaurante El Mirador',
                    'gratis': False,
                    'descuento_abonado': 20,
                    'creado_por': 'admin',
                    'participantes': ['maria']
                },
                {
                    'id': 2,
                    'titulo': 'Paseo por el Parque',
                    'descripcion': 'Caminata grupal por el parque central. ¡Ven a disfrutar la naturaleza!',
                    'fecha': '2026-04-20',
                    'hora': '10:00',
                    'lugar': 'Parque Central',
                    'gratis': True,
                    'descuento_abonado': 0,
                    'creado_por': 'admin',
                    'participantes': []
                },
                {
                    'id': 3,
                    'titulo': 'Taller de Cocina',
                    'descripcion': 'Aprende a cocinar platos deliciosos en compañía.',
                    'fecha': '2026-04-25',
                    'hora': '15:00',
                    'lugar': 'Centro Comunitario',
                    'gratis': False,
                    'descuento_abonado': 15,
                    'creado_por': 'maria',
                    'participantes': []
                }
            ],
            'comentarios': [],
            'puntajes': []
        }
        guardar_db(db_inicial)
    
    print("=" * 50)
    print("CompartiendoMomentos.ar")
    print("=" * 50)
    
    # En producción usar gunicorn, en desarrollo Flask
    if __name__ == '__main__':
        port = int(os.environ.get('PORT', 5000))
        debug = os.environ.get('FLASK_ENV') != 'production'
        app.run(debug=debug, port=port, host='0.0.0.0')
