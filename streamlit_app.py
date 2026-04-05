# FILE: streamlit_app.py
# MODULE: Streamlit Main Application Entry Point
# Enterprise GUI mit Multi-Page Architecture, Custom Components, PWA

from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st
from plotly.subplots import make_subplots
from streamlit_extras.colored_header import colored_header
from streamlit_option_menu import option_menu

# ==================== Page Configuration ====================

st.set_page_config(
    page_title="TrueAngels NGO Suite v2.0",
    page_icon="🤝",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        'Get Help': 'https://trueangels.de/help',
        'Report a bug': "https://trueangels.de/bug",
        'About': "# TrueAngels NGO Suite v2.0\nEnterprise-Grade Plattform für gemeinnützige Organisationen"
    }
)

# ==================== Custom CSS (Tailwind/Shadcn Style) ====================

def load_custom_css():
    """Lädt benutzerdefiniertes CSS im Shadcn/Tailwind Style mit Dark Mode Support"""

    # Dark Mode Toggle per CSS Variable
    dark_mode_css = """
    <style>
        /* CSS Variables für Theming */
        :root {
            --background: 0 0% 100%;
            --foreground: 222.2 84% 4.9%;
            --card: 0 0% 100%;
            --card-foreground: 222.2 84% 4.9%;
            --primary: 142.1 76.2% 36.3%;
            --primary-foreground: 355.7 100% 97.3%;
            --secondary: 210 40% 96.1%;
            --secondary-foreground: 222.2 47.4% 11.2%;
            --muted: 210 40% 96.1%;
            --muted-foreground: 215.4 16.3% 46.9%;
            --accent: 210 40% 96.1%;
            --accent-foreground: 222.2 47.4% 11.2%;
            --destructive: 0 84.2% 60.2%;
            --destructive-foreground: 210 40% 98%;
            --border: 214.3 31.8% 91.4%;
            --input: 214.3 31.8% 91.4%;
            --ring: 142.1 76.2% 36.3%;
            --radius: 0.5rem;
        }

        /* Dark Mode Styles */
        [data-theme="dark"] {
            --background: 222.2 84% 4.9%;
            --foreground: 210 40% 98%;
            --card: 222.2 84% 4.9%;
            --card-foreground: 210 40% 98%;
            --primary: 142.1 70.6% 45.3%;
            --primary-foreground: 144.9 80.4% 10%;
            --secondary: 217.2 32.6% 17.5%;
            --secondary-foreground: 210 40% 98%;
            --muted: 217.2 32.6% 17.5%;
            --muted-foreground: 215 20.2% 65.1%;
            --accent: 217.2 32.6% 17.5%;
            --accent-foreground: 210 40% 98%;
            --destructive: 0 62.8% 30.6%;
            --destructive-foreground: 210 40% 98%;
            --border: 217.2 32.6% 17.5%;
            --input: 217.2 32.6% 17.5%;
            --ring: 142.4 71.8% 29.2%;
        }

        /* Main Container Styling */
        .main .block-container {
            padding-top: 2rem;
            padding-bottom: 2rem;
            max-width: 1400px;
        }

        /* Card Styling (Shadcn inspired) */
        .card {
            border-radius: var(--radius);
            border: 1px solid hsl(var(--border));
            background-color: hsl(var(--card));
            color: hsl(var(--card-foreground));
            padding: 1.5rem;
            box-shadow: 0 1px 3px 0 rgb(0 0 0 / 0.1);
            transition: all 0.2s;
        }

        .card:hover {
            box-shadow: 0 10px 15px -3px rgb(0 0 0 / 0.1);
            transform: translateY(-2px);
        }

        /* Metric Cards */
        .metric-card {
            background: linear-gradient(135deg, hsl(var(--primary)) 0%, hsl(142.1 70.6% 45.3%) 100%);
            border-radius: var(--radius);
            padding: 1.25rem;
            color: white;
        }

        .metric-value {
            font-size: 2rem;
            font-weight: 700;
            margin: 0.5rem 0;
        }

        .metric-label {
            font-size: 0.875rem;
            opacity: 0.9;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }

        /* Button Styling */
        .stButton > button {
            border-radius: var(--radius);
            font-weight: 500;
            transition: all 0.2s;
        }

        .stButton > button:hover {
            transform: translateY(-1px);
            box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1);
        }

        /* Data Table Styling */
        .dataframe {
            border-radius: var(--radius);
            overflow: hidden;
        }

        .dataframe thead tr th {
            background-color: hsl(var(--secondary));
            color: hsl(var(--secondary-foreground));
            font-weight: 600;
            padding: 0.75rem;
        }

        .dataframe tbody tr:hover {
            background-color: hsl(var(--accent));
        }

        /* Sidebar Styling */
        .css-1d391kg {
            background-color: hsl(var(--card));
            border-right: 1px solid hsl(var(--border));
        }

        /* Tabs Styling */
        .stTabs [data-baseweb="tab-list"] {
            gap: 1rem;
            border-bottom: 2px solid hsl(var(--border));
        }

        .stTabs [data-baseweb="tab"] {
            border-radius: var(--radius);
            padding: 0.5rem 1rem;
            font-weight: 500;
        }

        .stTabs [aria-selected="true"] {
            background-color: hsl(var(--primary));
            color: hsl(var(--primary-foreground));
        }

        /* Animations */
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }

        .fade-in {
            animation: fadeIn 0.3s ease-out;
        }

        /* Progress Bar */
        .progress-bar {
            height: 8px;
            background-color: hsl(var(--muted));
            border-radius: 4px;
            overflow: hidden;
        }

        .progress-fill {
            height: 100%;
            background-color: hsl(var(--primary));
            border-radius: 4px;
            transition: width 0.3s ease;
        }

        /* Notification Badge */
        .badge {
            display: inline-block;
            padding: 0.25rem 0.5rem;
            font-size: 0.75rem;
            font-weight: 600;
            border-radius: 9999px;
            background-color: hsl(var(--primary));
            color: hsl(var(--primary-foreground));
        }

        /* Loading Spinner */
        .custom-spinner {
            border: 3px solid hsl(var(--muted));
            border-top: 3px solid hsl(var(--primary));
            border-radius: 50%;
            width: 40px;
            height: 40px;
            animation: spin 1s linear infinite;
        }

        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
    </style>
    """

    st.markdown(dark_mode_css, unsafe_allow_html=True)

    # Dark Mode Toggle JavaScript
    dark_mode_js = """
    <script>
        // Check for saved theme preference
        const savedTheme = localStorage.getItem('theme');
        if (savedTheme === 'dark') {
            document.documentElement.setAttribute('data-theme', 'dark');
        }

        function toggleDarkMode() {
            const currentTheme = document.documentElement.getAttribute('data-theme');
            if (currentTheme === 'dark') {
                document.documentElement.removeAttribute('data-theme');
                localStorage.setItem('theme', 'light');
            } else {
                document.documentElement.setAttribute('data-theme', 'dark');
                localStorage.setItem('theme', 'dark');
            }
        }
    </script>
    """
    st.markdown(dark_mode_js, unsafe_allow_html=True)

