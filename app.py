import io
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from PIL import Image

# Gemini opcional
GEMINI_AVAILABLE = True
try:
    from google import genai
    from google.genai import types
except Exception:
    GEMINI_AVAILABLE = False

# OCR opcional como fallback
OCR_AVAILABLE = True
try:
    import pytesseract
    from PIL import ImageOps, ImageFilter
except Exception:
    OCR_AVAILABLE = False

# =========================
# CONFIGURACIÓN GENERAL
# =========================
st.set_page_config(page_title="Control de Neumáticos", page_icon="🚚", layout="centered")

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "neumaticos.db"
FOTOS_DIR = BASE_DIR / "fotos_neumaticos"
FOTOS_DIR.mkdir(exist_ok=True)

EMPRESAS = ["Empresa A", "Empresa B", "Empresa C"]
POSICIONES = [
    "Delantero Izquierdo",
    "Delantero Derecho",
    "Tracción Izquierda Interno",
    "Tracción Izquierda Externo",
    "Tracción Derecha Interno",
    "Tracción Derecha Externo",
    "Remolque Izquierdo Interno",
    "Remolque Izquierdo Externo",
    "Remolque Derecho Interno",
    "Remolque Derecho Externo",
    "Otro",
]
ESTADOS = ["Nuevo", "Usado", "Recauchutado"]

MARCAS = [
    "Michelin", "Goodyear", "Pirelli", "Bridgestone", "Continental",
    "Firestone", "Dunlop", "Toyo", "Yokohama", "Hankook",
    "Kumho", "Sailun", "Apollo", "Triangle", "Double Coin",
    "BKT", "Linglong", "General Tire", "BFGoodrich",
]

DEFAULT_MODEL = "gemini-2.5-flash"

