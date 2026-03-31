from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_from_directory
from flask_cors import CORS
import os
from datetime import datetime
from werkzeug.utils import secure_filename
from pymongo import MongoClient
from bson.objectid import ObjectId
import mercadopago

app = Flask(__name__)

app.secret_key = os.environ.get('SECRET_KEY', 'compartiendomomentos2024')
CORS(app)

UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

MONGODB_URI = os.environ.get('MONGODB_URI', 'mongodb://localhost:27017/')
MERCADO_PAGO_ACCESS_TOKEN = os.environ.get('MERCADO_PAGO_ACCESS_TOKEN', 'TEST-xxxxx')

client = MongoClient(MONGODB_URI)
db = client['compartiendomomentos']

usuarios_col = db['usuarios']
actividades_col = db['actividades']
pagos_col = db['pagos']
suscripciones_col = db['suscripciones']

sdk = mercadopago.SDK(MERCADO_PAGO_ACCESS_TOKEN)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_current_user():
    if 'usuario' not in session:
        return None
    return usuarios_col.find_one({'username': session['usuario']})

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/')
def index():
    hoy = datetime.now().strftime('%Y-%m-%d')
    actividades = list(actividades_col.find({'fecha': {'$gte': hoy}}).sort('fecha', 1))
    return render_template('index.html', 
                         actividades=actividades,
                         usuario=session.get('usuario'))

@app.route('/actividades')
def actividades():
    hoy = datetime.now().strftime('%Y-%m-%d')
    actividades_list = list(actividades_col.find({'fecha': {'$gte': hoy}}).sort('fecha', 1))
    return render_template('actividades.html', actividades=actividades_list)

@app.route('/asociados')
def asociados():
    usuarios = list(usuarios_col.find({'activo': True}))
    usuarios_ordenados = sorted(usuarios, key=lambda x: get_rol_orden(x.get('rol', 'Socio')))
    return render_template('asociados.html', usuarios=usuarios_ordenados)

def get_rol_orden(rol):
    orden = {'Coordinador General': 1, 'Coordinador Principal': 2, 'Coordinador': 3, 'Socio': 4}
    return orden.get(rol, 5)

@app.route('/perfil')
def perfil():
    if 'usuario' not in session:
        return redirect(url_for('login'))
    usuario = get_current_user()
    if not usuario:
        return redirect(url_for('login'))
    return render_template('perfil.html', usuario=usuario, es_propio=True, puede_ver_detalles=True)

@app.route('/ver-perfil/<username>')
def ver_perfil(username):
    if 'usuario' not in session:
        return redirect(url_for('login'))
    usuario = usuarios_col.find_one({'username': username})
    if not usuario:
        flash('Usuario no encontrado', 'error')
        return redirect(url_for('asociados'))
    es_propio = session['usuario'] == username
    usuario_actual = get_current_user()
    puede_ver_detalles = usuario_actual and usuario_actual.get('tipo') == 'abonado'
    return render_template('perfil.html', 
                         usuario=usuario, 
                         es_propio=es_propio,
                         puede_ver_detalles=puede_ver_detalles)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        usuario = usuarios_col.find_one({'username': username, 'password': password})
        if usuario:
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
        
        if usuarios_col.find_one({'username': username}):
            flash('El usuario ya existe', 'error')
            return render_template('registro.html')
        
        nuevo_usuario = {
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
            'descripcion': '',
            'saldo': 0,
            'monedero': 0
        }
        
        usuarios_col.insert_one(nuevo_usuario)
        flash('¡Registro exitoso! Ahora puedes iniciar sesión', 'success')
        return redirect(url_for('login'))
    return render_template('registro.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Sesión cerrada', 'info')
    return redirect(url_for('index'))

