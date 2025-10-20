import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from textwrap import dedent
import pyodbc
import folium
from folium.plugins import HeatMap, Fullscreen
from streamlit_folium import st_folium
import os
from dotenv import load_dotenv
import hashlib

# Cargar variables de entorno
load_dotenv()

# Función de autenticación
def check_password():
    """Retorna True si el usuario ha ingresado la contraseña correcta."""
    
    def password_entered():
        """Verifica si la contraseña ingresada es correcta."""
        if st.session_state["password"] == os.getenv('APP_PASSWORD'):
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # No almacenar la contraseña
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        # Primera vez, mostrar input para contraseña
        st.text_input(
            "🔐 Ingresa la contraseña para acceder", 
            type="password", 
            on_change=password_entered, 
            key="password"
        )
        st.info("👆 Ingresa la contraseña para continuar")
        return False
    elif not st.session_state["password_correct"]:
        # Contraseña incorrecta, mostrar input nuevamente
        st.text_input(
            "🔐 Ingresa la contraseña para acceder", 
            type="password", 
            on_change=password_entered, 
            key="password"
        )
        st.error("❌ Contraseña incorrecta")
        return False
    else:
        # Contraseña correcta
        return True

# Configuración de la página
st.set_page_config(page_title="Top 10 por Mes", page_icon="🏆", layout="wide")

# Verificar autenticación antes de mostrar la aplicación
if not check_password():
    st.stop()  # No ejecutar el resto del código si no está autenticado

# Botón de logout en la sidebar
with st.sidebar:
    st.markdown("---")
    if st.button("🚪 Cerrar Sesión"):
        st.session_state["password_correct"] = False
        st.rerun()

MESES_ES = {1:"Enero",2:"Febrero",3:"Marzo",4:"Abril",5:"Mayo",6:"Junio",7:"Julio",8:"Agosto",9:"Septiembre",10:"Octubre",11:"Noviembre",12:"Diciembre"}

def conexion_bd():
    server = os.getenv('DB_SERVER')
    database = os.getenv('DB_DATABASE')
    username = os.getenv('DB_USERNAME')
    password = os.getenv('DB_PASSWORD')
    driver = '{ODBC Driver 17 for SQL Server}'
    conn_str = f'DRIVER={driver};SERVER={server};DATABASE={database};UID={username};PWD={password}'
    return pyodbc.connect(conn_str)

def limites_mes(anio, mes):
    inicio = datetime(anio, mes, 1, 0, 0, 0)
    fin = (inicio + relativedelta(months=1)) - timedelta(seconds=1)
    return inicio, fin