# =========================
# BASE DE DATOS
# =========================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS neumaticos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL,
            empresa TEXT NOT NULL,
            matricula TEXT NOT NULL,
            posicion TEXT NOT NULL,
            medida TEXT,
            marca TEXT,
            modelo TEXT,
            estado TEXT NOT NULL,
            foto TEXT,
            confianza REAL,
            texto_detectado TEXT,
            proveedor_lectura TEXT
        )
        """
    )
    conn.commit()

    cursor.execute("PRAGMA table_info(neumaticos)")
    cols = [row[1] for row in cursor.fetchall()]
    alter_statements = []
    if "confianza" not in cols:
        alter_statements.append("ALTER TABLE neumaticos ADD COLUMN confianza REAL")
    if "texto_detectado" not in cols:
        alter_statements.append("ALTER TABLE neumaticos ADD COLUMN texto_detectado TEXT")
    if "proveedor_lectura" not in cols:
        alter_statements.append("ALTER TABLE neumaticos ADD COLUMN proveedor_lectura TEXT")
    for stmt in alter_statements:
        cursor.execute(stmt)
    conn.commit()
    conn.close()


def guardar_registro(datos):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO neumaticos (
            fecha, empresa, matricula, posicion, medida, marca, modelo, estado, foto,
            confianza, texto_detectado, proveedor_lectura
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        datos,
    )
    conn.commit()
    conn.close()


def cargar_registros(f_empresa="", f_matricula="", f_marca=""):
    conn = sqlite3.connect(DB_PATH)
    query = "SELECT * FROM neumaticos WHERE 1=1"
    params = []

    if f_empresa:
        query += " AND empresa LIKE ?"
        params.append(f"%{f_empresa}%")
    if f_matricula:
        query += " AND matricula LIKE ?"
        params.append(f"%{f_matricula}%")
    if f_marca:
        query += " AND marca LIKE ?"
        params.append(f"%{f_marca}%")

    query += " ORDER BY id DESC"
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df

# =========================
# UTILIDADES
# =========================
def limpiar_texto(txt: str) -> str:
    txt = txt.replace("\n", " ")
    txt = re.sub(r"\s+", " ", txt)
    return txt.strip()


def guardar_foto(archivo, nombre_base: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    nombre = f"{timestamp}_{nombre_base}.jpg"
    ruta = FOTOS_DIR / nombre
    with open(ruta, "wb") as f:
        f.write(archivo.getbuffer())
    return str(ruta)


def excel_bytes(df: pd.DataFrame) -> bytes:
    ruta = BASE_DIR / "exportacion_neumaticos.xlsx"
    with pd.ExcelWriter(ruta, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Neumáticos")
    with open(ruta, "rb") as f:
        return f.read()


def imagen_a_bytes(img: Image.Image) -> bytes:
    buffer = io.BytesIO()
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def normalizar_marca(valor: str) -> str:
    if not valor:
        return ""
    valor_clean = valor.strip().lower()
    for marca in MARCAS:
        if marca.lower() == valor_clean:
            return marca
        if marca.lower() in valor_clean or valor_clean in marca.lower():
            return marca
    return valor.strip()

# =========================
# FALLBACK OCR
# =========================
def preprocesar_imagen_ocr(img: Image.Image) -> Image.Image:
    img = ImageOps.exif_transpose(img)
    img = img.convert("L")
    img = ImageOps.autocontrast(img)
    img = img.resize((img.width * 3, img.height * 3))
    img = img.filter(ImageFilter.SHARPEN)
    return img


def leer_ocr(img: Image.Image):
    if not OCR_AVAILABLE:
        return {
            "marca": "",
            "modelo": "",
            "medida": "",
            "confianza": 0.0,
            "texto_detectado": "",
            "proveedor": "manual",
            "error": "OCR no disponible",
        }
    try:
        img_proc = preprocesar_imagen_ocr(img)
        texto = pytesseract.image_to_string(img_proc, lang="eng", config="--oem 3 --psm 11")
        texto = limpiar_texto(texto)

        medida = ""
        patrones = [
            r"\b\d{3}/\d{2}\s?R\d{2}(?:\.\d)?\b",
            r"\b\d{3}/\d{2}R\d{2}(?:\.\d)?\b",
            r"\b\d{3}/\d{2}\s?ZR\d{2}(?:\.\d)?\b",
            r"\b\d{2,3}R\d{2}(?:\.\d)?\b",
        ]
        for patron in patrones:
            m = re.search(patron, texto, re.IGNORECASE)
            if m:
                medida = m.group(0).upper().replace("ZR", "R")
                break

        marca = ""
        texto_low = texto.lower()
        for item in MARCAS:
            if item.lower() in texto_low:
                marca = item
                break

        modelo = ""
        if marca and marca.lower() in texto.lower():
            idx = texto.lower().find(marca.lower())
            resto = texto[idx + len(marca):].strip()
            modelo = " ".join(resto.split()[:4]).strip(" -_/,. ")

        return {
            "marca": marca,
            "modelo": modelo,
            "medida": medida,
            "confianza": 0.35 if texto else 0.0,
            "texto_detectado": texto,
            "proveedor": "ocr",
            "error": "",
        }
    except Exception as e:
        return {
            "marca": "",
            "modelo": "",
            "medida": "",
            "confianza": 0.0,
            "texto_detectado": "",
            "proveedor": "manual",
            "error": str(e),
        }

# =========================
# GEMINI
# =========================
def analizar_con_gemini(img: Image.Image, api_key: str, model_name: str = DEFAULT_MODEL):
    if not GEMINI_AVAILABLE:
        return {
            "marca": "",
            "modelo": "",
            "medida": "",
            "confianza": 0.0,
            "texto_detectado": "",
            "proveedor": "manual",
            "error": "SDK de Gemini no disponible",
        }

    if not api_key:
        return {
            "marca": "",
            "modelo": "",
            "medida": "",
            "confianza": 0.0,
            "texto_detectado": "",
            "proveedor": "manual",
            "error": "Falta la API key de Gemini",
        }

    schema = {
        "type": "object",
        "properties": {
            "marca": {"type": "string"},
            "modelo": {"type": "string"},
            "medida": {"type": "string"},
            "confianza": {"type": "number"},
            "texto_detectado": {"type": "string"}
        },
        "required": ["marca", "modelo", "medida", "confianza", "texto_detectado"]
    }

    prompt = (
        "Analiza la imagen de un neumático de camión y devuelve solo JSON válido. "
        "Extrae únicamente estos campos: marca, modelo, medida, confianza, texto_detectado. "
        "La confianza debe ser un número entre 0 y 1. "
        "Si no estás seguro de un campo, devuélvelo como cadena vacía. "
        "No inventes información. "
        "La medida debe tener formato similar a 295/80 R22.5 cuando sea visible."
    )

    try:
        client = genai.Client(api_key=api_key)
        img_bytes = imagen_a_bytes(img)
        response = client.models.generate_content(
            model=model_name,
            contents=[
                prompt,
                types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg")
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_json_schema=schema,
                temperature=0.1,
            ),
        )

        raw_text = getattr(response, "text", "") or ""
        data = json.loads(raw_text)

        return {
            "marca": normalizar_marca(data.get("marca", "")),
            "modelo": limpiar_texto(str(data.get("modelo", ""))),
            "medida": limpiar_texto(str(data.get("medida", ""))).upper(),
            "confianza": float(data.get("confianza", 0.0) or 0.0),
            "texto_detectado": limpiar_texto(str(data.get("texto_detectado", ""))),
            "proveedor": "gemini",
            "error": "",
        }
    except Exception as e:
        return {
            "marca": "",
            "modelo": "",
            "medida": "",
            "confianza": 0.0,
            "texto_detectado": "",
            "proveedor": "manual",
            "error": str(e),
        }


def analizar_imagen(img: Image.Image, usar_gemini: bool, api_key: str, model_name: str):
    if usar_gemini and api_key:
        resultado_gemini = analizar_con_gemini(img, api_key, model_name)
        if not resultado_gemini.get("error"):
            return resultado_gemini
        resultado_ocr = leer_ocr(img)
        if resultado_ocr.get("texto_detectado"):
            resultado_ocr["error"] = f"Gemini falló: {resultado_gemini['error']}"
            return resultado_ocr
        return resultado_gemini
    return leer_ocr(img)

# =========================
# APP
# =========================
init_db()

st.title("🚚 Control de Neumáticos")
st.caption("Versión móvil con lectura inteligente de imágenes usando Gemini y fallback manual")

with st.expander("Configuración de lectura", expanded=True):
    usar_gemini = st.toggle("Usar Gemini como lector principal", value=True)
    api_key = st.text_input("Gemini API Key", type="password", help="No se guarda en la base de datos") if usar_gemini else ""
    model_name = st.text_input("Modelo Gemini", value=DEFAULT_MODEL) if usar_gemini else DEFAULT_MODEL

    col_a, col_b = st.columns(2)
    with col_a:
        if usar_gemini:
            st.info("Gemini activo" if api_key else "Introduce la API key para activar Gemini")
        else:
            st.info("Gemini desactivado")
    with col_b:
        st.info("OCR fallback disponible" if OCR_AVAILABLE else "OCR fallback no disponible")

if usar_gemini and not GEMINI_AVAILABLE:
    st.error("El SDK de Gemini no está instalado. Añade 'google-genai' al requirements.txt")

pestanas = st.tabs(["📷 Nuevo registro", "📋 Histórico"])

with pestanas[0]:
    st.subheader("Nuevo registro")
    st.info("Haz una foto del neumático, revisa los datos detectados y guarda el registro.")

    fuente_imagen = st.radio(
        "Origen de la foto",
        ["Usar cámara del móvil", "Subir imagen"],
        horizontal=False,
    )

    archivo_imagen = None
    if fuente_imagen == "Usar cámara del móvil":
        archivo_imagen = st.camera_input("Tomar foto del neumático")
    else:
        archivo_imagen = st.file_uploader("Subir foto del neumático", type=["jpg", "jpeg", "png", "webp"])

    resultado_lectura = {
        "marca": "",
        "modelo": "",
        "medida": "",
        "confianza": 0.0,
        "texto_detectado": "",
        "proveedor": "manual",
        "error": "",
    }

    if archivo_imagen:
        imagen = Image.open(archivo_imagen)
        st.image(imagen, caption="Imagen original", use_container_width=True)

        with st.spinner("Analizando imagen..."):
            resultado_lectura = analizar_imagen(imagen, usar_gemini, api_key, model_name)

        col_r1, col_r2 = st.columns(2)
        with col_r1:
            st.metric("Proveedor de lectura", resultado_lectura.get("proveedor", "manual"))
        with col_r2:
            st.metric("Confianza", f"{resultado_lectura.get('confianza', 0.0):.2f}")

        if resultado_lectura.get("texto_detectado"):
            with st.expander("Texto detectado"):
                st.write(resultado_lectura["texto_detectado"])

        if resultado_lectura.get("error"):
            st.warning(f"Lectura automática con incidencias: {resultado_lectura['error']}")

    fecha = st.date_input("Fecha", value=datetime.now().date())

    empresa = st.selectbox("Empresa", EMPRESAS + ["Otra"])
    if empresa == "Otra":
        empresa = st.text_input("Nombre de la empresa")

    matricula = st.text_input("Matrícula", placeholder="Ej.: 1234ABC")
    posicion = st.selectbox("Posición", POSICIONES)
    medida = st.text_input("Medida", value=resultado_lectura.get("medida", ""))
    marca = st.text_input("Marca", value=resultado_lectura.get("marca", ""))
    modelo = st.text_input("Modelo", value=resultado_lectura.get("modelo", ""))
    estado = st.selectbox("Estado", ESTADOS)

    guardar = st.button("Guardar registro", type="primary", use_container_width=True)

    if guardar:
        if not archivo_imagen:
            st.error("Debes hacer una foto o subir una imagen antes de guardar.")
        elif not empresa or not matricula.strip():
            st.error("Completa al menos la empresa y la matrícula.")
        else:
            nombre_base = re.sub(r"[^a-zA-Z0-9_-]", "_", matricula.strip().upper())
            ruta_foto = guardar_foto(archivo_imagen, nombre_base)
            guardar_registro((
                str(fecha),
                empresa.strip(),
                matricula.strip().upper(),
                posicion,
                medida.strip(),
                marca.strip(),
                modelo.strip(),
                estado,
                ruta_foto,
                float(resultado_lectura.get("confianza", 0.0) or 0.0),
                resultado_lectura.get("texto_detectado", ""),
                resultado_lectura.get("proveedor", "manual"),
            ))
            st.success("Registro guardado correctamente.")

with pestanas[1]:
    st.subheader("Histórico")

    col1, col2, col3 = st.columns(3)
    with col1:
        f_empresa = st.text_input("Filtrar por empresa")
    with col2:
        f_matricula = st.text_input("Filtrar por matrícula")
    with col3:
        f_marca = st.text_input("Filtrar por marca")

    df = cargar_registros(f_empresa, f_matricula, f_marca)

    if not df.empty:
        st.dataframe(df, use_container_width=True, hide_index=True)
        descarga_excel = excel_bytes(df)
        st.download_button(
            "Descargar Excel",
            data=descarga_excel,
            file_name=f"neumaticos_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    else:
        st.info("No hay registros todavía.")

st.markdown("---")
st.markdown("### requirements.txt")
st.code(
    """
streamlit
pandas
openpyxl
pillow
google-genai
pytesseract
    """,
    language="txt",
)

st.markdown("### packages.txt")
st.code(
    """
tesseract-ocr
    """,
    language="txt",
)

st.markdown("### Nota")
st.write(
    "Para usar la cámara del teléfono, abre la aplicación desde el navegador móvil y acepta el permiso de cámara. Si Gemini falla, la app intenta usar OCR como alternativa."
)

