from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_from_directory, make_response
from flask_cors import CORS
import os
from datetime import datetime, timedelta
from functools import wraps
from werkzeug.utils import secure_filename
from pymongo import MongoClient
from bson.objectid import ObjectId
import hashlib
import hmac
import secrets
import jwt
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# ============== SEGURIDAD ==============
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))

SESSION_COOKIE_SECURE = os.environ.get('FLASK_ENV') == 'production'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
PERMANENT_SESSION_LIFETIME = timedelta(days=7)

CORS(app, origins=["https://compartiendomomentos-ia.onrender.com", "http://localhost:5000"], supports_credentials=True)

# Configuración de archivos
UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'mp4', 'mov', 'webm'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# ============== MONGODB ==============
MONGODB_URI = os.environ.get('MONGODB_URI', '')

db = None
if MONGODB_URI:
    try:
        client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=3000)
        client.admin.command('ping')
        db = client['compartiendomomentos']
        print("[OK] MongoDB conectado")
    except Exception as e:
        print(f"[X] Error MongoDB: {str(e)[:50]}")
        db = None
else:
    print("[-] MongoDB no configurado, usando memoria")

usuarios_col = db['usuarios'] if db else None
actividades_col = db['actividades'] if db else None
pagos_col = db['pagos'] if db else None
suscripciones_col = db['suscripciones'] if db else None

# ============== FALLBACK EN MEMORIA ==============
class InMemoryDB:
    def __init__(self):
        self.usuarios = {}
        self.actividades = {}
        self.pagos = {}
        self.suscripciones = {}
        self._contadores = {'usuarios': 0, 'actividades': 0, 'pagos': 0, 'suscripciones': 0}
        print("[-] Usando base de datos en memoria (sin persistencia)")
    
    def insert_one(self, collection, data):
        self._contadores[collection] += 1
        data['_id'] = self._contadores[collection]
        self[collection][self._contadores[collection]] = data.copy()
        return type('Result', (), {'inserted_id': self._contadores[collection]})()
    
    def find_one(self, collection, query):
        for k, v in self[collection].items():
            if all(v.get(k2) == v2 for k2, v2 in query.items()):
                return v.copy()
        return None
    
    def find(self, collection, query=None):
        if query is None:
            return list(self[collection].values())
        results = []
        for v in self[collection].values():
            match = True
            for k, val in query.items():
                if k == '$gte':
                    for k2, v2 in val.items():
                        if v.get(k2, '') < v2:
                            match = False
                elif k == '$lt':
                    for k2, v2 in val.items():
                        if v.get(k2, '') >= v2:
                            match = False
                elif k == '$ne':
                    if v.get(k) == val:
                        match = False
                elif k == '$in':
                    if v.get(k) not in val:
                        match = False
                else:
                    if v.get(k) != val:
                        match = False
            if match:
                results.append(v.copy())
        return results
    
    def update_one(self, collection, query, update):
        doc = self.find_one(collection, query)
        if doc:
            if '$set' in update:
                self[collection][doc['_id']].update(update['$set'])
            if '$push' in update:
                for k, v in update['$push'].items():
                    if k not in self[collection][doc['_id']]:
                        self[collection][doc['_id']][k] = []
                    self[collection][doc['_id']][k].append(v)
            if '$inc' in update:
                for k, v in update['$inc'].items():
                    self[collection][doc['_id']][k] = self[collection][doc['_id']].get(k, 0) + v
            return type('Result', (), {'modified_count': 1})()
        return type('Result', (), {'modified_count': 0})()
    
    def delete_one(self, collection, query):
        doc = self.find_one(collection, query)
        if doc:
            del self[collection][doc['_id']]
            return type('Result', (), {'deleted_count': 1})()
        return type('Result', (), {'deleted_count': 0})()
    
    def count_documents(self, collection, query=None):
        if query:
            return len(self.find(collection, query))
        return len(self[collection])
    
    def __getitem__(self, key):
        return getattr(self, key)

