// FILE: wp-plugin/assets/js/admin-vue.js
// MODULE: Vue.js Admin Dashboard für WordPress Plugin
// Version: 3.0.0
// Verwaltung von Spenden, Projekten, Transparenz-Einstellungen

// ==================== Vue 3 Setup ====================
const { createApp, ref, reactive, computed, onMounted, onUnmounted, watch } = Vue;

// ==================== API Client ====================
const apiClient = {
    baseUrl: trueangels_ajax.rest_url + '/trueangels/v1',
    
    async request(endpoint, options = {}) {
        const defaultOptions = {
            headers: {
                'Content-Type': 'application/json',
                'X-WP-Nonce': trueangels_ajax.rest_nonce
            }
        };
        
        const response = await fetch(`${this.baseUrl}${endpoint}`, {
            ...defaultOptions,
            ...options
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.message || 'API request failed');
        }
        
        return response.json();
    },
    
    get(endpoint) {
        return this.request(endpoint, { method: 'GET' });
    },
    
    post(endpoint, data) {
        return this.request(endpoint, {
            method: 'POST',
            body: JSON.stringify(data)
        });
    },
    
    put(endpoint, data) {
        return this.request(endpoint, {
            method: 'PUT',
            body: JSON.stringify(data)
        });
    },
    
    delete(endpoint) {
        return this.request(endpoint, { method: 'DELETE' });
    }
};

// ==================== Formatting Helpers ====================
const formatCurrency = (amount) => {
    return new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR' }).format(amount);
};

const formatDate = (dateString) => {
    if (!dateString) return '-';
    const date = new Date(dateString);
    return date.toLocaleDateString('de-DE', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
};

const formatShortDate = (dateString) => {
    if (!dateString) return '-';
    const date = new Date(dateString);
    return date.toLocaleDateString('de-DE', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric'
    });
};

const getStatusBadge = (status) => {
    const badges = {
        'succeeded': '<span class="badge badge-success">✅ Erfolgreich</span>',
        'pending': '<span class="badge badge-warning">⏳ Ausstehend</span>',
        'failed': '<span class="badge badge-danger">❌ Fehlgeschlagen</span>',
        'refunded': '<span class="badge badge-info">↩️ Rückerstattet</span>'
    };
    return badges[status] || `<span class="badge badge-secondary">${status}</span>`;
};

