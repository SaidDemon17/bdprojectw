-- Fitness Planet Gym: ejecutar UNA VEZ en una base vacía (PostgreSQL 15+).
-- La transacción evita instalaciones parciales; nunca elimina datos existentes.
BEGIN;
SET TIME ZONE 'America/Lima';

CREATE TABLE cliente (
    id_cliente BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombres VARCHAR(80) NOT NULL CHECK (btrim(nombres) <> ''),
    apellidos VARCHAR(100) NOT NULL CHECK (btrim(apellidos) <> ''),
    dni VARCHAR(8) NOT NULL UNIQUE CHECK (dni ~ '^[0-9]{8}$'),
    telefono VARCHAR(20) NOT NULL,
    correo VARCHAR(150) NOT NULL UNIQUE CHECK (correo ~ '^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$'),
    fecha_nacimiento DATE NOT NULL CHECK (fecha_nacimiento >= DATE '1900-01-01')
);
CREATE UNIQUE INDEX cliente_correo_minusculas ON cliente (lower(correo));
CREATE INDEX cliente_apellido_idx ON cliente (lower(apellidos));
CREATE TABLE membresia (
    id_membresia BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tipo VARCHAR(30) NOT NULL UNIQUE,
    precio NUMERIC(10,2) NOT NULL CHECK (precio > 0),
    duracion_dias INTEGER NOT NULL CHECK (duracion_dias > 0)
);
CREATE TABLE inscripcion (
    id_inscripcion BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fecha_inicio DATE NOT NULL,
    fecha_fin DATE NOT NULL,
    estado VARCHAR(10) NOT NULL DEFAULT 'ACTIVA' CHECK (estado IN ('ACTIVA','VENCIDA','CANCELADA')),
    id_cliente BIGINT NOT NULL REFERENCES cliente ON DELETE RESTRICT,
    id_membresia BIGINT NOT NULL REFERENCES membresia ON DELETE RESTRICT,
    CHECK (fecha_fin >= fecha_inicio)
);
CREATE INDEX inscripcion_cliente_idx ON inscripcion(id_cliente);
CREATE INDEX inscripcion_membresia_idx ON inscripcion(id_membresia);
CREATE INDEX inscripcion_fin_idx ON inscripcion(fecha_fin);
CREATE TABLE pago (
    id_pago BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fecha_pago TIMESTAMPTZ NOT NULL DEFAULT now(),
    monto NUMERIC(10,2) NOT NULL CHECK (monto > 0),
    metodo_pago VARCHAR(15) NOT NULL CHECK (metodo_pago IN ('EFECTIVO','TARJETA','YAPE','PLIN','TRANSFERENCIA')),
    id_inscripcion BIGINT NOT NULL REFERENCES inscripcion ON DELETE RESTRICT
);
CREATE INDEX pago_inscripcion_idx ON pago(id_inscripcion);
CREATE INDEX pago_fecha_idx ON pago(fecha_pago);
CREATE TABLE asistencia (
    id_asistencia BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fecha_hora_ingreso TIMESTAMPTZ NOT NULL DEFAULT now(),
    id_inscripcion BIGINT NOT NULL REFERENCES inscripcion ON DELETE RESTRICT
);
CREATE INDEX asistencia_inscripcion_idx ON asistencia(id_inscripcion);
CREATE INDEX asistencia_fecha_idx ON asistencia(fecha_hora_ingreso);
CREATE TABLE entrenador (
    id_entrenador BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombres VARCHAR(80) NOT NULL,
    apellidos VARCHAR(100) NOT NULL,
    telefono VARCHAR(20) NOT NULL,
    especialidad VARCHAR(80) NOT NULL
);
CREATE TABLE clase (
    id_clase BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre VARCHAR(60) NOT NULL,
    horario TIME NOT NULL,
    capacidad INTEGER NOT NULL CHECK (capacidad BETWEEN 1 AND 200),
    id_entrenador BIGINT NOT NULL REFERENCES entrenador ON DELETE RESTRICT
);
CREATE INDEX clase_entrenador_idx ON clase(id_entrenador);
CREATE TABLE reserva (
    id_reserva BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fecha_reserva DATE NOT NULL,
    estado VARCHAR(12) NOT NULL DEFAULT 'CONFIRMADA' CHECK (estado IN ('PENDIENTE','CONFIRMADA','CANCELADA')),
    id_inscripcion BIGINT NOT NULL REFERENCES inscripcion ON DELETE RESTRICT,
    id_clase BIGINT NOT NULL REFERENCES clase ON DELETE RESTRICT,
    UNIQUE(id_inscripcion, id_clase, fecha_reserva)
);
CREATE INDEX reserva_ocupacion_idx ON reserva(id_clase, fecha_reserva) WHERE estado <> 'CANCELADA';
CREATE TABLE rutina (
    id_rutina BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre VARCHAR(80) NOT NULL,
    objetivo VARCHAR(200) NOT NULL,
    fecha_creacion DATE NOT NULL DEFAULT (now() AT TIME ZONE 'America/Lima')::date
);
CREATE TABLE ejercicio (
    id_ejercicio BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre VARCHAR(80) NOT NULL UNIQUE,
    descripcion TEXT NOT NULL,
    tipo VARCHAR(40) NOT NULL
);
CREATE TABLE rutina_ejercicio (
    id_rutina_ejercicio BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_rutina BIGINT NOT NULL REFERENCES rutina ON DELETE CASCADE,
    id_ejercicio BIGINT NOT NULL REFERENCES ejercicio ON DELETE RESTRICT,
    series INTEGER NOT NULL CHECK (series BETWEEN 1 AND 20),
    repeticiones INTEGER NOT NULL CHECK (repeticiones BETWEEN 1 AND 200),
    descanso_seg INTEGER NOT NULL CHECK (descanso_seg BETWEEN 0 AND 600),
    UNIQUE(id_rutina, id_ejercicio)
);
CREATE INDEX rutina_ejercicio_ejercicio_idx ON rutina_ejercicio(id_ejercicio);
CREATE TABLE asignacion_rutina (
    id_asignacion BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_inscripcion BIGINT NOT NULL REFERENCES inscripcion ON DELETE RESTRICT,
    id_rutina BIGINT NOT NULL REFERENCES rutina ON DELETE RESTRICT,
    fecha_asignacion DATE NOT NULL DEFAULT (now() AT TIME ZONE 'America/Lima')::date,
    UNIQUE(id_inscripcion, id_rutina, fecha_asignacion)
);
CREATE INDEX asignacion_rutina_rutina_idx ON asignacion_rutina(id_rutina);

