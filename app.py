import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import date
import hashlib
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots 
import time

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Poker Club", page_icon="♣️", layout="centered")

# COSTANTI
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
CREDENTIALS_FILE = "credentials.json"
SHEET_NAME = "PokerDB"

# --- CONNESSIONE GOOGLE SHEETS (Con Cache Risorse) ---
@st.cache_resource
def get_connection():
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, SCOPE)
        client = gspread.authorize(creds)
        sheet = client.open(SHEET_NAME)
        return sheet
    except Exception as e:
        st.error(f"Errore connessione Google Sheets: {e}")
        st.stop()

# --- INIT DB ---
@st.cache_resource
def init_db():
    try:
        sheet = get_connection()
        ws_users = sheet.worksheet("Utenti")
        if not ws_users.row_values(1): ws_users.append_row(["Username", "Password"])
        ws_clubs = sheet.worksheet("Club")
        if not ws_clubs.row_values(1): ws_clubs.append_row(["NomeClub", "Owner", "Membri"])
        ws_games = sheet.worksheet("Partite")
        if not ws_games.row_values(1): ws_games.append_row(["Data", "Giocatore", "BuyIn", "CashOut", "Profitto", "Club"])
    except Exception as e:
        time.sleep(1)

# --- BACKEND CACHED ---
def hash_password(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

@st.cache_data(ttl=600)
def carica_utenti():
    sheet = get_connection()
    ws = sheet.worksheet("Utenti")
    records = ws.get_all_records()
    users_dict = {}
    for r in records:
        users_dict[str(r["Username"])] = {"password": str(r["Password"])}
    return users_dict

def crea_utente(username, password):
    users = carica_utenti()
    if username in users: return False
    sheet = get_connection()
    ws = sheet.worksheet("Utenti")
    ws.append_row([username, hash_password(password)])
    st.cache_data.clear()
    return True

def verifica_login(username, password):
    users = carica_utenti()
    if username in users and users[username]["password"] == hash_password(password):
        return True
    return False

@st.cache_data(ttl=60)
def carica_clubs():
    sheet = get_connection()
    ws = sheet.worksheet("Club")
    records = ws.get_all_records()
    clubs_dict = {}
    for r in records:
        members_list = str(r["Membri"]).split(",") if r["Membri"] else []
        clubs_dict[str(r["NomeClub"])] = {"owner": str(r["Owner"]), "members": members_list}
    return clubs_dict

def crea_club(nome_club, owner):
    st.cache_data.clear() 
    clubs = carica_clubs()
    if nome_club in clubs: return False
    sheet = get_connection()
    ws = sheet.worksheet("Club")
    ws.append_row([nome_club, owner, owner]) 
    st.cache_data.clear()
    return True

def get_user_clubs(username):
    all_clubs = carica_clubs()
    return [name for name, data in all_clubs.items() if username in data["members"]]

def get_club_owner(club_name):
    clubs = carica_clubs()
    return clubs[club_name]["owner"] if club_name in clubs else None

def aggiungi_membro_al_club(club_name, new_member_username):
    users = carica_utenti()
    if new_member_username not in users: return "not_found"
    sheet = get_connection()
    ws = sheet.worksheet("Club")
    cell = ws.find(club_name)
    if not cell: return "error"
    row_idx = cell.row
    current_members_str = ws.cell(row_idx, 3).value 
    current_members = current_members_str.split(",") if current_members_str else []
    if new_member_username in current_members: return "already_in"
    current_members.append(new_member_username)
    new_members_str = ",".join(current_members)
    ws.update_cell(row_idx, 3, new_members_str)
    st.cache_data.clear()
    return "success"

@st.cache_data(ttl=60)
def carica_dati_club(club_name):
    sheet = get_connection()
    ws = sheet.worksheet("Partite")
    data = ws.get_all_records()
    df = pd.DataFrame(data)
    if df.empty: return pd.DataFrame()
    if "Club" in df.columns:
        df = df[df["Club"] == club_name].copy()
    return df

def salva_partita(club_name, dati_sessione_df):
    sheet = get_connection()
    ws = sheet.worksheet("Partite")
    rows_to_add = []
    for index, row in dati_sessione_df.iterrows():
        r = [str(row["Data"]), row["Giocatore"], float(row["BuyIn"]), float(row["CashOut"]), float(row["Profitto"]), club_name]
        rows_to_add.append(r)
    if rows_to_add:
        ws.append_rows(rows_to_add)
        st.cache_data.clear()

# --- IMPORTAZIONE MODIFICATA (Strategia Mista) ---
def importa_dati(club_name):
    st.header("📥 Importa da Excel")
    st.write("Carica qui il tuo file storico.")
    
    uploaded_file = st.file_uploader("Trascina qui il file (.xlsx o .csv)", type=["xlsx", "csv"])
    
    if uploaded_file:
        try:
            # 1. NON usiamo dtype=str per tutto. Lasciamo che Pandas capisca le date da solo.
            if uploaded_file.name.endswith('.csv'): 
                df_new = pd.read_csv(uploaded_file)
            else: 
                df_new = pd.read_excel(uploaded_file)
            
            # Pulizia nomi colonne
            df_new.columns = [c.strip() for c in df_new.columns]
            cols_lower = {c.lower(): c for c in df_new.columns}
            
            rename_map = {}
            if "nome del giocatore" in cols_lower: rename_map[cols_lower["nome del giocatore"]] = "Giocatore"
            elif "giocatore" in cols_lower: rename_map[cols_lower["giocatore"]] = "Giocatore"
            if "entrata" in cols_lower: rename_map[cols_lower["entrata"]] = "BuyIn"
            elif "buyin" in cols_lower: rename_map[cols_lower["buyin"]] = "BuyIn"
            for col in cols_lower:
                if "uscita" in col or "cashout" in col:
                    rename_map[cols_lower[col]] = "CashOut"
                    break
            if "data" in cols_lower: rename_map[cols_lower["data"]] = "Data"
            
            df_new = df_new.rename(columns=rename_map)
            
            # 2. PULIZIA NUMERI (Convertiamo a stringa SOLO ORA per pulire)
            def clean_number_italy(x):
                # Forziamo a stringa per analizzare virgole e punti
                s = str(x).strip()
                if s == "nan" or s == "": return 0.0
                
                s = s.replace("€", "").strip()
                s = s.replace("-", "0")
                
                # Se c'è la virgola, è un decimale italiano (17,50)
                if "," in s:
                    s = s.replace(".", "") # Via i punti delle migliaia
                    s = s.replace(",", ".") # Virgola diventa punto
                return float(s)

            for col in ["BuyIn", "CashOut"]:
                df_new[col] = df_new[col].apply(clean_number_italy)

            df_new["Profitto"] = df_new["CashOut"] - df_new["BuyIn"]
            
            # 3. DATE (Lasciamo che Pandas faccia la magia, poi forziamo il formato)
            # errors='coerce' metterà NaT se proprio non capisce, ma senza dtype=str dovrebbe capire quasi tutto
            df_new["Data"] = pd.to_datetime(df_new["Data"], dayfirst=True, errors='coerce')
            
            # Check righe perse
            righe_totali = len(df_new)
            df_new = df_new.dropna(subset=["Data"])
            righe_valide = len(df_new)
            
            if righe_valide < righe_totali:
                st.warning(f"⚠️ Attenzione: {righe_totali - righe_valide} righe ignorate per data non valida.")
            
            # Convertiamo in stringa YYYY-MM-DD per Google Sheets
            df_new["Data"] = df_new["Data"].dt.strftime('%Y-%m-%d')

            st.write(f"Anteprima ({righe_valide} righe pronte):")
            st.dataframe(df_new.head())
            
            if st.button("✅ Conferma Importazione"):
                sheet = get_connection()
                ws = sheet.worksheet("Partite")
                
                all_rows = []
                for index, row in df_new.iterrows():
                    r = [str(row["Data"]), row["Giocatore"], float(row["BuyIn"]), float(row["CashOut"]), float(row["Profitto"]), club_name]
                    all_rows.append(r)
                
                # CARICAMENTO A BLOCCHI
                chunk_size = 50
                progress_bar = st.progress(0)
                total_rows = len(all_rows)
                status_text = st.empty()
                
                for i in range(0, total_rows, chunk_size):
                    chunk = all_rows[i:i + chunk_size]
                    ws.append_rows(chunk)
                    progress = min((i + chunk_size) / total_rows, 1.0)
                    progress_bar.progress(progress)
                    status_text.text(f"Caricamento: {int(progress*100)}%...")
                    time.sleep(1.5)
                
                status_text.text("✅ Fatto!")
                st.success(f"Caricate {total_rows} righe con successo!")
                st.cache_data.clear()
                time.sleep(1)
                st.rerun()
                    
        except Exception as e:
            st.error(f"Errore: {e}")

# --- FRONTEND ---
if "logged_in" not in st.session_state: st.session_state.logged_in = False
if "username" not in st.session_state: st.session_state.username = None
if "current_club" not in st.session_state: st.session_state.current_club = None
if "session_data" not in st.session_state: st.session_state.session_data = []

try:
    init_db()
except:
    pass

def login_page():
    st.title("♣️ Poker Hub (Cloud Edition)")
    tab1, tab2 = st.tabs(["Accedi", "Registrati"])
    with tab1:
        u = st.text_input("Username", key="log_u")
        p = st.text_input("Password", type="password", key="log_p")
        if st.button("Entra"):
            if verifica_login(u, p):
                st.session_state.logged_in, st.session_state.username = True, u
                st.rerun()
            else: st.error("Dati errati")
    with tab2:
        nu, np = st.text_input("Nuovo Username"), st.text_input("Nuova Password", type="password")
        if st.button("Crea Account"):
            if crea_utente(nu, np): st.success("Creato! Vai su Accedi")
            else: st.error("Username occupato")

def gestisci_partita_live(club_name, is_host):
    st.subheader("🎲 Tavolo da Gioco")
    if not is_host:
        st.info("🔒 Solo l'Host può inserire i dati.")
        return

    df_session = pd.DataFrame(st.session_state.session_data)
    if df_session.empty:
        df_session = pd.DataFrame(columns=["Data", "Giocatore", "BuyIn", "CashOut", "Profitto"])

    clubs = carica_clubs()
    membri = clubs[club_name]["members"]

    with st.expander("Aggiungi Risultato", expanded=True):
        col_data, col_vuota = st.columns([1, 1])
        with col_data:
            data_selezionata = st.date_input("📅 Data della Partita", date.today())
        st.markdown("---")
        col1, col2 = st.columns(2)
        with col1: p_name = st.selectbox("Giocatore", membri)
        with col2:
            p_buyin = st.number_input("Buy-In", min_value=0.0, step=5.0, key="bi")
            p_cashout = st.number_input("Cash-Out", min_value=0.0, step=5.0, key="co")
        
        if st.button("➕ Aggiungi alla lista"):
            profit = p_cashout - p_buyin
            new_row = {"Data": data_selezionata, "Giocatore": p_name, "BuyIn": p_buyin, "CashOut": p_cashout, "Profitto": profit}
            st.session_state.session_data.append(new_row)
            st.rerun()

    if not df_session.empty:
        st.write("### Riepilogo Provvisorio")
        st.dataframe(df_session.style.format({"BuyIn": "€{:.2f}", "CashOut": "€{:.2f}", "Profitto": "€{:.2f}"}), use_container_width=True)
        tot_profit = df_session["Profitto"].sum()
        if tot_profit != 0: st.warning(f"⚠️ Discrepanza: {tot_profit}€")
        else: st.success("✅ Conti perfetti.")
        
        if st.button("💾 SALVA SESSIONE SU GOOGLE SHEETS", type="primary"):
            salva_partita(club_name, df_session)
            st.session_state.session_data = []
            st.balloons()
            st.success("Salvato nel Cloud!")
            st.rerun()

def mostra_statistiche(club_name, is_host):
    df = carica_dati_club(club_name)
    if df.empty:
        st.info("Nessuna partita registrata in questo club.")
        return
    
    df["Data"] = pd.to_datetime(df["Data"], errors='coerce')
    df["BuyIn"] = pd.to_numeric(df["BuyIn"], errors='coerce').fillna(0)
    df["CashOut"] = pd.to_numeric(df["CashOut"], errors='coerce').fillna(0)
    df["Profitto"] = pd.to_numeric(df["Profitto"], errors='coerce').fillna(0)
    df = df.dropna(subset=["Data"])

    st.header("📊 Centro Analisi")
    col_filter_1, col_filter_2 = st.columns(2)
    with col_filter_1:
        anni_disponibili = sorted(df["Data"].dt.year.unique(), reverse=True)
        opzioni_anno = ["Tutto lo Storico (All Time)"] + [str(a) for a in anni_disponibili]
        filtro_anno = st.selectbox("📅 Seleziona Periodo", opzioni_anno)
    
    df_filtered = df.copy()
    if filtro_anno != "Tutto lo Storico (All Time)":
        anno_sel = int(filtro_anno)
        df_filtered = df_filtered[df_filtered["Data"].dt.year == anno_sel]
        with col_filter_2:
            mesi_disponibili = sorted(df_filtered["Data"].dt.month.unique())
            opzioni_mese = ["Tutto l'Anno"] + [str(m) for m in mesi_disponibili]
            filtro_mese = st.selectbox("Mese (Opzionale)", opzioni_mese)
            if filtro_mese != "Tutto l'Anno":
                df_filtered = df_filtered[df_filtered["Data"].dt.month == int(filtro_mese)]
    
    if df_filtered.empty:
        st.warning("Nessuna partita trovata nel periodo selezionato.")
        return
    
    tab_pers, tab_club = st.tabs(["👤 Statistiche Personali", "🏆 Statistiche Globali Club"])
    with tab_pers:
        tutti_giocatori = sorted(df["Giocatore"].unique())
        if is_host:
            options = tutti_giocatori
            default_idx = 0
            if st.session_state.username in options: default_idx = options.index(st.session_state.username)
        else:
            options = [st.session_state.username] if st.session_state.username in tutti_giocatori else []
            default_idx = 0
        if not options:
            st.warning("Nessuna statistica disponibile.")
        else:
            selected_player = st.selectbox("Analizza Giocatore:", options, index=default_idx)
            all_dates = sorted(df_filtered["Data"].unique())
            full_timeline = pd.DataFrame({"Data": all_dates})
            player_data = df_filtered[df_filtered["Giocatore"] == selected_player].copy()
            df_p = pd.merge(full_timeline, player_data, on="Data", how="left")
            df_p["Giocatore"] = selected_player
            df_p["Profitto"] = df_p["Profitto"].fillna(0)
            df_p["BuyIn"] = df_p["BuyIn"].fillna(0)
            df_p = df_p.sort_values("Data")
            df_active = df_p[df_p["BuyIn"] > 0].copy() 
            
            if df_active.empty and df_p["Profitto"].sum() == 0:
                st.warning(f"Nessuna partita giocata per {selected_player}.")
            else:
                total_profit = df_p["Profitto"].sum()
                total_buyin = df_active["BuyIn"].sum()
                n_sessions_played = len(df_active)
                total_club_sessions = len(all_dates)
                attendance_pct = (n_sessions_played / total_club_sessions * 100) if total_club_sessions > 0 else 0
                roi = (total_profit / total_buyin * 100) if total_buyin > 0 else 0
                max_win = df_active["Profitto"].max() if not df_active.empty else 0
                max_loss = df_active["Profitto"].min() if not df_active.empty else 0
                wins_df = df_active[df_active["Profitto"] > 0]
                losses_df = df_active[df_active["Profitto"] < 0]
                avg_win = wins_df["Profitto"].mean() if not wins_df.empty else 0
                avg_loss = losses_df["Profitto"].mean() if not losses_df.empty else 0
                n_wins = len(wins_df)
                win_rate = (n_wins / n_sessions_played * 100) if n_sessions_played > 0 else 0
                std_dev = df_active["Profitto"].std()
                if pd.isna(std_dev): std_dev = 0
                
                # Streak Calc
                max_win_streak_count = 0; max_win_streak_money = 0; best_money_streak_val = 0; best_money_streak_count = 0
                max_loss_streak_count = 0; max_loss_streak_money = 0; worst_money_streak_val = 0; worst_money_streak_count = 0
                current_streak_type = 0; current_count = 0; current_sum = 0
                profits_loop = df_active["Profitto"].tolist() + [0] 
                for val in profits_loop:
                    tipo_attuale = 1 if val > 0 else (-1 if val < 0 else 0)
                    if tipo_attuale == 0: 
                        if current_streak_type == 1:
                            if current_count > max_win_streak_count: max_win_streak_count = current_count; max_win_streak_money = current_sum
                            if current_sum > best_money_streak_val: best_money_streak_val = current_sum; best_money_streak_count = current_count
                        elif current_streak_type == -1:
                            if current_count > max_loss_streak_count: max_loss_streak_count = current_count; max_loss_streak_money = current_sum
                            if current_sum < worst_money_streak_val: worst_money_streak_val = current_sum; worst_money_streak_count = current_count
                        current_streak_type = 0; current_count = 0; current_sum = 0
                        continue
                    if tipo_attuale == current_streak_type:
                        current_count += 1; current_sum += val
                    else:
                        if current_streak_type == 1: 
                            if current_count > max_win_streak_count: max_win_streak_count = current_count; max_win_streak_money = current_sum
                            if current_sum > best_money_streak_val: best_money_streak_val = current_sum; best_money_streak_count = current_count
                        elif current_streak_type == -1: 
                            if current_count > max_loss_streak_count: max_loss_streak_count = current_count; max_loss_streak_money = current_sum
                            if current_sum < worst_money_streak_val: worst_money_streak_val = current_sum; worst_money_streak_count = current_count
                        current_streak_type = tipo_attuale; current_count = 1; current_sum = val
                
                curr_streak = 0
                for p in df_active["Profitto"].iloc[::-1]:
                    if p > 0:
                        if curr_streak >= 0: curr_streak += 1
                        else: break
                    elif p < 0:
                        if curr_streak <= 0: curr_streak -= 1
                        else: break
                    else: break
                
                streak_icon = "🔥" if curr_streak > 0 else ("❄️" if curr_streak < 0 else "😐")
                
                st.markdown(f"### Report: {selected_player} ({filtro_anno})")
                k1, k2, k3, k4 = st.columns(4)
                k1.metric("Bilancio", f"€ {total_profit:.2f}", f"{streak_icon} {curr_streak} Streak")
                k2.metric("ROI %", f"{roi:.1f}%")
                k3.metric("Presenze", f"{attendance_pct:.0f}%", f"{n_sessions_played} su {total_club_sessions}")
                k4.metric("Win Rate", f"{win_rate:.0f}%", f"{n_wins}V - {len(losses_df)}P")
                
                st.write("")
                d1, d2, d3, d4 = st.columns(4)
                d1.metric("Max Vincita", f"€ {max_win:.0f}")
                d2.metric("Max Perdita", f"€ {max_loss:.0f}")
                d3.metric("Media Vincita", f"€ {avg_win:.1f}")
                d4.metric("Media Perdita", f"€ {avg_loss:.1f}")
                st.caption(f"📊 Volatilità: **€ {std_dev:.1f}**")
                st.markdown("---")
                
                st.subheader("🎢 Analisi Serie (Streak)")
                c_win, c_loss = st.columns(2)
                with c_win:
                    st.success("**🟢 RECORD POSITIVI**")
                    st.write("**Tempo:**"); st.markdown(f"### {max_win_streak_count} Sess."); st.caption(f"Guadagno: €{max_win_streak_money:.0f}")
                    st.write("---"); st.write("**Soldi:**"); st.markdown(f"### € {best_money_streak_val:.0f}"); st.caption(f"In {best_money_streak_count} Sess.")
                with c_loss:
                    st.error("**🔴 RECORD NEGATIVI**")
                    st.write("**Tempo:**"); st.markdown(f"### {max_loss_streak_count} Sess."); st.caption(f"Persi: €{max_loss_streak_money:.0f}")
                    st.write("---"); st.write("**Soldi:**"); st.markdown(f"### € {worst_money_streak_val:.0f}"); st.caption(f"In {worst_money_streak_count} Sess.")
                st.markdown("---")
                
                st.subheader("📊 Sessioni")
                df_active_plot = df_active.copy()
                df_active_plot["Colore"] = df_active_plot["Profitto"].apply(lambda x: "Vinta" if x >= 0 else "Persa")
                fig_bar = px.bar(df_active_plot, x="Data", y="Profitto", color="Colore", color_discrete_map={"Vinta": "#00CC96", "Persa": "#EF553B"}, text="Profitto")
                fig_bar.update_traces(texttemplate='%{text:.0f}€', textposition='outside')
                fig_bar.add_hline(y=0, line_dash="dash", line_color="white")
                fig_bar.update_layout(showlegend=False, xaxis_title=None, yaxis_title="€")
                st.plotly_chart(fig_bar, use_container_width=True)
                
                st.subheader("📈 Bankroll Dinamico")
                df_p["CumProfit"] = df_p["Profitto"].cumsum()
                start_date = df_p["Data"].min() - pd.Timedelta(days=1)
                row_zero = pd.DataFrame({"Data": [start_date], "CumProfit": [0], "Profitto": [0]})
                df_chart = pd.concat([row_zero, df_p]).sort_values("Data").reset_index(drop=True)
                df_chart["pos_fill"] = df_chart["CumProfit"].apply(lambda x: x if x > 0 else 0)
                df_chart["neg_fill"] = df_chart["CumProfit"].apply(lambda x: x if x < 0 else 0)
                
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=df_chart["Data"], y=df_chart["pos_fill"], fill='tozeroy', fillcolor="rgba(0, 204, 150, 0.2)", mode='none', hoverinfo='skip', showlegend=False))
                fig.add_trace(go.Scatter(x=df_chart["Data"], y=df_chart["neg_fill"], fill='tozeroy', fillcolor="rgba(239, 85, 59, 0.2)", mode='none', hoverinfo='skip', showlegend=False))
                green_x, green_y = [], []; red_x, red_y = [], []; blue_x, blue_y = [], []
                for i in range(1, len(df_chart)):
                    x0, y0 = df_chart["Data"].iloc[i-1], df_chart["CumProfit"].iloc[i-1]
                    x1, y1 = df_chart["Data"].iloc[i], df_chart["CumProfit"].iloc[i]
                    diff = df_chart["Profitto"].iloc[i] 
                    if diff > 0: green_x.extend([x0, x1, None]); green_y.extend([y0, y1, None])
                    elif diff < 0: red_x.extend([x0, x1, None]); red_y.extend([y0, y1, None])
                    else: blue_x.extend([x0, x1, None]); blue_y.extend([y0, y1, None])
                width_line = 3
                fig.add_trace(go.Scatter(x=green_x, y=green_y, mode='lines+markers', line=dict(color="#00CC96", width=width_line), marker=dict(size=4), name="Vittoria"))
                fig.add_trace(go.Scatter(x=red_x, y=red_y, mode='lines+markers', line=dict(color="#EF553B", width=width_line), marker=dict(size=4), name="Sconfitta"))
                fig.add_trace(go.Scatter(x=blue_x, y=blue_y, mode='lines+markers', line=dict(color="#636EFA", width=width_line, dash='dot'), marker=dict(size=4), name="Assente/Pari"))
                fig.update_layout(xaxis_title=None, yaxis_title="€ Totali", showlegend=False, hovermode="x unified")
                st.plotly_chart(fig, use_container_width=True)

    with tab_club:
        st.caption(f"Analisi periodo: **{filtro_anno}**")
        num_sessions = len(df_filtered["Data"].unique())
        total_buyin_all = df_filtered["BuyIn"].sum()
        
        player_profits = df_filtered.groupby("Giocatore")["Profitto"].sum()
        if not player_profits.empty:
            shark_name = player_profits.idxmax(); shark_val = player_profits.max()
        else:
            shark_name = "-"; shark_val = 0
            
        if not df_filtered.empty:
            sniper_idx = df_filtered["Profitto"].idxmax(); sniper_name = df_filtered.loc[sniper_idx, "Giocatore"]; sniper_val = df_filtered.loc[sniper_idx, "Profitto"]
        else:
            sniper_name = "-"; sniper_val = 0
            
        all_players = sorted(df_filtered["Giocatore"].unique())
        with st.expander("⚙️ Opzioni calcolo presenze (Escludi Host)"):
            excluded_players = st.multiselect("Escludi giocatori dal premio 'Stakanovista'", all_players, default=[])
        attendance_counts = df_filtered.groupby("Giocatore")["Data"].nunique()
        attendance_counts_clean = attendance_counts.drop(excluded_players, errors='ignore')
        if not attendance_counts_clean.empty:
            stak_name = attendance_counts_clean.idxmax(); stak_val = attendance_counts_clean.max()
        else:
            stak_name = "N/A"; stak_val = 0
        
        avg_money_per_session = total_buyin_all / num_sessions if num_sessions > 0 else 0
        avg_players_per_session = len(df_filtered) / num_sessions if num_sessions > 0 else 0
        
        st.subheader("🏆 Hall of Fame")
        k1, k2, k3 = st.columns(3)
        k1.metric("🦈 Top Shark", shark_name, f"€ {shark_val:.0f}")
        k2.metric("🎖️ Stakanovista", stak_name, f"{stak_val} su {num_sessions}")
        k3.metric("🎯 Sniper", sniper_name, f"€ {sniper_val:.0f}")
        
        st.markdown("---")
        st.subheader("💰 Salute del Club")
        k4, k5, k6 = st.columns(3)
        k4.metric("Volume Totale", f"€ {total_buyin_all:.0f}")
        k5.metric("Pot Medio", f"€ {avg_money_per_session:.0f}")
        k6.metric("Partecipanti Medi", f"{avg_players_per_session:.1f}")
        st.markdown("---")
        
        st.subheader("⚔️ Il Trono (Storia del Record)")
        df_pivot = df_filtered.pivot_table(index="Data", columns="Giocatore", values="Profitto", aggfunc="sum").fillna(0)
        df_cumsum = df_pivot.cumsum()
        if not df_cumsum.empty:
            leader_series = df_cumsum.idxmax(axis=1); max_val_series = df_cumsum.max(axis=1)   
            df_race = pd.DataFrame({"Leader": leader_series, "Profitto": max_val_series}).reset_index().sort_values("Data")
            start_date_all = df_race["Data"].min() - pd.Timedelta(days=1)
            first_leader = df_race.iloc[0]["Leader"] if not df_race.empty else "N/A"
            row_zero = pd.DataFrame({"Data": [start_date_all], "Leader": [first_leader], "Profitto": [0]})
            df_race = pd.concat([row_zero, df_race]).sort_values("Data")
            fig_race = go.Figure()
            unique_leaders = df_race["Leader"].unique(); colors = px.colors.qualitative.Plotly 
            color_map = {player: colors[i % len(colors)] for i, player in enumerate(unique_leaders)}
            for i in range(1, len(df_race)):
                x0, y0 = df_race["Data"].iloc[i-1], df_race["Profitto"].iloc[i-1]; x1, y1 = df_race["Data"].iloc[i], df_race["Profitto"].iloc[i]; current_leader = df_race["Leader"].iloc[i] 
                fig_race.add_trace(go.Scatter(x=[x0, x1], y=[y0, y1], mode='lines+markers', line=dict(color=color_map.get(current_leader, 'grey'), width=4), marker=dict(size=8, color=color_map.get(current_leader, 'grey')), name=current_leader, legendgroup=current_leader, showlegend=False, hovertemplate=f"<b>{current_leader}</b><br>Record: €%{{y:.0f}}<extra></extra>"))
            for leader in unique_leaders: fig_race.add_trace(go.Scatter(x=[None], y=[None], mode='markers', marker=dict(size=10, color=color_map.get(leader, 'grey')), name=leader, legendgroup=leader, showlegend=True))
            fig_race.update_layout(xaxis_title=None, yaxis_title="Profitto Record (€)", hovermode="closest"); st.plotly_chart(fig_race, use_container_width=True)
        else: st.info("Dati insufficienti per il grafico del Trono.")
        
        st.subheader("💓 Il Polso del Club")
        daily_stats = df_filtered.groupby("Data").agg(Players=("Giocatore", "count"), Pot=("BuyIn", "sum")).sort_index()
        fig_combo = make_subplots(specs=[[{"secondary_y": True}]])
        fig_combo.add_trace(go.Bar(x=daily_stats.index, y=daily_stats["Players"], name="N° Giocatori", marker_color="#636EFA", opacity=0.5), secondary_y=False)
        fig_combo.add_trace(go.Scatter(x=daily_stats.index, y=daily_stats["Pot"], name="Pot (€)", mode='lines+markers', line=dict(color="#00CC96", width=3)), secondary_y=True)
        fig_combo.update_layout(hovermode="x unified", showlegend=False)
        fig_combo.update_yaxes(title_text="N° Giocatori", secondary_y=False, showgrid=False)
        fig_combo.update_yaxes(title_text="Pot (€)", secondary_y=True, showgrid=True)
        st.plotly_chart(fig_combo, use_container_width=True)
        
        st.markdown("---")
        st.subheader("📋 Classifica Dettagliata")
        stats = df_filtered.groupby("Giocatore").agg({"Data": "nunique", "BuyIn": "sum", "Profitto": "sum"})
        stats = stats.rename(columns={"Data": "Sessioni", "BuyIn": "Volume (€)"})
        stats["ROI %"] = (stats["Profitto"] / stats["Volume (€)"] * 100).round(1).fillna(0.0)
        view_stats = stats[["Sessioni", "Volume (€)", "Profitto", "ROI %"]].sort_values("Profitto", ascending=False)
        st.dataframe(view_stats.style.format({"Profitto": "€ {:.2f}", "Volume (€)": "€ {:.0f}", "ROI %": "{:.1f}%"}).background_gradient(subset=["Profitto"], cmap="RdYlGn", vmin=-50, vmax=50), use_container_width=True)