mem_db = InMemoryDB() if not db else None

def get_collection(name):
    if db:
        return globals().get(f'{name}_col')
    return mem_db.usuarios if name == 'usuarios' else (mem_db.actividades if name == 'actividades' else (mem_db.pagos if name == 'pagos' else None))

# ============== MERCADOPAGO ==============
MERCADO_PAGO_ACCESS_TOKEN = os.environ.get('MERCADO_PAGO_ACCESS_TOKEN', '')
MERCADO_PAGO_CLIENT_ID = os.environ.get('MERCADO_PAGO_CLIENT_ID', '')
MERCADO_PAGO_CLIENT_SECRET = os.environ.get('MERCADO_PAGO_CLIENT_SECRET', '')

try:
    import mercadopago
    sdk = mercadopago.SDK(MERCADO_PAGO_ACCESS_TOKEN) if MERCADO_PAGO_ACCESS_TOKEN else None
    print("[OK] MercadoPago configurado" if sdk else "[-] MercadoPago sin token")
except:
    sdk = None
    print("[-] MercadoPago no disponible")

# ============== TOKEN JWT ==============
JWT_SECRET = os.environ.get('JWT_SECRET', secrets.token_hex(32))
JWT_ALGORITHM = 'HS256'
JWT_EXPIRATION = 24

