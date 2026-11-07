"""Aplicación académica de Fitness Planet Gym; SQL explícito y formularios en español."""
import hmac
import os
import re
import secrets
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps
from zoneinfo import ZoneInfo

import psycopg2
from dotenv import load_dotenv
from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

import db

load_dotenv()
LIMA = ZoneInfo("America/Lima")
METODOS = ("EFECTIVO", "TARJETA", "YAPE", "PLIN", "TRANSFERENCIA")

# Cada indicador conserva exactamente la consulta que se muestra al profesor.
REPORTES = {
    "ingresos": ("Ingresos del mes", """
SELECT coalesce(sum(monto),0) AS valor FROM pago
WHERE fecha_pago >= date_trunc('month', now() AT TIME ZONE 'America/Lima') AT TIME ZONE 'America/Lima'
  AND fecha_pago < (date_trunc('month', now() AT TIME ZONE 'America/Lima') + interval '1 month') AT TIME ZONE 'America/Lima';"""),
    "activos": ("Clientes activos", """
SELECT count(DISTINCT id_cliente) AS valor FROM vw_inscripciones_estado
WHERE estado_efectivo='ACTIVA'
  AND (now() AT TIME ZONE 'America/Lima')::date BETWEEN fecha_inicio AND fecha_fin;"""),
    "por_vencer": ("Por vencer en 7 días", """
SELECT count(*) AS valor FROM vw_inscripciones_estado
WHERE estado_efectivo='ACTIVA'
  AND fecha_inicio <= (now() AT TIME ZONE 'America/Lima')::date
  AND fecha_fin BETWEEN (now() AT TIME ZONE 'America/Lima')::date
                   AND (now() AT TIME ZONE 'America/Lima')::date + 7;"""),
    "asistencia": ("Asistencia por día · últimos 28 días", """
SELECT extract(isodow FROM fecha_hora_ingreso AT TIME ZONE 'America/Lima')::int AS dia,
       count(*) AS total FROM asistencia
WHERE fecha_hora_ingreso >= (((now() AT TIME ZONE 'America/Lima')::date - 27)::timestamp AT TIME ZONE 'America/Lima')
  AND fecha_hora_ingreso <= now()
GROUP BY dia ORDER BY dia;"""),
    "popular": ("Clase más reservada", """
SELECT c.nombre, count(r.id_reserva) AS total FROM clase c
JOIN reserva r ON r.id_clase=c.id_clase
WHERE r.estado <> 'CANCELADA'
GROUP BY c.id_clase,c.nombre ORDER BY total DESC,c.nombre LIMIT 1;"""),
}
INSCRIPCIONES_SQL = """
SELECT i.*, c.nombres || ' ' || c.apellidos AS cliente, c.dni,
       m.tipo, s.precio,s.pagado,s.saldo
FROM vw_inscripciones_estado i JOIN cliente c USING(id_cliente)
JOIN membresia m USING(id_membresia) JOIN vw_saldos s USING(id_inscripcion)
ORDER BY i.id_inscripcion DESC
"""
CLASES_SQL = """
SELECT c.*, e.nombres || ' ' || e.apellidos AS entrenador,
       count(r.id_reserva) FILTER (WHERE r.estado <> 'CANCELADA') AS ocupados,
       c.capacidad-count(r.id_reserva) FILTER (WHERE r.estado <> 'CANCELADA') AS disponibles
FROM clase c JOIN entrenador e USING(id_entrenador)
LEFT JOIN reserva r ON r.id_clase=c.id_clase AND r.fecha_reserva=%s
GROUP BY c.id_clase,e.id_entrenador ORDER BY c.horario,c.nombre
"""


def hoy():
    """Obtener la fecha comercial sin depender del huso horario del servidor."""
    return datetime.now(LIMA).date()


def texto(nombre, maximo, minimo=1):
    """Recortar espacios y rechazar controles y longitudes fuera de rango."""
    valor = request.form.get(nombre, "").strip()
    if not minimo <= len(valor) <= maximo or any(ord(c) < 32 for c in valor):
        raise ValueError(f"El campo {nombre.replace('_', ' ')} debe tener entre {minimo} y {maximo} caracteres.")
    return valor