def gestisci_storico(club_name, is_host):
    st.header("📜 Storico (Cloud)")
    df = carica_dati_club(club_name)
    if not df.empty:
        # Pulizia e ordinamento
        df["Data"] = pd.to_datetime(df["Data"], errors='coerce')
        df = df.sort_values("Data", ascending=False)
        st.dataframe(df.style.format({"BuyIn": "€ {:.2f}", "CashOut": "€ {:.2f}", "Profitto": "€ {:.2f}"}))
    else:
        st.info("Nessuno storico.")

def dashboard_club(club_name):
    owner = get_club_owner(club_name)
    is_host = (st.session_state.username == owner)
    st.title(f"🏠 {club_name}")
    opzioni = ["Partita in Corso", "Statistiche", "Storico", "Membri"]
    if is_host: opzioni.append("Importa Dati")
    menu = st.radio("Menu", opzioni, horizontal=True)
    if menu == "Partita in Corso": gestisci_partita_live(club_name, is_host)
    elif menu == "Statistiche": mostra_statistiche(club_name, is_host)
    elif menu == "Storico": gestisci_storico(club_name, is_host)
    elif menu == "Membri":
        clubs = carica_clubs()
        st.table(pd.DataFrame(clubs[club_name]["members"], columns=["Membri"]))
        if is_host:
            u = st.text_input("Username invito")
            if st.button("Invita") and u: aggiungi_membro_al_club(club_name, u)
    elif menu == "Importa Dati":
        if is_host: importa_dati(club_name)
        else: st.error("Accesso Negato")

def main_app():
    st.sidebar.write(f"Utente: **{st.session_state.username}**")
    if st.sidebar.button("Logout"): st.session_state.logged_in = False; st.rerun()
    my_clubs = get_user_clubs(st.session_state.username)
    if not st.session_state.current_club:
        st.header("I tuoi Club")
        for club in my_clubs:
            if st.button(f"Entra in {club}"): st.session_state.current_club = club; st.rerun()
        with st.expander("Crea Nuovo Club"):
            n = st.text_input("Nome Club")
            if st.button("Crea") and n: crea_club(n, st.session_state.username); st.rerun()
    else:
        if st.sidebar.button("🔙 Indietro"): st.session_state.current_club = None; st.rerun()
        dashboard_club(st.session_state.current_club)

if st.session_state.logged_in: main_app()
else: login_page()