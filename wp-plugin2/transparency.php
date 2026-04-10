<?php
/**
 * Plugin Name: TrueAngels Transparency Suite
 * Plugin URI: https://trueangels.org/transparency
 * Description: DSGVO-compliant donation transparency widgets with SKR42 accounting
 * Version: 2.0.0
 * Author: TrueAngels e.V.
 * License: GPL v2 or later
 * Text Domain: trueangels-transparency
 */

// Sicherheitscheck
if (!defined('ABSPATH')) {
    exit;
}

// Plugin Konstanten
define('TA_TRANSPARENCY_VERSION', '2.0.0');
define('TA_API_URL', 'https://api.trueangels.org/api/v1');
define('TA_CACHE_HOURS', 6);

// Hauptklasse
class TrueAngelsTransparencySuite {
    
    private static $instance = null;
    
    public static function get_instance() {
        if (null === self::$instance) {
            self::$instance = new self();
        }
        return self::$instance;
    }
    
    private function __construct() {
        $this->init_hooks();
        $this->register_shortcodes();
        $this->register_ajax_endpoints();
    }
    
    private function init_hooks() {
        add_action('wp_enqueue_scripts', [$this, 'enqueue_assets']);
        add_action('admin_menu', [$this, 'add_admin_menu']);
        add_action('rest_api_init', [$this, 'register_rest_endpoints']);
        add_action('wp_ajax_ta_refresh_data', [$this, 'ajax_refresh_data']);
        add_action('wp_ajax_nopriv_ta_refresh_data', [$this, 'ajax_refresh_data']);
    }
    
    private function register_shortcodes() {
        add_shortcode('ta_donations_stream', [$this, 'render_donations_stream']);
        add_shortcode('ta_project_progress', [$this, 'render_project_progress']);
        add_shortcode('ta_financial_dashboard', [$this, 'render_financial_dashboard']);
        add_shortcode('ta_tax_donations', [$this, 'render_tax_donations']);
        add_shortcode('ta_impact_metrics', [$this, 'render_impact_metrics']);
    }
    
    public function enqueue_assets() {
        // Vue.js und Komponenten
        wp_enqueue_script('vue', 'https://cdn.jsdelivr.net/npm/vue@2.7.14/dist/vue.js', [], '2.7.14');
        wp_enqueue_script('chart-js', 'https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js', [], '4.4.0');
        wp_enqueue_script('moment', 'https://cdn.jsdelivr.net/npm/moment@2.29.4/moment.min.js', [], '2.29.4');
        
        // TailwindCSS für modernes Styling
        wp_enqueue_style('tailwind', 'https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css');
        
        // Font Awesome Icons
        wp_enqueue_style('fontawesome', 'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css');
        
        // Plugin Assets
        wp_enqueue_style('ta-transparency', plugin_dir_url(__FILE__) . 'assets/css/transparency.css', [], TA_TRANSPARENCY_VERSION);
        wp_enqueue_script('ta-transparency', plugin_dir_url(__FILE__) . 'assets/js/transparency.js', ['vue', 'chart-js'], TA_TRANSPARENCY_VERSION, true);
        
        // Lokalisierung für AJAX
        wp_localize_script('ta-transparency', 'ta_ajax', [
            'ajax_url' => admin_url('admin-ajax.php'),
            'nonce' => wp_create_nonce('ta_transparency_nonce'),
            'api_url' => TA_API_URL,
            'refresh_interval' => TA_CACHE_HOURS * 3600 * 1000
        ]);
    }
    