def generate_token(user_data, expiration_hours=JWT_EXPIRATION):
    payload = {
        'user_id': str(user_data.get('_id', '')),
        'username': user_data.get('username', ''),
        'tipo': user_data.get('tipo', 'gratuito'),
        'rol': user_data.get('rol', 'Socio'),
        'exp': datetime.utcnow() + timedelta(hours=expiration_hours),
        'iat': datetime.utcnow()
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def verify_token(token):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        if token and token.startswith('Bearer '):
            token = token[7:]
            payload = verify_token(token)
            if payload:
                session['usuario'] = payload['username']
                session['tipo'] = payload['tipo']
                session['rol'] = payload['rol']
                return f(*args, **kwargs)
        if 'usuario' not in session:
            return jsonify({'error': 'Token requerido'}), 401
        return f(*args, **kwargs)
    return decorated

# ============== HELPERS ==============
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(password, hashed):
    return hmac.compare_digest(hash_password(password), hashed)

def get_current_user():
    if 'usuario' not in session:
        return None
    col = usuarios_col if usuarios_col else (mem_db.usuarios if mem_db else None)
    if not col:
        return None
    if mem_db and not usuarios_col:
        return mem_db.find_one('usuarios', {'username': session['usuario']})
    return col.find_one({'username': session['usuario']})

def login_user(user):
    session.permanent = True
    session['usuario'] = user['username']
    session['tipo'] = user.get('tipo', 'gratuito')
    session['rol'] = user.get('rol', 'Socio')
    session['user_id'] = str(user.get('_id', ''))
    token = generate_token(user)
    session['token'] = token
    return token

def csrf_token():
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(32)
    return session['csrf_token']

def verify_csrf(token):
    return 'csrf_token' in session and session['csrf_token'] == token

app.jinja_env.globals.update(csrf_token=csrf_token)

@app.before_request
def csrf_protect():
    if request.method == 'POST':
        if request.is_json:
            return
        token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
        if not verify_csrf(token):
            flash('Error de seguridad. Recarga la página e intenta de nuevo.', 'error')
            return redirect(request.url)

# ============== RUTAS ==============
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/')
def index():
    hoy = datetime.now().strftime('%Y-%m-%d')
    actividades = []
    if mem_db and not actividades_col:
        todas = mem_db.find('actividades', {'fecha': {'$gte': hoy}})
        actividades = sorted(todas, key=lambda x: x.get('fecha', ''))
    elif actividades_col:
        actividades = list(actividades_col.find({'fecha': {'$gte': hoy}}).sort('fecha', 1))
    return render_template('index.html', 
                         actividades=actividades,
                         usuario=session.get('usuario'))

@app.route('/actividad/<actividad_id>')
def actividad_detalle(actividad_id):
    try:
        if mem_db and not actividades_col:
            actividad = mem_db.find_one('actividades', {'_id': int(actividad_id)})
        elif actividades_col:
            actividad = actividades_col.find_one({'_id': ObjectId(actividad_id)})
        else:
            actividad = None
        
        if not actividad:
            flash('Actividad no encontrada', 'error')
            return redirect(url_for('actividades'))
        
        if not isinstance(actividad.get('suscritos'), list):
            actividad['suscritos'] = []
        if not isinstance(actividad.get('interesados'), list):
            actividad['interesados'] = []
        if not isinstance(actividad.get('reels'), list):
            actividad['reels'] = []
        
        return render_template('actividad_detalle.html', actividad=actividad)
    except:
        flash('Actividad no encontrada', 'error')
        return redirect(url_for('actividades'))

@app.route('/actividades')
def actividades():
    hoy = datetime.now().strftime('%Y-%m-%d')
    actividades_list = []
    if mem_db and not actividades_col:
        todas = mem_db.find('actividades', {'fecha': {'$gte': hoy}})
        actividades_list = sorted(todas, key=lambda x: x.get('fecha', ''))
    elif actividades_col:
        actividades_list = list(actividades_col.find({'fecha': {'$gte': hoy}}).sort('fecha', 1))
    return render_template('actividades.html', actividades=actividades_list)

@app.route('/asociados')
def asociados():
    usuarios = []
    if mem_db and not usuarios_col:
        usuarios = mem_db.find('usuarios', {'activo': True})
    elif usuarios_col:
        usuarios = list(usuarios_col.find({'activo': True}))
    usuarios = sorted(usuarios, key=lambda x: get_rol_orden(x.get('rol', 'Socio')))
    return render_template('asociados.html', usuarios=usuarios)

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
    usuario = usuarios_col.find_one({'username': username}) if usuarios_col else None
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

# ============== AUTENTICACIÓN ==============
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        col = usuarios_col if usuarios_col else (mem_db.usuarios if mem_db else None)
        if not col:
            flash('Base de datos no disponible', 'error')
            return render_template('login.html')
        
        user = mem_db.find_one('usuarios', {'username': username}) if mem_db and not usuarios_col else usuarios_col.find_one({'username': username}) if usuarios_col else None
        
        if user and verify_password(password, user.get('password_hash', '')):
            login_user(user)
            flash('¡Bienvenido!', 'success')
            return redirect(url_for('index'))
        elif user and password == user.get('password', ''):
            login_user(user)
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
        
        col = usuarios_col if usuarios_col else (mem_db.usuarios if mem_db else None)
        if not col:
            flash('Base de datos no disponible', 'error')
            return render_template('registro.html')
        
        existing = mem_db.find_one('usuarios', {'username': username}) if mem_db and not usuarios_col else usuarios_col.find_one({'username': username}) if usuarios_col else None
        if existing:
            flash('El usuario ya existe', 'error')
            return render_template('registro.html')
        
        nuevo_usuario = {
            'username': username,
            'email': email,
            'password': password,
            'password_hash': hash_password(password),
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
            'monedero': 0,
            'token_api': secrets.token_hex(32),
            'ultimo_login': None
        }
        
        if mem_db and not usuarios_col:
            mem_db.insert_one('usuarios', nuevo_usuario)
        else:
            usuarios_col.insert_one(nuevo_usuario)
        flash('¡Registro exitoso! Ahora puedes iniciar sesión', 'success')
        return redirect(url_for('login'))
    return render_template('registro.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Sesión cerrada', 'info')
    return redirect(url_for('index'))

@app.route('/api/token', methods=['POST'])
def api_token():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    
    if not usuarios_col:
        return jsonify({'error': 'Servicio no disponible'}), 503
    
    user = usuarios_col.find_one({'username': username})
    
    if user and (password == user.get('password', '') or verify_password(password, user.get('password_hash', ''))):
        usuarios_col.update_one({'username': username}, {'$set': {'ultimo_login': datetime.now().isoformat()}})
        token = generate_token(user)
        return jsonify({
            'token': token,
            'user': {
                'username': user['username'],
                'nombre': user.get('nombre', ''),
                'tipo': user.get('tipo', 'gratuito'),
                'rol': user.get('rol', 'Socio')
            }
        })
    
    return jsonify({'error': 'Credenciales inválidas'}), 401

# ============== PERFIL ==============
@app.route('/editar-perfil', methods=['GET', 'POST'])
def editar_perfil():
    if 'usuario' not in session:
        return redirect(url_for('login'))
    
    usuario = get_current_user()
    if request.method == 'POST':
        if usuarios_col:
            update_data = {
                'nombre': request.form['nombre'],
                'email': request.form['email'],
                'descripcion': request.form.get('descripcion', '')
            }
            usuarios_col.update_one({'username': session['usuario']}, {'$set': update_data})
        
        if 'foto_perfil' in request.files:
            file = request.files['foto_perfil']
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(f"perfil_{session['usuario']}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{file.filename.rsplit('.', 1)[1].lower()}")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                if usuarios_col:
                    usuarios_col.update_one({'username': session['usuario']}, {'$set': {'foto_perfil': filename}})
        
        if 'fotos' in request.files and usuario.get('tipo') == 'abonado':
            files = request.files.getlist('fotos')
            for file in files:
                if file and file.filename and allowed_file(file.filename):
                    foto_id = len(usuario.get('fotos', [])) + 1
                    filename = secure_filename(f"foto_{session['usuario']}_{foto_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{file.filename.rsplit('.', 1)[1].lower()}")
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    if usuarios_col:
                        usuarios_col.update_one(
                            {'username': session['usuario']},
                            {'$push': {'fotos': {'nombre': filename, 'descripcion': '', 'fecha': datetime.now().strftime('%Y-%m-%d')}}}
                        )
        
        flash('Perfil actualizado', 'success')
        return redirect(url_for('perfil'))
    
    return render_template('editar_perfil.html', usuario=usuario)

# ============== SUSCRIPCIÓN ==============
@app.route('/suscribirse', methods=['GET', 'POST'])
def suscribirse():
    if 'usuario' not in session:
        return redirect(url_for('login'))
    
    usuario = get_current_user()
    
    if request.method == 'POST':
        if usuarios_col:
            usuarios_col.update_one({'username': session['usuario']}, {'$set': {'tipo': 'abonado'}})
            session['tipo'] = 'abonado'
        
        if sdk and MERCADO_PAGO_ACCESS_TOKEN:
            preference_data = {
                "items": [{
                    "title": "Suscripción Abonado - Compartiendo Momentos",
                    "quantity": 1,
                    "currency_id": "ARS",
                    "unit_price": 2500
                }],
                "back_urls": {
                    "success": url_for('pago_exitoso', _external=True),
                    "failure": url_for('pago_fallido', _external=True),
                    "pending": url_for('pago_pendiente', _external=True)
                },
                "external_reference": session['usuario'],
            }
            
            try:
                preference_response = sdk.preference().create(preference_data)
                preference = preference_response.get('response', {})
                init_point = preference.get('init_point', '')
                if init_point:
                    return redirect(init_point)
            except Exception as e:
                print(f"Error MercadoPago: {e}")
        
        flash('¡Felicidades! Ahora eres Abonado', 'success')
        return redirect(url_for('perfil'))
    
    return render_template('suscribirse.html', usuario=usuario)

@app.route('/pago-exitoso')
def pago_exitoso():
    if 'usuario' in session and usuarios_col:
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
        if sdk:
            try:
                payment = sdk.payment().get(payment_id)
                if payment.get('response', {}).get('status') == 'approved':
                    external_ref = payment.get('response', {}).get('external_reference')
                    if external_ref and usuarios_col:
                        usuarios_col.update_one({'username': external_ref}, {'$set': {'tipo': 'abonado'}})
            except:
                pass
    return jsonify({'status': 'ok'})

@app.route('/cancelar-suscripcion', methods=['POST'])
def cancelar_suscripcion():
    if 'usuario' not in session:
        return redirect(url_for('login'))
    if usuarios_col:
        usuarios_col.update_one({'username': session['usuario']}, {'$set': {'tipo': 'gratuito'}})
    session['tipo'] = 'gratuito'
    flash('Suscripción cancelada', 'info')
    return redirect(url_for('perfil'))

# ============== MONEDERO ==============
@app.route('/mi-monedero')
def mi_monedero():
    if 'usuario' not in session:
        return redirect(url_for('login'))
    usuario = get_current_user()
    pagos = list(pagos_col.find({'usuario': session['usuario']}).sort('fecha', -1)) if pagos_col else []
    return render_template('mi_monedero.html', usuario=usuario, pagos=pagos)

@app.route('/recargar-monedero', methods=['GET', 'POST'])
def recargar_monedero():
    if 'usuario' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        monto = float(request.form.get('monto', 0))
        if monto > 0 and sdk and MERCADO_PAGO_ACCESS_TOKEN:
            preference_data = {
                "items": [{
                    "title": f"Recarga de Monedero - ${monto}",
                    "quantity": 1,
                    "currency_id": "ARS",
                    "unit_price": monto
                }],
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
            except Exception as e:
                print(f"Error MercadoPago: {e}")
        
        flash('Error al procesar el pago', 'error')
    
    usuario = get_current_user()
    return render_template('recargar_monedero.html', usuario=usuario)

@app.route('/recarga-exitosa')
def recarga_exitosa():
    if 'usuario' in session:
        ref = request.args.get('external_reference', '')
        if ':' in ref:
            parts = ref.split(':')
            monto = float(parts[2]) if len(parts) > 2 else 0
            if usuarios_col:
                usuarios_col.update_one({'username': session['usuario']}, {'$inc': {'monedero': monto}})
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

# ============== ADMIN ACTIVIDADES ==============
@app.route('/admin/actividades', methods=['GET', 'POST'])
def admin_actividades():
    if 'usuario' not in session:
        return redirect(url_for('login'))
    
    if session.get('rol') not in ['Coordinador', 'Coordinador Principal', 'Coordinador General']:
        flash('No tienes permisos para administrar', 'error')
        return redirect(url_for('index'))
    
    if request.method == 'POST' and actividades_col:
        accion = request.form.get('accion')
        
        if accion == 'crear':
            portada_filename = ''
            if 'portada' in request.files:
                file = request.files['portada']
                if file and file.filename and allowed_file(file.filename):
                    portada_filename = secure_filename(f"actividad_{datetime.now().strftime('%Y%m%d%H%M%S')}.{file.filename.rsplit('.', 1)[1].lower()}")
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
            try:
                actividades_col.delete_one({'_id': ObjectId(actividad_id)})
                flash('Actividad eliminada', 'info')
            except:
                flash('Error al eliminar', 'error')
        
        elif accion == 'borrar_pasados':
            hoy = datetime.now().strftime('%Y-%m-%d')
            actividades_col.delete_many({'fecha': {'$lt': hoy}})
            flash('Actividades pasadas eliminadas', 'info')
    
    hoy = datetime.now().strftime('%Y-%m-%d')
    actividades_futuras = list(actividades_col.find({'fecha': {'$gte': hoy}}).sort('fecha', 1)) if actividades_col else []
    actividades_pasadas = list(actividades_col.find({'fecha': {'$lt': hoy}}).sort('fecha', -1)) if actividades_col else []
    
    return render_template('admin_actividades.html', 
                         actividades=actividades_futuras, 
                         actividades_pasadas=actividades_pasadas)

@app.route('/actividad/<actividad_id>/interes', methods=['POST'])
def actividad_interes(actividad_id):
    if 'usuario' not in session:
        return redirect(url_for('login'))
    
    try:
        username = session['usuario']
        
        if mem_db and not actividades_col:
            actividad = mem_db.find_one('actividades', {'_id': int(actividad_id)})
            if actividad:
                if 'interesados' not in actividad:
                    actividad['interesados'] = []
                if username not in actividad['interesados']:
                    actividad['interesados'].append(username)
                    mem_db.update_one('actividades', {'_id': int(actividad_id)}, {'$set': {'interesados': actividad['interesados']}})
                    flash('Marcado como interesado', 'success')
                else:
                    flash('Ya marcaste interés en esta actividad', 'info')
        elif actividades_col:
            actividad = actividades_col.find_one({'_id': ObjectId(actividad_id)})
            if actividad:
                if username not in actividad.get('interesados', []):
                    actividades_col.update_one({'_id': ObjectId(actividad_id)}, {'$push': {'interesados': username}})
                    flash('Marcado como interesado', 'success')
                else:
                    flash('Ya marcaste interés en esta actividad', 'info')
    except Exception as e:
        flash('Error al marcar interés', 'error')
    
    return redirect(url_for('actividad_detalle', actividad_id=actividad_id))

@app.route('/actividad/<actividad_id>/suscribirse', methods=['POST'])
def actividad_suscribirse(actividad_id):
    if 'usuario' not in session:
        return redirect(url_for('login'))
    
    try:
        username = session['usuario']
        
        if mem_db and not actividades_col:
            actividad = mem_db.find_one('actividades', {'_id': int(actividad_id)})
            if actividad:
                if 'suscritos' not in actividad:
                    actividad['suscritos'] = []
                if username not in actividad['suscritos']:
                    actividad['suscritos'].append(username)
                    mem_db.update_one('actividades', {'_id': int(actividad_id)}, {'$set': {'suscritos': actividad['suscritos']}})
                    flash('Te suscribiste a la actividad', 'success')
                else:
                    flash('Ya estás subscripto a esta actividad', 'info')
        elif actividades_col:
            actividad = actividades_col.find_one({'_id': ObjectId(actividad_id)})
            if actividad:
                if username not in actividad.get('suscritos', []):
                    actividades_col.update_one({'_id': ObjectId(actividad_id)}, {'$push': {'suscritos': username}})
                    flash('Te suscribiste a la actividad', 'success')
                else:
                    flash('Ya estás subscripto a esta actividad', 'info')
    except Exception as e:
        flash('Error al suscribirse', 'error')
    
    return redirect(url_for('actividad_detalle', actividad_id=actividad_id))

@app.route('/crear-actividad', methods=['GET', 'POST'])
def crear_actividad():
    if 'usuario' not in session:
        return redirect(url_for('login'))
    
    if session.get('rol') not in ['Coordinador', 'Coordinador Principal', 'Coordinador General']:
        flash('No tienes permisos para crear actividades', 'error')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        portada_filename = ''
        if 'portada' in request.files:
            file = request.files['portada']
            if file and file.filename and allowed_file(file.filename):
                portada_filename = secure_filename(f"actividad_{datetime.now().strftime('%Y%m%d%H%M%S')}.{file.filename.rsplit('.', 1)[1].lower()}")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], portada_filename))
        
        reels = []
        i = 0
        while f'reel_{i}' in request.files:
            reel_file = request.files[f'reel_{i}']
            reel_titulo = request.form.get(f'reel_titulo_{i}', '')
            if reel_file and reel_file.filename and allowed_file(reel_file.filename):
                ext = reel_file.filename.rsplit('.', 1)[1].lower()
                reel_filename = secure_filename(f"reel_{datetime.now().strftime('%Y%m%d%H%M%S')}_{i}.{ext}")
                reel_file.save(os.path.join(app.config['UPLOAD_FOLDER'], reel_filename))
                reels.append({
                    'video': reel_filename,
                    'titulo': reel_titulo,
                    'thumbnail': ''
                })
            i += 1
        
        nueva_actividad = {
            'titulo': request.form['titulo'],
            'descripcion': request.form['descripcion'],
            'detalles': request.form.get('detalles', ''),
            'fecha': request.form['fecha'],
            'hora': request.form['hora'],
            'lugar': request.form['lugar'],
            'gratis': request.form.get('gratis') == 'on',
            'precio': float(request.form.get('precio', 0)),
            'descuento_abonado': float(request.form.get('descuento', 0)),
            'coordinador': session['usuario'],
            'participantes': [],
            'suscritos': [],
            'interesados': [],
            'portada': portada_filename,
            'reels': reels,
            'fotos': [],
            'estado': 'activa',
            'fecha_creacion': datetime.now().strftime('%Y-%m-%d')
        }
        
        if mem_db and not actividades_col:
            mem_db.insert_one('actividades', nueva_actividad)
        elif actividades_col:
            actividades_col.insert_one(nueva_actividad)
        
        flash('Actividad creada exitosamente', 'success')
        return redirect(url_for('admin_actividades'))
    
    return render_template('crear_actividad.html')
