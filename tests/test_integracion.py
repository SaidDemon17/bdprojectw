"""Verificar restricciones, concurrencia, seguridad y recorridos administrativos."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import psycopg2
import pytest

from conftest import formulario


def test_modelo_y_datos(connection):
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM pg_tables WHERE schemaname='public' AND rowsecurity")
        assert cursor.fetchone()[0] == 12
        for tabla, cantidad in [('cliente',15),('membresia',3),('entrenador',5),('clase',8),('inscripcion',20),('ejercicio',10),('rutina',4)]:
            # Los identificadores de esta lista son constantes internas de la prueba.
            from psycopg2 import sql
            cursor.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier(tabla)))
            assert cursor.fetchone()[0] >= cantidad
        cursor.execute('SELECT count(*) FROM inscripcion i JOIN membresia m USING(id_membresia) WHERE i.fecha_fin <> i.fecha_inicio+m.duracion_dias')
        assert cursor.fetchone()[0] == 0
        cursor.execute("SELECT estado,estado_efectivo FROM vw_inscripciones_estado WHERE id_inscripcion=14")
        assert cursor.fetchone() == ('ACTIVA', 'VENCIDA')


def test_pago_excesivo_y_actualizacion(connection):
    with connection.cursor() as cursor:
        cursor.execute("INSERT INTO pago(id_inscripcion,monto,metodo_pago) VALUES (1,20,'PLIN') RETURNING id_pago")
        identificador = cursor.fetchone()[0]
        with pytest.raises(psycopg2.errors.CheckViolation, match='saldo pendiente'):
            cursor.execute('UPDATE pago SET monto=61 WHERE id_pago=%s', (identificador,))


@pytest.mark.parametrize('tabla', ['asistencia', 'reserva'])
def test_rechazo_inscripcion_vencida(connection, tabla):
    with connection.cursor() as cursor:
        with pytest.raises(psycopg2.errors.CheckViolation, match='ACTIVA'):
            if tabla == 'asistencia':
                cursor.execute('INSERT INTO asistencia(id_inscripcion) VALUES (11)')
            else:
                cursor.execute("INSERT INTO reserva(id_inscripcion,id_clase,fecha_reserva) VALUES (11,1,(now() AT TIME ZONE 'America/Lima')::date)")


def test_reserva_fuera_de_vigencia(connection):
    with connection.cursor() as cursor:
        with pytest.raises(psycopg2.errors.CheckViolation, match='fecha elegida'):
            cursor.execute("INSERT INTO reserva(id_inscripcion,id_clase,fecha_reserva) VALUES (1,2,(now() AT TIME ZONE 'America/Lima')::date+10)")


def test_cupo_cancelacion_y_reactivacion(connection):
    with connection.cursor() as cursor:
        cursor.execute("INSERT INTO clase(nombre,horario,capacidad,id_entrenador) VALUES ('Cupo de prueba','10:00',1,1) RETURNING id_clase")
        clase = cursor.fetchone()[0]
        cursor.execute("INSERT INTO reserva(id_inscripcion,id_clase,fecha_reserva,estado) VALUES (6,%s,(now() AT TIME ZONE 'America/Lima')::date,'PENDIENTE') RETURNING id_reserva", (clase,))
        reserva = cursor.fetchone()[0]
        cursor.execute('SAVEPOINT antes_exceso')
        with pytest.raises(psycopg2.errors.CheckViolation, match='cupos'):
            cursor.execute("INSERT INTO reserva(id_inscripcion,id_clase,fecha_reserva) VALUES (7,%s,(now() AT TIME ZONE 'America/Lima')::date)", (clase,))
        cursor.execute('ROLLBACK TO SAVEPOINT antes_exceso')
        cursor.execute("UPDATE reserva SET estado='CANCELADA' WHERE id_reserva=%s", (reserva,))
        cursor.execute("INSERT INTO reserva(id_inscripcion,id_clase,fecha_reserva) VALUES (7,%s,(now() AT TIME ZONE 'America/Lima')::date)", (clase,))
        with pytest.raises(psycopg2.errors.CheckViolation, match='cupos'):
            cursor.execute("UPDATE reserva SET estado='CONFIRMADA' WHERE id_reserva=%s", (reserva,))


def test_rangos_futuros_y_limites_inclusivos(connection):
    with connection.cursor() as cursor:
        cursor.execute("INSERT INTO inscripcion(id_cliente,id_membresia,fecha_inicio) VALUES (1,1,(now() AT TIME ZONE 'America/Lima')::date-30) RETURNING id_inscripcion")
        ultima = cursor.fetchone()[0]
        cursor.execute('INSERT INTO asistencia(id_inscripcion) VALUES (%s)', (ultima,))
        cursor.execute("INSERT INTO inscripcion(id_cliente,id_membresia,fecha_inicio) VALUES (1,1,(now() AT TIME ZONE 'America/Lima')::date+1) RETURNING id_inscripcion")
        futura = cursor.fetchone()[0]
        with pytest.raises(psycopg2.errors.CheckViolation):
            cursor.execute('INSERT INTO asistencia(id_inscripcion) VALUES (%s)', (futura,))


@pytest.mark.parametrize('operacion', ['pago', 'reserva'])
def test_operaciones_concurrentes(database_url, operacion):
    """Dos conexiones reales compiten por el saldo o el último cupo."""
    with psycopg2.connect(database_url) as connection:
        with connection.cursor() as cursor:
            if operacion == 'pago':
                cursor.execute("INSERT INTO inscripcion(id_cliente,id_membresia,fecha_inicio) VALUES (15,1,(now() AT TIME ZONE 'America/Lima')::date) RETURNING id_inscripcion")
            else:
                cursor.execute("INSERT INTO clase(nombre,horario,capacidad,id_entrenador) VALUES ('Concurrencia','11:00',1,1) RETURNING id_clase")
            identificador = cursor.fetchone()[0]
    barrera = Barrier(2)

    def competir(numero):
        connection = psycopg2.connect(database_url)
        try:
            barrera.wait(timeout=10)
            with connection:
                with connection.cursor() as cursor:
                    if operacion == 'pago':
                        cursor.execute("INSERT INTO pago(id_inscripcion,monto,metodo_pago) VALUES (%s,80,'YAPE')", (identificador,))
                    else:
                        cursor.execute("INSERT INTO reserva(id_inscripcion,id_clase,fecha_reserva) VALUES (%s,%s,(now() AT TIME ZONE 'America/Lima')::date)", (numero+6, identificador))
            return 'aceptado'
        except psycopg2.errors.CheckViolation:
            return 'rechazado'
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        resultados = list(executor.map(competir, (0,1)))
    assert sorted(resultados) == ['aceptado','rechazado']


def test_rls_sin_politica_publica(connection):
    with connection.cursor() as cursor:
        cursor.execute("CREATE ROLE visitante_prueba NOLOGIN")
        cursor.execute('GRANT USAGE ON SCHEMA public TO visitante_prueba')
        cursor.execute('GRANT SELECT ON cliente,vw_inscripciones_estado,inscripcion TO visitante_prueba')
        cursor.execute('SET LOCAL ROLE visitante_prueba')
        cursor.execute('SELECT count(*) FROM cliente')
        assert cursor.fetchone()[0] == 0
        cursor.execute('SELECT count(*) FROM vw_inscripciones_estado')
        assert cursor.fetchone()[0] == 0


def test_login_csrf_y_proteccion(client):
    assert client.get('/admin').status_code == 302
    assert client.post('/login', data={'usuario': 'intruso'}).status_code == 400
    client.get('/login')
    respuesta = client.post('/login', data=formulario(client, {'usuario': 'intruso','password': 'incorrecta'}), follow_redirects=True)
    assert b'Credenciales inv' in respuesta.data
    assert client.get('/admin/pagos').status_code == 302


@pytest.mark.parametrize('ruta', ['/', '/calendario', '/login', '/health'])
def test_rutas_publicas(client, ruta):
    assert client.get(ruta).status_code == 200


@pytest.mark.parametrize('ruta', ['/admin','/admin/clientes','/admin/clientes/nuevo','/admin/inscripciones','/admin/pagos','/admin/asistencia','/admin/clases','/admin/rutinas'])
def test_panel_completo(admin, ruta):
    respuesta = admin.get(ruta)
    assert respuesta.status_code == 200
    assert b'Traceback' not in respuesta.data


def test_crud_cliente_y_validacion(admin):
    datos = {'nombres': 'Prueba <script>alert(1)</script>', 'apellidos': 'Integración',
             'dni': '80000101','telefono':'987654321','correo':'integracion@example.com','fecha_nacimiento':'2000-01-01'}
    assert admin.post('/admin/clientes/nuevo', data=formulario(admin, datos)).status_code == 302
    import db
    cliente = db.fetch_one('SELECT * FROM cliente WHERE dni=%s', (datos['dni'],))
    respuesta = admin.get('/admin/clientes?q=80000101')
    assert b'&lt;script&gt;' in respuesta.data and b'<script>alert(1)' not in respuesta.data
    datos['nombres'] = 'Cliente actualizado'
    ruta = f"/admin/clientes/{cliente['id_cliente']}/editar"
    admin.post(ruta, data=formulario(admin, datos))
    assert db.fetch_one('SELECT nombres FROM cliente WHERE dni=%s', (datos['dni'],))['nombres'] == 'Cliente actualizado'
    datos['dni'] = 'invalido'
    respuesta = admin.post(ruta, data=formulario(admin, datos), follow_redirects=True)
    assert b'8 d' in respuesta.data
    admin.post(f"/admin/clientes/{cliente['id_cliente']}/eliminar", data=formulario(admin, {}))
    assert db.fetch_one('SELECT * FROM cliente WHERE id_cliente=%s', (cliente['id_cliente'],)) is None


def test_flujo_inscripcion_pago_asistencia_y_rutina(admin):
    import db
    from app import hoy
    admin.post('/admin/inscripciones', data=formulario(admin, {'id_cliente':15, 'id_membresia':2, 'fecha_inicio':hoy().isoformat()}))
    inscripcion = db.fetch_one('SELECT * FROM inscripcion ORDER BY id_inscripcion DESC LIMIT 1')
    identificador = inscripcion['id_inscripcion']
    assert (inscripcion['fecha_fin']-inscripcion['fecha_inicio']).days == 90
    admin.post('/admin/pagos', data=formulario(admin, {'id_inscripcion':identificador,'monto':'100.50','metodo_pago':'YAPE'}))
    assert str(db.fetch_one('SELECT saldo FROM vw_saldos WHERE id_inscripcion=%s', (identificador,))['saldo']) == '219.50'
    respuesta = admin.post('/admin/pagos', data=formulario(admin, {'id_inscripcion':identificador,'monto':'220','metodo_pago':'YAPE'}), follow_redirects=True)
    assert b'supera el saldo' in respuesta.data
    admin.post('/admin/asistencia', data=formulario(admin, {'dni':'70123415'}))
    assert db.fetch_one('SELECT count(*) AS n FROM asistencia WHERE id_inscripcion=%s', (identificador,))['n'] == 1
    admin.post('/admin/rutinas', data=formulario(admin, {'nombre':'Rutina de integración','objetivo':'Probar atomicidad',
        'ejercicios':['1','2'],'series_1':3,'repeticiones_1':12,'descanso_1':60,'series_2':4,'repeticiones_2':10,'descanso_2':90}))
    rutina = db.fetch_one('SELECT id_rutina FROM rutina ORDER BY id_rutina DESC LIMIT 1')['id_rutina']
    admin.post('/admin/rutinas/asignar', data=formulario(admin, {'id_inscripcion':identificador,'id_rutina':rutina}))
    assert db.fetch_one('SELECT count(*) AS n FROM asignacion_rutina WHERE id_inscripcion=%s AND id_rutina=%s', (identificador,rutina))['n'] == 1
    assert db.fetch_one('SELECT count(*) AS n FROM rutina_ejercicio WHERE id_rutina=%s', (rutina,))['n'] == 2
    admin.post('/logout', data=formulario(admin, {}))
    assert admin.get('/admin').status_code == 302