@app.route('/editar-perfil', methods=['GET', 'POST'])
def editar_perfil():
    if 'usuario' not in session:
        return redirect(url_for('login'))
    
    usuario = get_current_user()
    if request.method == 'POST':
        usuarios_col.update_one(
            {'username': session['usuario']},
            {'$set': {
                'nombre': request.form['nombre'],
                'email': request.form['email'],
                'descripcion': request.form.get('descripcion', '')
            }}
        )
        
        if 'foto_perfil' in request.files:
            file = request.files['foto_perfil']
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(f"perfil_{session['usuario']}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{file.filename.rsplit('.', 1)[1].lower()}")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                usuarios_col.update_one({'username': session['usuario']}, {'$set': {'foto_perfil': filename}})
        
        if 'fotos' in request.files and usuario.get('tipo') == 'abonado':
            files = request.files.getlist('fotos')
            for file in files:
                if file and file.filename and allowed_file(file.filename):
                    foto_id = len(usuario.get('fotos', [])) + 1
                    filename = secure_filename(f"foto_{session['usuario']}_{foto_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{file.filename.rsplit('.', 1)[1].lower()}")
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    usuarios_col.update_one(
                        {'username': session['usuario']},
                        {'$push': {'fotos': {'nombre': filename, 'descripcion': request.form.get(f'desc_foto_{foto_id}', ''), 'fecha': datetime.now().strftime('%Y-%m-%d')}}}
                    )
        
        flash('Perfil actualizado', 'success')
        return redirect(url_for('perfil'))
    
    return render_template('editar_perfil.html', usuario=usuario)

@app.route('/suscribirse', methods=['GET', 'POST'])
def suscribirse():
    if 'usuario' not in session:
        return redirect(url_for('login'))
    
    usuario = get_current_user()
    
    if request.method == 'POST':
        preference_data = {
            "items": [
                {
                    "title": "Suscripción Abonado - Compartiendo Momentos",
                    "quantity": 1,
                    "currency_id": "ARS",
                    "unit_price": 2500
                }
            ],
            "back_urls": {
                "success": url_for('pago_exitoso', _external=True),
                "failure": url_for('pago_fallido', _external=True),
                "pending": url_for('pago_pendiente', _external=True)
            },
            "external_reference": session['usuario'],
            "notification_url": url_for('webhook_mercadopago', _external=True)
        }
        
        try:
            preference_response = sdk.preference().create(preference_data)
            preference = preference_response.get('response', {})
            init_point = preference.get('init_point', '')
            
            if init_point:
                return redirect(init_point)
            else:
                usuarios_col.update_one({'username': session['usuario']}, {'$set': {'tipo': 'abonado'}})
                session['tipo'] = 'abonado'
                flash('¡Felicidades! Ahora eres Abonado', 'success')
                return redirect(url_for('perfil'))
        except Exception as e:
            usuarios_col.update_one({'username': session['usuario']}, {'$set': {'tipo': 'abonado'}})
            session['tipo'] = 'abonado'
            flash('¡Felicidades! Ahora eres Abonado', 'success')
            return redirect(url_for('perfil'))
    
    return render_template('suscribirse.html', usuario=usuario)

