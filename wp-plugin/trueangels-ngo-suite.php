<?php
/**
 * FILE: wp-plugin/trueangels-ngo-suite.php
 * MODULE: WordPress Main Plugin File
 * Plugin Name: TrueAngels NGO Suite
 * Plugin URI: https://trueangels.de/wordpress
 * Description: Enterprise Integration zwischen WordPress und TrueAngels NGO Suite v2.0
 * Version: 2.0.0
 * Author: TrueAngels e.V.
 * Author URI: https://trueangels.de
 * License: GPL v2 or later
 * Text Domain: trueangels-ngo
 * Domain Path: /languages
 */

// Prevent direct access
if (!defined('ABSPATH')) {
    exit;
}

// ==================== Plugin Constants ====================

define('TRUEANGELS_VERSION', '2.0.0');
define('TRUEANGELS_PLUGIN_DIR', plugin_dir_path(__FILE__));
define('TRUEANGELS_PLUGIN_URL', plugin_dir_url(__FILE__));
define('TRUEANGELS_API_URL', get_option('trueangels_api_url', 'https://api.trueangels.de'));
define('TRUEANGELS_API_KEY', get_option('trueangels_api_key', ''));

// ==================== Main Plugin Class ====================

class TrueAngelsNGOPlugin {
    
    private static $instance = null;
    private $api_client;
    private $vue_assets_loaded = false;
    
    public static function get_instance() {
        if (null === self::$instance) {
            self::$instance = new self();
        }
        return self::$instance;
    }
    
    private function __construct() {
        $this->init_hooks();
        $this->init_api_client();
    }
    
    private function init_hooks() {
        // Admin hooks
        add_action('admin_menu', [$this, 'add_admin_menu']);
        add_action('admin_enqueue_scripts', [$this, 'enqueue_admin_assets']);
        add_action('admin_init', [$this, 'register_settings']);
        
        // Frontend hooks
        add_action('wp_enqueue_scripts', [$this, 'enqueue_frontend_assets']);
        add_shortcode('trueangels_donation_form', [$this, 'render_donation_form_shortcode']);
        add_shortcode('trueangels_projects', [$this, 'render_projects_shortcode']);
        add_shortcode('trueangels_campaign_widget', [$this, 'render_campaign_widget']);
        
        // REST API endpoints
        add_action('rest_api_init', [$this, 'register_rest_routes']);
        
        // AJAX handlers
        add_action('wp_ajax_trueangels_create_donation', [$this, 'ajax_create_donation']);
        add_action('wp_ajax_nopriv_trueangels_create_donation', [$this, 'ajax_create_donation']);
        
        // Cron jobs
        add_filter('cron_schedules', [$this, 'add_cron_intervals']);
        register_activation_hook(__FILE__, [$this, 'activate_plugin']);
        register_deactivation_hook(__FILE__, [$this, 'deactivate_plugin']);
    }
    
    private function init_api_client() {
        require_once TRUEANGELS_PLUGIN_DIR . 'includes/class-api-client.php';
        $this->api_client = new TrueAngels_APIClient(TRUEANGELS_API_URL, TRUEANGELS_API_KEY);
    }
    
    // ==================== Admin Menu ====================
    
    public function add_admin_menu() {
        add_menu_page(
            __('TrueAngels NGO Suite', 'trueangels-ngo'),
            'TrueAngels',
            'manage_options',
            'trueangels-dashboard',
            [$this, 'render_admin_dashboard'],
            'dashicons-heart',
            30
        );
        
        add_submenu_page(
            'trueangels-dashboard',
            __('Dashboard', 'trueangels-ngo'),
            __('Dashboard', 'trueangels-ngo'),
            'manage_options',
            'trueangels-dashboard',
            [$this, 'render_admin_dashboard']
        );
        
        add_submenu_page(
            'trueangels-dashboard',
            __('Donations', 'trueangels-ngo'),
            __('Donations', 'trueangels-ngo'),
            'manage_options',
            'trueangels-donations',
            [$this, 'render_admin_donations']
        );
        
        add_submenu_page(
            'trueangels-dashboard',
            __('Settings', 'trueangels-ngo'),
            __('Settings', 'trueangels-ngo'),
            'manage_options',
            'trueangels-settings',
            [$this, 'render_admin_settings']
        );
        
        add_submenu_page(
            'trueangels-dashboard',
            __('Audit Log', 'trueangels-ngo'),
            __('Audit Log', 'trueangels-ngo'),
            'manage_options',
            'trueangels-audit',
            [$this, 'render_admin_audit']
        );
    }
    