@st.cache_data(show_spinner=False)
def consulta_top10_metricas(inicio_dt, fin_dt):
    inicio_fn = inicio_dt.strftime('%Y-%m-%d')
    fin_fn = (inicio_dt + relativedelta(months=1)).strftime('%Y-%m-%d')
    inicio = inicio_dt.strftime('%Y-%m-%d %H:%M:%S')
    fin = fin_dt.strftime('%Y-%m-%d %H:%M:%S')
    sql = dedent(f"""
    WITH Metrics AS (
        SELECT
            R.id_restaurant,
            R.name_restaurant,
            CAST(COUNT(O.id_order) AS INT) AS numPedido,
            COUNT(DISTINCT AC.id_address) AS numClients,
            CAST(AVG(CASE WHEN O.payment NOT IN (3,4) THEN (O.total + O.costo_envio) END) AS DECIMAL(10,2)) AS ticketAvg,
            AVG(DATEDIFF(MINUTE, O.start_delivery_datetime, O.arrival_client_date)) AS deliveryTimeAvg,
            AVG(DATEDIFF(MINUTE, O.order_acceptance_date, O.start_delivery_datetime)) AS deliveryWaitTimeAvg,
            COUNT(CASE WHEN P.payment != 'Efectivo' AND O.payment NOT IN (3,7,4) THEN 1 END) AS ordersToCard,
            COUNT(CASE WHEN P.payment = 'Efectivo' THEN 1 END) AS ordersToCash,
            COUNT(CASE WHEN P.id_payment IN (3,7,4) THEN 1 END) AS ordersToTransference
        FROM [dev_apprisa_delivery].[dbo].tbl_restaurants R
        INNER JOIN [dev_apprisa_delivery].[dbo].tbl_orders O ON R.id_restaurant = O.restaurant
        INNER JOIN [dev_apprisa_delivery].[dbo].ctl_payment P ON P.id_payment = O.payment
        INNER JOIN [dev_apprisa_delivery].[dbo].tbl_address_client AC ON AC.id_address = O.id_address
        WHERE O.order_completion_date BETWEEN '{inicio}' AND '{fin}' AND O.[status] = 24
        GROUP BY R.id_restaurant,R.name_restaurant
    ),
    OrdersByDay AS (
        SELECT
            R.id_restaurant,
            DATENAME(WEEKDAY, O.order_completion_date) AS dia_semana,
            COUNT(*) AS pedidos
        FROM [dev_apprisa_delivery].[dbo].tbl_restaurants R
        INNER JOIN [dev_apprisa_delivery].[dbo].tbl_orders O ON R.id_restaurant = O.restaurant
        WHERE O.order_completion_date BETWEEN '{inicio}' AND '{fin}' AND O.[status] = 24
        GROUP BY R.id_restaurant, DATENAME(WEEKDAY, O.order_completion_date)
    ),
    Pivoted AS (
        SELECT *
        FROM OrdersByDay
        PIVOT (SUM(pedidos) FOR dia_semana IN ([Monday],[Tuesday],[Wednesday],[Thursday],[Friday],[Saturday],[Sunday])) AS p
    )
    SELECT
        M.id_restaurant,
        M.name_restaurant,
        M.numClients,
        M.ticketAvg,
        M.deliveryTimeAvg,
        M.deliveryWaitTimeAvg,
        M.ordersToCard,
        M.ordersToCash,
        M.ordersToTransference,
        ISNULL(P.[Monday],0) AS [Monday],
        ISNULL(P.[Tuesday],0) AS [Tuesday],
        ISNULL(P.[Wednesday],0) AS [Wednesday],
        ISNULL(P.[Thursday],0) AS [Thursday],
        ISNULL(P.[Friday],0) AS [Friday],
        ISNULL(P.[Saturday],0) AS [Saturday],
        ISNULL(P.[Sunday],0) AS [Sunday]
    FROM Metrics M
    LEFT JOIN Pivoted P ON M.id_restaurant = P.id_restaurant
    ORDER BY M.numPedido DESC;
    """)
    conn = conexion_bd()
    df = pd.read_sql(sql, conn)
    conn.close()
    return df

@st.cache_data(show_spinner=False)
def consulta_coordenadas_mes(id_restaurante, inicio_dt, fin_dt):
    inicio = inicio_dt.strftime('%Y-%m-%d %H:%M:%S')
    fin = fin_dt.strftime('%Y-%m-%d %H:%M:%S')
    sql = dedent(f"""
        SELECT 
            ISNULL(tac.latitude, ads.ad_latitude) AS lat,
            ISNULL(tac.longitude, ads.ad_longitude) AS lon
        FROM [dev_apprisa_delivery].[dbo].tbl_orders tbo
        LEFT JOIN [dev_apprisa_delivery].[dbo].tbl_address_client tac ON tac.id_address = tbo.id_address
        LEFT JOIN [dev_apprisa_delivery].[dbo].addresses ads ON tbo.addresses_id = ads.ad_id
        WHERE tbo.[status] = 24
          AND tbo.restaurant = {id_restaurante}
          AND tbo.order_completion_date BETWEEN '{inicio}' AND '{fin}'
    """)
    conn = conexion_bd()
    df = pd.read_sql(sql, conn)
    conn.close()
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
    return df.dropna(subset=["lat","lon"])