# ==================== Session State Initialization ====================

def init_session_state():
    """Initialisiert Session State Variablen"""
    if 'authenticated' not in st.session_state:
        st.session_state.authenticated = False
    if 'user' not in st.session_state:
        st.session_state.user = None
    if 'dark_mode' not in st.session_state:
        st.session_state.dark_mode = False
    if 'selected_project' not in st.session_state:
        st.session_state.selected_project = None
    if 'notifications' not in st.session_state:
        st.session_state.notifications = []
    if 'page' not in st.session_state:
        st.session_state.page = "dashboard"

# ==================== Authentication ====================

def login_page():
    """Login Page mit OAuth2/JWT"""

    col1, col2, col3 = st.columns([1, 2, 1])

    with col2:
        st.markdown("""
            <div style="text-align: center; margin-bottom: 2rem;">
                <h1 style="color: hsl(var(--primary));">🤝 TrueAngels</h1>
                <p style="color: hsl(var(--muted-foreground));">Enterprise NGO Suite v2.0</p>
            </div>
        """, unsafe_allow_html=True)

        with st.form("login_form"):
            email = st.text_input("E-Mail", placeholder="admin@trueangels.de")
            password = st.text_input("Passwort", type="password", placeholder="••••••••")
            col_a, col_b = st.columns(2)
            with col_a:
                submit = st.form_submit_button("Anmelden", use_container_width=True)
            with col_b:
                st.form_submit_button("Registrieren", use_container_width=True)

            if submit:
                # API Call to backend
                try:
                    response = requests.post(
                        "http://localhost:8000/api/v1/auth/login",
                        json={"email": email, "password": password}
                    )
                    if response.status_code == 200:
                        data = response.json()
                        st.session_state.authenticated = True
                        st.session_state.user = data['user']
                        st.session_state.token = data['access_token']
                        st.rerun()
                    else:
                        st.error("Ungültige Anmeldedaten")
                except Exception as e:
                    st.error(f"Verbindungsfehler: {e}")

        # Demo Account Hinweis
        st.info("💡 Demo-Zugang: admin@trueangels.de / admin123")

