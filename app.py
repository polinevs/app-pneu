import re
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from PIL import Image

# OCR opcional
OCR_AVAILABLE = True
try:
    import pytesseract
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
    "BKT", "Linglong", "General Tire",
]

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
            foto TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def guardar_registro(datos):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO neumaticos (fecha, empresa, matricula, posicion, medida, marca, modelo, estado, foto)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
# FUNCIONES OCR
# =========================
def limpiar_texto(txt: str) -> str:
    return re.sub(r"\s+", " ", txt.replace("\n", " ")).strip()


def leer_ocr(img: Image.Image) -> str:
    if not OCR_AVAILABLE:
        return ""
    try:
        texto = pytesseract.image_to_string(img, lang="eng")
        return limpiar_texto(texto)
    except Exception:
        return ""


def extraer_medida(txt: str) -> str:
    patrones = [
        r"\b\d{3}/\d{2}\s?R\d{2}(?:\.\d)?\b",
        r"\b\d{3}/\d{2}R\d{2}(?:\.\d)?\b",
        r"\b\d{2,3}R\d{2}(?:\.\d)?\b",
    ]
    for patron in patrones:
        m = re.search(patron, txt, re.IGNORECASE)
        if m:
            return m.group(0).upper()
    return ""


def extraer_marca(txt: str) -> str:
    txt_low = txt.lower()
    for marca in MARCAS:
        if marca.lower() in txt_low:
            return marca
    return ""


def extraer_modelo(txt: str, marca: str) -> str:
    if not txt:
        return ""

    txt = limpiar_texto(txt)
    if marca and marca.lower() in txt.lower():
        idx = txt.lower().find(marca.lower())
        resto = txt[idx + len(marca):].strip()
        palabras = resto.split()
        return " ".join(palabras[:3]).strip(" -_/,. ")
    return ""


def analizar_imagen(img: Image.Image):
    texto = leer_ocr(img)
    medida = extraer_medida(texto)
    marca = extraer_marca(texto)
    modelo = extraer_modelo(texto, marca)
    return texto, medida, marca, modelo

# =========================
# UTILIDADES
# =========================
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

# =========================
# APP
# =========================
init_db()

st.title("🚚 Control de Neumáticos")
st.caption("Versión móvil para registrar cambios de neumáticos directamente desde el teléfono")

pestanas = st.tabs(["📷 Nuevo registro", "📋 Histórico"])

with pestanas[0]:
    st.subheader("Nuevo registro")
    st.info("Haz una foto del neumático, revisa los datos y guarda el registro.")

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

    texto_ocr = ""
    medida_detectada = ""
    marca_detectada = ""
    modelo_detectado = ""

    if archivo_imagen:
        imagen = Image.open(archivo_imagen)
        st.image(imagen, caption="Imagen capturada", use_container_width=True)

        with st.spinner("Analizando imagen..."):
            texto_ocr, medida_detectada, marca_detectada, modelo_detectado = analizar_imagen(imagen)

        if not OCR_AVAILABLE:
            st.warning("OCR no está instalado. Los campos automáticos deberán completarse manualmente.")

        if texto_ocr:
            with st.expander("Texto detectado en la imagen"):
                st.write(texto_ocr)

    fecha = st.date_input("Fecha", value=datetime.now().date())

    empresa = st.selectbox("Empresa", EMPRESAS + ["Otra"])
    if empresa == "Otra":
        empresa = st.text_input("Nombre de la empresa")

    matricula = st.text_input("Matrícula", placeholder="Ej.: 1234ABC")
    posicion = st.selectbox("Posición", POSICIONES)
    medida = st.text_input("Medida", value=medida_detectada)
    marca = st.text_input("Marca", value=marca_detectada)
    modelo = st.text_input("Modelo", value=modelo_detectado)
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
            ))
            st.success("Registro guardado correctamente.")
            st.balloons()

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
st.markdown("### Instalación")
st.code(
    """
pip install streamlit pandas openpyxl pillow pytesseract
streamlit run app.py
    """,
    language="bash",
)

st.markdown("### Nota importante para móvil")
st.write(
    "Para usar la cámara del teléfono, abre la aplicación desde el navegador móvil y acepta el permiso de cámara."
)