    public function register_settings() {
        register_setting('trueangels_settings', 'trueangels_api_url');
        register_setting('trueangels_settings', 'trueangels_api_key');
        register_setting('trueangels_settings', 'trueangels_default_project');
        register_setting('trueangels_settings', 'trueangels_enable_audit');
        register_setting('trueangels_settings', 'trueangels_cache_duration');
        
        add_settings_section(
            'trueangels_main_section',
            __('API Configuration', 'trueangels-ngo'),
            [$this, 'render_settings_section'],
            'trueangels-settings'
        );
        
        add_settings_field(
            'trueangels_api_url',
            __('API URL', 'trueangels-ngo'),
            [$this, 'render_api_url_field'],
            'trueangels-settings',
            'trueangels_main_section'
        );
        
        add_settings_field(
            'trueangels_api_key',
            __('API Key', 'trueangels-ngo'),
            [$this, 'render_api_key_field'],
            'trueangels-settings',
            'trueangels_main_section'
        );
    }
    
    // ==================== Admin Page Renderers ====================
    
    public function render_admin_dashboard() {
        ?>
        <div class="wrap">
            <h1><?php _e('TrueAngels NGO Suite Dashboard', 'trueangels-ngo'); ?></h1>
            
            <div id="trueangels-admin-app">
                <div class="trueangels-loading">Loading dashboard...</div>
            </div>
            
            <div class="trueangels-stats-grid">
                <div class="trueangels-stat-card">
                    <h3><?php _e('Total Donations', 'trueangels-ngo'); ?></h3>
                    <div class="trueangels-stat-value" id="trueangels-total-donations">—</div>
                    <div class="trueangels-stat-change" id="trueangels-donation-change"></div>
                </div>
                
                <div class="trueangels-stat-card">
                    <h3><?php _e('Active Projects', 'trueangels-ngo'); ?></h3>
                    <div class="trueangels-stat-value" id="trueangels-active-projects">—</div>
                    <div class="trueangels-stat-sub"><?php _e('currently running', 'trueangels-ngo'); ?></div>
                </div>
                
                <div class="trueangels-stat-card">
                    <h3><?php _e('Donors', 'trueangels-ngo'); ?></h3>
                    <div class="trueangels-stat-value" id="trueangels-total-donors">—</div>
                    <div class="trueangels-stat-change" id="trueangels-donors-change"></div>
                </div>
                
                <div class="trueangels-stat-card">
                    <h3><?php _e('Project Efficiency', 'trueangels-ngo'); ?></h3>
                    <div class="trueangels-stat-value" id="trueangels-efficiency">—</div>
                    <div class="trueangels-stat-sub"><?php _e('of budget used', 'trueangels-ngo'); ?></div>
                </div>
            </div>
            
            <div class="trueangels-chart-container">
                <canvas id="trueangels-donation-chart"></canvas>
            </div>
        </div>
        
        <script>
        jQuery(document).ready(function($) {
            // Load dashboard data via AJAX
            $.ajax({
                url: '<?php echo rest_url('trueangels/v1/dashboard/stats'); ?>',
                method: 'GET',
                beforeSend: function(xhr) {
                    xhr.setRequestHeader('X-WP-Nonce', '<?php echo wp_create_nonce('wp_rest'); ?>');
                },
                success: function(data) {
                    $('#trueangels-total-donations').text('€' + data.total_donations.toLocaleString());
                    $('#trueangels-active-projects').text(data.active_projects);
                    $('#trueangels-total-donors').text(data.total_donors);
                    $('#trueangels-efficiency').text(data.efficiency + '%');
                    
                    if (data.donation_change > 0) {
                        $('#trueangels-donation-change').html('↑ ' + data.donation_change + '%').css('color', 'green');
                    } else {
                        $('#trueangels-donation-change').html('↓ ' + Math.abs(data.donation_change) + '%').css('color', 'red');
                    }
                }
            });
        });
        </script>
        <?php
    }
    