@st.cache_data(show_spinner=False)
def consulta_pedidos_hora_mes(id_restaurante, inicio_dt, fin_dt):
    inicio = inicio_dt.strftime('%Y-%m-%d %H:%M:%S')
    fin = fin_dt.strftime('%Y-%m-%d %H:%M:%S')
    sql = dedent(f"""
        SELECT DATEPART(HOUR, O.order_completion_date) AS hora, COUNT(*) AS pedidos
        FROM [dev_apprisa_delivery].[dbo].tbl_orders O
        WHERE O.order_completion_date BETWEEN '{inicio}' AND '{fin}'
          AND O.[status] = 24
          AND O.restaurant = {id_restaurante}
        GROUP BY DATEPART(HOUR, O.order_completion_date)
        HAVING COUNT(*) > 0
        ORDER BY hora
    """)
    conn = conexion_bd()
    df = pd.read_sql(sql, conn)
    conn.close()
    return df

@st.cache_data(show_spinner=False)
def consulta_diaria_restaurante(id_restaurante, inicio_fecha, fin_fecha):
    inicio = inicio_fecha.strftime('%Y-%m-%d')
    fin = fin_fecha.strftime('%Y-%m-%d')
    sql = dedent(f"""
        SELECT 
            CONVERT(date, o.order_completion_date) AS fecha,
            COUNT(o.id_order) AS pedidos
        FROM [dev_apprisa_delivery].[dbo].tbl_orders o
        WHERE o.order_completion_date>'{inicio}' AND o.order_completion_date < '{fin}'
          AND o.status = 24
          AND o.restaurant = {id_restaurante}
        GROUP BY CONVERT(date, o.order_completion_date)
        ORDER BY fecha
    """)
    conn = conexion_bd()
    df = pd.read_sql(sql, conn)
    conn.close()
    return df

@st.cache_data(show_spinner=False)
def consulta_resumen_mes(id_restaurante, inicio_dt, fin_dt):
    inicio = inicio_dt.strftime('%Y-%m-%d %H:%M:%S')
    fin = fin_dt.strftime('%Y-%m-%d %H:%M:%S')
    sql = dedent(f"""
        SELECT 
            COUNT(*) AS pedidos,
            COUNT(DISTINCT CONVERT(date, order_completion_date)) AS dias_activos,
            SUM(costo_credits) AS creditos
        FROM [dev_apprisa_delivery].[dbo].tbl_orders
        WHERE [status]=24 AND restaurant={id_restaurante}
          AND order_completion_date BETWEEN '{inicio}' AND '{fin}'
    """).replace("costo_credits","costo_creditos")
    conn = conexion_bd()
    df = pd.read_sql(sql, conn)
    conn.close()
    return int(df.iloc[0]["pedidos"]), int(df.iloc[0]["dias_activos"]), float(df.iloc[0]["creditos"] if df.iloc[0]["creditos"] is not None else 0)

def grafico_dias_semana_es(fila):
    mapa = {"Monday":"Lunes","Tuesday":"Martes","Wednesday":"Miércoles","Thursday":"Jueves","Friday":"Viernes","Saturday":"Sábado","Sunday":"Domingo"}
    dias = []
    pedidos = []
    for en, es in mapa.items():
        dias.append(es)
        pedidos.append(int(fila.get(en, 0)))
    df = pd.DataFrame({"Día": dias, "Pedidos": pedidos}).sort_values("Pedidos", ascending=False)
    fig = px.pie(df, names="Día", values="Pedidos", title="Distribución de pedidos por día de la semana")
    return fig

def tabla_top10(df):
    dias = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
    df2 = df.copy()
    df2["Pedidos Mes"] = df2[dias].sum(axis=1)
    df2 = df2[["name_restaurant","Pedidos Mes","ticketAvg","deliveryTimeAvg","deliveryWaitTimeAvg","ordersToCard","ordersToCash","ordersToTransference"]]
    df2 = df2.rename(columns={
        "name_restaurant":"Establecimiento",
        "ticketAvg":"Ticket Promedio",
        "deliveryTimeAvg":"Tiempo Delivery (min)",
        "deliveryWaitTimeAvg":"Tiempo Espera (min)",
        "ordersToCard":"Pagos Tarjeta",
        "ordersToCash":"Pagos Efectivo",
        "ordersToTransference":"Pagos Transferencia"
    })
    return df2

