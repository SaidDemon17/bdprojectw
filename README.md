# Fitness Planet Gym

Aplicación académica para **Teoría y Diseño de Base de Datos**, desarrollada con Python 3.11+, Flask, Jinja2, Bootstrap 5, psycopg2 y PostgreSQL 15+. No utiliza ORM: todas las consultas se encuentran en `app.py`, `db.py` y el script SQL. Empresa ficticia peruana; zona horaria `America/Lima`, moneda soles (S/).

## Funcionalidades

- Sitio público con planes provenientes de la base y calendario diario con entrenador y cupos.
- Login administrativo con sesión firmada, contraseña Werkzeug y CSRF en todos los POST.
- Clientes: alta, búsqueda por DNI exacto o apellido, edición y eliminación si no hay inscripciones relacionadas.
- Inscripciones con fin automático, estado registrado/efectivo y avisos de vencimiento.
- Pagos parciales por cinco métodos, historial y saldo por inscripción.
- Asistencia por DNI, solo con inscripción activa y vigente.
- Clases diarias, creación de clases, reservas por fecha, cancelación y reactivación.
- Rutinas con múltiples ejercicios, series, repeticiones y descansos; asignaciones a inscripciones.
- Dashboard con ingresos del mes, clientes activos, próximos vencimientos, asistencia por día y clase más reservada. Cada consulta ejecutada se puede abrir en un acordeón.

## Estructura

```text
app.py                         Rutas, validaciones y consultas SQL explícitas
db.py                          Pool por proceso y transacciones
sql/schema_y_datos.sql          12 tablas, datos, índices, vistas, funciones, triggers y RLS
templates/base.html            Herencia, navegación y mensajes
 templates/macros.html         Campos, CSRF, estados y tabla de clases
 templates/inicio.html         Portada y planes
 templates/calendario.html     Cupos por fecha
 templates/login.html          Acceso administrativo
 templates/dashboard.html      Indicadores y SQL ejecutado
 templates/clientes.html        Búsqueda y directorio
 templates/cliente_form.html    Alta y edición
 templates/inscripciones.html   Vigencias y nuevas inscripciones
 templates/pagos.html           Cobros y saldos
 templates/asistencia.html      Control de ingreso
 templates/clases.html          Calendario, creación de clases y reservas
 templates/rutinas.html         Ejercicios y asignaciones
 templates/error.html           Errores sin detalles sensibles
static/css/style.css           Identidad deportiva y diseño adaptable
requirements.txt               Dependencias de producción
requirements-dev.txt           Dependencias de pruebas
Procfile                       Inicio de gunicorn
.env.example                   Variables sin secretos
.gitignore                     Exclusiones locales
tests/                         Pruebas con una base PostgreSQL temporal
SUSTENTACION_SQL.md             Explicación del modelo y consultas
```

## 1. Crear la base en Supabase

1. Crear una cuenta en Supabase y un proyecto nuevo. Elegir una región cercana y guardar la contraseña de la base de datos en un gestor de contraseñas.
2. Esperar a que termine el aprovisionamiento. Abrir **SQL Editor → New query**.
3. Copiar **todo** `sql/schema_y_datos.sql` y ejecutarlo una vez en el esquema `public` vacío. Incluye `BEGIN/COMMIT`: si algo falla no debe quedar una instalación parcial.
4. Verificar las 12 tablas, `vw_inscripciones_estado` y `vw_saldos` en el explorador de base de datos. El script habilita RLS en todas las tablas.
5. Comprobar `SELECT count(*) FROM public.cliente;` (15) y `SELECT count(*) FROM public.inscripcion;` (20).

El script no borra tablas ni incluye `DROP TABLE`. No es una migración idempotente: ejecutarlo otra vez devuelve `relation already exists`. Para repetir la demostración, crear otra base/proyecto de prueba; para un proyecto con datos, escribir una migración específica. Todos los nombres, correos `example.com` y DNI de muestra son ficticios.

### Obtener la cadena del pooler

En **Connect** del proyecto, seleccionar **Transaction pooler** (habitualmente puerto 6543) o **Session pooler** (habitualmente 5432) y copiar la URI exacta presentada por Supabase. El usuario suele ser `postgres.PROJECT_REF`; el hostname y región varían. No copiar el host directo `db.PROJECT_REF.supabase.co` si la red de Render solo permite IPv4.