-- La duración se expresa en días; ambos extremos de vigencia son inclusivos.
CREATE FUNCTION calcular_fin() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE dias INTEGER;
BEGIN
    IF TG_OP = 'UPDATE' AND (NEW.id_membresia <> OLD.id_membresia OR NEW.fecha_inicio <> OLD.fecha_inicio) THEN
        RAISE EXCEPTION 'La membresía y el inicio son inmutables; cree una nueva inscripción.' USING ERRCODE='23514';
    END IF;
    SELECT duracion_dias INTO STRICT dias FROM membresia WHERE id_membresia = NEW.id_membresia;
    NEW.fecha_fin := NEW.fecha_inicio + dias;
    RETURN NEW;
END $$;
CREATE TRIGGER inscripcion_fin BEFORE INSERT OR UPDATE ON inscripcion FOR EACH ROW EXECUTE FUNCTION calcular_fin();

-- Evitar que cambios de catálogo alteren deudas y vigencias históricas.
CREATE FUNCTION proteger_membresia() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (NEW.precio <> OLD.precio OR NEW.duracion_dias <> OLD.duracion_dias)
       AND EXISTS (SELECT 1 FROM inscripcion WHERE id_membresia=OLD.id_membresia) THEN
        RAISE EXCEPTION 'El plan tiene inscripciones; cree otro plan para cambiar precio o duración.' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER membresia_historica BEFORE UPDATE ON membresia FOR EACH ROW EXECUTE FUNCTION proteger_membresia();