def mapa_calor(df_coords):
    if df_coords.empty:
        return None
    m = folium.Map(location=[df_coords["lat"].mean(), df_coords["lon"].mean()], zoom_start=12, tiles="OpenStreetMap", control_scale=True)
    HeatMap(data=df_coords[["lat","lon"]].values, radius=15, blur=10, max_zoom=13).add_to(m)
    Fullscreen().add_to(m)
    return m

def tabla_y_grafico_mensual(df_diario):
    if df_diario.empty:
        return None, None
    df = df_diario.copy()
    df["fecha"] = pd.to_datetime(df["fecha"])
    dfm = df.groupby(pd.Grouper(key="fecha", freq="M"))["pedidos"].sum().reset_index()
    dfm["Mes"] = dfm["fecha"].dt.month.map(MESES_ES) + " " + dfm["fecha"].dt.year.astype(str)
    dfm["Variación %"] = dfm["pedidos"].pct_change().replace([np.inf,-np.inf], np.nan)*100
    dfm = dfm.rename(columns={"pedidos":"Pedidos"})
    fig = px.bar(dfm.sort_values("fecha"), x="Mes", y="Pedidos", title="Pedidos por mes y variación", text="Pedidos")
    fig.update_traces(textposition="outside")
    return dfm[["Mes","Pedidos","Variación %"]], fig

def ventana_pico_horaria(df_horas, cobertura=0.8):
    if df_horas.empty:
        return None
    base = pd.DataFrame({"hora": list(range(24))}).merge(df_horas, on="hora", how="left").fillna({"pedidos":0})
    total = int(base["pedidos"].sum())
    if total == 0:
        return None
    objetivo = total * cobertura
    mejor_inicio = 0
    mejor_fin = 23
    mejor_ancho = 24
    mejor_suma = 0
    for ancho in range(1,25):
        for inicio in range(0,24-ancho+1):
            fin = inicio + ancho - 1
            suma = int(base.loc[(base["hora"]>=inicio)&(base["hora"]<=fin),"pedidos"].sum())
            if suma >= objetivo:
                if ancho < mejor_ancho or (ancho == mejor_ancho and suma > mejor_suma):
                    mejor_inicio, mejor_fin, mejor_ancho, mejor_suma = inicio, fin, ancho, suma
        if mejor_suma >= objetivo:
            break
    porcentaje = 100 * mejor_suma / total
    return mejor_inicio, mejor_fin, porcentaje, total

def analisis_textual(df_horas, df_diario_mes, titulo_mes):
    vm = ventana_pico_horaria(df_horas, 0.8)
    if vm is None:
        texto_picos = f"**Patrones Diarios ({titulo_mes})**\n\n- Sin datos suficientes para calcular picos"
    else:
        hi, hf, porc, _ = vm
        hora_pico = int(df_horas.loc[df_horas["pedidos"].idxmax(),"hora"]) if not df_horas.empty else 0
        pedidos_pico = int(df_horas["pedidos"].max()) if not df_horas.empty else 0
        texto_picos = f"**Patrones Diarios ({titulo_mes})**\n\n- Pico de Actividad: {hi:02d}:00 - {hf:02d}:00 (Representa el {porc:.0f}% de pedidos del día)\n- Hora Pico Absoluta: {hora_pico:02d}:00 ({pedidos_pico} pedidos)"
    if df_diario_mes.empty:
        texto_semana = "**Evolución Semanal**\n\n- Sin datos"
    else:
        df = df_diario_mes.copy()
        df["semana"] = df["fecha"].dt.isocalendar().week
        sem = df.groupby("semana")["pedidos"].sum().reset_index().sort_values("semana")
        semana_max = int(sem.loc[sem["pedidos"].idxmax(),"semana"])
        pedidos_max = int(sem["pedidos"].max())
        tendencia = "Estable"
        if len(sem) > 1:
            pendiente = (sem["pedidos"].iloc[-1] - sem["pedidos"].iloc[0]) / len(sem)
            if pendiente > 0.5:
                tendencia = "Crecimiento"
            elif pendiente < -0.5:
                tendencia = "Declive"
        texto_semana = f"**Evolución Semanal**\n\n- Semana más Fuerte: Semana {semana_max} ({pedidos_max} pedidos)\n- Tendencia General: {tendencia}"
    return texto_picos, texto_semana