Sustituir la contraseña localmente y agregar `?sslmode=require` (si ya hay parámetros, usar `&sslmode=require`). Una plantilla se encuentra en `.env.example`. No utilizar la URL HTTP de la API ni una clave `anon`/`service_role` como contraseña PostgreSQL.

Si la contraseña tiene `@`, `:`, `/`, `#`, `%` u otros caracteres reservados, codificar **solo la contraseña**, no la URI completa. Puede hacerse sin mostrarla en el terminal:

```python
# Ejecutar en una sesión local privada; pegar el resultado solo en las variables del entorno.
from getpass import getpass
from urllib.parse import quote
print(quote(getpass('Contraseña de PostgreSQL: '), safe=''))
```

Este proyecto es compatible con Transaction pooler: usa transacciones breves y consultas normales de psycopg2, sin `PREPARE`, tablas temporales persistentes ni estado de sesión requerido entre transacciones. Cada consulta de fecha usa explícitamente Lima. No usa la API REST de Supabase.

## 2. Configurar y ejecutar localmente

Desde la raíz del repositorio:

```bash
python --version
python -m venv .venv
source .venv/bin/activate
# En Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env
```

Crear una clave aleatoria:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Copiar el resultado a `SECRET_KEY`. Debe tener al menos 32 caracteres. Crear un hash de contraseña con entrada oculta:

```bash
python -c "from getpass import getpass; from werkzeug.security import generate_password_hash; print(generate_password_hash(getpass('Contraseña del administrador: ')))"
```

Completar `.env`:

| Variable | Uso |
| --- | --- |
| `DATABASE_URL` | URI PostgreSQL del pooler con SSL |
| `SECRET_KEY` | Secreto aleatorio para firmar sesiones y tokens CSRF |
| `ADMIN_USER` | Usuario administrativo elegido |
| `ADMIN_PASSWORD_HASH` | Hash completo generado por Werkzeug; entre comillas simples en `.env` |
| `ADMIN_PASSWORD` | Alternativa para desarrollo: se transforma a hash en memoria al arrancar. Preferir `ADMIN_PASSWORD_HASH` |
| `SESSION_COOKIE_SECURE` | `false` para HTTP local; **`true`** para Render HTTPS |
| `DB_POOL_MAX` | Máximo de conexiones por proceso, predeterminado 5 |

Si se definen hash y contraseña, prevalece el hash. No hay usuario o contraseña predeterminados. No compartir `.env`, hashes ni URLs completas en capturas, commits o mensajes. Reiniciar el proceso al cambiar variables.

```bash
python app.py
```

Abrir `http://127.0.0.1:5000`. El acceso administrativo está en `/login`. El comando `python app.py` es solo para desarrollo y tiene el depurador desactivado.

## 3. Desplegar en Render

1. Subir los archivos a un repositorio GitHub propio y conectar ese repositorio con Render. No subir `.env`.
2. Crear **New → Web Service**, seleccionar el repositorio y su rama. Elegir runtime **Python 3** y dejar **Root Directory** vacío si los archivos están en la raíz.
3. Configurar:

   | Ajuste | Valor |
   | --- | --- |
   | Build Command | `pip install -r requirements.txt` |
   | Start Command | `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --threads 2 --timeout 60` |
   | Health Check Path | `/health` |
   | Variable `PYTHON_VERSION` | `3.11.11` (o una versión compatible 3.11+ admitida por Render) |

4. Añadir `DATABASE_URL`, `SECRET_KEY`, `ADMIN_USER` y `ADMIN_PASSWORD_HASH` en **Environment**. Pegar los valores reales sin comillas de `.env`. Añadir `SESSION_COOKIE_SECURE=true` y `DB_POOL_MAX=3`.
5. Crear el servicio y esperar al despliegue. Abrir la URL HTTPS, revisar los planes y entrar al panel.
6. Si se cambia una variable, usar el reinicio o redespliegue del servicio. Revisar **Logs** ante errores sin publicar secretos.

El `Procfile` contiene exactamente `web: gunicorn app:app`, también utilizable por plataformas que detectan este formato. El Start Command explícito de Render especifica el puerto y los procesos. El pool se crea después del fork de cada worker. Con 2 workers y `DB_POOL_MAX=3`, hay hasta 6 conexiones cliente al pooler; ajustar según límites del plan. No agregar `--preload` para compartir conexiones abiertas.

La base se inicializa manualmente con SQL Editor, no en cada arranque de gunicorn. Los datos persisten en Supabase aunque Render reinicie. `/health` informa que el proceso web está disponible; no certifica conectividad con la base. La portada y el panel sí consultan PostgreSQL.