# ==================== Sidebar Navigation ====================

def render_sidebar():
    """Renderet die Sidebar Navigation mit Icons"""

    with st.sidebar:
        # Logo und Titel
        st.markdown("""
            <div style="text-align: center; padding: 1rem 0;">
                <div style="font-size: 3rem;">🤝</div>
                <h2 style="margin: 0;">TrueAngels</h2>
                <p style="color: hsl(var(--muted-foreground)); font-size: 0.875rem;">NGO Suite v2.0</p>
            </div>
        """, unsafe_allow_html=True)

        st.divider()

        # Dark Mode Toggle
        col1, col2 = st.columns([3, 1])
        with col1:
            st.write("🌓 Dark Mode")
        with col2:
            dark_mode = st.toggle("", value=st.session_state.dark_mode)
            if dark_mode != st.session_state.dark_mode:
                st.session_state.dark_mode = dark_mode
                st.rerun()

        st.divider()

        # Navigation Menu
        selected = option_menu(
            menu_title=None,
            options=["Dashboard", "Spenden", "Projekte", "Lager", "Berichte", "Social Media", "Einstellungen"],
            icons=["house", "heart", "folder", "box", "file-text", "share", "gear"],
            menu_icon="cast",
            default_index=0,
            styles={
                "container": {"padding": "0!important", "background-color": "transparent"},
                "icon": {"font-size": "1.2rem", "margin-right": "0.5rem"},
                "nav-link": {
                    "font-size": "1rem",
                    "text-align": "left",
                    "margin": "0.25rem 0",
                    "border-radius": "0.5rem",
                },
                "nav-link-selected": {
                    "background-color": "hsl(var(--primary))",
                },
            }
        )

        st.session_state.page = selected.lower().replace(" ", "_")

        st.divider()

        # User Info
        if st.session_state.user:
            st.markdown(f"""
                <div style="padding: 1rem; background-color: hsl(var(--secondary)); border-radius: 0.5rem;">
                    <div style="display: flex; align-items: center; gap: 0.75rem;">
                        <div style="width: 40px; height: 40px; background-color: hsl(var(--primary)); border-radius: 50%; display: flex; align-items: center; justify-content: center;">
                            👤
                        </div>
                        <div>
                            <div style="font-weight: 600;">{st.session_state.user.get('email', 'User')}</div>
                            <div style="font-size: 0.75rem; color: hsl(var(--muted-foreground));">{st.session_state.user.get('role', 'donor')}</div>
                        </div>
                    </div>
                </div>
            """, unsafe_allow_html=True)

            if st.button("🚪 Abmelden", use_container_width=True):
                st.session_state.authenticated = False
                st.session_state.user = None
                st.rerun()

# ==================== Dashboard Page ====================