    /**
     * Shortcode: Live Donations Stream (DSGVO-konform)
     * Usage: [ta_donations_stream project_id="123" limit="20" anonymize="true"]
     */
    public function render_donations_stream($atts) {
        $attrs = shortcode_atts([
            'project_id' => null,
            'limit' => 50,
            'anonymize' => 'true',
            'show_amounts' => 'true',
            'show_dates' => 'true',
            'layout' => 'grid' // grid, list, timeline
        ], $atts);
        
        ob_start();
        ?>
        <div id="ta-donations-stream-<?php echo esc_attr($attrs['project_id'] ?: 'global'); ?>" 
             class="ta-transparency-widget ta-donations-stream"
             data-project-id="<?php echo esc_attr($attrs['project_id']); ?>"
             data-limit="<?php echo esc_attr($attrs['limit']); ?>"
             data-anonymize="<?php echo esc_attr($attrs['anonymize']); ?>"
             data-show-amounts="<?php echo esc_attr($attrs['show_amounts']); ?>"
             data-show-dates="<?php echo esc_attr($attrs['show_dates']); ?>"
             data-layout="<?php echo esc_attr($attrs['layout']); ?>">
            
            <div class="ta-loading">
                <div class="ta-spinner"></div>
                <p>Lade Spendenübersicht...</p>
            </div>
            
            <div class="ta-stream-container" style="display: none;">
                <div class="ta-stream-header">
                    <h3 class="ta-title">
                        <i class="fas fa-hand-holding-heart"></i> 
                        Aktuelle Spenden
                    </h3>
                    <button class="ta-refresh-btn" title="Aktualisieren">
                        <i class="fas fa-sync-alt"></i>
                    </button>
                </div>
                
                <div class="ta-stream-stats">
                    <div class="ta-stat-card">
                        <span class="ta-stat-label">Gesamtspenden</span>
                        <span class="ta-stat-value" id="ta-total-donations">0</span>
                    </div>
                    <div class="ta-stat-card">
                        <span class="ta-stat-label">Spender*innen</span>
                        <span class="ta-stat-value" id="ta-unique-donors">0</span>
                    </div>
                    <div class="ta-stat-card">
                        <span class="ta-stat-label">Ø Spende</span>
                        <span class="ta-stat-value" id="ta-avg-donation">0 €</span>
                    </div>
                </div>
                
                <div class="ta-stream-content ta-layout-<?php echo esc_attr($attrs['layout']); ?>">
                    <!-- Vue.js rendert hier die Spenden -->
                </div>
                
                <div class="ta-stream-footer">
                    <button class="ta-load-more-btn">Mehr anzeigen <i class="fas fa-chevron-down"></i></button>
                </div>
            </div>
        </div>
        <?php
        return ob_get_clean();
    }
    
    /**
     * Shortcode: Project Progress Dashboard
     * Usage: [ta_project_progress project_id="123" show_breakdown="true"]
     */
    public function render_project_progress($atts) {
        $attrs = shortcode_atts([
            'project_id' => null,
            'show_breakdown' => 'true',
            'show_timeline' => 'true',
            'theme' => 'modern'
        ], $atts);
        
        if (!$attrs['project_id']) {
            return '<div class="ta-error">Bitte Projekt-ID angeben: [ta_project_progress project_id="123"]</div>';
        }
        
        ob_start();
        ?>
        <div id="ta-project-progress-<?php echo esc_attr($attrs['project_id']); ?>" 
             class="ta-transparency-widget ta-project-progress"
             data-project-id="<?php echo esc_attr($attrs['project_id']); ?>"
             data-show-breakdown="<?php echo esc_attr($attrs['show_breakdown']); ?>"
             data-show-timeline="<?php echo esc_attr($attrs['show_timeline']); ?>"
             data-theme="<?php echo esc_attr($attrs['theme']); ?>">
            
            <div class="ta-loading">
                <div class="ta-spinner"></div>
                <p>Lade Projektfortschritt...</p>
            </div>
            
            <div class="ta-progress-container" style="display: none;">
                <div class="ta-progress-header">
                    <h3 class="ta-project-title">
                        <i class="fas fa-project-diagram"></i> 
                        <span id="ta-project-name">Projekt</span>
                    </h3>
                </div>
                
                <div class="ta-progress-ring">
                    <canvas id="ta-funding-chart" width="200" height="200"></canvas>
                    <div class="ta-progress-percentage">
                        <span id="ta-funding-percent">0</span>%
                    </div>
                </div>
                
                <div class="ta-progress-details">
                    <div class="ta-progress-bar-container">
                        <div class="ta-progress-bar-label">
                            <span>Finanzierungsziel</span>
                            <span id="ta-budget-planned">0 €</span>
                        </div>
                        <div class="ta-progress-bar">
                            <div class="ta-progress-fill" id="ta-progress-fill" style="width: 0%"></div>
                        </div>
                        <div class="ta-progress-stats">
                            <span>Bereits gespendet: <strong id="ta-donations-received">0 €</strong></span>
                            <span>Noch benötigt: <strong id="ta-remaining-need">0 €</strong></span>
                        </div>
                    </div>
                    
                    <div class="ta-expense-breakdown" id="ta-expense-breakdown" style="display: <?php echo $attrs['show_breakdown'] === 'true' ? 'block' : 'none'; ?>">
                        <h4>Verwendungsnachweis</h4>
                        <canvas id="ta-expense-chart" width="400" height="200"></canvas>
                        <div class="ta-expense-list" id="ta-expense-list"></div>
                    </div>
                </div>
                
                <div class="ta-impact-metrics" id="ta-impact-metrics">
                    <h4>Direkte Hilfe</h4>
                    <div class="ta-metrics-grid">
                        <!-- Dynamische Impact-Metriken -->
                    </div>
                </div>
            </div>
        </div>
        <?php
        return ob_get_clean();
    }
    