## 4. Seguridad y RLS

Las consultas de la aplicación usan SQL estático y parámetros `%s`. Se valida longitud, formato, fechas, identificadores y montos decimales; Jinja escapa contenido y todos los formularios de modificación usan CSRF. Las modificaciones se ejecutan por POST y requieren sesión. Cookies HttpOnly, SameSite=Lax, Secure en HTTPS, vigencia de ocho horas y cabeceras contra embebido y detección incorrecta de contenido.

RLS en Supabase **no sustituye** el login Flask. Los usuarios de esta web no se autentican con Supabase Auth. `postgres` y los roles con `BYPASSRLS` o propietarios de tablas pueden omitir RLS; la conexión del backend debe permanecer privada. El token HTTP `service_role` no es una credencial para psycopg2. Usar el rol PostgreSQL que realmente figure en la cadena del pooler.

El script revoca acceso de los roles `anon` y `authenticated` a las tablas y vistas si existen (en PostgreSQL local pueden no existir). Ninguna política abre datos a esos roles. La política `backend_solo` permite filas solo al rol SQL **`gym_backend`** cuando se elige usarlo. Las vistas tienen `security_invoker=true`: respetan privilegios y RLS del consultante y requieren PostgreSQL 15+.

Para reducir privilegios, un administrador de la BD puede crear una vez un rol dedicado desde SQL Editor; introducir una contraseña real privada en lugar del marcador y no guardar esta sentencia con el secreto:

```sql
-- Configuración opcional de un backend con privilegios limitados.
CREATE ROLE gym_backend LOGIN PASSWORD 'REEMPLAZAR_PRIVADAMENTE';
GRANT USAGE ON SCHEMA public TO gym_backend;
GRANT SELECT, INSERT, UPDATE, DELETE ON
 public.cliente, public.membresia, public.inscripcion, public.pago,
 public.asistencia, public.entrenador, public.clase, public.reserva,
 public.rutina, public.ejercicio, public.rutina_ejercicio, public.asignacion_rutina
TO gym_backend;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO gym_backend;
GRANT SELECT ON public.vw_inscripciones_estado, public.vw_saldos TO gym_backend;
```

Después, configurar el usuario del pooler como corresponda al rol dedicado, por ejemplo `gym_backend.PROJECT_REF`, siguiendo la cadena y soporte de roles de Supabase. No usar el rol `authenticated` para la conexión Flask. Las políticas no conceden permisos de tabla por sí mismas: también se necesitan los `GRANT`. Las funciones de trigger no son `SECURITY DEFINER`, por lo que no elevan privilegios.

Este proyecto tiene un único administrador por configuración. Para producción con muchos empleados conviene ampliar el modelo con usuarios, roles, auditoría, recuperación de contraseña y limitación de intentos centralizada. No se añadieron tablas fuera del modelo académico de 12 tablas.

## 5. Recorrido para la demostración

1. Portada: comprobar los tres precios y consultar clases por fecha.
2. Panel: abrir el SQL de cada indicador. Hay datos relativos a la fecha actual en Lima.
3. Clientes: buscar `70123401` o `Quispe`, registrar y editar otro cliente.
4. Inscripciones: elegir cliente, plan y fecha; comprobar el cálculo de fin.
5. Pagos: la inscripción #1 tiene pago parcial; intentar superar su saldo y después ingresar un pago válido.
6. Asistencia: probar `70123406` (vigente) y `70123411` (vencida en los datos iniciales).
7. Clases: crear una clase de capacidad 1, reservarla con una inscripción vigente e intentar reservar con otra. Cancelar la primera y volver a reservar.
8. Rutinas: crear una con varios ejercicios y asignarla a una inscripción; revisar el detalle.

## 6. Pruebas reproducibles

Las pruebas requieren PostgreSQL **15+** real y un usuario de **un clúster local descartable** con `CREATEDB` y `CREATEROLE` (la prueba RLS crea un rol dentro de una transacción que revierte). No apuntar a Supabase ni a una base de producción. Las pruebas crean una base `fitness_test_<uuid>` nueva, instalan el script, prueban la aplicación y eliminan únicamente esa base al finalizar; nunca inicializan ni limpian la base indicada en la URL.

```bash
pip install -r requirements-dev.txt
# Usar una URL LOCAL propia; no hay una contraseña de pruebas incluida.
export TEST_DATABASE_URL='postgresql://USUARIO:CLAVE@localhost:5432/postgres'
pytest -q
```