    public function render_admin_donations() {
        ?>
        <div class="wrap">
            <h1><?php _e('Donations Management', 'trueangels-ngo'); ?></h1>
            
            <div class="trueangels-donations-filter">
                <input type="text" id="trueangels-search-donations" placeholder="<?php _e('Search donations...', 'trueangels-ngo'); ?>">
                <select id="trueangels-status-filter">
                    <option value="all"><?php _e('All Status', 'trueangels-ngo'); ?></option>
                    <option value="succeeded"><?php _e('Succeeded', 'trueangels-ngo'); ?></option>
                    <option value="pending"><?php _e('Pending', 'trueangels-ngo'); ?></option>
                    <option value="failed"><?php _e('Failed', 'trueangels-ngo'); ?></option>
                </select>
                <button id="trueangels-export-csv" class="button button-primary"><?php _e('Export CSV', 'trueangels-ngo'); ?></button>
            </div>
            
            <table class="wp-list-table widefat fixed striped" id="trueangels-donations-table">
                <thead>
                    <tr>
                        <th><?php _e('ID', 'trueangels-ngo'); ?></th>
                        <th><?php _e('Donor', 'trueangels-ngo'); ?></th>
                        <th><?php _e('Amount', 'trueangels-ngo'); ?></th>
                        <th><?php _e('Project', 'trueangels-ngo'); ?></th>
                        <th><?php _e('Date', 'trueangels-ngo'); ?></th>
                        <th><?php _e('Status', 'trueangels-ngo'); ?></th>
                        <th><?php _e('Actions', 'trueangels-ngo'); ?></th>
                    </tr>
                </thead>
                <tbody id="trueangels-donations-list">
                    <tr><td colspan="7"><?php _e('Loading donations...', 'trueangels-ngo'); ?></td></tr>
                </tbody>
            </table>
            
            <div class="trueangels-pagination" id="trueangels-pagination"></div>
        </div>
        <?php
    }
    