    /**
     * Shortcode: Financial Dashboard (SKR42-konform)
     * Usage: [ta_financial_dashboard year="2024" show_monthly="true"]
     */
    public function render_financial_dashboard($atts) {
        $attrs = shortcode_atts([
            'year' => date('Y'),
            'show_monthly' => 'true',
            'show_categories' => 'true',
            'currency' => 'EUR'
        ], $atts);
        
        ob_start();
        ?>
        <div id="ta-financial-dashboard" 
             class="ta-transparency-widget ta-financial-dashboard"
             data-year="<?php echo esc_attr($attrs['year']); ?>"
             data-show-monthly="<?php echo esc_attr($attrs['show_monthly']); ?>"
             data-show-categories="<?php echo esc_attr($attrs['show_categories']); ?>">
            
            <div class="ta-loading">
                <div class="ta-spinner"></div>
                <p>Lade Finanzdaten...</p>
            </div>
            
            <div class="ta-finance-container" style="display: none;">
                <div class="ta-finance-header">
                    <h3><i class="fas fa-chart-line"></i> Finanzübersicht <?php echo esc_html($attrs['year']); ?></h3>
                    <div class="ta-year-selector">
                        <select id="ta-year-select">
                            <?php for($y = 2020; $y <= date('Y'); $y++): ?>
                                <option value="<?php echo $y; ?>" <?php echo $y == $attrs['year'] ? 'selected' : ''; ?>>
                                    <?php echo $y; ?>
                                </option>
                            <?php endfor; ?>
                        </select>
                    </div>
                </div>
                
                <div class="ta-finance-stats">
                    <div class="ta-finance-card income">
                        <i class="fas fa-arrow-up"></i>
                        <div class="ta-finance-info">
                            <span class="ta-label">Einnahmen</span>
                            <span class="ta-value" id="ta-total-income">0 €</span>
                        </div>
                    </div>
                    <div class="ta-finance-card expenses">
                        <i class="fas fa-arrow-down"></i>
                        <div class="ta-finance-info">
                            <span class="ta-label">Ausgaben</span>
                            <span class="ta-value" id="ta-total-expenses">0 €</span>
                        </div>
                    </div>
                    <div class="ta-finance-card balance">
                        <i class="fas fa-scale-balanced"></i>
                        <div class="ta-finance-info">
                            <span class="ta-label">Überschuss</span>
                            <span class="ta-value" id="ta-balance">0 €</span>
                        </div>
                    </div>
                    <div class="ta-finance-card admin-cost">
                        <i class="fas fa-building"></i>
                        <div class="ta-finance-info">
                            <span class="ta-label">Verwaltungskosten</span>
                            <span class="ta-value" id="ta-admin-costs">0 €</span>
                            <span class="ta-percent" id="ta-admin-percent">0%</span>
                        </div>
                    </div>
                </div>
                
                <div class="ta-finance-charts">
                    <div class="ta-chart-card">
                        <h4>Monatliche Entwicklung</h4>
                        <canvas id="ta-monthly-chart"></canvas>
                    </div>
                    <div class="ta-chart-card">
                        <h4>Kategorie-Verteilung</h4>
                        <canvas id="ta-category-chart"></canvas>
                    </div>
                </div>
                
                <div class="ta-skr42-table">
                    <h4>SKR42 Kontenübersicht</h4>
                    <div class="ta-table-responsive">
                        <table class="ta-table">
                            <thead>
                                <tr>
                                    <th>Konto</th>
                                    <th>Bezeichnung</th>
                                    <th>Soll</th>
                                    <th>Haben</th>
                                    <th>Saldo</th>
                                </tr>
                            </thead>
                            <tbody id="ta-skr42-table-body">
                                <!-- Dynamisch befüllt -->
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>
        <?php
        return ob_get_clean();
    }
    