Sin `TEST_DATABASE_URL`, pytest marca las pruebas de integración como omitidas. Se comprueban el modelo, las fechas inclusivas, RLS, pagos excesivos, cupos, cancelación, concurrencia con dos conexiones, formularios CSRF, login, CRUD, saldos, asistencia y rutinas. Las transacciones individuales revierten sus cambios y la base aleatoria se elimina al final.

Durante la construcción se validó el script y la aplicación con PostgreSQL 16.2 y se revisaron las pantallas en Chromium a 1440 y 390 píxeles. Supabase y Render requieren las cuentas y variables del propietario; no están aprovisionados ni conectados automáticamente por este repositorio.

## 7. Solución de errores comunes

| Síntoma | Causa probable y solución |
| --- | --- |
| `Network is unreachable` o error IPv6 | Se usó el host directo. Elegir Transaction/Session pooler compatible con IPv4 y su puerto exacto. |
| Error SSL o conexión rechazada | Añadir `sslmode=require`, confirmar host/puerto del pooler y que el proyecto esté activo. No desactivar verificación TLS del sistema. |
| `Tenant or user not found` | Revisar usuario completo del pooler, referencia del proyecto y región. |
| `password authentication failed` | Usar contraseña de la base, codificar caracteres reservados y reemplazar el marcador de la URI. |
| `relation ... does not exist` | Ejecutar el SQL completo en el proyecto correcto, con esquema `public`. |
| `permission denied` con rol dedicado | Aplicar los `GRANT` anteriores, confirmar el nombre de rol en la política y permisos de secuencias/vistas. |
| RLS deja vacía una consulta de la API | Es intencional para anon/authenticated. Esta aplicación consulta desde Flask, no desde el navegador a Supabase. |
| Login vuelve a la pantalla inicial en local | Usar `SESSION_COOKIE_SECURE=false` con HTTP; borrar cookies antiguas y verificar `SECRET_KEY` estable. |
| `Configure SECRET_KEY` | Establecer un secreto aleatorio de al menos 32 caracteres antes de iniciar gunicorn. |
| Error de login | Confirmar variables, hash completo y que no se pegaron comillas extra en Render. |
| Formulario caducado (400) | Recargar; pudo cambiar la clave de sesión o expirar la sesión. No deshabilitar CSRF. |
| Primera carga lenta en Render gratuito | El servicio puede suspenderse por inactividad; esperar el arranque o usar un plan sin suspensión. Las condiciones del plan pueden cambiar. |
| Proyecto Supabase pausado | Reactivarlo en el panel según las condiciones vigentes del plan. |
| Demasiadas conexiones | Reducir workers y `DB_POOL_MAX`, usar pooler y comprobar límites de Supabase. |
| Estilos no cargan | Bootstrap llega por CDN; permitir `cdn.jsdelivr.net`. Los estilos propios están en `static/css/style.css`. |

## Observaciones del modelo

- Las clases son **diarias recurrentes** a una hora de Lima. La combinación clase + fecha representa la sesión y determina su cupo. Para días específicos, feriados, sedes o múltiples horarios sería necesaria una entidad sesión/calendario adicional.
- El fin se calcula literalmente `inicio + duracion_dias`, con extremos inclusivos, tal como pide el enunciado: un plan de 30 días iniciado el día 1 termina el 31. No se sustituyó por `duracion_dias - 1` ni por meses naturales.
- El vencimiento es efectivo en una vista; no se cambia masivamente el estado guardado. Cancelación tiene prioridad sobre vencimiento; una inscripción futura aparece como programada y aún no permite ingresar.
- Se permiten varias inscripciones por cliente. La asistencia por DNI elige la vigente con fin más lejano y luego mayor ID. No se exige pago completo para ingresar porque el enunciado no lo exige.
- Precio y duración de un plan ya usado se protegen mediante trigger. La inscripción no cambia de plan ni de inicio. Esto conserva la deuda histórica sin añadir columnas al modelo. Para otro precio se crea un nuevo plan; para renovación, otra inscripción.
- Reserva no cancelada consume cupo, incluso si su estado es PENDIENTE. Una cancelación no se borra; reservar otra vez reactiva la fila para respetar la clave única.
- Las rutinas pueden asignarse a cualquier inscripción para conservar planificación e historial; eso no autoriza acceso al gimnasio.
- Los pagos son positivos y parciales; no se modelan devoluciones, descuentos, facturación tributaria o cambios retroactivos de precio.