    public function render_admin_settings() {
        ?>
        <div class="wrap">
            <h1><?php _e('TrueAngels Settings', 'trueangels-ngo'); ?></h1>
            <form method="post" action="options.php">
                <?php settings_fields('trueangels_settings'); ?>
                <?php do_settings_sections('trueangels-settings'); ?>
                
                <table class="form-table">
                    <tr valign="top">
                        <th scope="row"><?php _e('API URL', 'trueangels-ngo'); ?></th>
                        <td>
                            <input type="url" name="trueangels_api_url" 
                                   value="<?php echo esc_attr(get_option('trueangels_api_url', 'https://api.trueangels.de')); ?>" 
                                   class="regular-text" />
                            <p class="description"><?php _e('TrueAngels API endpoint URL', 'trueangels-ngo'); ?></p>
                        </td>
                    </tr>
                    
                    <tr valign="top">
                        <th scope="row"><?php _e('API Key', 'trueangels-ngo'); ?></th>
                        <td>
                            <input type="password" name="trueangels_api_key" 
                                   value="<?php echo esc_attr(get_option('trueangels_api_key', '')); ?>" 
                                   class="regular-text" />
                            <p class="description"><?php _e('Your TrueAngels API key from the NGO Suite', 'trueangels-ngo'); ?></p>
                        </td>
                    </tr>
                    
                    <tr valign="top">
                        <th scope="row"><?php _e('Default Project', 'trueangels-ngo'); ?></th>
                        <td>
                            <select name="trueangels_default_project" id="trueangels-default-project">
                                <option value=""><?php _e('Select project...', 'trueangels-ngo'); ?></option>
                            </select>
                            <p class="description"><?php _e('Default project for donation forms', 'trueangels-ngo'); ?></p>
                        </td>
                    </tr>
                    
                    <tr valign="top">
                        <th scope="row"><?php _e('Enable Audit Log', 'trueangels-ngo'); ?></th>
                        <td>
                            <input type="checkbox" name="trueangels_enable_audit" 
                                   value="1" <?php checked(1, get_option('trueangels_enable_audit', 1)); ?> />
                            <p class="description"><?php _e('Log all API calls for compliance', 'trueangels-ngo'); ?></p>
                        </td>
                    </tr>
                    
                    <tr valign="top">
                        <th scope="row"><?php _e('Cache Duration', 'trueangels-ngo'); ?></th>
                        <td>
                            <input type="number" name="trueangels_cache_duration" 
                                   value="<?php echo esc_attr(get_option('trueangels_cache_duration', 300)); ?>" 
                                   class="small-text" /> <?php _e('seconds', 'trueangels-ngo'); ?>
                            <p class="description"><?php _e('How long to cache API responses', 'trueangels-ngo'); ?></p>
                        </td>
                    </tr>
                </table>
                
                <?php submit_button(); ?>
            </form>
            
            <div class="trueangels-test-connection">
                <h3><?php _e('Test Connection', 'trueangels-ngo'); ?></h3>
                <button id="trueangels-test-connection" class="button"><?php _e('Test API Connection', 'trueangels-ngo'); ?></button>
                <span id="trueangels-connection-result"></span>
            </div>
        </div>
        
        <script>
        jQuery(document).ready(function($) {
            // Load projects for dropdown
            $.ajax({
                url: '<?php echo rest_url('trueangels/v1/projects'); ?>',
                method: 'GET',
                success: function(projects) {
                    var select = $('#trueangels-default-project');
                    $.each(projects, function(i, project) {
                        select.append($('<option>', {
                            value: project.id,
                            text: project.name
                        }));
                    });
                    select.val('<?php echo esc_js(get_option('trueangels_default_project')); ?>');
                }
            });
            
            // Test connection
            $('#trueangels-test-connection').click(function() {
                var resultSpan = $('#trueangels-connection-result');
                resultSpan.html('<?php _e('Testing...', 'trueangels-ngo'); ?>');
                
                $.ajax({
                    url: '<?php echo rest_url('trueangels/v1/test-connection'); ?>',
                    method: 'GET',
                    success: function(data) {
                        resultSpan.html('<span style="color: green;">✓ ' + data.message + '</span>');
                    },
                    error: function() {
                        resultSpan.html('<span style="color: red;">✗ Connection failed</span>');
                    }
                });
            });
        });
        </script>
        <?php
    }
    
    public function render_admin_audit() {
        ?>
        <div class="wrap">
            <h1><?php _e('Audit Log', 'trueangels-ngo'); ?></h1>
            
            <div class="trueangels-audit-filters">
                <input type="text" id="trueangels-audit-search" placeholder="<?php _e('Search...', 'trueangels-ngo'); ?>">
                <input type="date" id="trueangels-audit-date" placeholder="<?php _e('Filter by date', 'trueangels-ngo'); ?>">
                <button id="trueangels-export-audit" class="button"><?php _e('Export Audit Log', 'trueangels-ngo'); ?></button>
            </div>
            
            <table class="wp-list-table widefat fixed striped" id="trueangels-audit-table">
                <thead>
                    <tr>
                        <th><?php _e('Timestamp', 'trueangels-ngo'); ?></th>
                        <th><?php _e('User', 'trueangels-ngo'); ?></th>
                        <th><?php _e('Action', 'trueangels-ngo'); ?></th>
                        <th><?php _e('Entity', 'trueangels-ngo'); ?></th>
                        <th><?php _e('IP Address', 'trueangels-ngo'); ?></th>
                        <th><?php _e('Details', 'trueangels-ngo'); ?></th>
                    </tr>
                </thead>
                <tbody id="trueangels-audit-list">
                    <tr><td colspan="6"><?php _e('Loading audit log...', 'trueangels-ngo'); ?></td></tr>
                </tbody>
            </table>
        </div>
        <?php
    }
    