    /**
     * Shortcode: Tax-Deductible Donations (Spendenbescheinigung)
     * Usage: [ta_tax_donations user_id="123" year="2024"]
     */
    public function render_tax_donations($atts) {
        // Nur für eingeloggte User (DSGVO)
        if (!is_user_logged_in()) {
            return '<div class="ta-login-required">Bitte <a href="' . wp_login_url(get_permalink()) . '">einloggen</a> um Ihre Spenden zu sehen.</div>';
        }
        
        $current_user = wp_get_current_user();
        $attrs = shortcode_atts([
            'user_id' => $current_user->ID,
            'year' => date('Y'),
            'format' => 'table' // table, certificate
        ], $atts);
        
        ob_start();
        ?>
        <div id="ta-tax-donations" 
             class="ta-transparency-widget ta-tax-donations"
             data-user-id="<?php echo esc_attr($attrs['user_id']); ?>"
             data-year="<?php echo esc_attr($attrs['year']); ?>"
             data-format="<?php echo esc_attr($attrs['format']); ?>">
            
            <div class="ta-loading">
                <div class="ta-spinner"></div>
                <p>Lade Ihre Spenden...</p>
            </div>
            
            <div class="ta-tax-container" style="display: none;">
                <div class="ta-tax-header">
                    <h3><i class="fas fa-file-invoice-dollar"></i> Ihre Spendenübersicht <?php echo esc_html($attrs['year']); ?></h3>
                    <button class="ta-download-pdf" id="ta-download-certificate">
                        <i class="fas fa-download"></i> Spendenbescheinigung PDF
                    </button>
                </div>
                
                <div class="ta-tax-summary">
                    <div class="ta-tax-card">
                        <span class="ta-tax-label">Gesamtspenden</span>
                        <span class="ta-tax-amount" id="ta-user-total">0 €</span>
                    </div>
                    <div class="ta-tax-card">
                        <span class="ta-tax-label">Davon steuerlich absetzbar</span>
                        <span class="ta-tax-amount" id="ta-user-deductible">0 €</span>
                    </div>
                    <div class="ta-tax-card">
                        <span class="ta-tax-label">Anzahl Spenden</span>
                        <span class="ta-tax-count" id="ta-user-count">0</span>
                    </div>
                </div>
                
                <div class="ta-tax-table-wrapper">
                    <table class="ta-tax-table">
                        <thead>
                            <tr>
                                <th>Datum</th>
                                <th>Projekt</th>
                                <th>Betrag</th>
                                <th>Steuerlich absetzbar</th>
                                <th>Bescheinigung</th>
                            </tr>
                        </thead>
                        <tbody id="ta-tax-table-body">
                            <!-- Dynamisch befüllt -->
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
        <?php
        return ob_get_clean();
    }
    