-- Bloquear la fila padre serializa pagos concurrentes sobre una misma deuda.
CREATE FUNCTION validar_pago() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE precio_plan NUMERIC; pagado NUMERIC;
BEGIN
    IF TG_OP='UPDATE' AND NEW.id_inscripcion <> OLD.id_inscripcion THEN
        RAISE EXCEPTION 'No se puede mover un pago a otra inscripción.' USING ERRCODE='23514';
    END IF;
    PERFORM 1 FROM inscripcion WHERE id_inscripcion=NEW.id_inscripcion FOR UPDATE;
    SELECT m.precio INTO precio_plan FROM inscripcion i JOIN membresia m USING(id_membresia)
      WHERE i.id_inscripcion=NEW.id_inscripcion;
    SELECT coalesce(sum(monto),0) INTO pagado FROM pago
      WHERE id_inscripcion=NEW.id_inscripcion AND id_pago <> NEW.id_pago;
    IF pagado + NEW.monto > precio_plan THEN
        RAISE EXCEPTION 'El pago supera el saldo pendiente de S/ %.', precio_plan-pagado USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER pago_limite BEFORE INSERT OR UPDATE ON pago FOR EACH ROW EXECUTE FUNCTION validar_pago();

CREATE FUNCTION validar_asistencia() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE i inscripcion%ROWTYPE; hoy DATE := (now() AT TIME ZONE 'America/Lima')::date;
BEGIN
    SELECT * INTO i FROM inscripcion WHERE id_inscripcion=NEW.id_inscripcion FOR UPDATE;
    IF NOT FOUND OR i.estado <> 'ACTIVA' OR hoy NOT BETWEEN i.fecha_inicio AND i.fecha_fin
       OR (NEW.fecha_hora_ingreso AT TIME ZONE 'America/Lima')::date NOT BETWEEN i.fecha_inicio AND i.fecha_fin THEN
        RAISE EXCEPTION 'La asistencia requiere una inscripción ACTIVA y vigente.' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER asistencia_vigente BEFORE INSERT OR UPDATE ON asistencia FOR EACH ROW EXECUTE FUNCTION validar_asistencia();

CREATE FUNCTION validar_reserva() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE i inscripcion%ROWTYPE; cupos INTEGER; ocupados INTEGER;
        hoy DATE := (now() AT TIME ZONE 'America/Lima')::date;
BEGIN
    IF TG_OP='UPDATE' AND (NEW.id_clase <> OLD.id_clase OR NEW.id_inscripcion <> OLD.id_inscripcion OR NEW.fecha_reserva <> OLD.fecha_reserva) THEN
        RAISE EXCEPTION 'Cancele la reserva y cree otra para cambiar clase, fecha o inscripción.' USING ERRCODE='23514';
    END IF;
    -- El bloqueo de clase protege el conteo; pendientes y confirmadas consumen cupo.
    SELECT capacidad INTO cupos FROM clase WHERE id_clase=NEW.id_clase FOR UPDATE;
    IF NEW.estado='CANCELADA' THEN RETURN NEW; END IF;
    SELECT * INTO i FROM inscripcion WHERE id_inscripcion=NEW.id_inscripcion FOR UPDATE;
    IF NOT FOUND OR i.estado <> 'ACTIVA' OR hoy NOT BETWEEN i.fecha_inicio AND i.fecha_fin
       OR NEW.fecha_reserva < hoy OR NEW.fecha_reserva NOT BETWEEN i.fecha_inicio AND i.fecha_fin THEN
        RAISE EXCEPTION 'La reserva requiere inscripción ACTIVA vigente hoy y en la fecha elegida, sin fechas pasadas.' USING ERRCODE='23514';
    END IF;
    SELECT count(*) INTO ocupados FROM reserva WHERE id_clase=NEW.id_clase
      AND fecha_reserva=NEW.fecha_reserva AND estado <> 'CANCELADA' AND id_reserva <> NEW.id_reserva;
    IF ocupados >= cupos THEN
        RAISE EXCEPTION 'La clase ya no tiene cupos para esa fecha.' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER reserva_cupo BEFORE INSERT OR UPDATE ON reserva FOR EACH ROW EXECUTE FUNCTION validar_reserva();

-- Una capacidad nueva nunca debe quedar por debajo de reservas existentes.
CREATE FUNCTION proteger_capacidad() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM reserva WHERE id_clase=OLD.id_clase AND estado <> 'CANCELADA'
               GROUP BY fecha_reserva HAVING count(*) > NEW.capacidad) THEN
        RAISE EXCEPTION 'La capacidad es menor que la ocupación existente.' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER clase_capacidad BEFORE UPDATE OF capacidad ON clase FOR EACH ROW EXECUTE FUNCTION proteger_capacidad();