    // ==================== Shortcodes ====================
    
    public function render_donation_form_shortcode($atts) {
        $atts = shortcode_atts([
            'project_id' => get_option('trueangels_default_project', ''),
            'button_text' => __('Donate Now', 'trueangels-ngo'),
            'amounts' => '10,25,50,100,250',
            'currency' => 'EUR',
            'theme' => 'light'
        ], $atts);
        
        ob_start();
        ?>
        <div class="trueangels-donation-wrapper" data-theme="<?php echo esc_attr($atts['theme']); ?>">
            <div id="trueangels-donation-form-root" 
                 data-project-id="<?php echo esc_attr($atts['project_id']); ?>"
                 data-button-text="<?php echo esc_attr($atts['button_text']); ?>"
                 data-amounts="<?php echo esc_attr($atts['amounts']); ?>"
                 data-currency="<?php echo esc_attr($atts['currency']); ?>">
            </div>
        </div>
        <?php
        return ob_get_clean();
    }
    
    public function render_projects_shortcode($atts) {
        $atts = shortcode_atts([
            'limit' => 5,
            'show_progress' => 'yes',
            'layout' => 'grid'
        ], $atts);
        
        ob_start();
        ?>
        <div class="trueangels-projects-wrapper">
            <div id="trueangels-projects-root" 
                 data-limit="<?php echo esc_attr($atts['limit']); ?>"
                 data-show-progress="<?php echo esc_attr($atts['show_progress']); ?>"
                 data-layout="<?php echo esc_attr($atts['layout']); ?>">
            </div>
        </div>
        <?php
        return ob_get_clean();
    }
    
    public function render_campaign_widget($atts) {
        $atts = shortcode_atts([
            'campaign_id' => '',
            'title' => __('Support Our Campaign', 'trueangels-ngo'),
            'show_donors' => 'yes'
        ], $atts);
        
        ob_start();
        ?>
        <div class="trueangels-campaign-widget">
            <h3><?php echo esc_html($atts['title']); ?></h3>
            <div id="trueangels-campaign-root" data-campaign-id="<?php echo esc_attr($atts['campaign_id']); ?>">
                <div class="trueangels-loading-spinner"></div>
            </div>
        </div>
        <?php
        return ob_get_clean();
    }
    
    // ==================== REST API Routes ====================
    
    public function register_rest_routes() {
        register_rest_route('trueangels/v1', '/dashboard/stats', [
            'methods' => 'GET',
            'callback' => [$this, 'api_get_dashboard_stats'],
            'permission_callback' => [$this, 'api_check_admin_permission']
        ]);
        
        register_rest_route('trueangels/v1', '/donations', [
            'methods' => 'GET',
            'callback' => [$this, 'api_get_donations'],
            'permission_callback' => [$this, 'api_check_admin_permission']
        ]);
        
        register_rest_route('trueangels/v1', '/donations', [
            'methods' => 'POST',
            'callback' => [$this, 'api_create_donation'],
            'permission_callback' => '__return_true'
        ]);
        
        register_rest_route('trueangels/v1', '/projects', [
            'methods' => 'GET',
            'callback' => [$this, 'api_get_projects'],
            'permission_callback' => '__return_true'
        ]);
        
        register_rest_route('trueangels/v1', '/projects/(?P<id>[a-f0-9-]+)', [
            'methods' => 'GET',
            'callback' => [$this, 'api_get_project'],
            'permission_callback' => '__return_true'
        ]);
        
        register_rest_route('trueangels/v1', '/test-connection', [
            'methods' => 'GET',
            'callback' => [$this, 'api_test_connection'],
            'permission_callback' => [$this, 'api_check_admin_permission']
        ]);
        
        register_rest_route('trueangels/v1', '/audit-log', [
            'methods' => 'GET',
            'callback' => [$this, 'api_get_audit_log'],
            'permission_callback' => [$this, 'api_check_admin_permission']
        ]);
        
        register_rest_route('trueangels/v1', '/export/donations', [
            'methods' => 'GET',
            'callback' => [$this, 'api_export_donations'],
            'permission_callback' => [$this, 'api_check_admin_permission']
        ]);
    }
    
