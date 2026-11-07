"""Pruebas reales en una base nueva; jamás se reutiliza la base de la aplicación."""
import os
import uuid
from pathlib import Path

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import make_dsn
import pytest

# Las credenciales efímeras solo pertenecen al proceso de pruebas.
os.environ.setdefault('SECRET_KEY', uuid.uuid4().hex + uuid.uuid4().hex)


@pytest.fixture(scope='session')
def database_url():
    """Crear una base aislada; TEST_DATABASE_URL necesita permiso CREATEDB."""
    origen = os.getenv('TEST_DATABASE_URL')
    if not origen:
        pytest.skip('Defina TEST_DATABASE_URL de un PostgreSQL local con permiso CREATEDB.')
    nombre = 'fitness_test_' + uuid.uuid4().hex
    administrador = psycopg2.connect(origen)
    administrador.autocommit = True
    with administrador.cursor() as cursor:
        cursor.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(nombre)))
    destino = make_dsn(origen, dbname=nombre)
    with psycopg2.connect(destino) as connection:
        with connection.cursor() as cursor:
            cursor.execute(Path('sql/schema_y_datos.sql').read_text())
    os.environ['DATABASE_URL'] = destino
    yield destino
    import db
    if db._pool:
        db._pool.closeall()
        db._pool = None
    with administrador.cursor() as cursor:
        cursor.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(nombre)))
    administrador.close()


@pytest.fixture
def connection(database_url):
    """Revertir las modificaciones SQL de cada prueba unitaria de integración."""
    connection = psycopg2.connect(database_url)
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


@pytest.fixture
def app(database_url):
    from app import create_app
    from werkzeug.security import generate_password_hash
    return create_app({'TESTING': True, 'SESSION_COOKIE_SECURE': False,
                       'ADMIN_USER': 'operador_pruebas',
                       'ADMIN_PASSWORD_HASH': generate_password_hash('clave-efimera-de-prueba')})


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin(client):
    """Autenticar por la ruta real con CSRF, sin falsificar la sesión."""
    client.get('/login')
    with client.session_transaction() as sesion:
        token = sesion['csrf']
    respuesta = client.post('/login', data={'usuario': 'operador_pruebas',
        'password': 'clave-efimera-de-prueba', 'csrf_token': token})
    assert respuesta.status_code == 302 and respuesta.location.endswith('/admin')
    return client


def formulario(client, datos):
    """Incluir el token de la sesión que utiliza el navegador de prueba."""
    with client.session_transaction() as sesion:
        return dict(datos, csrf_token=sesion['csrf'])