@app.route('/pago-exitoso')
def pago_exitoso():
    if 'usuario' in session:
        usuarios_col.update_one({'username': session['usuario']}, {'$set': {'tipo': 'abonado'}})
        session['tipo'] = 'abonado'
        pagos_col.insert_one({
            'usuario': session['usuario'],
            'tipo': 'suscripcion',
            'monto': 2500,
            'estado': 'aprobado',
            'fecha': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
        flash('¡Pago exitoso! Ahora eres Abonado', 'success')
    return redirect(url_for('perfil'))

@app.route('/pago-fallido')
def pago_fallido():
    flash('El pago fue cancelado. Intenta nuevamente.', 'error')
    return redirect(url_for('suscribirse'))

@app.route('/pago-pendiente')
def pago_pendiente():
    flash('El pago está pendiente. Te notificaremos cuando se confirme.', 'info')
    return redirect(url_for('index'))

@app.route('/webhook/mercadopago', methods=['POST'])
def webhook_mercadopago():
    if request.json and request.json.get('type') == 'payment':
        payment_id = request.json['data']['id']
        try:
            payment = sdk.payment().get(payment_id)
            if payment.get('response', {}).get('status') == 'approved':
                external_ref = payment.get('response', {}).get('external_reference')
                if external_ref:
                    usuarios_col.update_one({'username': external_ref}, {'$set': {'tipo': 'abonado'}})
        except:
            pass
    return jsonify({'status': 'ok'})

@app.route('/cancelar-suscripcion', methods=['POST'])
def cancelar_suscripcion():
    if 'usuario' not in session:
        return redirect(url_for('login'))
    usuarios_col.update_one({'username': session['usuario']}, {'$set': {'tipo': 'gratuito'}})
    session['tipo'] = 'gratuito'
    flash('Suscripción cancelada', 'info')
    return redirect(url_for('perfil'))

@app.route('/mi-monedero')
def mi_monedero():
    if 'usuario' not in session:
        return redirect(url_for('login'))
    usuario = get_current_user()
    pagos = list(pagos_col.find({'usuario': session['usuario']}).sort('fecha', -1))
    return render_template('mi_monedero.html', usuario=usuario, pagos=pagos)

@app.route('/recargar-monedero', methods=['GET', 'POST'])
def recargar_monedero():
    if 'usuario' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        monto = float(request.form.get('monto', 0))
        if monto > 0:
            preference_data = {
                "items": [
                    {
                        "title": f"Recarga de Monedero - ${monto}",
                        "quantity": 1,
                        "currency_id": "ARS",
                        "unit_price": monto
                    }
                ],
                "back_urls": {
                    "success": url_for('recarga_exitosa', _external=True),
                    "failure": url_for('recarga_fallida', _external=True),
                    "pending": url_for('recarga_pendiente', _external=True)
                },
                "external_reference": f"recarga:{session['usuario']}:{monto}",
            }
            
            try:
                preference_response = sdk.preference().create(preference_data)
                preference = preference_response.get('response', {})
                init_point = preference.get('init_point', '')
                if init_point:
                    return redirect(init_point)
            except:
                flash('Error al procesar el pago', 'error')
        
    usuario = get_current_user()
    return render_template('recargar_monedero.html', usuario=usuario)

@app.route('/recarga-exitosa')
def recarga_exitosa():
    if 'usuario' in session:
        flash('¡Recarga exitosa! Tu monedero ha sido acreditado.', 'success')
    return redirect(url_for('mi_monedero'))

@app.route('/recarga-fallida')
def recarga_fallida():
    flash('La recarga fue cancelada.', 'error')
    return redirect(url_for('mi_monedero'))

@app.route('/recarga-pendiente')
def recarga_pendiente():
    flash('La recarga está pendiente.', 'info')
    return redirect(url_for('mi_monedero'))

@app.route('/admin/actividades', methods=['GET', 'POST'])
def admin_actividades():
    if 'usuario' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        accion = request.form.get('accion')
        
        if accion == 'crear':
            portada_filename = ''
            if 'portada' in request.files:
                file = request.files['portada']
                if file and file.filename and allowed_file(file.filename):
                    portada_filename = secure_filename(f"actividad_portada_{datetime.now().strftime('%Y%m%d%H%M%S')}.{file.filename.rsplit('.', 1)[1].lower()}")
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], portada_filename))
            
            nueva_actividad = {
                'titulo': request.form['titulo'],
                'descripcion': request.form['descripcion'],
                'fecha': request.form['fecha'],
                'hora': request.form['hora'],
                'lugar': request.form['lugar'],
                'gratis': request.form.get('gratis') == 'on',
                'precio': float(request.form.get('precio', 0)),
                'descuento_abonado': float(request.form.get('descuento', 0)),
                'coordinador': session['usuario'],
                'participantes': [],
                'portada': portada_filename,
                'fotos': [],
                'estado': 'activa',
                'fecha_creacion': datetime.now().strftime('%Y-%m-%d')
            }
            actividades_col.insert_one(nueva_actividad)
            flash('Actividad creada', 'success')
        
        elif accion == 'eliminar':
            actividad_id = request.form.get('actividad_id')
            actividades_col.delete_one({'_id': ObjectId(actividad_id)})
            flash('Actividad eliminada', 'info')
        
        elif accion == 'borrar_pasados':
            hoy = datetime.now().strftime('%Y-%m-%d')
            actividades_col.delete_many({'fecha': {'$lt': hoy}})
            flash('Actividades pasadas eliminadas', 'info')
    
    hoy = datetime.now().strftime('%Y-%m-%d')
    actividades_futuras = list(actividades_col.find({'fecha': {'$gte': hoy}}).sort('fecha', 1))
    actividades_pasadas = list(actividades_col.find({'fecha': {'$lt': hoy}}).sort('fecha', -1))
    
    return render_template('admin_actividades.html', 
                         actividades=actividades_futuras, 
                         actividades_pasadas=actividades_pasadas)