    // ==================== API Callbacks ====================
    
    public function api_get_dashboard_stats($request) {
        try {
            $stats = $this->api_client->get('/reports/dashboard/kpis');
            
            return new WP_REST_Response([
                'success' => true,
                'total_donations' => $stats['total_donations_current_year'] ?? 0,
                'active_projects' => $stats['active_projects'] ?? 0,
                'total_donors' => $stats['donors_count'] ?? 0,
                'efficiency' => $stats['project_efficiency'] ?? 0,
                'donation_change' => $this->calculate_percentage_change(
                    $stats['total_donations_current_year'] ?? 0,
                    $stats['total_donations_previous_year'] ?? 0
                )
            ], 200);
        } catch (Exception $e) {
            return new WP_REST_Response(['success' => false, 'error' => $e->getMessage()], 500);
        }
    }
    
    public function api_get_donations($request) {
        $page = $request->get_param('page') ?: 1;
        $per_page = $request->get_param('per_page') ?: 20;
        $status = $request->get_param('status');
        $search = $request->get_param('search');
        
        try {
            $params = ['page' => $page, 'per_page' => $per_page];
            if ($status && $status !== 'all') $params['status'] = $status;
            if ($search) $params['search'] = $search;
            
            $donations = $this->api_client->get('/donations', $params);
            
            return new WP_REST_Response([
                'success' => true,
                'data' => $donations,
                'total' => count($donations),
                'page' => $page,
                'per_page' => $per_page
            ], 200);
        } catch (Exception $e) {
            return new WP_REST_Response(['success' => false, 'error' => $e->getMessage()], 500);
        }
    }
    
    public function api_create_donation($request) {
        $params = $request->get_json_params();
        
        // Validate required fields
        if (empty($params['amount']) || empty($params['donor_email'])) {
            return new WP_REST_Response([
                'success' => false,
                'error' => __('Amount and donor email are required', 'trueangels-ngo')
            ], 400);
        }
        
        try {
            $donation = $this->api_client->post('/payments/create-donation', $params);
            
            // Log audit if enabled
            if (get_option('trueangels_enable_audit', 1)) {
                $this->log_audit('donation_created', $donation['id'], $params);
            }
            
            return new WP_REST_Response([
                'success' => true,
                'donation_id' => $donation['donation_id'],
                'payment_intent_id' => $donation['payment_intent_id'],
                'client_secret' => $donation['client_secret'],
                'redirect_url' => $donation['redirect_url'] ?? null
            ], 200);
        } catch (Exception $e) {
            return new WP_REST_Response(['success' => false, 'error' => $e->getMessage()], 500);
        }
    }
    
    public function api_get_projects($request) {
        $cache_key = 'trueangels_projects_cache';
        $cached = get_transient($cache_key);
        
        if ($cached && get_option('trueangels_cache_duration', 300) > 0) {
            return new WP_REST_Response($cached, 200);
        }
        
        try {
            $projects = $this->api_client->get('/projects');
            
            $formatted_projects = array_map(function($project) {
                return [
                    'id' => $project['id'],
                    'name' => $project['name'],
                    'description' => $project['description'],
                    'progress' => $project['progress'] ?? 0,
                    'donations_total' => $project['donations_total'] ?? 0,
                    'budget_total' => $project['budget_total'] ?? 0
                ];
            }, $projects);
            
            set_transient($cache_key, $formatted_projects, get_option('trueangels_cache_duration', 300));
            
            return new WP_REST_Response($formatted_projects, 200);
        } catch (Exception $e) {
            return new WP_REST_Response(['error' => $e->getMessage()], 500);
        }
    }
    