def entero(nombre, minimo=1, maximo=9223372036854775807):
    """Validar enteros antes de usarlos como identificadores o cantidades."""
    valor = request.form.get(nombre, "")
    if not re.fullmatch(r"[0-9]{1,19}", valor):
        raise ValueError(f"Revise el campo {nombre.replace('_', ' ')}.")
    numero = int(valor)
    if not minimo <= numero <= maximo:
        raise ValueError(f"El campo {nombre.replace('_', ' ')} está fuera del rango permitido.")
    return numero


def fecha(nombre, formulario=True):
    """Aceptar únicamente fechas ISO completas de formularios HTML."""
    valor = (request.form if formulario else request.args).get(nombre, "")
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", valor):
            raise ValueError
        return date.fromisoformat(valor)
    except ValueError:
        raise ValueError(f"Ingrese una fecha válida en {nombre.replace('_', ' ')}.") from None


def admin_required(funcion):
    """Proteger las operaciones administrativas con una sesión firmada."""
    @wraps(funcion)
    def protegida(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("login"))
        return funcion(*args, **kwargs)
    return protegida


def create_app(test_config=None):
    """Configurar Flask sin abrir conexiones hasta la primera consulta."""
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.getenv("SECRET_KEY"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "true").lower() == "true",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        MAX_CONTENT_LENGTH=64 * 1024,
        ADMIN_USER=os.getenv("ADMIN_USER", ""),
        ADMIN_PASSWORD_HASH=os.getenv("ADMIN_PASSWORD_HASH", ""),
    )
    if not app.config["ADMIN_PASSWORD_HASH"] and os.getenv("ADMIN_PASSWORD"):
        app.config["ADMIN_PASSWORD_HASH"] = generate_password_hash(os.environ["ADMIN_PASSWORD"])
    if test_config:
        app.config.update(test_config)
    if not app.config["SECRET_KEY"] or len(app.config["SECRET_KEY"]) < 32:
        raise RuntimeError("Configure SECRET_KEY con al menos 32 caracteres aleatorios (consulte README.md).")

    @app.before_request
    def proteger_formularios():
        """Exigir un token CSRF en todos los POST, incluido el inicio de sesión."""
        if request.method == "POST":
            esperado = session.get("csrf", "")
            recibido = request.form.get("csrf_token", "")
            if not esperado or not hmac.compare_digest(esperado.encode(), recibido.encode()):
                abort(400, description="El formulario caducó. Recargue la página e inténtelo nuevamente.")

    @app.context_processor
    def contexto():
        if "csrf" not in session:
            session["csrf"] = secrets.token_hex(32)
        return {"csrf_token": session["csrf"], "hoy": hoy(), "metodos": METODOS}

    @app.template_filter("soles")
    def soles(valor):
        return f"S/ {Decimal(valor or 0):,.2f}"

    @app.template_filter("lima")
    def hora_lima(valor):
        return valor.astimezone(LIMA).strftime("%d/%m/%Y %H:%M") if valor else "—"

    @app.template_filter("estado_badge")
    def estado_badge(i):
        if i["estado_efectivo"] != "ACTIVA":
            return ("danger" if i["estado_efectivo"] == "VENCIDA" else "secondary", i["estado_efectivo"].capitalize())
        if i["fecha_inicio"] > hoy():
            return ("info", "Programada")
        if i["fecha_fin"] <= hoy() + timedelta(days=7):
            return ("warning", "Por vencer")
        return ("success", "Activa")

    @app.after_request
    def cabeceras(respuesta):
        respuesta.headers["X-Content-Type-Options"] = "nosniff"
        respuesta.headers["X-Frame-Options"] = "DENY"
        respuesta.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if request.path.startswith("/admin") or request.path == "/login":
            respuesta.headers["Cache-Control"] = "no-store"
        return respuesta

    @app.errorhandler(ValueError)
    def entrada_invalida(error):
        flash(str(error), "warning")
        return redirect(destino_seguro())

    def destino_seguro():
        """Regresar solo a endpoints propios; no redirigir a URLs del cliente."""
        destinos = {"cliente_nuevo": "clientes", "cliente_editar": "clientes", "cliente_eliminar": "clientes",
                    "inscripciones": "inscripciones", "pago_nuevo": "pagos", "asistencia": "asistencia",
                    "clase_nueva": "clases", "reserva_nueva": "clases", "reserva_cancelar": "clases",
                    "rutina_nueva": "rutinas", "rutina_ejercicio": "rutinas", "rutina_asignar": "rutinas"}
        return url_for(destinos.get(request.endpoint, "inicio"))

    @app.errorhandler(psycopg2.Error)
    def error_postgres(error):
        # No mostrar direcciones, credenciales ni detalles internos de conexión.
        codigo = error.pgcode
        if codigo == "23514":
            flash(error.diag.message_primary, "warning")
        elif codigo == "23505":
            flash("Ese registro ya existe. Revise DNI, correo o una reserva/asignación repetida.", "warning")
        elif codigo == "23503":
            flash("El registro tiene relaciones o una referencia dejó de existir. Revise los datos.", "warning")
        elif codigo in ("40001", "40P01", "55P03"):
            flash("Otra operación está usando estos datos. Inténtelo nuevamente.", "warning")
        else:
            app.logger.error("Fallo de PostgreSQL; código=%s", codigo or "conexión")
            return render_template("error.html", titulo="Base de datos no disponible",
                                   mensaje="Revise DATABASE_URL, SSL y la instalación del esquema según el README."), 503
        if request.method == "POST":
            return redirect(destino_seguro())
        return render_template("error.html", titulo="No se pudo consultar", mensaje="Revise los datos e inténtelo nuevamente."), 409

    @app.errorhandler(400)
    @app.errorhandler(404)
    @app.errorhandler(413)
    def error_http(error):
        return render_template("error.html", titulo=f"Error {error.code}", mensaje=error.description), error.code

    @app.get("/health")
    def health():
        # Render puede comprobar el proceso sin consumir conexiones del pool.
        return {"estado": "ok"}

    @app.get("/")
    def inicio():
        planes = db.fetch_all("SELECT * FROM membresia ORDER BY precio")
        clases = db.fetch_all(CLASES_SQL, (hoy(),))
        return render_template("inicio.html", planes=planes, clases=clases)

    @app.get("/calendario")
    def calendario():
        dia = fecha("fecha", False) if request.args.get("fecha") else hoy()
        return render_template("calendario.html", clases=db.fetch_all(CLASES_SQL, (dia,)), dia=dia)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            usuario = request.form.get("usuario", "")[:100]
            clave = request.form.get("password", "")
            configurado = bool(app.config["ADMIN_USER"] and app.config["ADMIN_PASSWORD_HASH"])
            if configurado and len(clave) <= 256 and hmac.compare_digest(usuario.encode(), app.config["ADMIN_USER"].encode()) and check_password_hash(app.config["ADMIN_PASSWORD_HASH"], clave):
                session.clear()
                session.update(admin=True, csrf=secrets.token_hex(32))
                session.permanent = True
                return redirect(url_for("dashboard"))
            flash("Credenciales inválidas o administrador sin configurar.", "danger")
        return render_template("login.html")

    @app.post("/logout")
    @admin_required
    def logout():
        session.clear()
        return redirect(url_for("inicio"))

    @app.get("/admin")
    @admin_required
    def dashboard():
        resultados = {clave: db.fetch_all(sql) for clave, (_, sql) in REPORTES.items()}
        dias = {fila["dia"]: fila["total"] for fila in resultados["asistencia"]}
        semana = [(nombre, dias.get(n, 0)) for n, nombre in enumerate(("Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"), 1)]
        return render_template("dashboard.html", datos=resultados, reportes=REPORTES, semana=semana,
                               max_asistencia=max([v for _, v in semana] + [1]))

    @app.get("/admin/clientes")
    @admin_required
    def clientes():
        busqueda = request.args.get("q", "").strip()[:80]
        filas = db.fetch_all("""SELECT * FROM cliente WHERE %s='' OR dni=%s OR apellidos ILIKE %s
                               ORDER BY apellidos,nombres""", (busqueda, busqueda, "%" + busqueda + "%"))
        return render_template("clientes.html", clientes=filas, busqueda=busqueda)

    def datos_cliente():
        dni = texto("dni", 8, 8)
        telefono = texto("telefono", 20, 7)
        correo = texto("correo", 150, 5).lower()
        nacimiento = fecha("fecha_nacimiento")
        if not re.fullmatch(r"[0-9]{8}", dni):
            raise ValueError("El DNI debe tener exactamente 8 dígitos.")
        if not re.fullmatch(r"\+?[0-9 ()-]{7,20}", telefono):
            raise ValueError("Ingrese un teléfono válido.")
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", correo):
            raise ValueError("Ingrese un correo válido.")
        if not date(1900, 1, 1) <= nacimiento <= hoy():
            raise ValueError("La fecha de nacimiento debe estar entre 1900 y hoy.")
        return (texto("nombres", 80), texto("apellidos", 100), dni, telefono, correo, nacimiento)

    @app.route("/admin/clientes/nuevo", methods=["GET", "POST"])
    @admin_required
    def cliente_nuevo():
        if request.method == "POST":
            db.execute("INSERT INTO cliente(nombres,apellidos,dni,telefono,correo,fecha_nacimiento) VALUES (%s,%s,%s,%s,%s,%s)", datos_cliente())
            flash("Cliente registrado.", "success")
            return redirect(url_for("clientes"))
        return render_template("cliente_form.html", cliente=None)

    @app.route("/admin/clientes/<int:identificador>/editar", methods=["GET", "POST"])
    @admin_required
    def cliente_editar(identificador):
        cliente = db.fetch_one("SELECT * FROM cliente WHERE id_cliente=%s", (identificador,))
        if not cliente:
            abort(404)
        if request.method == "POST":
            db.execute("UPDATE cliente SET nombres=%s,apellidos=%s,dni=%s,telefono=%s,correo=%s,fecha_nacimiento=%s WHERE id_cliente=%s", datos_cliente() + (identificador,))
            flash("Cliente actualizado.", "success")
            return redirect(url_for("clientes"))
        return render_template("cliente_form.html", cliente=cliente)

    @app.post("/admin/clientes/<int:identificador>/eliminar")
    @admin_required
    def cliente_eliminar(identificador):
        db.execute("DELETE FROM cliente WHERE id_cliente=%s", (identificador,))
        flash("Cliente eliminado si existía. Las inscripciones vinculadas impiden eliminarlo.", "success")
        return redirect(url_for("clientes"))

    @app.route("/admin/inscripciones", methods=["GET", "POST"])
    @admin_required
    def inscripciones():
        if request.method == "POST":
            db.execute("INSERT INTO inscripcion(id_cliente,id_membresia,fecha_inicio) VALUES (%s,%s,%s)",
                       (entero("id_cliente"), entero("id_membresia"), fecha("fecha_inicio")))
            flash("Inscripción creada. PostgreSQL calculó la fecha de fin.", "success")
            return redirect(url_for("inscripciones"))
        return render_template("inscripciones.html", filas=db.fetch_all(INSCRIPCIONES_SQL),
                               clientes=db.fetch_all("SELECT * FROM cliente ORDER BY apellidos"),
                               planes=db.fetch_all("SELECT * FROM membresia ORDER BY precio"))

    @app.get("/admin/pagos")
    @admin_required
    def pagos():
        movimientos = db.fetch_all("""SELECT p.*,c.nombres || ' ' || c.apellidos AS cliente
            FROM pago p JOIN inscripcion i USING(id_inscripcion) JOIN cliente c USING(id_cliente)
            ORDER BY p.fecha_pago DESC,p.id_pago DESC""")
        return render_template("pagos.html", filas=db.fetch_all(INSCRIPCIONES_SQL), pagos=movimientos)

    @app.post("/admin/pagos")
    @admin_required
    def pago_nuevo():
        identificador = entero("id_inscripcion")
        metodo = texto("metodo_pago", 15)
        if metodo not in METODOS:
            raise ValueError("Seleccione un método de pago válido.")
        try:
            bruto = request.form.get("monto", "")
            if not re.fullmatch(r"[0-9]{1,8}(\.[0-9]{1,2})?", bruto):
                raise InvalidOperation
            monto = Decimal(bruto)
            if monto <= 0:
                raise InvalidOperation
        except InvalidOperation:
            raise ValueError("Ingrese un monto positivo con hasta dos decimales.") from None
        with db.transaction() as cursor:
            cursor.execute("SELECT id_inscripcion FROM inscripcion WHERE id_inscripcion=%s FOR UPDATE", (identificador,))
            if not cursor.fetchone():
                raise ValueError("La inscripción no existe.")
            cursor.execute("SELECT saldo FROM vw_saldos WHERE id_inscripcion=%s", (identificador,))
            if monto > cursor.fetchone()["saldo"]:
                raise ValueError("El pago supera el saldo pendiente de la inscripción.")
            cursor.execute("INSERT INTO pago(id_inscripcion,monto,metodo_pago) VALUES (%s,%s,%s)", (identificador, monto, metodo))
        flash("Pago registrado y saldo actualizado.", "success")
        return redirect(url_for("pagos"))

    @app.route("/admin/asistencia", methods=["GET", "POST"])
    @admin_required
    def asistencia():
        if request.method == "POST":
            dni = texto("dni", 8, 8)
            if not re.fullmatch(r"[0-9]{8}", dni):
                raise ValueError("El DNI debe tener 8 dígitos.")
            with db.transaction() as cursor:
                cursor.execute("""SELECT i.id_inscripcion FROM inscripcion i JOIN cliente c USING(id_cliente)
                    WHERE c.dni=%s AND i.estado='ACTIVA' AND %s BETWEEN i.fecha_inicio AND i.fecha_fin
                    ORDER BY i.fecha_fin DESC,i.id_inscripcion DESC LIMIT 1 FOR UPDATE OF i""", (dni, hoy()))
                inscripcion = cursor.fetchone()
                if not inscripcion:
                    raise ValueError("El DNI no tiene una inscripción ACTIVA y vigente.")
                cursor.execute("INSERT INTO asistencia(id_inscripcion) VALUES (%s)", (inscripcion["id_inscripcion"],))
            flash("Ingreso registrado. ¡Buen entrenamiento!", "success")
            return redirect(url_for("asistencia"))
        ingresos = db.fetch_all("""SELECT a.*,c.nombres || ' ' || c.apellidos AS cliente,c.dni
            FROM asistencia a JOIN inscripcion i USING(id_inscripcion) JOIN cliente c USING(id_cliente)
            WHERE (a.fecha_hora_ingreso AT TIME ZONE 'America/Lima')::date=%s
            ORDER BY a.fecha_hora_ingreso DESC""", (hoy(),))
        return render_template("asistencia.html", ingresos=ingresos)

    @app.get("/admin/clases")
    @admin_required
    def clases():
        dia = fecha("fecha", False) if request.args.get("fecha") else hoy()
        reservas = db.fetch_all("""SELECT r.*, c.nombre, cl.nombres || ' ' || cl.apellidos AS cliente,cl.dni
            FROM reserva r JOIN clase c USING(id_clase) JOIN inscripcion i USING(id_inscripcion)
            JOIN cliente cl USING(id_cliente) WHERE r.fecha_reserva=%s ORDER BY c.horario,r.id_reserva""", (dia,))
        activas = [i for i in db.fetch_all(INSCRIPCIONES_SQL) if i["estado_efectivo"] == "ACTIVA" and i["fecha_inicio"] <= hoy() <= i["fecha_fin"]]
        return render_template("clases.html", dia=dia, clases=db.fetch_all(CLASES_SQL, (dia,)),
                               reservas=reservas, inscripciones=activas,
                               entrenadores=db.fetch_all("SELECT * FROM entrenador ORDER BY apellidos"))

    @app.post("/admin/clases/nueva")
    @admin_required
    def clase_nueva():
        try:
            horario = datetime.strptime(request.form.get("horario", ""), "%H:%M").time()
        except ValueError:
            raise ValueError("Ingrese un horario válido.") from None
        db.execute("INSERT INTO clase(nombre,horario,capacidad,id_entrenador) VALUES (%s,%s,%s,%s)",
                   (texto("nombre", 60), horario, entero("capacidad", 1, 200), entero("id_entrenador")))
        flash("Clase creada en el calendario diario.", "success")
        return redirect(url_for("clases"))

    @app.post("/admin/reservas")
    @admin_required
    def reserva_nueva():
        dia = fecha("fecha_reserva")
        inscripcion = entero("id_inscripcion")
        clase = entero("id_clase")
        # Reactivar una cancelada respeta el UNIQUE; el trigger vuelve a validar el cupo.
        db.execute("""INSERT INTO reserva(id_inscripcion,id_clase,fecha_reserva) VALUES (%s,%s,%s)
            ON CONFLICT (id_inscripcion,id_clase,fecha_reserva) DO UPDATE SET estado='CONFIRMADA'""", (inscripcion, clase, dia))
        flash("Reserva confirmada.", "success")
        return redirect(url_for("clases", fecha=dia.isoformat()))

    @app.post("/admin/reservas/<int:identificador>/cancelar")
    @admin_required
    def reserva_cancelar(identificador):
        db.execute("UPDATE reserva SET estado='CANCELADA' WHERE id_reserva=%s", (identificador,))
        flash("Reserva cancelada; cupo liberado.", "success")
        return redirect(url_for("clases"))

    @app.get("/admin/rutinas")
    @admin_required
    def rutinas():
        filas = db.fetch_all("SELECT * FROM rutina ORDER BY id_rutina DESC")
        ejercicios_asignados = db.fetch_all("""SELECT re.*,e.nombre,e.descripcion,e.tipo FROM rutina_ejercicio re
            JOIN ejercicio e USING(id_ejercicio) ORDER BY re.id_rutina,re.id_rutina_ejercicio""")
        por_rutina = {}
        for ejercicio in ejercicios_asignados:
            por_rutina.setdefault(ejercicio["id_rutina"], []).append(ejercicio)
        asignaciones = db.fetch_all("""SELECT a.*,r.nombre,c.nombres || ' ' || c.apellidos AS cliente
            FROM asignacion_rutina a JOIN rutina r USING(id_rutina) JOIN inscripcion i USING(id_inscripcion)
            JOIN cliente c USING(id_cliente) ORDER BY a.fecha_asignacion DESC,a.id_asignacion DESC""")
        return render_template("rutinas.html", rutinas=filas, por_rutina=por_rutina, asignaciones=asignaciones,
                               ejercicios=db.fetch_all("SELECT * FROM ejercicio ORDER BY nombre"),
                               inscripciones=db.fetch_all(INSCRIPCIONES_SQL))

    @app.post("/admin/rutinas")
    @admin_required
    def rutina_nueva():
        nombre, objetivo = texto("nombre", 80), texto("objetivo", 200)
        seleccion = request.form.getlist("ejercicios")
        if not seleccion or len(seleccion) > 100 or len(seleccion) != len(set(seleccion)):
            raise ValueError("Seleccione al menos un ejercicio, sin repetirlo.")
        detalles = []
        for identificador in seleccion:
            if not re.fullmatch(r"[0-9]{1,19}", identificador) or not 1 <= int(identificador) <= 9223372036854775807:
                raise ValueError("Ejercicio inválido.")
            detalles.append((int(identificador), entero("series_" + identificador, 1, 20),
                             entero("repeticiones_" + identificador, 1, 200), entero("descanso_" + identificador, 0, 600)))
        with db.transaction() as cursor:
            cursor.execute("INSERT INTO rutina(nombre,objetivo) VALUES (%s,%s) RETURNING id_rutina", (nombre, objetivo))
            nueva = cursor.fetchone()["id_rutina"]
            for detalle in detalles:
                cursor.execute("INSERT INTO rutina_ejercicio(id_rutina,id_ejercicio,series,repeticiones,descanso_seg) VALUES (%s,%s,%s,%s,%s)", (nueva,) + detalle)
        flash("Rutina y ejercicios guardados en una sola transacción.", "success")
        return redirect(url_for("rutinas"))

    @app.post("/admin/rutinas/ejercicio")
    @admin_required
    def rutina_ejercicio():
        db.execute("INSERT INTO rutina_ejercicio(id_rutina,id_ejercicio,series,repeticiones,descanso_seg) VALUES (%s,%s,%s,%s,%s)",
                   (entero("id_rutina"), entero("id_ejercicio"), entero("series", 1, 20), entero("repeticiones", 1, 200), entero("descanso_seg", 0, 600)))
        flash("Ejercicio agregado a la rutina.", "success")
        return redirect(url_for("rutinas"))

    @app.post("/admin/rutinas/asignar")
    @admin_required
    def rutina_asignar():
        db.execute("INSERT INTO asignacion_rutina(id_inscripcion,id_rutina) VALUES (%s,%s)", (entero("id_inscripcion"), entero("id_rutina")))
        flash("Rutina asignada a la inscripción.", "success")
        return redirect(url_for("rutinas"))

    return app


app = create_app()

if __name__ == "__main__":
    # El depurador queda desactivado; en producción se usa gunicorn.
    app.run(host="127.0.0.1", port=5000)