// ==================== Dashboard Component ====================
const Dashboard = {
    template: `
        <div class="trueangels-dashboard">
            <!-- Stats Cards -->
            <div class="trueangels-stats-grid">
                <div class="trueangels-stat-card" v-for="stat in stats" :key="stat.label">
                    <div class="trueangels-stat-icon">{{ stat.icon }}</div>
                    <div class="trueangels-stat-value">{{ stat.value }}</div>
                    <div class="trueangels-stat-label">{{ stat.label }}</div>
                    <div class="trueangels-stat-change" :class="stat.change >= 0 ? 'positive' : 'negative'">
                        {{ stat.change >= 0 ? '↑' : '↓' }} {{ Math.abs(stat.change) }}%
                    </div>
                </div>
            </div>
            
            <!-- Charts Row -->
            <div class="trueangels-charts-row">
                <div class="trueangels-chart-card">
                    <h3>📈 Spendenentwicklung</h3>
                    <canvas id="donation-chart"></canvas>
                </div>
                <div class="trueangels-chart-card">
                    <h3>📊 Verteilung nach Projekt</h3>
                    <canvas id="projects-chart"></canvas>
                </div>
            </div>
            
            <!-- Recent Donations -->
            <div class="trueangels-table-card">
                <h3>🕒 Letzte Spenden</h3>
                <div class="trueangels-table-responsive">
                    <table class="wp-list-table widefat fixed striped">
                        <thead>
                            <tr>
                                <th>Datum</th>
                                <th>Spender</th>
                                <th>Betrag</th>
                                <th>Projekt</th>
                                <th>Status</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="donation in recentDonations" :key="donation.id">
                                <td>{{ formatDate(donation.created_at) }}</td>
                                <td>{{ donation.donor_name || 'Anonym' }}</td>
                                <td class="trueangels-amount">{{ formatCurrency(donation.amount) }}</td>
                                <td>{{ donation.project_name }}</td>
                                <td v-html="getStatusBadge(donation.status)"></td>
                            </tr>
                            <tr v-if="recentDonations.length === 0">
                                <td colspan="5" class="trueangels-no-data">Keine Spenden vorhanden</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    `,
    
    setup() {
        const stats = ref([
            { icon: '💰', label: 'Gesamtspenden', value: '€0', change: 0 },
            { icon: '🏗️', label: 'Aktive Projekte', value: '0', change: 0 },
            { icon: '👥', label: 'Spender', value: '0', change: 0 },
            { icon: '⭐', label: 'Durchschnitt', value: '€0', change: 0 }
        ]);
        
        const recentDonations = ref([]);
        let donationChart = null;
        let projectsChart = null;
        
        const loadDashboardData = async () => {
            try {
                const data = await apiClient.get('/dashboard/stats');
                
                stats.value = [
                    { icon: '💰', label: 'Gesamtspenden', value: formatCurrency(data.total_donations), change: data.donation_change },
                    { icon: '🏗️', label: 'Aktive Projekte', value: data.active_projects, change: 0 },
                    { icon: '👥', label: 'Spender', value: data.total_donors, change: data.donors_change },
                    { icon: '⭐', label: 'Durchschnitt', value: formatCurrency(data.avg_donation), change: 0 }
                ];
                
                // Load charts data
                const chartData = await apiClient.get('/dashboard/charts');
                initCharts(chartData);
                
                // Load recent donations
                const donations = await apiClient.get('/donations?per_page=10');
                recentDonations.value = donations.data || [];
                
            } catch (error) {
                console.error('Failed to load dashboard:', error);
            }
        };
        
        const initCharts = (data) => {
            // Donation Chart
            const donationCtx = document.getElementById('donation-chart')?.getContext('2d');
            if (donationCtx && window.Chart) {
                if (donationChart) donationChart.destroy();
                donationChart = new Chart(donationCtx, {
                    type: 'line',
                    data: {
                        labels: data.donations_by_month?.months || [],
                        datasets: [{
                            label: 'Spenden (€)',
                            data: data.donations_by_month?.values || [],
                            borderColor: '#2d6a4f',
                            backgroundColor: 'rgba(45, 106, 79, 0.1)',
                            fill: true,
                            tension: 0.4
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: true,
                        plugins: {
                            tooltip: {
                                callbacks: {
                                    label: (ctx) => `${ctx.dataset.label}: ${formatCurrency(ctx.raw)}`
                                }
                            }
                        }
                    }
                });
            }
            
            // Projects Chart
            const projectsCtx = document.getElementById('projects-chart')?.getContext('2d');
            if (projectsCtx && window.Chart) {
                if (projectsChart) projectsChart.destroy();
                projectsChart = new Chart(projectsCtx, {
                    type: 'pie',
                    data: {
                        labels: data.donations_by_project?.projects || [],
                        datasets: [{
                            data: data.donations_by_project?.values || [],
                            backgroundColor: ['#2d6a4f', '#40916c', '#52b788', '#74c69d', '#95d5b2']
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: true,
                        plugins: {
                            tooltip: {
                                callbacks: {
                                    label: (ctx) => `${ctx.label}: ${formatCurrency(ctx.raw)}`
                                }
                            }
                        }
                    }
                });
            }
        };
        
        onMounted(() => {
            loadDashboardData();
        });
        
        onUnmounted(() => {
            if (donationChart) donationChart.destroy();
            if (projectsChart) projectsChart.destroy();
        });
        
        return {
            stats,
            recentDonations,
            formatCurrency,
            formatDate,
            getStatusBadge
        };
    }
};

// ==================== Donations Management Component ====================
const DonationsManager = {
    template: `
        <div class="trueangels-donations">
            <!-- Filter Bar -->
            <div class="trueangels-filter-bar">
                <div class="trueangels-filter-group">
                    <input type="text" v-model="filters.search" placeholder="🔍 Suchen..." class="trueangels-filter-input">
                </div>
                <div class="trueangels-filter-group">
                    <select v-model="filters.status" class="trueangels-filter-select">
                        <option value="all">Alle Status</option>
                        <option value="succeeded">Erfolgreich</option>
                        <option value="pending">Ausstehend</option>
                        <option value="failed">Fehlgeschlagen</option>
                        <option value="refunded">Rückerstattet</option>
                    </select>
                </div>
                <div class="trueangels-filter-group">
                    <select v-model="filters.project" class="trueangels-filter-select">
                        <option value="all">Alle Projekte</option>
                        <option v-for="project in projects" :key="project.id" :value="project.id">
                            {{ project.name }}
                        </option>
                    </select>
                </div>
                <div class="trueangels-filter-group">
                    <input type="date" v-model="filters.date_from" class="trueangels-filter-input" placeholder="Von">
                    <input type="date" v-model="filters.date_to" class="trueangels-filter-input" placeholder="Bis">
                </div>
                <button @click="exportData" class="button button-primary">📥 Exportieren</button>
            </div>
            
            <!-- Donations Table -->
            <div class="trueangels-table-responsive">
                <table class="wp-list-table widefat fixed striped">
                    <thead>
                        <tr>
                            <th>ID</th>
                            <th>Datum</th>
                            <th>Spender</th>
                            <th>Betrag</th>
                            <th>Projekt</th>
                            <th>Methode</th>
                            <th>Status</th>
                            <th>Aktionen</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="donation in donations" :key="donation.id">
                            <td>{{ donation.id.substring(0, 8) }}...</td>
                            <td>{{ formatShortDate(donation.created_at) }}</td>
                            <td>{{ donation.donor_name || 'Anonym' }}</td>
                            <td class="trueangels-amount">{{ formatCurrency(donation.amount) }}</td>
                            <td>{{ donation.project_name }}</td>
                            <td>{{ donation.payment_provider }}</td>
                            <td v-html="getStatusBadge(donation.status)"></td>
                            <td>
                                <button @click="viewDonation(donation)" class="button button-small">👁️</button>
                                <button v-if="donation.status === 'succeeded'" @click="refundDonation(donation)" class="button button-small">↩️</button>
                                <button @click="downloadReceipt(donation)" class="button button-small">📄</button>
                            </td>
                        </tr>
                        <tr v-if="donations.length === 0">
                            <td colspan="8" class="trueangels-no-data">Keine Spenden gefunden</td>
                        </tr>
                    </tbody>
                </table>
            </div>
            
            <!-- Pagination -->
            <div class="trueangels-pagination" v-if="totalPages > 1">
                <button @click="prevPage" :disabled="currentPage === 1" class="button">« Zurück</button>
                <span class="trueangels-page-info">Seite {{ currentPage }} von {{ totalPages }}</span>
                <button @click="nextPage" :disabled="currentPage === totalPages" class="button">Weiter »</button>
            </div>
            
            <!-- Donation Modal -->
            <div class="trueangels-modal" v-if="selectedDonation" @click.self="closeModal">
                <div class="trueangels-modal-content">
                    <div class="trueangels-modal-header">
                        <h3>Spendendetails</h3>
                        <button @click="closeModal" class="trueangels-modal-close">&times;</button>
                    </div>
                    <div class="trueangels-modal-body">
                        <div class="trueangels-detail-row">
                            <strong>Spenden-ID:</strong> {{ selectedDonation.id }}
                        </div>
                        <div class="trueangels-detail-row">
                            <strong>Datum:</strong> {{ formatDate(selectedDonation.created_at) }}
                        </div>
                        <div class="trueangels-detail-row">
                            <strong>Spender:</strong> {{ selectedDonation.donor_name || 'Anonym' }}
                        </div>
                        <div class="trueangels-detail-row">
                            <strong>E-Mail:</strong> {{ selectedDonation.donor_email || '-' }}
                        </div>
                        <div class="trueangels-detail-row">
                            <strong>Betrag:</strong> <span class="trueangels-amount">{{ formatCurrency(selectedDonation.amount) }}</span>
                        </div>
                        <div class="trueangels-detail-row">
                            <strong>Projekt:</strong> {{ selectedDonation.project_name }}
                        </div>
                        <div class="trueangels-detail-row">
                            <strong>Zahlungsmethode:</strong> {{ selectedDonation.payment_provider }}
                        </div>
                        <div class="trueangels-detail-row">
                            <strong>Status:</strong> <span v-html="getStatusBadge(selectedDonation.status)"></span>
                        </div>
                        <div class="trueangels-detail-row" v-if="selectedDonation.payment_intent_id">
                            <strong>Transaktions-ID:</strong> <code>{{ selectedDonation.payment_intent_id }}</code>
                        </div>
                    </div>
                    <div class="trueangels-modal-footer">
                        <button @click="downloadReceipt(selectedDonation)" class="button button-primary">📄 Bescheinigung</button>
                        <button @click="closeModal" class="button">Schließen</button>
                    </div>
                </div>
            </div>
        </div>
    `,
    
    setup() {
        const donations = ref([]);
        const projects = ref([]);
        const currentPage = ref(1);
        const totalPages = ref(1);
        const selectedDonation = ref(null);
        
        const filters = reactive({
            search: '',
            status: 'all',
            project: 'all',
            date_from: '',
            date_to: ''
        });
        
        const loadDonations = async () => {
            try {
                const params = new URLSearchParams({
                    page: currentPage.value,
                    per_page: 20,
                    ...(filters.search && { search: filters.search }),
                    ...(filters.status !== 'all' && { status: filters.status }),
                    ...(filters.project !== 'all' && { project: filters.project }),
                    ...(filters.date_from && { date_from: filters.date_from }),
                    ...(filters.date_to && { date_to: filters.date_to })
                });
                
                const data = await apiClient.get(`/donations?${params}`);
                donations.value = data.data || [];
                totalPages.value = Math.ceil((data.total || 0) / 20);
            } catch (error) {
                console.error('Failed to load donations:', error);
            }
        };
        
        const loadProjects = async () => {
            try {
                projects.value = await apiClient.get('/projects');
            } catch (error) {
                console.error('Failed to load projects:', error);
            }
        };
        
        const exportData = async () => {
            const params = new URLSearchParams({
                start_date: filters.date_from || '2024-01-01',
                end_date: filters.date_to || new Date().toISOString().split('T')[0],
                format: 'excel'
            });
            
            window.open(`${apiClient.baseUrl}/export/donations?${params}`, '_blank');
        };
        
        const viewDonation = (donation) => {
            selectedDonation.value = donation;
        };
        
        const refundDonation = async (donation) => {
            if (!confirm(`Möchten Sie die Spende über ${formatCurrency(donation.amount)} wirklich zurückerstatten?`)) return;
            
            try {
                await apiClient.post(`/donations/${donation.id}/refund`);
                alert('Rückerstattung wurde eingeleitet');
                loadDonations();
            } catch (error) {
                alert('Fehler bei der Rückerstattung: ' + error.message);
            }
        };
        
        const downloadReceipt = async (donation) => {
            window.open(`${apiClient.baseUrl}/reports/donation-receipt/${donation.id}`, '_blank');
        };
        
        const prevPage = () => {
            if (currentPage.value > 1) {
                currentPage.value--;
                loadDonations();
            }
        };
        
        const nextPage = () => {
            if (currentPage.value < totalPages.value) {
                currentPage.value++;
                loadDonations();
            }
        };
        
        const closeModal = () => {
            selectedDonation.value = null;
        };
        
        // Watch filters
        watch([() => filters.search, () => filters.status, () => filters.project, () => filters.date_from, () => filters.date_to], () => {
            currentPage.value = 1;
            loadDonations();
        });
        
        onMounted(() => {
            loadDonations();
            loadProjects();
        });
        
        return {
            donations,
            projects,
            currentPage,
            totalPages,
            filters,
            selectedDonation,
            formatCurrency,
            formatDate,
            formatShortDate,
            getStatusBadge,
            loadDonations,
            exportData,
            viewDonation,
            refundDonation,
            downloadReceipt,
            prevPage,
            nextPage,
            closeModal
        };
    }
};

// ==================== Settings Component ====================
const Settings = {
    template: `
        <div class="trueangels-settings">
            <form @submit.prevent="saveSettings">
                <div class="trueangels-settings-section">
                    <h3>🔧 API Konfiguration</h3>
                    <div class="trueangels-settings-field">
                        <label>API URL</label>
                        <input type="url" v-model="settings.api_url" class="regular-text">
                        <p class="description">TrueAngels API Endpoint URL</p>
                    </div>
                    <div class="trueangels-settings-field">
                        <label>API Key</label>
                        <input type="password" v-model="settings.api_key" class="regular-text">
                        <p class="description">Ihr TrueAngels API Key</p>
                    </div>
                </div>
                
                <div class="trueangels-settings-section">
                    <h3>🎨 Darstellung</h3>
                    <div class="trueangels-settings-field">
                        <label>Standard-Projekt</label>
                        <select v-model="settings.default_project">
                            <option value="">Bitte wählen...</option>
                            <option v-for="project in projects" :key="project.id" :value="project.id">
                                {{ project.name }}
                            </option>
                        </select>
                    </div>
                    <div class="trueangels-settings-field">
                        <label>
                            <input type="checkbox" v-model="settings.enable_audit">
                            Audit-Log aktivieren
                        </label>
                    </div>
                    <div class="trueangels-settings-field">
                        <label>Cache Dauer (Sekunden)</label>
                        <input type="number" v-model.number="settings.cache_duration" class="small-text">
                    </div>
                </div>
                
                <div class="trueangels-settings-section">
                    <h3>🔔 Benachrichtigungen</h3>
                    <div class="trueangels-settings-field">
                        <label>
                            <input type="checkbox" v-model="settings.notify_on_donation">
                            Bei neuen Spenden benachrichtigen
                        </label>
                    </div>
                    <div class="trueangels-settings-field">
                        <label>E-Mail für Benachrichtigungen</label>
                        <input type="email" v-model="settings.notification_email" class="regular-text">
                    </div>
                </div>
                
                <div class="trueangels-settings-actions">
                    <button type="submit" class="button button-primary" :disabled="saving">
                        {{ saving ? 'Speichern...' : 'Einstellungen speichern' }}
                    </button>
                    <button type="button" @click="testConnection" class="button" :disabled="testing">
                        {{ testing ? 'Teste...' : 'Verbindung testen' }}
                    </button>
                </div>
                
                <div v-if="testResult" class="trueangels-test-result" :class="testResult.success ? 'success' : 'error'">
                    {{ testResult.message }}
                </div>
            </form>
        </div>
    `,
    
    setup() {
        const settings = reactive({
            api_url: trueangels_ajax.api_url || '',
            api_key: '',
            default_project: '',
            enable_audit: true,
            cache_duration: 300,
            notify_on_donation: true,
            notification_email: ''
        });
        
        const projects = ref([]);
        const saving = ref(false);
        const testing = ref(false);
        const testResult = ref(null);
        
        const loadSettings = () => {
            // Load from WordPress options
            settings.api_url = window.trueangels_settings?.api_url || '';
            settings.default_project = window.trueangels_settings?.default_project || '';
            settings.enable_audit = window.trueangels_settings?.enable_audit !== false;
            settings.cache_duration = window.trueangels_settings?.cache_duration || 300;
        };
        
        const loadProjects = async () => {
            try {
                projects.value = await apiClient.get('/projects');
            } catch (error) {
                console.error('Failed to load projects:', error);
            }
        };
        
        const saveSettings = async () => {
            saving.value = true;
            try {
                await apiClient.post('/settings', settings);
                alert('Einstellungen wurden gespeichert!');
            } catch (error) {
                alert('Fehler beim Speichern: ' + error.message);
            } finally {
                saving.value = false;
            }
        };
        
        const testConnection = async () => {
            testing.value = true;
            testResult.value = null;
            try {
                await apiClient.get('/test-connection');
                testResult.value = {
                    success: true,
                    message: '✅ Verbindung erfolgreich! Die API ist erreichbar.'
                };
            } catch (error) {
                testResult.value = {
                    success: false,
                    message: `❌ Verbindung fehlgeschlagen: ${error.message}`
                };
            } finally {
                testing.value = false;
            }
        };
        
        onMounted(() => {
            loadSettings();
            loadProjects();
        });
        
        return {
            settings,
            projects,
            saving,
            testing,
            testResult,
            saveSettings,
            testConnection
        };
    }
};

// ==================== Audit Log Component ====================
const AuditLogViewer = {
    template: `
        <div class="trueangels-audit">
            <div class="trueangels-audit-filters">
                <input type="text" v-model="filters.search" placeholder="🔍 Suchen..." class="regular-text">
                <input type="date" v-model="filters.date" class="regular-text">
                <button @click="loadLogs" class="button">🔄 Aktualisieren</button>
                <button @click="exportLogs" class="button button-primary">📥 Exportieren</button>
            </div>
            
            <div class="trueangels-table-responsive">
                <table class="wp-list-table widefat fixed striped">
                    <thead>
                        <tr>
                            <th>Zeitstempel</th>
                            <th>Benutzer</th>
                            <th>Aktion</th>
                            <th>Entity</th>
                            <th>IP-Adresse</th>
                            <th>Details</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="log in logs" :key="log.id">
                            <td>{{ formatDate(log.timestamp) }}</td>
                            <td>{{ log.user_name || 'System' }}</td>
                            <td><code>{{ log.action }}</code></td>
                            <td>{{ log.entity_type }}</td>
                            <td>{{ log.ip_address || '-' }}</td>
                            <td>
                                <button @click="viewDetails(log)" class="button button-small">👁️ Details</button>
                            </td>
                        </tr>
                        <tr v-if="logs.length === 0">
                            <td colspan="6" class="trueangels-no-data">Keine Audit-Logs gefunden</td>
                        </tr>
                    </tbody>
                </table>
            </div>
            
            <!-- Details Modal -->
            <div class="trueangels-modal" v-if="selectedLog" @click.self="closeModal">
                <div class="trueangels-modal-content trueangels-modal-large">
                    <div class="trueangels-modal-header">
                        <h3>Audit-Details</h3>
                        <button @click="closeModal" class="trueangels-modal-close">&times;</button>
                    </div>
                    <div class="trueangels-modal-body">
                        <div class="trueangels-detail-row">
                            <strong>Aktion:</strong> <code>{{ selectedLog.action }}</code>
                        </div>
                        <div class="trueangels-detail-row">
                            <strong>Entity:</strong> {{ selectedLog.entity_type }} ({{ selectedLog.entity_id }})
                        </div>
                        <div class="trueangels-detail-row">
                            <strong>Benutzer:</strong> {{ selectedLog.user_name || 'System' }}
                        </div>
                        <div class="trueangels-detail-row">
                            <strong>IP-Adresse:</strong> {{ selectedLog.ip_address || '-' }}
                        </div>
                        <div class="trueangels-detail-row">
                            <strong>Zeitstempel:</strong> {{ formatDate(selectedLog.timestamp) }}
                        </div>
                        <div class="trueangels-detail-row" v-if="selectedLog.old_values">
                            <strong>Alte Werte:</strong>
                            <pre>{{ JSON.stringify(selectedLog.old_values, null, 2) }}</pre>
                        </div>
                        <div class="trueangels-detail-row" v-if="selectedLog.new_values">
                            <strong>Neue Werte:</strong>
                            <pre>{{ JSON.stringify(selectedLog.new_values, null, 2) }}</pre>
                        </div>
                    </div>
                    <div class="trueangels-modal-footer">
                        <button @click="closeModal" class="button">Schließen</button>
                    </div>
                </div>
            </div>
        </div>
    `,
    
    setup() {
        const logs = ref([]);
        const selectedLog = ref(null);
        const filters = reactive({
            search: '',
            date: ''
        });
        
        const loadLogs = async () => {
            try {
                const params = new URLSearchParams();
                if (filters.date) params.append('date', filters.date);
                const data = await apiClient.get(`/audit-log?${params}`);
                logs.value = data;
            } catch (error) {
                console.error('Failed to load audit logs:', error);
            }
        };
        
        const exportLogs = () => {
            const params = new URLSearchParams({
                format: 'csv',
                ...(filters.date && { date: filters.date })
            });
            window.open(`${apiClient.baseUrl}/export/audit?${params}`, '_blank');
        };
        
        const viewDetails = (log) => {
            selectedLog.value = log;
        };
        
        const closeModal = () => {
            selectedLog.value = null;
        };
        
        const formatDate = (dateString) => {
            if (!dateString) return '-';
            const date = new Date(dateString);
            return date.toLocaleString('de-DE');
        };
        
        onMounted(() => {
            loadLogs();
        });
        
        return {
            logs,
            selectedLog,
            filters,
            loadLogs,
            exportLogs,
            viewDetails,
            closeModal,
            formatDate
        };
    }
};

// ==================== Routes / Navigation ====================
const routes = {
    dashboard: Dashboard,
    donations: DonationsManager,
    settings: Settings,
    audit: AuditLogViewer
};

// ==================== Main App ====================
const App = {
    setup() {
        const currentView = ref('dashboard');
        
        const currentComponent = computed(() => {
            return routes[currentView.value] || Dashboard;
        });
        
        const navigateTo = (view) => {
            currentView.value = view;
        };
        
        return {
            currentView,
            currentComponent,
            navigateTo
        };
    },
    template: `
        <div class="trueangels-admin-app">
            <div class="trueangels-admin-nav">
                <button @click="navigateTo('dashboard')" :class="{ active: currentView === 'dashboard' }">
                    📊 Dashboard
                </button>
                <button @click="navigateTo('donations')" :class="{ active: currentView === 'donations' }">
                    💝 Spenden
                </button>
                <button @click="navigateTo('audit')" :class="{ active: currentView === 'audit' }">
                    📋 Audit-Log
                </button>
                <button @click="navigateTo('settings')" :class="{ active: currentView === 'settings' }">
                    ⚙️ Einstellungen
                </button>
            </div>
            <div class="trueangels-admin-content">
                <component :is="currentComponent"></component>
            </div>
        </div>
    `
};

// ==================== Initialize App ====================
document.addEventListener('DOMContentLoaded', () => {
    const adminRoot = document.getElementById('trueangels-admin-app');
    if (adminRoot) {
        const app = createApp(App);
        app.mount('#trueangels-admin-app');
    }
});