    public function api_get_project($request) {
        $project_id = $request->get_param('id');
        
        try {
            $project = $this->api_client->get("/projects/{$project_id}");
            
            return new WP_REST_Response([
                'id' => $project['id'],
                'name' => $project['name'],
                'description' => $project['description'],
                'progress' => ($project['donations_total'] / $project['budget_total']) * 100,
                'donations_total' => $project['donations_total'],
                'budget_total' => $project['budget_total'],
                'recent_donations' => $project['recent_donations'] ?? []
            ], 200);
        } catch (Exception $e) {
            return new WP_REST_Response(['error' => $e->getMessage()], 500);
        }
    }
    
    public function api_test_connection($request) {
        try {
            $health = $this->api_client->get('/health');
            
            if ($health && isset($health['status'])) {
                return new WP_REST_Response([
                    'success' => true,
                    'message' => __('API connection successful', 'trueangels-ngo'),
                    'version' => $health['version'] ?? 'unknown'
                ], 200);
            }
        } catch (Exception $e) {
            return new WP_REST_Response([
                'success' => false,
                'message' => $e->getMessage()
            ], 500);
        }
    }
    
    public function api_get_audit_log($request) {
        if (!get_option('trueangels_enable_audit', 1)) {
            return new WP_REST_Response(['error' => __('Audit log disabled', 'trueangels-ngo')], 403);
        }
        
        global $wpdb;
        $table_name = $wpdb->prefix . 'trueangels_audit';
        
        $logs = $wpdb->get_results("SELECT * FROM {$table_name} ORDER BY created_at DESC LIMIT 100", ARRAY_A);
        
        return new WP_REST_Response($logs, 200);
    }
    
    public function api_export_donations($request) {
        $format = $request->get_param('format') ?: 'csv';
        
        try {
            $donations = $this->api_client->get('/reports/export/donations', [
                'start_date' => date('Y-m-d', strtotime('-30 days')),
                'end_date' => date('Y-m-d'),
                'format' => $format
            ]);
            
            if ($format === 'csv') {
                header('Content-Type: text/csv');
                header('Content-Disposition: attachment; filename="donations_export.csv"');
                echo $donations;
                exit;
            }
            
            return new WP_REST_Response($donations, 200);
        } catch (Exception $e) {
            return new WP_REST_Response(['error' => $e->getMessage()], 500);
        }
    }
    
    // ==================== AJAX Handlers ====================
    
    public function ajax_create_donation() {
        check_ajax_referer('trueangels_nonce', 'nonce');
        
        $params = [
            'amount' => $_POST['amount'],
            'donor_email' => $_POST['donor_email'],
            'donor_name' => $_POST['donor_name'] ?? '',
            'project_id' => $_POST['project_id'],
            'payment_provider' => $_POST['payment_provider'] ?? 'stripe'
        ];
        
        try {
            $result = $this->api_client->post('/payments/create-donation', $params);
            
            wp_send_json_success($result);
        } catch (Exception $e) {
            wp_send_json_error(['message' => $e->getMessage()]);
        }
    }
    
    // ==================== Asset Loading ====================
    
    public function enqueue_admin_assets($hook) {
        if (strpos($hook, 'trueangels') === false) {
            return;
        }
        
        wp_enqueue_script(
            'trueangels-admin-vue',
            TRUEANGELS_PLUGIN_URL . 'assets/js/admin-vue.js',
            ['jquery'],
            TRUEANGELS_VERSION,
            true
        );
        
        wp_enqueue_style(
            'trueangels-admin-style',
            TRUEANGELS_PLUGIN_URL . 'assets/css/admin-style.css',
            [],
            TRUEANGELS_VERSION
        );
        
        wp_localize_script('trueangels-admin-vue', 'trueangels_ajax', [
            'ajax_url' => admin_url('admin-ajax.php'),
            'nonce' => wp_create_nonce('trueangels_nonce'),
            'rest_url' => rest_url('trueangels/v1'),
            'rest_nonce' => wp_create_nonce('wp_rest')
        ]);
    }
    