def app():
    st.title("🏆 Top 10 por Mes")
    hoy = datetime.now()
    anios = list(range(hoy.year-3, hoy.year+1))
    with st.sidebar:
        st.header("Periodo")
        anio_sel = st.selectbox("Año", anios, index=anios.index(hoy.year))
        mes_sel = st.selectbox("Mes", list(MESES_ES.values()), index=hoy.month-1)
    mes_num = [k for k,v in MESES_ES.items() if v == mes_sel][0]
    inicio_mes, fin_mes = limites_mes(anio_sel, mes_num)
    df_top = consulta_top10_metricas(inicio_mes, fin_mes)
    if df_top.empty:
        st.info("Aún no hay datos para el mes seleccionado.")
        return
    c1, c2 = st.columns([1.2,1])
    with c1:
        st.subheader(f"Top 10 • {mes_sel} {anio_sel}")
        st.dataframe(tabla_top10(df_top), hide_index=True, use_container_width=True)
    with c2:
        cols_dias = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
        df_top["Pedidos Mes"] = df_top[cols_dias].sum(axis=1)
        df_top10 = df_metricas.sort_values("Pedidos Mes", ascending=False).head(10)
        fig_top = px.bar(df_top10, x="name_restaurant", y="Pedidos Mes", title="Top 10 Establecimientos por Pedidos")
        fig_top.update_layout(xaxis_title="Establecimiento", yaxis_title="Pedidos")
        st.plotly_chart(fig_top, use_container_width=True)
    with st.sidebar:
        st.header("Establecimiento del Top 10")
        opciones = df_top["name_restaurant"].tolist()
        establecimiento_sel = st.selectbox("Selecciona", opciones, index=0)
    fila_sel = df_top[df_top["name_restaurant"]==establecimiento_sel].iloc[0]
    st.markdown(f"### {establecimiento_sel}")
    k1,k2,k3,k4 = st.columns(4)
    k1.metric("Ticket promedio", f"${float(fila_sel['ticketAvg']):,.2f}")
    k2.metric("Tiempo de entrega promedio (minutos)", f"{float(fila_sel['deliveryTimeAvg']):.1f}")
    k3.metric("Tiempo espera promedio (minutos)", f"{float(fila_sel['deliveryWaitTimeAvg']):.1f}")
    k4.metric("Clientes únicos", f"{int(fila_sel['numClients'])}")
    col_a, col_b = st.columns([1.2,1])
    with col_a:
        st.subheader(f"Mapa de Calor de Clientes • {mes_sel} {anio_sel}")
        coords = consulta_coordenadas_mes(int(fila_sel["id_restaurant"]), inicio_mes, fin_mes)
        mapa = mapa_calor(coords)
        if mapa is None:
            st.warning("Sin datos de ubicación para el mes seleccionado.")
        else:
            st_folium(mapa, width=1200, height=500, key=f"map_{anio_sel}_{mes_num}_{int(fila_sel['id_restaurant'])}")
    with col_b:
        st.subheader("Pagos")
        p1,p2,p3 = st.columns(3)
        p1.metric("Tarjeta", int(fila_sel["ordersToCard"]))
        p2.metric("Efectivo", int(fila_sel["ordersToCash"]))
        p3.metric("Transferencia", int(fila_sel["ordersToTransference"]))
    df_horas = consulta_pedidos_hora_mes(int(fila_sel["id_restaurant"]), inicio_mes, fin_mes)
    inicio_anio = datetime(anio_sel, 1, 1)
    fin_anio = datetime(anio_sel, 12, 31, 23, 59, 59)
    df_diario = consulta_diaria_restaurante(int(fila_sel["id_restaurant"]), inicio_anio, fin_anio).copy()
    df_diario["fecha"] = pd.to_datetime(df_diario["fecha"])
    inicio_mes_ts = pd.Timestamp(inicio_mes.year, inicio_mes.month, inicio_mes.day)
    fin_mes_ts = pd.Timestamp(fin_mes.year, fin_mes.month, fin_mes.day)
    df_diario_mes = df_diario[(df_diario["fecha"] >= inicio_mes_ts) & (df_diario["fecha"] <= fin_mes_ts)].copy()
    pedidos_mes, dias_activos_mes, creditos_mes = consulta_resumen_mes(int(fila_sel["id_restaurant"]), inicio_mes, fin_mes)
    inicio_ant, fin_ant = limites_mes(*(inicio_mes - relativedelta(months=1)).timetuple()[:2])
    pedidos_ant, dias_activos_ant, creditos_ant = consulta_resumen_mes(int(fila_sel["id_restaurant"]), inicio_ant, fin_ant)
    prom_mes = pedidos_mes / dias_activos_mes if dias_activos_mes > 0 else 0
    prom_ant = pedidos_ant / dias_activos_ant if dias_activos_ant > 0 else 0
    d1 = f"{((pedidos_mes - pedidos_ant)/pedidos_ant*100):.1f}%" if pedidos_ant>0 else None
    d2 = f"{((dias_activos_mes - dias_activos_ant)/dias_activos_ant*100):.1f}%" if dias_activos_ant>0 else None
    d3 = f"{((prom_mes - prom_ant)/prom_ant*100):.1f}%" if prom_ant>0 else None
    d4 = f"{((creditos_mes - creditos_ant)/creditos_ant*100):.1f}%" if creditos_ant>0 else None
    m1,m2,m3 = st.columns(3)
    m1.metric("Total de Pedidos", pedidos_mes, d1)
    m2.metric("Días Activos", dias_activos_mes, d2)
    m3.metric("Promedio de Pedidos por Día", f"{prom_mes:.1f}", d3)
    #m4.metric("Créditos Usados", f"{creditos_mes:,.0f}", d4)
    texto_picos, texto_semana = analisis_textual(df_horas, df_diario_mes, f"{mes_sel} {anio_sel}")
    st.markdown(texto_picos)
    st.markdown(texto_semana)
    st.subheader(f"📊 Gráfica de Pedidos • {mes_sel} {anio_sel}")
    fig_linea = go.Figure()
    fig_linea.add_trace(go.Scatter(x=df_diario_mes["fecha"], y=df_diario_mes["pedidos"], mode="lines+markers", line=dict(width=2)))
    fig_linea.update_layout(title=f"Pedidos por Día • {mes_sel} {anio_sel}", xaxis_title="Fecha", yaxis_title="Número de Pedidos", hovermode="x unified")
    st.plotly_chart(fig_linea, use_container_width=True)
    st.subheader("Pedidos por día de la semana")
    st.plotly_chart(grafico_dias_semana_es(fila_sel), use_container_width=True)
    st.subheader("Pedidos por hora")
    if df_horas.empty:
        st.warning("Sin pedidos por hora en el mes seleccionado.")
    else:
        df_horas = df_horas.sort_values("hora")
        df_horas["Hora"] = df_horas["hora"].astype(int).astype(str).str.zfill(2)+":00"
        fig_h = px.bar(df_horas, x="Hora", y="pedidos", text="pedidos", title=f"Pedidos por hora • {mes_sel} {anio_sel}")
        fig_h.update_traces(textposition="outside")
        st.plotly_chart(fig_h, use_container_width=True)
    st.subheader("Pedidos por mes y tasa de cambio")
    tabla_m, fig_m = tabla_y_grafico_mensual(df_diario)
    st.plotly_chart(fig_m, use_container_width=True)
    st.dataframe(tabla_m.fillna(0), hide_index=True, use_container_width=True)

if __name__ == "__main__":
    app()