@app.route('/actividad/<actividad_id>/participar', methods=['POST'])
def participar_actividad(actividad_id):
    if 'usuario' not in session:
        return redirect(url_for('login'))
    
    actividad = actividades_col.find_one({'_id': ObjectId(actividad_id)})
    if actividad and session['usuario'] not in actividad.get('participantes', []):
        actividades_col.update_one(
            {'_id': ObjectId(actividad_id)},
            {'$push': {'participantes': session['usuario']}}
        )
        flash('¡Te inscribiste a la actividad!', 'success')
    else:
        flash('Ya estás inscripto', 'warning')
    
    return redirect(url_for('index'))

@app.route('/dar-puntaje/<usuario_id>', methods=['POST'])
def dar_puntaje(usuario_id):
    if 'usuario' not in session:
        return redirect(url_for('login'))
    
    usuario_actual = get_current_user()
    if usuario_actual.get('tipo') != 'abonado':
        flash('Solo los abonados pueden dar puntaje', 'error')
        return redirect(url_for('asociados'))
    
    puntaje = int(request.form.get('puntaje', 0))
    usuario_obj = usuarios_col.find_one({'_id': ObjectId(usuario_id)})
    
    if usuario_obj:
        nuevo_puntaje = usuario_obj.get('puntaje', 0) + puntaje
        rol_nuevo = 'Socio'
        if nuevo_puntaje >= 100:
            rol_nuevo = 'Coordinador General'
        elif nuevo_puntaje >= 50:
            rol_nuevo = 'Coordinador Principal'
        elif nuevo_puntaje >= 20:
            rol_nuevo = 'Coordinador'
        
        usuarios_col.update_one(
            {'_id': ObjectId(usuario_id)},
            {'$set': {'puntaje': nuevo_puntaje, 'rol': rol_nuevo}}
        )
        flash(f'Puntaje {puntaje} asignado a {usuario_obj["nombre"]}', 'success')
    
    return redirect(url_for('asociados'))

@app.route('/social')
def social():
    if 'usuario' not in session:
        return redirect(url_for('login'))
    usuarios = list(usuarios_col.find({'activo': True, 'username': {'$ne': session['usuario']}}))
    usuario_actual = get_current_user()
    puede_ver = usuario_actual and usuario_actual.get('tipo') == 'abonado'
    return render_template('social.html', usuarios=usuarios, puede_ver_detalles=puede_ver)

def init_db():
    if usuarios_col.count_documents({}) == 0:
        usuarios_col.insert_many([
            {
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
                'descripcion': 'Coordinador general',
                'saldo': 0,
                'monedero': 0
            },
            {
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
                'descripcion': 'Me encanta conocer gente nueva',
                'saldo': 0,
                'monedero': 0
            },
            {
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
                'descripcion': '',
                'saldo': 0,
                'monedero': 0
            }
        ])
    
    if actividades_col.count_documents({}) == 0:
        actividades_col.insert_many([
            {
                'titulo': 'Cena de Integración',
                'descripcion': 'Una cena especial para conocer nuevas personas.',
                'fecha': '2026-04-15',
                'hora': '20:00',
                'lugar': 'Restaurante El Mirador',
                'gratis': False,
                'precio': 1500,
                'descuento_abonado': 20,
                'coordinador': 'admin',
                'participantes': ['maria'],
                'portada': '',
                'fotos': [],
                'estado': 'activa',
                'fecha_creacion': '2024-03-01'
            },
            {
                'titulo': 'Paseo por el Parque',
                'descripcion': 'Caminata grupal por el parque central.',
                'fecha': '2026-04-20',
                'hora': '10:00',
                'lugar': 'Parque Central',
                'gratis': True,
                'precio': 0,
                'descuento_abonado': 0,
                'coordinador': 'admin',
                'participantes': [],
                'portada': '',
                'fotos': [],
                'estado': 'activa',
                'fecha_creacion': '2024-03-01'
            }
        ])

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, port=port, host='0.0.0.0')
