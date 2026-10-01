""" 
URL base: http://rmcab.ambientebogota.gov.co/Report/HighestPM25?id=1&UserDateString=YYYY-MM-DD

- Rango de fechas: (2009-04-01 a 2015-08-31)
- Checkpoint/resume: si ele script se interrumpe, al volver a correrlo continúa donde quedó, sin repetir descargas ya exitosas 

Uso:
    a) Sondeo rápido para confirmar que hay datos en el rango deseado
    python scraper_rmcab_pm25.py --sondeo

    b) Descarfa completa del rango (con resumen por si se corta)
    python scraper_rmcab_pm25.py --inicio 2009-04-01 --fin 2015-08-31 --salida rmcab_pm25_2009_2015.csv

    c) Si se interrumpe, simpleemente cuelve a correr el mismo comando: el script detecta y el checkpoint continúa donde quedó

"""


import argparse
import csv
import os
import time
from datetime import datetime, timedelta
 
import pandas as pd
import requests
from bs4 import BeautifulSoup
 
BASE_URL = "http://rmcab.ambientebogota.gov.co/Report/HighestPM25"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}
 
COLUMNAS_FINALES = [
    "fecha", "zona", "estacion", "unidades",
    "pm25_24h", "hora_24h", "pm25_1h", "hora_1h"
]
 
 
def rango_fechas(inicio: str, fin: str):
    d0 = datetime.strptime(inicio, "%Y-%m-%d")
    d1 = datetime.strptime(fin, "%Y-%m-%d")
    while d0 <= d1:
        yield d0.strftime("%Y-%m-%d")
        d0 += timedelta(days=1)
 
 
def obtener_html(fecha: str, id_condado: int = 1, timeout: int = 20,
                  max_reintentos: int = 4):
    """
    Descarga el HTML con reintentos y backoff exponencial.
    Devuelve None si todos los reintentos fallan (para no tumbar el script completo).
    """
    params = {"id": id_condado, "UserDateString": fecha}
    espera = 1.0
    for intento in range(1, max_reintentos + 1):
        try:
            resp = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=timeout)
            resp.raise_for_status()
            return resp.text
        except requests.exceptions.RequestException as e:
            print(f"    intento {intento}/{max_reintentos} falló para {fecha}: {e}")
            if intento < max_reintentos:
                time.sleep(espera)
                espera *= 2  # backoff exponencial: 1s, 2s, 4s, 8s...
    print(f"    -> {fecha} descartado tras {max_reintentos} intentos")
    return None
 
 
def parsear_tabla(html: str, fecha: str, debug: bool = False):
    """
    Extrae la tabla de estaciones/PM2.5 directamente con BeautifulSoup
    (sin pasar por pd.read_html, que en pandas 3.x puede confundir un
    string de HTML largo con una ruta de archivo).
    Devuelve None si no encuentra tabla válida o no tiene filas de datos.
    """
    try:
        soup = BeautifulSoup(html, "html.parser")
        tabla_html = soup.find("table", class_="DataTable")
        if tabla_html is None:
            if debug:
                print("    [debug] no se encontró <table class='DataTable'> en el HTML")
            return None
 
        filas = tabla_html.find("tbody").find_all("tr")
        if not filas:
            if debug:
                print("    [debug] la tabla no tiene filas en <tbody>")
            return None
 
        registros = []
        for fila in filas:
            celdas = fila.find_all("td")
            if len(celdas) != 7:
                continue  # fila inesperada, se ignora
            valores = [c.get_text(strip=True) for c in celdas]
            registros.append(valores)
 
        if not registros:
            if debug:
                print("    [debug] no se extrajeron filas válidas de 7 celdas")
            return None
 
        tabla = pd.DataFrame(
            registros,
            columns=["zona", "estacion", "unidades",
                     "pm25_24h", "hora_24h", "pm25_1h", "hora_1h"]
        )
 
        if debug:
            print(f"    [debug] tabla extraída: {tabla.shape[0]} filas")
 
    except Exception as e:
        if debug:
            print(f"    [debug] excepción al parsear: {type(e).__name__}: {e}")
        return None
 
    tabla["fecha"] = fecha
    return tabla[COLUMNAS_FINALES]
 
 
def convertir_numeros(df: pd.DataFrame) -> pd.DataFrame:
    for col in ["pm25_24h", "pm25_1h"]:
        df[col] = (
            df[col].astype(str)
            .str.replace(",", ".", regex=False)
            .replace("nan", pd.NA)
        )
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df
 
 
def cargar_checkpoint(ruta_checkpoint: str) -> set:
    """Devuelve el set de fechas ya descargadas exitosamente."""
    if os.path.exists(ruta_checkpoint):
        with open(ruta_checkpoint, "r") as f:
            return set(line.strip() for line in f if line.strip())
    return set()
 
 