    public function enqueue_frontend_assets() {
        wp_enqueue_script(
            'trueangels-frontend-vue',
            TRUEANGELS_PLUGIN_URL . 'assets/js/frontend-vue.js',
            ['jquery'],
            TRUEANGELS_VERSION,
            true
        );
        
        wp_enqueue_style(
            'trueangels-frontend-style',
            TRUEANGELS_PLUGIN_URL . 'assets/css/frontend-style.css',
            [],
            TRUEANGELS_VERSION
        );
        
        wp_localize_script('trueangels-frontend-vue', 'trueangels_frontend', [
            'ajax_url' => admin_url('admin-ajax.php'),
            'rest_url' => rest_url('trueangels/v1'),
            'nonce' => wp_create_nonce('trueangels_nonce'),
            'rest_nonce' => wp_create_nonce('wp_rest'),
            'stripe_key' => get_option('trueangels_stripe_key', '')
        ]);
    }
    
    // ==================== Helper Methods ====================
    
    private function calculate_percentage_change($current, $previous) {
        if ($previous == 0) return 0;
        return round((($current - $previous) / $previous) * 100, 1);
    }
    
    private function log_audit($action, $entity_id, $data = []) {
        global $wpdb;
        
        $table_name = $wpdb->prefix . 'trueangels_audit';
        
        $wpdb->insert($table_name, [
            'user_id' => get_current_user_id(),
            'action' => $action,
            'entity_id' => $entity_id,
            'data' => json_encode($data),
            'ip_address' => $_SERVER['REMOTE_ADDR'],
            'user_agent' => $_SERVER['HTTP_USER_AGENT'],
            'created_at' => current_time('mysql')
        ]);
    }
    
    // ==================== Activation/Deactivation ====================
    
    public function activate_plugin() {
        $this->create_audit_table();
        $this->schedule_cron_jobs();
        flush_rewrite_rules();
    }
    
    public function deactivate_plugin() {
        wp_clear_scheduled_hook('trueangels_sync_donations');
        flush_rewrite_rules();
    }
    
    private function create_audit_table() {
        global $wpdb;
        
        $table_name = $wpdb->prefix . 'trueangels_audit';
        $charset_collate = $wpdb->get_charset_collate();
        
        $sql = "CREATE TABLE IF NOT EXISTS $table_name (
            id bigint(20) NOT NULL AUTO_INCREMENT,
            user_id bigint(20) DEFAULT NULL,
            action varchar(100) NOT NULL,
            entity_id varchar(100) DEFAULT NULL,
            data longtext DEFAULT NULL,
            ip_address varchar(45) DEFAULT NULL,
            user_agent text DEFAULT NULL,
            created_at datetime DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            KEY idx_action (action),
            KEY idx_created_at (created_at)
        ) $charset_collate;";
        
        require_once(ABSPATH . 'wp-admin/includes/upgrade.php');
        dbDelta($sql);
    }
    
    private function schedule_cron_jobs() {
        if (!wp_next_scheduled('trueangels_sync_donations')) {
            wp_schedule_event(time(), 'hourly', 'trueangels_sync_donations');
        }
    }
    
    public function add_cron_intervals($schedules) {
        $schedules['trueangels_hourly'] = [
            'interval' => 3600,
            'display' => __('TrueAngels Hourly', 'trueangels-ngo')
        ];
        return $schedules;
    }
}

// ==================== Initialize Plugin ====================

function trueangels_ngo_init() {
    return TrueAngelsNGOPlugin::get_instance();
}

add_action('plugins_loaded', 'trueangels_ngo_init');