def participar_actividad(actividad_id):
    if 'usuario' not in session:
        return redirect(url_for('login'))
    
    if actividades_col:
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
    if usuarios_col:
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
    usuarios = list(usuarios_col.find({'activo': True, 'username': {'$ne': session['usuario']}})) if usuarios_col else []
    usuario_actual = get_current_user()
    puede_ver = usuario_actual and usuario_actual.get('tipo') == 'abonado'
    return render_template('social.html', usuarios=usuarios, puede_ver_detalles=puede_ver)

# ============== API ==============
@app.route('/api/actividades')
def api_actividades():
    if not actividades_col:
        return jsonify({'error': 'Servicio no disponible'}), 503
    
    hoy = datetime.now().strftime('%Y-%m-%d')
    actividades = list(actividades_col.find({'fecha': {'$gte': hoy}}).sort('fecha', 1))
    
    for a in actividades:
        a['_id'] = str(a['_id'])
    
    return jsonify({'actividades': actividades})

@app.route('/api/usuarios')
@token_required
def api_usuarios():
    if not usuarios_col:
        return jsonify({'error': 'Servicio no disponible'}), 503
    
    usuarios = list(usuarios_col.find({'activo': True}, {'password': 0, 'password_hash': 0}))
    for u in usuarios:
        u['_id'] = str(u['_id'])
    
    return jsonify({'usuarios': usuarios})