def marcar_checkpoint(ruta_checkpoint: str, fecha: str):
    with open(ruta_checkpoint, "a") as f:
        f.write(fecha + "\n")
 
 
def sondeo(fechas_ancla, id_condado: int = 1):
    """Prueba unas pocas fechas para ver si hay datos, antes de lanzar todo."""
    print("=== SONDEO: verificando disponibilidad de datos ===\n")
    for fecha in fechas_ancla:
        print(f"-- {fecha} --")
        html = obtener_html(fecha, id_condado=id_condado, max_reintentos=2)
        if html is None:
            print(f"{fecha}: sin respuesta del servidor")
            continue
        df = parsear_tabla(html, fecha, debug=True)
        if df is None:
            print(f"{fecha}: no se encontró tabla de datos (probablemente sin datos históricos)")
        else:
            con_datos = df["pm25_24h"].notna().sum() if not df.empty else 0
            print(f"{fecha}: tabla encontrada, {len(df)} estaciones, {con_datos} con valores PM2.5")
        time.sleep(1)
    print("\n=== Fin del sondeo ===")
 
 
def main():
    ap = argparse.ArgumentParser(description="Scraper RMCAB PM2.5 (rango largo, con resume)")
    ap.add_argument("--inicio", default="2009-04-01", help="Fecha inicio YYYY-MM-DD")
    ap.add_argument("--fin", default="2015-08-31", help="Fecha fin YYYY-MM-DD")
    ap.add_argument("--id", type=int, default=1, help="id de condado/zona (default 1)")
    ap.add_argument("--salida", default="rmcab_pm25_2009_2015.csv", help="Archivo CSV de salida")
    ap.add_argument("--espera", type=float, default=1.5,
                     help="Segundos de espera entre requests exitosos")
    ap.add_argument("--sondeo", action="store_true",
                     help="Solo prueba fechas ancla para verificar disponibilidad de datos")
    args = ap.parse_args()
 
    if args.sondeo:
        # Fechas ancla: inicio del rango, y cada ~1 año dentro del rango pedido
        fechas_ancla = ["2009-04-01", "2009-07-01", "2010-01-01", "2011-01-01",
                         "2012-01-01", "2013-01-01", "2014-01-01", "2015-01-01",
                         "2015-08-31"]
        sondeo(fechas_ancla, id_condado=args.id)
        return
 
    checkpoint_path = args.salida + ".checkpoint"
    ya_descargadas = cargar_checkpoint(checkpoint_path)
 
    escribir_encabezado = not os.path.exists(args.salida)
    todas_las_fechas = list(rango_fechas(args.inicio, args.fin))
    pendientes = [f for f in todas_las_fechas if f not in ya_descargadas]
 
    print(f"Total de fechas en el rango: {len(todas_las_fechas)}")
    print(f"Ya descargadas (checkpoint): {len(ya_descargadas)}")
    print(f"Pendientes por descargar: {len(pendientes)}\n")
 
    if not pendientes:
        print("Nada pendiente. Todo el rango ya fue descargado.")
        return
 
    fallidas = []
 
    with open(args.salida, "a", newline="", encoding="utf-8-sig") as f_out:
        writer = csv.writer(f_out)
        if escribir_encabezado:
            writer.writerow(COLUMNAS_FINALES)
 
        for i, fecha in enumerate(pendientes):
            print(f"[{i+1}/{len(pendientes)}] {fecha} ...", end=" ")
            html = obtener_html(fecha, id_condado=args.id)
 
            if html is None:
                print("FALLÓ (sin respuesta)")
                fallidas.append(fecha)
                continue
 
            df = parsear_tabla(html, fecha)
            if df is None or df.empty:
                print("sin tabla de datos (posiblemente fuera de rango histórico)")
                # Igual lo marcamos como "procesado" para no reintentar infinitamente
                marcar_checkpoint(checkpoint_path, fecha)
                continue
 
            df = convertir_numeros(df)
            for _, row in df.iterrows():
                writer.writerow([row[c] for c in COLUMNAS_FINALES])
            f_out.flush()
 
            marcar_checkpoint(checkpoint_path, fecha)
            print(f"OK ({len(df)} estaciones)")
 
            time.sleep(args.espera)
 
    print(f"\nProceso terminado. Datos guardados en: {args.salida}")
    if fallidas:
        print(f"\n{len(fallidas)} fechas fallaron y NO quedaron en el checkpoint:")
        print(fallidas[:20], "..." if len(fallidas) > 20 else "")
        print("Vuelve a correr el mismo comando para reintentarlas automáticamente.")
 
 
if __name__ == "__main__":
    main()