-- security_invoker respeta permisos y RLS del rol que consulta (PostgreSQL 15+).
CREATE VIEW vw_inscripciones_estado WITH (security_invoker=true) AS
SELECT i.*, CASE WHEN i.estado='CANCELADA' THEN 'CANCELADA'
    WHEN i.fecha_fin < (now() AT TIME ZONE 'America/Lima')::date THEN 'VENCIDA'
    ELSE i.estado END AS estado_efectivo
FROM inscripcion i;
CREATE VIEW vw_saldos WITH (security_invoker=true) AS
SELECT i.id_inscripcion, m.precio, coalesce(sum(p.monto),0)::numeric(10,2) AS pagado,
       (m.precio-coalesce(sum(p.monto),0))::numeric(10,2) AS saldo
FROM inscripcion i JOIN membresia m USING(id_membresia)
LEFT JOIN pago p USING(id_inscripcion) GROUP BY i.id_inscripcion,m.precio;

-- Cierre de la API de Supabase: NO se autoriza a anon ni authenticated.
-- postgres y service_role omiten RLS por atributos del rol; gym_backend sí usa esta política.
DO $$
DECLARE tabla TEXT; rol TEXT;
BEGIN
    FOREACH tabla IN ARRAY ARRAY['cliente','membresia','inscripcion','pago','asistencia','entrenador','clase','reserva','rutina','ejercicio','rutina_ejercicio','asignacion_rutina'] LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',tabla);
        EXECUTE format('CREATE POLICY backend_solo ON public.%I FOR ALL TO PUBLIC USING (current_user = ''gym_backend'') WITH CHECK (current_user = ''gym_backend'')',tabla);
        FOREACH rol IN ARRAY ARRAY['anon','authenticated'] LOOP
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname=rol) THEN
                EXECUTE format('REVOKE ALL ON public.%I FROM %I',tabla,rol);
            END IF;
        END LOOP;
    END LOOP;
    FOREACH rol IN ARRAY ARRAY['anon','authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname=rol) THEN
            EXECUTE format('REVOKE ALL ON public.vw_inscripciones_estado, public.vw_saldos FROM %I',rol);
        END IF;
    END LOOP;
END $$;

-- Datos ficticios, fechas relativas a Lima para que la demostración siga vigente.
INSERT INTO cliente(nombres,apellidos,dni,telefono,correo,fecha_nacimiento) VALUES
('Lucía','Quispe Huamán','70123401','987654301','lucia.quispe@example.com','1998-04-12'),
('Diego','Flores Rojas','70123402','987654302','diego.flores@example.com','1996-09-22'),
('Valeria','Mamani Torres','70123403','987654303','valeria.mamani@example.com','2001-02-18'),
('José','García Mendoza','70123404','987654304','jose.garcia@example.com','1993-06-05'),
('Camila','Vargas Soto','70123405','987654305','camila.vargas@example.com','2000-12-20'),
('Luis','Huamán Castillo','70123406','987654306','luis.huaman@example.com','1990-07-14'),
('María','Condori Ramos','70123407','987654307','maria.condori@example.com','1997-03-08'),
('Andrés','Paredes León','70123408','987654308','andres.paredes@example.com','1995-11-03'),
('Fernanda','Cruz Salazar','70123409','987654309','fernanda.cruz@example.com','2002-05-16'),
('Renato','Chávez Díaz','70123410','987654310','renato.chavez@example.com','1994-08-27'),
('Daniela','Reyes Aguilar','70123411','987654311','daniela.reyes@example.com','1999-01-09'),
('Miguel','Rojas Medina','70123412','987654312','miguel.rojas@example.com','1992-10-30'),
('Alejandra','Sánchez Peña','70123413','987654313','alejandra.sanchez@example.com','2003-04-25'),
('Jorge','Velásquez Ruiz','70123414','987654314','jorge.velasquez@example.com','1988-02-11'),
('Paola','Espinoza Silva','70123415','987654315','paola.espinoza@example.com','1996-06-19');
INSERT INTO membresia(tipo,precio,duracion_dias) VALUES ('Mensual',120,30),('Trimestral',320,90),('Semestral',590,180);
INSERT INTO entrenador(nombres,apellidos,telefono,especialidad) VALUES
('Carlos','Gutiérrez','999111201','Spinning'),('Ana','Ponce','999111202','Yoga'),
('Milagros','Rivas','999111203','Zumba'),('Pedro','Núñez','999111204','Funcional'),('Rosa','Vega','999111205','Fuerza');
-- Cada clase representa una sesión diaria recurrente, a la hora indicada.
INSERT INTO clase(nombre,horario,capacidad,id_entrenador) VALUES
('Spinning Power','06:00',18,1),('Yoga Flow','07:00',15,2),('Zumba Energy','08:00',22,3),
('Funcional AM','09:00',16,4),('Fuerza Total','12:00',12,5),('Spinning Sunset','18:00',18,1),
('Yoga Balance','19:00',15,2),('Funcional Night','20:00',16,4);
-- 10 activas, 5 vencidas efectivas (3 registradas y 2 calculadas), 5 canceladas.
INSERT INTO inscripcion(fecha_inicio,estado,id_cliente,id_membresia)
SELECT (now() AT TIME ZONE 'America/Lima')::date - CASE WHEN n<=5 THEN 26 WHEN n<=10 THEN 8 WHEN n<=15 THEN 50 ELSE 10 END,
       CASE WHEN n>15 THEN 'CANCELADA' WHEN n BETWEEN 11 AND 13 THEN 'VENCIDA' ELSE 'ACTIVA' END,
       ((n-1)%15)+1, CASE WHEN n<=5 OR n BETWEEN 11 AND 15 THEN 1 ELSE ((n-1)%3)+1 END
FROM generate_series(1,20) AS n;
INSERT INTO pago(monto,metodo_pago,id_inscripcion,fecha_pago)
SELECT CASE WHEN id_inscripcion%2=0 THEN 120 ELSE 60 END,
       CASE WHEN id_inscripcion%2=0 THEN 'YAPE' ELSE 'EFECTIVO' END,
       id_inscripcion, now() - interval '1 day' FROM inscripcion WHERE id_inscripcion<=15;
INSERT INTO asistencia(id_inscripcion,fecha_hora_ingreso)
SELECT i, now() - (d * interval '1 day') FROM generate_series(6,10) i CROSS JOIN generate_series(0,6) d;
INSERT INTO reserva(fecha_reserva,id_inscripcion,id_clase)
SELECT (now() AT TIME ZONE 'America/Lima')::date + (n%3), n, ((n-1)%8)+1 FROM generate_series(1,10) n;
INSERT INTO ejercicio(nombre,descripcion,tipo) VALUES
('Sentadilla','Mantener espalda neutra y rodillas alineadas.','Fuerza'),('Press de banca','Descender la barra de forma controlada.','Fuerza'),
('Peso muerto','Empujar el suelo sin redondear la espalda.','Fuerza'),('Remo con mancuerna','Llevar el codo hacia la cadera.','Fuerza'),
('Plancha','Mantener abdomen firme y postura estable.','Core'),('Zancadas','Alternar piernas con pasos controlados.','Fuerza'),
('Bicicleta','Regular resistencia según condición física.','Cardio'),('Burpees','Adaptar el salto al nivel del alumno.','Funcional'),
('Puente de glúteos','Elevar la cadera sin arquear la zona lumbar.','Fuerza'),('Movilidad de hombros','Realizar círculos suaves sin dolor.','Movilidad');
INSERT INTO rutina(nombre,objetivo) VALUES ('Base de fuerza','Aprender patrones básicos con buena técnica.'),
('Cardio activo','Mejorar resistencia cardiovascular.'),('Core y movilidad','Fortalecer el abdomen y ampliar movilidad.'),
('Funcional completo','Entrenar fuerza y resistencia de todo el cuerpo.');
INSERT INTO rutina_ejercicio(id_rutina,id_ejercicio,series,repeticiones,descanso_seg) VALUES
(1,1,3,12,60),(1,2,3,10,90),(1,3,3,8,90),(1,4,3,12,60),
(2,7,4,60,30),(2,8,3,12,60),(2,6,3,14,45),
(3,5,3,30,45),(3,9,3,15,45),(3,10,2,12,30),
(4,1,3,15,45),(4,6,3,12,45),(4,8,3,10,60);
INSERT INTO asignacion_rutina(id_inscripcion,id_rutina)
SELECT n, ((n-1)%4)+1 FROM generate_series(1,10) n;
COMMIT;