    /**
     * Shortcode: Impact Metrics
     * Usage: [ta_impact_metrics project_id="123" metrics="meals,people,houses"]
     */
    public function render_impact_metrics($atts) {
        $attrs = shortcode_atts([
            'project_id' => null,
            'metrics' => 'meals,people,houses,water',
            'layout' => 'grid',
            'animation' => 'counter'
        ], $atts);
        
        ob_start();
        ?>
        <div id="ta-impact-metrics-<?php echo esc_attr($attrs['project_id'] ?: 'global'); ?>" 
             class="ta-transparency-widget ta-impact-widget"
             data-project-id="<?php echo esc_attr($attrs['project_id']); ?>"
             data-metrics="<?php echo esc_attr($attrs['metrics']); ?>"
             data-layout="<?php echo esc_attr($attrs['layout']); ?>"
             data-animation="<?php echo esc_attr($attrs['animation']); ?>">
            
            <div class="ta-loading">
                <div class="ta-spinner"></div>
                <p>Lade Wirkungsdaten...</p>
            </div>
            
            <div class="ta-impact-container" style="display: none;">
                <div class="ta-impact-grid ta-layout-<?php echo esc_attr($attrs['layout']); ?>" id="ta-impact-grid">
                    <!-- Dynamische Impact-Karten -->
                </div>
            </div>
        </div>
        <?php
        return ob_get_clean();
    }
    
    /**
     * REST API Endpoints
     */
    public function register_rest_endpoints() {
        register_rest_route('ta/v1', '/donations', [
            'methods' => 'GET',
            'callback' => [$this, 'api_get_donations'],
            'permission_callback' => '__return_true'
        ]);
        
        register_rest_route('ta/v1', '/project/(?P<id>\d+)', [
            'methods' => 'GET',
            'callback' => [$this, 'api_get_project'],
            'permission_callback' => '__return_true'
        ]);
        
        register_rest_route('ta/v1', '/financial/(?P<year>\d+)', [
            'methods' => 'GET',
            'callback' => [$this, 'api_get_financials'],
            'permission_callback' => '__return_true'
        ]);
    }
    
    /**
     * API: DSGVO-konforme Spenden (anonymisiert)
     */
    public function api_get_donations($request) {
        $project_id = $request->get_param('project_id');
        $limit = min($request->get_param('limit') ?: 50, 100);
        $anonymize = $request->get_param('anonymize') !== 'false';
        
        // Cache Key
        $cache_key = "ta_donations_{$project_id}_{$limit}_{$anonymize}";
        $cached = get_transient($cache_key);
        
        if ($cached !== false) {
            return rest_ensure_response($cached);
        }
        
        // API Call zu TrueAngels Backend
        $response = wp_remote_get(TA_API_URL . '/donations/public', [
            'headers' => [
                'X-API-Key' => get_option('ta_api_key'),
                'Content-Type' => 'application/json'
            ],
            'body' => [
                'project_id' => $project_id,
                'limit' => $limit,
                'anonymize' => $anonymize
            ],
            'timeout' => 10
        ]);
        
        if (is_wp_error($response)) {
            return new WP_Error('api_error', 'Fehler beim Laden der Daten', ['status' => 500]);
        }
        
        $data = json_decode(wp_remote_retrieve_body($response), true);
        
        // DSGVO: Entferne personenbezogene Daten
        if ($anonymize && isset($data['donations'])) {
            foreach ($data['donations'] as &$donation) {
                unset($donation['donor_email']);
                unset($donation['donor_address']);
                if (isset($donation['donor_name'])) {
                    $donation['donor_name'] = $this->anonymize_name($donation['donor_name']);
                }
            }
        }
        
        // Cache für 6 Stunden
        set_transient($cache_key, $data, TA_CACHE_HOURS * HOUR_IN_SECONDS);
        
        return rest_ensure_response($data);
    }
    