def dashboard_page():
    """Main Dashboard mit KPIs, Charts, Aktivitäten"""

    st.markdown('<div class="fade-in">', unsafe_allow_html=True)

    # Header
    colored_header(
        label="Dashboard",
        description="Willkommen zurück! Hier ist Ihr aktueller Überblick.",
        color_name="green-70"
    )

    # KPI Cards Row
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.markdown("""
            <div class="metric-card">
                <div class="metric-label">Gesamtspenden (2024)</div>
                <div class="metric-value">€125.432</div>
                <div style="font-size: 0.875rem;">↑ 12% zum Vormonat</div>
            </div>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown("""
            <div class="metric-card">
                <div class="metric-label">Aktive Projekte</div>
                <div class="metric-value">5</div>
                <div style="font-size: 0.875rem;">2 in Planung</div>
            </div>
        """, unsafe_allow_html=True)

    with col3:
        st.markdown("""
            <div class="metric-card">
                <div class="metric-label">Spender</div>
                <div class="metric-value">342</div>
                <div style="font-size: 0.875rem;">↑ 18 neue diesen Monat</div>
            </div>
        """, unsafe_allow_html=True)

    with col4:
        st.markdown("""
            <div class="metric-card">
                <div class="metric-label">Projekteffizienz</div>
                <div class="metric-value">87.5%</div>
                <div style="font-size: 0.875rem;">Ziel: 90%</div>
            </div>
        """, unsafe_allow_html=True)

    st.markdown('<br>', unsafe_allow_html=True)

    # Charts Row
    col1, col2 = st.columns(2)

    with col1:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.subheader("📈 Spendenentwicklung")

        # Sample Data - In Production: From API
        months = ['Jan', 'Feb', 'Mär', 'Apr', 'Mai', 'Jun', 'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez']
        donations = [8500, 9200, 10500, 11800, 12400, 13100, 14500, 15200, 16800, 17500, 18200, 19500]

        fig = px.line(
            x=months, y=donations,
            labels={'x': 'Monat', 'y': 'Spenden (€)'},
            title="Spenden 2024"
        )
        fig.update_layout(
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)',
            font_color='hsl(var(--foreground))'
        )
        fig.update_traces(line_color='hsl(var(--primary))', line_width=3)
        st.plotly_chart(fig, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

    with col2:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.subheader("📊 Spenden nach Projekt")

        projects = ['Bildung', 'Gesundheit', 'Umwelt', 'Soziales']
        values = [45000, 32000, 28000, 20000]
        colors = ['#2d6a4f', '#40916c', '#52b788', '#74c69d']

        fig = px.pie(
            values=values, names=projects,
            title="Verteilung nach Projekt",
            color_discrete_sequence=colors
        )
        fig.update_layout(
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)',
            font_color='hsl(var(--foreground))'
        )
        st.plotly_chart(fig, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

    # Second Row
    col1, col2 = st.columns(2)

    with col1:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.subheader("🎯 Projektfortschritt")

        projects_data = [
            {"name": "Bildungsinitiative", "progress": 75, "budget": 50000, "spent": 37500},
            {"name": "Medizinische Hilfe", "progress": 60, "budget": 40000, "spent": 24000},
            {"name": "Umweltschutz", "progress": 90, "budget": 30000, "spent": 27000},
            {"name": "Sozialberatung", "progress": 45, "budget": 25000, "spent": 11250},
        ]

        for project in projects_data:
            st.markdown(f"""
                <div style="margin-bottom: 1rem;">
                    <div style="display: flex; justify-content: space-between; margin-bottom: 0.25rem;">
                        <span style="font-weight: 500;">{project['name']}</span>
                        <span>{project['progress']}%</span>
                    </div>
                    <div class="progress-bar">
                        <div class="progress-fill" style="width: {project['progress']}%;"></div>
                    </div>
                    <div style="display: flex; justify-content: space-between; margin-top: 0.25rem; font-size: 0.75rem; color: hsl(var(--muted-foreground));">
                        <span>Budget: €{project['budget']:,}</span>
                        <span>Ausgaben: €{project['spent']:,}</span>
                    </div>
                </div>
            """, unsafe_allow_html=True)

        st.markdown('</div>', unsafe_allow_html=True)

    with col2:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.subheader("🕒 Letzte Aktivitäten")

        activities = [
            {"time": "vor 5 Minuten", "action": "Neue Spende €150", "user": "Max Mustermann"},
            {"time": "vor 1 Stunde", "action": "Projekt-Update", "user": "Anna Schmidt"},
            {"time": "vor 3 Stunden", "action": "Lagerbestand aktualisiert", "user": "John Doe"},
            {"time": "vor 1 Tag", "action": "Social Media Post", "user": "Lisa Meyer"},
        ]

        for activity in activities:
            st.markdown(f"""
                <div style="display: flex; align-items: center; gap: 1rem; padding: 0.75rem 0; border-bottom: 1px solid hsl(var(--border));">
                    <div style="width: 8px; height: 8px; background-color: hsl(var(--primary)); border-radius: 50%;"></div>
                    <div style="flex: 1;">
                        <div style="font-weight: 500;">{activity['action']}</div>
                        <div style="font-size: 0.75rem; color: hsl(var(--muted-foreground));">{activity['user']} • {activity['time']}</div>
                    </div>
                </div>
            """, unsafe_allow_html=True)

        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)

# ==================== Donations Page ====================

def donations_page():
    """Spendenverwaltung mit Tabelle und Formular"""

    st.markdown('<div class="fade-in">', unsafe_allow_html=True)

    colored_header(
        label="Spendenverwaltung",
        description="Verwalten Sie eingehende Spenden und generieren Sie Bescheinigungen.",
        color_name="green-70"
    )

    # Tabs
    tab1, tab2, tab3 = st.tabs(["📋 Alle Spenden", "➕ Neue Spende", "📊 Statistiken"])

    with tab1:
        st.markdown('<div class="card">', unsafe_allow_html=True)

        # Filter
        col1, col2, col3 = st.columns(3)
        with col1:
            date_range = st.selectbox("Zeitraum", ["Heute", "Diese Woche", "Diesen Monat", "Dieses Jahr", "Benutzerdefiniert"])
        with col2:
            status_filter = st.multiselect("Status", ["pending", "succeeded", "failed", "refunded"], default=["succeeded"])
        with col3:
            project_filter = st.selectbox("Projekt", ["Alle", "Bildung", "Gesundheit", "Umwelt", "Soziales"])

        # Sample Data
        donations_data = {
            "Datum": ["2024-01-15", "2024-01-14", "2024-01-13", "2024-01-12", "2024-01-11"],
            "Spender": ["Max Mustermann", "Anna Schmidt", "John Doe", "Lisa Meyer", "Thomas Weber"],
            "Betrag": ["€150,00", "€50,00", "€200,00", "€75,00", "€100,00"],
            "Projekt": ["Bildung", "Gesundheit", "Umwelt", "Soziales", "Bildung"],
            "Status": ["✅ Erfolgreich", "✅ Erfolgreich", "✅ Erfolgreich", "⏳ Ausstehend", "✅ Erfolgreich"],
            "Bescheinigung": ["📄 PDF", "📄 PDF", "📄 PDF", "-", "📄 PDF"]
        }

        df = pd.DataFrame(donations_data)
        st.dataframe(df, use_container_width=True, hide_index=True)

        st.markdown('</div>', unsafe_allow_html=True)

    with tab2:
        st.markdown('<div class="card">', unsafe_allow_html=True)

        with st.form("new_donation_form"):
            col1, col2 = st.columns(2)
            with col1:
                amount = st.number_input("Betrag (€)", min_value=1.0, max_value=100000.0, step=10.0)
                donor_name = st.text_input("Spender Name")
                donor_email = st.text_input("E-Mail")
            with col2:
                project = st.selectbox("Projekt", ["Bildungsinitiative", "Medizinische Hilfe", "Umweltschutz", "Sozialberatung"])
                payment_method = st.selectbox("Zahlungsmethode", ["Stripe", "PayPal", "Klarna", "SEPA", "Bar"])
                donation_date = st.date_input("Datum", datetime.now())

            notes = st.text_area("Notizen (optional)")

            col1, col2, col3 = st.columns([1, 1, 1])
            with col2:
                submitted = st.form_submit_button("💝 Spende erfassen", use_container_width=True)
                if submitted:
                    st.success(f"Spende über €{amount:,.2f} von {donor_name} wurde erfasst!")

        st.markdown('</div>', unsafe_allow_html=True)

    with tab3:
        st.markdown('<div class="card">', unsafe_allow_html=True)

        # Statistics
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Gesamtspenden (MTD)", "€12.450", "↑ €2.100")
        with col2:
            st.metric("Durchschnittliche Spende", "€87,50", "↑ €12,30")
        with col3:
            st.metric("Neue Spender", "18", "↑ 5")

        # Chart
        fig = make_subplots(rows=1, cols=2, subplot_titles=("Spenden pro Tag", "Spenden pro Projekt"))

        # Daily donations
        days = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So']
        daily = [1250, 1800, 950, 2100, 3200, 2800, 1500]
        fig.add_trace(go.Bar(x=days, y=daily, marker_color='#2d6a4f'), row=1, col=1)

        # Project distribution
        projects = ['Bildung', 'Gesundheit', 'Umwelt', 'Soziales']
        project_values = [45000, 32000, 28000, 20000]
        fig.add_trace(go.Pie(labels=projects, values=project_values, marker_colors=['#2d6a4f', '#40916c', '#52b788', '#74c69d']), row=1, col=2)

        fig.update_layout(height=400, showlegend=False, template="plotly_white")
        st.plotly_chart(fig, use_container_width=True)

        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)

# ==================== Projects Page ====================

def projects_page():
    """Projektmanagement mit KPIs und Fortschritt"""

    st.markdown('<div class="fade-in">', unsafe_allow_html=True)

    colored_header(
        label="Projektmanagement",
        description="Übersicht und Verwaltung aller Projekte.",
        color_name="green-70"
    )

    # Project Cards
    projects = [
        {
            "name": "Bildungsinitiative",
            "description": "Unterstützung von Schulen in Entwicklungsländern",
            "progress": 75,
            "budget": 50000,
            "donations": 37500,
            "status": "active",
            "image": "🎓"
        },
        {
            "name": "Medizinische Hilfe",
            "description": "Mobile Kliniken für entlegene Regionen",
            "progress": 60,
            "budget": 40000,
            "donations": 24000,
            "status": "active",
            "image": "🏥"
        },
        {
            "name": "Umweltschutz",
            "description": "Aufforstung und Meeresschutz",
            "progress": 90,
            "budget": 30000,
            "donations": 27000,
            "status": "active",
            "image": "🌱"
        },
        {
            "name": "Sozialberatung",
            "description": "Kostenlose Beratung für Bedürftige",
            "progress": 45,
            "budget": 25000,
            "donations": 11250,
            "status": "planning",
            "image": "🤝"
        }
    ]

    for project in projects:
        with st.container():
            col1, col2 = st.columns([1, 3])
            with col1:
                st.markdown(f"""
                    <div style="font-size: 4rem; text-align: center;">
                        {project['image']}
                    </div>
                """, unsafe_allow_html=True)
            with col2:
                status_badge = "🟢 Aktiv" if project['status'] == 'active' else "🟡 In Planung"
                st.markdown(f"""
                    <div>
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <h3 style="margin: 0;">{project['name']}</h3>
                            <span class="badge">{status_badge}</span>
                        </div>
                        <p style="color: hsl(var(--muted-foreground));">{project['description']}</p>
                        <div style="margin-top: 1rem;">
                            <div style="display: flex; justify-content: space-between; margin-bottom: 0.25rem;">
                                <span>Fortschritt</span>
                                <span>{project['progress']}%</span>
                            </div>
                            <div class="progress-bar">
                                <div class="progress-fill" style="width: {project['progress']}%;"></div>
                            </div>
                            <div style="display: flex; justify-content: space-between; margin-top: 1rem;">
                                <div>
                                    <div style="font-size: 0.75rem; color: hsl(var(--muted-foreground));">Budget</div>
                                    <div style="font-weight: 600;">€{project['budget']:,}</div>
                                </div>
                                <div>
                                    <div style="font-size: 0.75rem; color: hsl(var(--muted-foreground));">Spenden</div>
                                    <div style="font-weight: 600;">€{project['donations']:,}</div>
                                </div>
                                <div>
                                    <div style="font-size: 0.75rem; color: hsl(var(--muted-foreground));">Verbleibend</div>
                                    <div style="font-weight: 600;">€{project['budget'] - project['donations']:,}</div>
                                </div>
                            </div>
                        </div>
                    </div>
                """, unsafe_allow_html=True)
            st.divider()

    # New Project Button
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        if st.button("➕ Neues Projekt erstellen", use_container_width=True):
            st.info("Projekt-Erstellungsformular wird geladen...")

# ==================== Settings Page ====================

def settings_page():
    """Benutzereinstellungen und Konfiguration"""

    st.markdown('<div class="fade-in">', unsafe_allow_html=True)

    colored_header(
        label="Einstellungen",
        description="Verwalten Sie Ihre Kontoeinstellungen und Präferenzen.",
        color_name="green-70"
    )

    tabs = st.tabs(["👤 Profil", "🔐 Sicherheit", "🔔 Benachrichtigungen", "📱 API Zugang"])

    with tabs[0]:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.subheader("Persönliche Informationen")

        col1, col2 = st.columns(2)
        with col1:
            st.text_input("Vorname", value="Max")
            st.text_input("E-Mail", value="max@trueangels.de")
            st.selectbox("Sprache", ["Deutsch", "English", "Français", "Español"])
        with col2:
            st.text_input("Nachname", value="Mustermann")
            st.text_input("Telefon", value="+49 123 456789")
            st.selectbox("Zeitzone", ["Europe/Berlin", "Europe/London", "America/New_York"])

        st.markdown('</div>', unsafe_allow_html=True)

    with tabs[1]:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.subheader("Sicherheitseinstellungen")

        st.checkbox("Zwei-Faktor-Authentifizierung aktivieren")
        st.checkbox("Login-Benachrichtigungen per E-Mail")
        st.checkbox("Geräteverwaltung")

        st.markdown("---")
        st.subheader("Passwort ändern")

        col1, col2 = st.columns(2)
        with col1:
            st.text_input("Aktuelles Passwort", type="password")
            st.text_input("Neues Passwort", type="password")
        with col2:
            st.text_input("Neues Passwort bestätigen", type="password")

        if st.button("Passwort aktualisieren"):
            st.success("Passwort wurde erfolgreich geändert!")

        st.markdown('</div>', unsafe_allow_html=True)

    with tabs[2]:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.subheader("Benachrichtigungseinstellungen")

        st.checkbox("📧 Neue Spendenbenachrichtigungen", value=True)
        st.checkbox("📧 Projekt-Updates", value=True)
        st.checkbox("📧 Monatliche Berichte", value=True)
        st.checkbox("💬 Social Media Aktivitäten", value=False)
        st.checkbox("⚠️ Sicherheitswarnungen", value=True)

        st.markdown('</div>', unsafe_allow_html=True)

    with tabs[3]:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.subheader("API Zugang")

        st.info("API Key für externe Integrationen (WordPress, Betterplace, etc.)")

        api_key = "ta_live_xxxxxxxxxxxxx"
        st.code(api_key, language="text")

        if st.button("Neuen API Key generieren"):
            st.warning("Achtung: Der alte API Key wird ungültig!")

        st.markdown("---")
        st.subheader("Webhook Endpunkte")

        webhook_url = st.text_input("Webhook URL", placeholder="https://your-server.com/webhook")
        st.multiselect("Events", ["spende.erstellt", "projekt.aktualisiert", "lager.bewegung"])

        if st.button("Webhook registrieren"):
            st.success("Webhook erfolgreich registriert!")

        st.markdown('</div>', unsafe_allow_html=True)

# ==================== PWA Service Worker ====================

def setup_pwa():
    """Konfiguriert PWA (Progressive Web App) Support"""

    pwa_html = """
    <link rel="manifest" href="/manifest.json">
    <meta name="theme-color" content="#2d6a4f">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="apple-mobile-web-app-title" content="TrueAngels">
    <link rel="apple-touch-icon" href="/icon-192.png">
    <script>
        if ('serviceWorker' in navigator) {
            navigator.serviceWorker.register('/sw.js').then(function(registration) {
                console.log('Service Worker registered with scope:', registration.scope);
            }).catch(function(error) {
                console.log('Service Worker registration failed:', error);
            });
        }
    </script>
    """
    st.markdown(pwa_html, unsafe_allow_html=True)

# ==================== Main App ====================

def main():
    """Main Application Entry Point"""

    # Load CSS and PWA
    load_custom_css()
    setup_pwa()
    init_session_state()

    # Check Authentication
    if not st.session_state.authenticated:
        login_page()
    else:
        render_sidebar()

        # Page Routing
        if st.session_state.page == "dashboard":
            dashboard_page()
        elif st.session_state.page == "spenden":
            donations_page()
        elif st.session_state.page == "projekte":
            projects_page()
        elif st.session_state.page == "lager":
            st.info("Lagerverwaltung - Coming Soon!")
        elif st.session_state.page == "berichte":
            st.info("Berichte - Coming Soon!")
        elif st.session_state.page == "social_media":
            st.info("Social Media - Coming Soon!")
        elif st.session_state.page == "einstellungen":
            settings_page()
        else:
            dashboard_page()

# Run App
if __name__ == "__main__":
    main()