# ============== ERRORES ==============
@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', error='Página no encontrada'), 404

@app.errorhandler(500)
def server_error(e):
    return render_template('error.html', error='Error del servidor'), 500

# ============== INICIALIZAR ==============
def init_db():
    usuarios_demo = [
        {
            'username': 'admin',
            'email': 'admin@compartiendomomentos.com',
            'password': 'admin123',
            'password_hash': hash_password('admin123'),
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
            'monedero': 0,
            'token_api': secrets.token_hex(32)
        },
        {
            'username': 'maria',
            'email': 'maria@email.com',
            'password': 'maria123',
            'password_hash': hash_password('maria123'),
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
            'monedero': 0,
            'token_api': secrets.token_hex(32)
        },
        {
            'username': 'juan',
            'email': 'juan@email.com',
            'password': 'juan123',
            'password_hash': hash_password('juan123'),
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
            'monedero': 0,
            'token_api': secrets.token_hex(32)
        }
    ]
    
    if mem_db and not usuarios_col:
        if mem_db.count_documents('usuarios') == 0:
            for u in usuarios_demo:
                mem_db.insert_one('usuarios', u)
        print("[OK] Usuarios de prueba creados (en memoria)")
    elif usuarios_col and usuarios_col.count_documents({}) == 0:
        usuarios_col.insert_many(usuarios_demo)
        print("[OK] Usuarios de prueba creados")

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, port=port, host='0.0.0.0')