    /**
     * Hilfsfunktion: Name anonymisieren (DSGVO)
     */
    private function anonymize_name($name) {
        $parts = explode(' ', trim($name));
        if (count($parts) === 1) {
            return substr($parts[0], 0, 1) . '***';
        }
        return $parts[0] . ' ' . substr($parts[1], 0, 1) . '.';
    }
    
    /**
     * AJAX Handler für Live-Refresh
     */
    public function ajax_refresh_data() {
        check_ajax_referer('ta_transparency_nonce', 'nonce');
        
        $type = sanitize_text_field($_POST['type']);
        $id = sanitize_text_field($_POST['id']);
        
        // Clear cache für diese Anfrage
        $cache_key = "ta_{$type}_{$id}";
        delete_transient($cache_key);
        
        wp_send_json_success(['message' => 'Cache gelöscht', 'type' => $type]);
    }
    
    /**
     * Admin Menu
     */
    public function add_admin_menu() {
        add_menu_page(
            'TrueAngels Transparency',
            'TA Transparency',
            'manage_options',
            'ta-transparency',
            [$this, 'render_admin_page'],
            'dashicons-chart-area',
            30
        );
    }
    
    public function render_admin_page() {
        ?>
        <div class="wrap ta-admin-wrap">
            <h1>TrueAngels Transparency Suite</h1>
            
            <div class="ta-admin-card">
                <h2>Shortcode Generator</h2>
                <form id="ta-shortcode-generator">
                    <select id="ta-shortcode-type">
                        <option value="donations_stream">Spenden-Stream</option>
                        <option value="project_progress">Projektfortschritt</option>
                        <option value="financial_dashboard">Finanzdashboard</option>
                        <option value="tax_donations">Steuerbescheinigung</option>
                        <option value="impact_metrics">Wirkungsmetriken</option>
                    </select>
                    
                    <div id="ta-shortcode-options"></div>
                    
                    <button type="button" class="button button-primary" id="ta-generate-shortcode">
                        Shortcode generieren
                    </button>
                    
                    <div class="ta-shortcode-result">
                        <code id="ta-shortcode-output"></code>
                        <button class="button button-secondary ta-copy-shortcode">Kopieren</button>
                    </div>
                </form>
            </div>
            
            <div class="ta-admin-card">
                <h2>Einstellungen</h2>
                <form method="post" action="options.php">
                    <?php settings_fields('ta_transparency_settings'); ?>
                    <table class="form-table">
                        <tr>
                            <th>API Endpoint</th>
                            <td><input type="url" name="ta_api_url" value="<?php echo get_option('ta_api_url', TA_API_URL); ?>" class="regular-text"></td>
                        </tr>
                        <tr>
                            <th>API Key</th>
                            <td><input type="password" name="ta_api_key" value="<?php echo get_option('ta_api_key'); ?>" class="regular-text"></td>
                        </tr>
                        <tr>
                            <th>Cache Dauer (Stunden)</th>
                            <td><input type="number" name="ta_cache_hours" value="<?php echo get_option('ta_cache_hours', TA_CACHE_HOURS); ?>" min="1" max="24"></td>
                        </tr>
                        <tr>
                            <th>DSGVO-Modus</th>
                            <td>
                                <label><input type="checkbox" name="ta_gdpr_mode" value="1" <?php checked(get_option('ta_gdpr_mode', 1)); ?>> 
                                Anonymisierung aktivieren</label>
                            </td>
                        </tr>
                    </table>
                    <?php submit_button(); ?>
                </form>
            </div>
        </div>
        
        <style>
            .ta-admin-wrap { padding: 20px; }
            .ta-admin-card { background: #fff; border: 1px solid #ccd0d4; border-radius: 4px; padding: 20px; margin-bottom: 20px; }
            .ta-shortcode-result { margin-top: 15px; padding: 10px; background: #f1f1f1; border-radius: 4px; display: flex; gap: 10px; align-items: center; }
            .ta-shortcode-result code { flex: 1; font-size: 14px; }
        </style>
        <?php
    }
}

// Plugin initialisieren
TrueAngelsTransparencySuite::get_instance();
